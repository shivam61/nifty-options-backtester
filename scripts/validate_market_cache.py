#!/usr/bin/env python3
"""Read-only validator for the market-data parquet cache and the built dataset.

Never writes into any cache directory. The report goes to --out (default stdout).

Modes
  default      scan *.parquet files in --cache-dir: per-file stats, price-range
               ticker classification (all plausible candidates), byte-identical
               Close series, near-duplicate groups, ticker coverage.
  --dataset    also build the combined dataset through
               data.market_data.MarketDataFetcher with MARKET_DATA_CACHE_ONLY=1
               and run the dataset checks (pairwise identity, named-column
               sanity, freshness). Opt-in because it imports the data layer.
  --selftest   offline run against synthetic clean and corrupted frames written
               to a temp dir; asserts exit 1 for corrupted and 0 for clean.

Exit codes: 0 all checks pass, 1 a check failed, 2 usage/runtime error.
"""

import argparse
import hashlib
import os
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / ".cache"

NEAR_DUP_FRAC = 0.95          # overlapping dates that must be np.isclose
NEAR_DUP_MIN_OVERLAP = 30     # minimum overlapping rows to compare two files
IDENTITY_FAIL_FRAC = 0.50     # column pair identical on more than this -> FAIL
DATASET_FRESHNESS_DAYS = 5


# ---------------------------------------------------------------------------
# File-level ticker signatures (median / min / max of Close)
# ---------------------------------------------------------------------------

def _nifty_like(s: dict) -> bool:
    return 2000 <= s["median"] <= 30000 and s["median"] > 6000 and s["min"] >= 2000


def _band(lo: float, hi: float):
    return lambda s: lo <= s["median"] <= hi


TICKER_SIGNATURES = {
    "nifty": lambda s: 2000 <= s["median"] <= 30000 and s["median"] > 6000,
    "india_vix": lambda s: 10 <= s["median"] <= 30 and s["max"] < 100,
    "brent": _band(20, 130),
    "wti": _band(20, 130),
    "usdinr": _band(40, 96),
    "gold": _band(800, 5500),
    "dxy": _band(70, 115),
    "sp500": lambda s: 600 <= s["median"] <= 8000 and not _nifty_like(s),
    "nifty_bank": _band(5000, 60000),
    "nifty_it": _band(2000, 46000),
    "silver": _band(12, 50),
    "eem": _band(13, 72),
    "hang_seng": _band(8000, 33500),
    "stoxx50": _band(1700, 6600),
    "us_10y": _band(0.5, 5),
    "us_vix": _band(9, 85),
}

# ---------------------------------------------------------------------------
# Dataset-level expected ranges (median of the combined dataset column).
# nifty_close..europe mirror tests/test_feature_store.py TICKER_RANGES;
# us_10y is absent there, so it uses the file-signature band above.
# ---------------------------------------------------------------------------

DATASET_RANGES = {
    "nifty_close": (3_000, 30_000, "Nifty 50 index"),
    "vix": (12, 40, "India VIX"),
    "crude": (30, 110, "Crude oil (Brent, USD/bbl)"),
    "usdinr": (45, 95, "USD/INR exchange rate"),
    "gold": (1_000, 4_500, "Gold futures (USD/oz)"),
    "dxy": (78, 112, "DXY Dollar Index"),
    "us_vix": (12, 35, "US VIX (CBOE)"),
    "us_10y": (0.5, 5, "US 10-year yield (%)"),
    "sp500": (1_000, 7_000, "S&P 500"),
    "nifty_bank": (5_000, 55_000, "Bank Nifty"),
    "silver": (12, 50, "Silver futures (USD/oz)"),
    "nifty_it": (3_000, 40_000, "Nifty IT"),
    "em_etf": (20, 65, "EM ETF (EEM)"),
    "hang_seng": (12_000, 33_000, "Hang Seng Index"),
    "europe": (2_000, 6_000, "EuroStoxx 50"),
}


# ---------------------------------------------------------------------------
# File scan
# ---------------------------------------------------------------------------

def _close_stats(close: pd.Series) -> dict:
    return {
        "median": float(close.median()),
        "min": float(close.min()),
        "max": float(close.max()),
    }


def classify(stats: dict) -> list[str]:
    """Every ticker whose signature matches (overlapping by design)."""
    return [name for name, pred in TICKER_SIGNATURES.items() if pred(stats)]


def scan_file(path: Path) -> tuple[dict, pd.Series | None]:
    rec: dict = {"file": path.name, "rows": 0, "first": None, "last": None,
                 "columns": [], "error": None, "close_n": 0,
                 "close_min": None, "close_med": None, "close_max": None,
                 "candidates": [], "close_hash": None}
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # unreadable file is a reported failure, not a crash
        rec["error"] = f"{type(exc).__name__}: {exc}"
        return rec, None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    rec["rows"] = len(df)
    rec["columns"] = [str(c) for c in df.columns]

    idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df.index, errors="coerce")
    if len(idx):
        rec["first"] = str(pd.Timestamp(idx.min()).date())
        rec["last"] = str(pd.Timestamp(idx.max()).date())

    if "Close" not in df.columns:
        return rec, None

    close = pd.Series(pd.to_numeric(df["Close"], errors="coerce").to_numpy(), index=idx).dropna()
    close = close[~close.index.duplicated(keep="last")].sort_index()
    if close.empty:
        return rec, None

    stats = _close_stats(close)
    rec.update(close_n=len(close), close_min=stats["min"], close_med=stats["median"],
               close_max=stats["max"], candidates=classify(stats))
    rec["close_hash"] = hashlib.sha256(
        np.ascontiguousarray(close.to_numpy(dtype="float64")).tobytes()
    ).hexdigest()
    rec["first"] = str(pd.Timestamp(close.index.min()).date())
    rec["last"] = str(pd.Timestamp(close.index.max()).date())
    return rec, close


def scan_cache(cache_dir: Path) -> tuple[list[dict], dict[str, pd.Series]]:
    if not cache_dir.is_dir():
        raise RuntimeError(f"cache dir not found: {cache_dir}")
    paths = sorted(cache_dir.glob("*.parquet"))
    if not paths:
        raise RuntimeError(f"no *.parquet files in {cache_dir}")
    records, closes = [], {}
    for p in paths:
        rec, close = scan_file(p)
        records.append(rec)
        if close is not None:
            closes[rec["file"]] = close
    return records, closes


def overlap_frac(a: pd.Series, b: pd.Series) -> float | None:
    common = a.index.intersection(b.index)
    if len(common) < NEAR_DUP_MIN_OVERLAP:
        return None
    av = a.reindex(common).to_numpy(dtype="float64")
    bv = b.reindex(common).to_numpy(dtype="float64")
    return float(np.mean(np.isclose(av, bv)))


def duplicate_groups(records: list[dict], closes: dict[str, pd.Series]):
    """Returns (identical_groups, near_duplicate_groups) as lists of filenames."""
    by_hash: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["close_hash"]:
            by_hash[r["close_hash"]].append(r["file"])
    identical = [sorted(v) for v in by_hash.values() if len(v) > 1]

    names = sorted(closes)
    parent = {n: n for n in names}

    def find(n: str) -> str:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            frac = overlap_frac(closes[a], closes[b])
            if frac is not None and frac > NEAR_DUP_FRAC:
                parent[find(a)] = find(b)

    groups: dict[str, list[str]] = defaultdict(list)
    for n in names:
        groups[find(n)].append(n)
    near = [sorted(v) for v in groups.values() if len(v) > 1]
    return identical, near


def coverage(records: list[dict]) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {t: [] for t in TICKER_SIGNATURES}
    for r in records:
        for t in r["candidates"]:
            hits[t].append(r["file"])
    return hits


def file_checks(records: list[dict], identical: list[list[str]]) -> list[tuple[str, bool, str]]:
    checks = []
    unreadable = [r["file"] for r in records if r["error"]]
    checks.append(("all parquet files readable", not unreadable,
                   "all readable" if not unreadable else "unreadable: " + ", ".join(unreadable)))
    hits = coverage(records)
    missing = [t for t, files in hits.items() if not files]
    checks.append(("every ticker has a matching file", not missing,
                   f"{len(TICKER_SIGNATURES) - len(missing)}/{len(TICKER_SIGNATURES)} covered"
                   + (f"; missing: {', '.join(missing)}" if missing else "")))
    # Phase 3 rule: pairwise identity must be none. Byte-identical Close series
    # are the signature of copy-contamination; signatures alone cannot say which
    # copy is the wrong ticker, so any identical group fails and needs --dataset.
    n_files = sum(len(g) for g in identical)
    checks.append(("no byte-identical Close series", not identical,
                   "none" if not identical else
                   f"{len(identical)} group(s), {n_files} files; run --dataset to attribute"))
    return checks


# ---------------------------------------------------------------------------
# Dataset checks
# ---------------------------------------------------------------------------

def _identity_frac(x: np.ndarray, y: np.ndarray) -> float:
    mask = ~(np.isnan(x) | np.isnan(y))
    if not mask.any():
        return 0.0
    return float(np.mean(np.isclose(x[mask], y[mask])))


def pair_frac(df: pd.DataFrame, a: str, b: str) -> float | None:
    if a not in df.columns or b not in df.columns:
        return None
    return _identity_frac(df[a].to_numpy(dtype="float64"), df[b].to_numpy(dtype="float64"))


def identity_pairs(df: pd.DataFrame, cols: list[str]) -> list[tuple[str, str, float]]:
    present = [c for c in cols if c in df.columns]
    arrays = {c: df[c].to_numpy(dtype="float64") for c in present}
    out = []
    for i, a in enumerate(present):
        for b in present[i + 1:]:
            out.append((a, b, _identity_frac(arrays[a], arrays[b])))
    return sorted(out, key=lambda t: -t[2])


def dataset_column_stats(df: pd.DataFrame) -> list[dict]:
    rows = []
    for col in DATASET_RANGES:
        if col not in df.columns:
            rows.append({"col": col, "missing": True})
            continue
        s = df[col].astype("float64")
        valid = s.dropna()
        rows.append({
            "col": col, "missing": False, "rows": len(s),
            "first": str(pd.Timestamp(valid.index.min()).date()) if len(valid) else "-",
            "last": str(pd.Timestamp(valid.index.max()).date()) if len(valid) else "-",
            "min": float(valid.min()) if len(valid) else np.nan,
            "median": float(valid.median()) if len(valid) else np.nan,
            "max": float(valid.max()) if len(valid) else np.nan,
            "nan_pct": 100.0 * float(s.isna().mean()),
        })
    return rows


def evaluate_dataset(df: pd.DataFrame, asof: date,
                     max_stale_days: int = DATASET_FRESHNESS_DAYS) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    pairs = identity_pairs(df, list(DATASET_RANGES))
    bad = [p for p in pairs if p[2] > IDENTITY_FAIL_FRAC]
    checks.append(("no identical column pairs >50%", not bad,
                   ", ".join(f"{a}=={b} {f:.0%}" for a, b, f in bad) or "none"))

    for a, b, label in [("crude", "us_vix", "crude != us_vix"), ("usdinr", "dxy", "usdinr != dxy")]:
        f = pair_frac(df, a, b)
        if f is None:
            checks.append((label, False, f"column missing ({a} or {b})"))
        else:
            checks.append((label, f <= IDENTITY_FAIL_FRAC, f"identity {f:.1%}"))

    if "nifty_bank" not in df.columns:
        checks.append(("nifty_bank 20k-65k after 2023", False, "column missing"))
    else:
        nb = df["nifty_bank"].astype("float64").dropna()
        post = nb[nb.index > pd.Timestamp("2023-12-31")]
        out = post[(post < 20_000) | (post > 65_000)]
        checks.append(("nifty_bank 20k-65k after 2023",
                       len(post) > 0 and len(out) == 0,
                       f"{len(out)} of {len(post)} post-2023 rows outside"))

    for col, (lo, hi, desc) in DATASET_RANGES.items():
        if col not in df.columns:
            checks.append((f"median in range: {col}", False, "column missing"))
            continue
        valid = df[col].astype("float64").dropna()
        if valid.empty:
            checks.append((f"median in range: {col}", False, "no valid rows"))
            continue
        med = float(valid.median())
        checks.append((f"median in range: {col}", lo <= med <= hi,
                       f"{desc}: median={med:.4g} expected [{lo}, {hi}]"))

    if df.empty:
        checks.append(("last date fresh", False, "empty dataset"))
    else:
        last = pd.Timestamp(df.index.max()).date()
        stale = int(np.busday_count(last, asof))
        checks.append(("last date fresh", stale <= max_stale_days,
                       f"last={last} asof={asof} business_days_stale={stale} (max {max_stale_days})"))
    return checks


def build_dataset_frame(cache_dir: Path, start: date, end: date) -> pd.DataFrame:
    os.environ["MARKET_DATA_CACHE_ONLY"] = "1"  # must be set before the data layer is used
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from data import market_data as md  # noqa: E402  (import after env var on purpose)

    # Read from the requested cache dir. Cache-only mode never writes.
    md.CACHE_DIR = Path(cache_dir)
    return md.MarketDataFetcher(start, end).build_combined_dataset()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def exit_code(checks: list[tuple[str, bool, str]]) -> int:
    return 0 if all(ok for _, ok, _ in checks) else 1


def _fmt(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    if isinstance(x, float):
        return f"{x:.6g}"
    return str(x)


def format_checks(checks: list[tuple[str, bool, str]]) -> str:
    lines = [f"{'CHECK':<52}{'RESULT':<8}DETAIL"]
    for name, ok, detail in checks:
        lines.append(f"{name:<52}{('PASS' if ok else 'FAIL'):<8}{detail}")
    lines.append(f"OVERALL: {'PASS' if exit_code(checks) == 0 else 'FAIL'}")
    return "\n".join(lines)


def format_file_report(records, closes, identical, near) -> str:
    out = ["== FILE SCAN =="]
    out.append(f"{'file':<40}{'rows':>6} {'first':<11}{'last':<11}"
               f"{'min':>10}{'median':>12}{'max':>12} {'ncol':>4}  hash8  candidates")
    for r in records:
        if r["error"]:
            out.append(f"{r['file']:<40}ERROR {r['error']}")
            continue
        cands = ",".join(r["candidates"]) or "(unclassified)"
        if len(r["candidates"]) > 1:
            cands += "  [AMBIGUOUS]"
        h = (r["close_hash"] or "")[:8]
        out.append(f"{r['file']:<40}{r['rows']:>6} {str(r['first']):<11}{str(r['last']):<11}"
                   f"{_fmt(r['close_min']):>10}{_fmt(r['close_med']):>12}{_fmt(r['close_max']):>12}"
                   f" {len(r['columns']):>4}  {h}  {cands}")

    out.append("")
    out.append("== TICKER COVERAGE (files matching each signature; overlaps counted in each) ==")
    hits = coverage(records)
    for t, files in hits.items():
        out.append(f"{t:<12}{len(files):>4} file(s)")

    out.append("")
    out.append("== BYTE-IDENTICAL CLOSE SERIES ==")
    out.extend("  " + ", ".join(g) for g in identical) if identical else out.append("  none")
    out.append("== NEAR-DUPLICATE GROUPS (>95% np.isclose on overlapping dates) ==")
    out.extend("  " + ", ".join(g) for g in near) if near else out.append("  none")
    out.append("  note: same-ticker files with different date windows also group here; "
               "a group is suspicious only if it mixes files with different candidate tickers.")
    return "\n".join(out)


def format_dataset_report(df: pd.DataFrame, asof: date) -> str:
    out = ["== DATASET COLUMNS ==",
           f"{'col':<14}{'rows':>6} {'first':<11}{'last':<11}{'min':>12}{'median':>12}{'max':>12}{'nan%':>8}"]
    for r in dataset_column_stats(df):
        if r["missing"]:
            out.append(f"{r['col']:<14}MISSING")
            continue
        out.append(f"{r['col']:<14}{r['rows']:>6} {r['first']:<11}{r['last']:<11}"
                   f"{_fmt(r['min']):>12}{_fmt(r['median']):>12}{_fmt(r['max']):>12}{r['nan_pct']:>7.1f}%")
    out.append("")
    out.append("== PAIRWISE IDENTITY (fraction of rows np.isclose); pairs >50% listed ==")
    big = [p for p in identity_pairs(df, list(DATASET_RANGES)) if p[2] > IDENTITY_FAIL_FRAC]
    if big:
        out.extend(f"  {a} == {b}: {f:.1%}" for a, b, f in big)
    else:
        out.append("  none")
    return "\n".join(out)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {s!r}") from exc


def run_validation(args) -> tuple[str, list[tuple[str, bool, str]]]:
    records, closes = scan_cache(args.cache_dir)
    identical, near = duplicate_groups(records, closes)
    parts = [f"cache dir: {args.cache_dir}  files: {len(records)}  asof: {args.asof}"]
    parts.append(format_file_report(records, closes, identical, near))
    checks = file_checks(records, identical)

    if args.dataset:
        df = build_dataset_frame(args.cache_dir, args.start, args.end)
        parts.append(format_dataset_report(df, args.asof))
        checks += evaluate_dataset(df, args.asof, args.max_stale_days)

    parts.append("== CHECKS ==")
    parts.append(format_checks(checks))
    return "\n".join(parts), checks


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

_SYNTH_BASE = {
    "nifty_close": 22_000, "vix": 14, "crude": 75, "usdinr": 84, "gold": 2_000,
    "dxy": 98, "us_vix": 16, "us_10y": 4.2, "sp500": 6_000, "nifty_bank": 45_000,
    "silver": 30, "nifty_it": 30_000, "em_etf": 40, "hang_seng": 20_000, "europe": 4_500,
}


def synthetic_raw(asof: date, seed: int = 7) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp(asof), periods=320)  # covers post-2023 rows
    return {k: pd.Series(v * np.exp(rng.normal(0, 0.01, len(idx))), index=idx, name=k)
            for k, v in _SYNTH_BASE.items()}


def corrupt_raw(raw: dict[str, pd.Series]) -> dict[str, pd.Series]:
    bad = dict(raw)
    bad["crude"] = raw["us_vix"].copy()      # crude == us_vix copy
    bad["usdinr"] = raw["dxy"].copy()        # usdinr == dxy copy
    bad["nifty_bank"] = raw["sp500"].copy()  # nifty_bank == sp500 copy
    return bad


def _write_raw_cache(raw: dict[str, pd.Series], cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for k, s in raw.items():
        frame = pd.DataFrame({"Open": s, "High": s, "Low": s, "Close": s, "Volume": 0.0})
        frame.index.name = "Date"
        frame.to_parquet(cache_dir / f"{k}.parquet")


def selftest() -> int:
    asof = date(2026, 10, 9)
    clean = synthetic_raw(asof)
    corrupt = corrupt_raw(clean)
    results: list[tuple[str, bool, str]] = []

    clean_df = pd.DataFrame(clean)
    corrupt_df = pd.DataFrame(corrupt)
    clean_checks = evaluate_dataset(clean_df, asof)
    corrupt_checks = evaluate_dataset(corrupt_df, asof)
    clean_rc, corrupt_rc = exit_code(clean_checks), exit_code(corrupt_checks)
    results.append(("clean dataset -> exit 0", clean_rc == 0, f"exit={clean_rc}"))
    results.append(("corrupted dataset -> exit 1", corrupt_rc == 1, f"exit={corrupt_rc}"))
    failed = {name for name, ok, _ in corrupt_checks if not ok}
    for name in ("crude != us_vix", "usdinr != dxy", "no identical column pairs >50%"):
        results.append((f"corrupted flags: {name}", name in failed, "failed" if name in failed else "NOT flagged"))

    with tempfile.TemporaryDirectory(prefix="validate_cache_selftest_") as tmp:
        tmp_path = Path(tmp)
        clean_dir, corrupt_dir = tmp_path / "clean", tmp_path / "corrupt"
        _write_raw_cache(clean, clean_dir)
        _write_raw_cache(corrupt, corrupt_dir)

        rec_c, close_c = scan_cache(clean_dir)
        ident_c, near_c = duplicate_groups(rec_c, close_c)
        results.append(("clean cache: no duplicate groups", not ident_c and not near_c,
                        f"identical={len(ident_c)} near={len(near_c)}"))

        rec_x, close_x = scan_cache(corrupt_dir)
        ident_x, _ = duplicate_groups(rec_x, close_x)
        want = [["crude.parquet", "us_vix.parquet"], ["dxy.parquet", "usdinr.parquet"],
                ["nifty_bank.parquet", "sp500.parquet"]]
        found = all(any(set(w) <= set(g) for g in ident_x) for w in want)
        results.append(("corrupt cache: 3 identical groups found", found,
                        "; ".join(", ".join(g) for g in ident_x) or "none"))
        file_rc = exit_code(file_checks(rec_x, ident_x))
        results.append(("corrupt cache file checks -> exit 1", file_rc == 1, f"exit={file_rc}"))

    print(format_checks(results))
    return 0 if all(ok for _, ok, _ in results) else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read-only validator for the market-data cache and dataset.")
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
                   help="directory of *.parquet cache files (default: <repo>/data/.cache)")
    p.add_argument("--dataset", action="store_true",
                   help="also build the combined dataset (MARKET_DATA_CACHE_ONLY=1) and check it")
    p.add_argument("--start", type=_parse_date, default=date(2009, 1, 1), help="dataset start (YYYY-MM-DD)")
    p.add_argument("--end", type=_parse_date, default=None, help="dataset end (default: --asof)")
    p.add_argument("--asof", type=_parse_date, default=None, help="reference date (default: today)")
    p.add_argument("--max-stale-days", type=int, default=DATASET_FRESHNESS_DAYS,
                   help="max business days between last dataset date and --asof")
    p.add_argument("--out", type=Path, default=None, help="write full report here (default: stdout)")
    p.add_argument("--selftest", action="store_true", help="run offline synthetic self-test")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()

    args.asof = args.asof or date.today()
    args.end = args.end or args.asof
    try:
        text, checks = run_validation(args)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(format_checks(checks))
        print(f"report written to {args.out}")
    else:
        print(text)
    return exit_code(checks)


if __name__ == "__main__":
    sys.exit(main())
