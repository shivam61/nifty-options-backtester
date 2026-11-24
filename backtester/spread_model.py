"""
Data-driven half-spread model for the real-price chain engine (opt-in, ChainConfig.spread_model).

Source: live NSE option-chain quote snapshots logged by scripts/log_option_quotes.py into
paper_trading/tracker/QUOTE_LOG*.csv. These are the owner's own logs, not licensed archive data.

Observed half-spread for a two-sided quote: half = (ask - bid) / 2; the fraction of mid is
half / ((ask + bid) / 2). Quotes are bucketed on three keys:
    moneyness   |K/S - 1|     lt1pct | 1to2pct | 2to4pct | gt4pct   (same bands as the logger)
    dte         calendar DTE   dte_le5 | dte_6to8 | dte_ge9
    vix         India VIX      vix_lt13 | vix_ge13                   (same split as the logger)

A bucket is CALIBRATED only when it has at least `min_samples` quote rows (default 30) AND at least
`min_snapshots` distinct snapshots (default 3; an addition to the row count, because quotes inside
one snapshot are highly correlated). A calibrated bucket returns the median observed fraction of mid
times the engine's settle price. Anything else (bucket missing, too few samples, non-positive price)
falls back to the flat CostModel value, and the fallback is flagged. Lookup is exact-bucket only:
nothing is interpolated from neighbouring buckets.

The result is the base half-spread; the engine's slippage multiplier (1.0 / 1.5 / 2.0x) still
applies on top. A table cannot support a pass/fail verdict until its buckets are calibrated; see
docs/SPREAD_MODEL.md.

CLI (build table, print coverage):
    python -m backtester.spread_model --out data/spread_table.json
    python -m backtester.spread_model --table data/spread_table.json     # coverage report only
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_GLOB = str(REPO_ROOT / "paper_trading" / "tracker" / "QUOTE_LOG*.csv")
DEFAULT_TABLE = REPO_ROOT / "data" / "spread_table.json"
DEFAULT_MIN_SAMPLES = 30
DEFAULT_MIN_SNAPSHOTS = 3
TABLE_VERSION = 1

MONEYNESS_BANDS = ("lt1pct", "1to2pct", "2to4pct", "gt4pct")
DTE_BANDS = ("dte_le5", "dte_6to8", "dte_ge9")
VIX_BANDS = ("vix_lt13", "vix_ge13")

# Result of SpreadModel.half_spread. value is Rs/unit BEFORE the slippage multiplier.
SpreadEstimate = namedtuple("SpreadEstimate", "value calibrated reason bucket")

REASON_CALIBRATED = "calibrated"
REASON_NO_BUCKET = "no_bucket"
REASON_BELOW_MIN = "below_min_samples"
REASON_BAD_PRICE = "bad_price"


def moneyness_band(strike: float, spot: float) -> str:
    m = strike / spot if spot > 0 else 1.0
    d = abs(m - 1.0)
    if d < 0.01:
        return "lt1pct"
    if d < 0.02:
        return "1to2pct"
    if d < 0.04:
        return "2to4pct"
    return "gt4pct"


def dte_band(dte: float) -> str:
    if dte <= 5:
        return "dte_le5"
    if dte <= 8:
        return "dte_6to8"
    return "dte_ge9"


def vix_band(vix: float) -> str:
    return "vix_lt13" if vix < 13 else "vix_ge13"


def bucket_key(strike: float, spot: float, dte: float, vix: float) -> str:
    return f"{moneyness_band(strike, spot)}|{dte_band(dte)}|{vix_band(vix)}"


# ─────────────────────────────────────────────────────────────── building

_ROW_COLS = ["snapshot", "date", "strike", "spot", "dte", "vix", "mid", "half", "frac", "bucket", "source_file"]


def load_quote_rows(paths: Iterable[str | Path]) -> pd.DataFrame:
    """Two-sided, in-window, non-forced NSE quotes from the given CSV logs, de-duplicated."""
    frames = []
    for p in paths:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        df["source_file"] = Path(p).name
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=_ROW_COLS)
    raw = pd.concat(frames, ignore_index=True)
    for c in ("bid", "ask", "strike", "spot", "dte", "vix"):
        raw[c] = pd.to_numeric(raw[c].replace("", float("nan")), errors="coerce")
    keep = (raw["source"] == "nse") & (raw["in_window"] == "1") & (raw["forced"] == "0")
    keep &= raw["quote_status"] == "ok"
    keep &= raw[["bid", "ask", "strike", "spot", "dte", "vix"]].notna().all(axis=1)
    keep &= (raw["bid"] > 0) & (raw["ask"] >= raw["bid"]) & (raw["spot"] > 0)
    d = raw.loc[keep].copy()
    if d.empty:
        return pd.DataFrame(columns=_ROW_COLS)
    d = d.drop_duplicates(subset=["timestamp_ist", "source", "expiry", "strike", "option_type"])
    d["snapshot"] = d["timestamp_ist"]
    d["date"] = d["timestamp_ist"].str[:10]
    d["mid"] = (d["ask"] + d["bid"]) / 2
    d["half"] = (d["ask"] - d["bid"]) / 2
    d["frac"] = d["half"] / d["mid"]
    d["bucket"] = [bucket_key(k, s, t, v) for k, s, t, v in zip(d["strike"], d["spot"], d["dte"], d["vix"])]
    return d[_ROW_COLS].reset_index(drop=True)


def build_table(rows: pd.DataFrame, *, min_samples: int = DEFAULT_MIN_SAMPLES,
                min_snapshots: int = DEFAULT_MIN_SNAPSHOTS, sources: Optional[list] = None) -> dict:
    """Bucket table as a JSON-serialisable dict. Every observed bucket is listed, calibrated or not."""
    buckets = {}
    for key, g in rows.groupby("bucket"):
        n = int(len(g))
        snaps = int(g["snapshot"].nunique())
        fr = g["frac"].astype(float)
        buckets[key] = {
            "n_rows": n,
            "n_snapshots": snaps,
            "n_dates": int(g["date"].nunique()),
            "calibrated": bool(n >= min_samples and snaps >= min_snapshots),
            "frac_of_mid_median": round(float(fr.median()), 6),
            "frac_of_mid_p25": round(float(fr.quantile(0.25)), 6),
            "frac_of_mid_p75": round(float(fr.quantile(0.75)), 6),
            "half_rs_median": round(float(g["half"].median()), 4),
            "mid_rs_median": round(float(g["mid"].median()), 4),
        }
    return {
        "version": TABLE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources or [],
        "rows_used": int(len(rows)),
        "snapshots_used": int(rows["snapshot"].nunique()) if len(rows) else 0,
        "min_samples": int(min_samples),
        "min_snapshots": int(min_snapshots),
        "bands": {"moneyness": list(MONEYNESS_BANDS), "dte": list(DTE_BANDS), "vix": list(VIX_BANDS)},
        "buckets": buckets,
    }


# ─────────────────────────────────────────────────────────────── model

class SpreadModel:
    """Calibrated half-spread lookup. Construct from a table dict, or SpreadModel.load(path)."""

    def __init__(self, table: dict, *, min_samples: Optional[int] = None, min_snapshots: Optional[int] = None):
        if int(table.get("version", -1)) != TABLE_VERSION:
            raise ValueError(f"unsupported spread table version {table.get('version')!r}")
        self.table = table
        self.min_samples = (int(table.get("min_samples", DEFAULT_MIN_SAMPLES))
                            if min_samples is None else int(min_samples))
        self.min_snapshots = (int(table.get("min_snapshots", DEFAULT_MIN_SNAPSHOTS))
                              if min_snapshots is None else int(min_snapshots))
        self.buckets = table.get("buckets", {})

    @classmethod
    def load(cls, path: str | Path, **kw) -> "SpreadModel":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), **kw)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.table, indent=1), encoding="utf-8")

    def is_calibrated(self, key: str) -> bool:
        b = self.buckets.get(key)
        if b is None:
            return False
        return b["n_rows"] >= self.min_samples and b["n_snapshots"] >= self.min_snapshots

    def half_spread(self, strike: float, spot: float, dte: float, vix: float, price: float,
                    flat: Optional[float] = None) -> SpreadEstimate:
        """Half-spread in Rs/unit for one leg, before the slippage multiplier.

        Calibrated bucket: median observed fraction of mid x price.
        Otherwise: `flat` (the CostModel value the engine would use), calibrated=False, reason set.
        A fallback with flat=None returns NaN, so the caller cannot silently charge zero.
        """
        key = bucket_key(strike, spot, dte, vix)
        if not (price is not None and math.isfinite(price) and price > 0):
            reason = REASON_BAD_PRICE
        elif key not in self.buckets:
            reason = REASON_NO_BUCKET
        elif not self.is_calibrated(key):
            reason = REASON_BELOW_MIN
        else:
            frac = float(self.buckets[key]["frac_of_mid_median"])
            return SpreadEstimate(frac * float(price), True, REASON_CALIBRATED, key)
        return SpreadEstimate(float(flat) if flat is not None else float("nan"), False, reason, key)

    def coverage(self) -> list[dict]:
        out = []
        for key in sorted(self.buckets):
            b = self.buckets[key]
            out.append({"bucket": key, "n_rows": b["n_rows"], "n_snapshots": b["n_snapshots"],
                        "n_dates": b["n_dates"], "calibrated": self.is_calibrated(key),
                        "frac_of_mid_median": b["frac_of_mid_median"]})
        return out


def format_coverage(model: SpreadModel) -> str:
    cov = model.coverage()
    cal = sum(1 for c in cov if c["calibrated"])
    lines = [f"spread table: {len(cov)} observed buckets, {cal} calibrated "
             f"(min_samples={model.min_samples}, min_snapshots={model.min_snapshots}); "
             f"rows_used={model.table.get('rows_used')} snapshots_used={model.table.get('snapshots_used')}",
             f"{'bucket':<30}{'rows':>6}{'snaps':>7}{'dates':>7}{'frac/mid':>10}  status"]
    for c in cov:
        status = "calibrated" if c["calibrated"] else "FALLBACK"
        lines.append(f"{c['bucket']:<30}{c['n_rows']:>6}{c['n_snapshots']:>7}{c['n_dates']:>7}"
                     f"{c['frac_of_mid_median']:>10.4f}  {status}")
    lines.append("Buckets not listed (any other moneyness x DTE x VIX combination) always fall back.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", nargs="+", default=[DEFAULT_LOG_GLOB],
                    help="quote-log CSV paths or globs (default: paper_trading/tracker/QUOTE_LOG*.csv)")
    ap.add_argument("--out", type=Path, default=None, help="write the table JSON here")
    ap.add_argument("--table", type=Path, default=None, help="report on an existing table (no build)")
    ap.add_argument("--min-samples", type=int, default=DEFAULT_MIN_SAMPLES)
    ap.add_argument("--min-snapshots", type=int, default=DEFAULT_MIN_SNAPSHOTS)
    a = ap.parse_args(argv)
    if a.table is not None:
        print(format_coverage(SpreadModel.load(a.table)))
        return 0
    paths: list[str] = []
    for pat in a.logs:
        paths.extend(sorted(glob.glob(pat)) or ([pat] if Path(pat).exists() else []))
    if not paths:
        print("no quote logs found", file=sys.stderr)
        return 2
    rows = load_quote_rows(paths)
    table = build_table(rows, min_samples=a.min_samples, min_snapshots=a.min_snapshots,
                        sources=[Path(p).name for p in paths])
    model = SpreadModel(table)
    print(format_coverage(model))
    if a.out is not None:
        model.save(a.out)
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
