#!/usr/bin/env python3
"""PRICED random-entry null (DESCRIPTIVE, not a verdict; no registry writes; DEV window 2019-02-11..2023-12-31 only).

Question: does a post-hoc variant (skip-monthly-expiry) beat a random choice of the same number of entry weeks
drawn from the SAME priced baseline trades (real archive prices, gate off, lots=10)?

Null draws (1000 each): (a) year-stratified random subset with the variant's per-year counts; (b) block version:
random whole calendar months per year until the variant's per-year trade count is reached.
Baseline trades are read from logs/explore/skip_monthly/trades_*.csv (written by explore_skip_monthly.py on the
same window/config); pass --rerun to regenerate them with the chain engine instead.

    python scripts/priced_random_null.py [--rerun] [--draws 1000] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

START, END = date(2019, 2, 11), date(2023, 12, 31)
SRC = REPO_ROOT / "logs" / "explore" / "skip_monthly"
OUT = REPO_ROOT / "logs" / "explore" / "random_null"
STRUCTS = ("PCS", "IC")
SLIPS = (1.0, 0.3)


def resample_null(pl, strata, counts, draws=1000, seed=0, blocks=None):
    """Null distribution of mean(pl) under random selection.

    pl: per-trade Rs/lot; strata: per-trade stratum label (e.g. year); counts: {stratum: n to draw}.
    blocks=None: draw counts[s] trades without replacement within each stratum.
    blocks=array (per-trade block label, e.g. year-month): within each stratum draw whole blocks in random order
    until the stratum's trade count reaches counts[s] (may overshoot by < one block).
    Returns (means[draws], sizes[draws]).
    """
    pl = np.asarray(pl, float)
    strata = np.asarray(strata)
    rng = np.random.default_rng(seed)
    idx = {s: np.flatnonzero(strata == s) for s in counts if counts[s] > 0}
    for s, ix in idx.items():
        if len(ix) < counts[s]:
            raise ValueError(f"stratum {s}: need {counts[s]} > available {len(ix)}")
    bl = np.asarray(blocks) if blocks is not None else None
    bmap = {}
    if bl is not None:
        for s, ix in idx.items():
            labs = bl[ix]
            bmap[s] = [ix[labs == b] for b in np.unique(labs)]
    means = np.empty(draws)
    sizes = np.empty(draws, int)
    for d in range(draws):
        parts = []
        for s, ix in idx.items():
            if bl is None:
                parts.append(rng.choice(ix, size=counts[s], replace=False))
            else:
                got = 0
                for j in rng.permutation(len(bmap[s])):
                    if got >= counts[s]:
                        break
                    parts.append(bmap[s][j])
                    got += len(bmap[s][j])
        sel = np.concatenate(parts) if parts else np.array([], int)
        sizes[d] = sel.size
        means[d] = pl[sel].mean() if sel.size else np.nan
    return means, sizes


def compare(real_mean, null_means):
    m = null_means[~np.isnan(null_means)]
    ge = (m >= real_mean).sum()
    le = (m <= real_mean).sum()
    return {
        "real_mean": float(real_mean),
        "null_mean": float(m.mean()), "null_sd": float(m.std(ddof=1)),
        "null_p05": float(np.percentile(m, 5)), "null_p95": float(np.percentile(m, 95)),
        "percentile": float((m < real_mean).mean() * 100),
        "p_one_sided": float((1 + ge) / (1 + m.size)),   # P(null mean >= real mean)
        "p_two_sided": float(min(1.0, 2 * min(1 + ge, 1 + le) / (1 + m.size))),
    }


def load_baseline(name, slip, rerun):
    f = SRC / f"trades_{name}_{slip}.csv"
    if rerun or not f.exists():
        import run_round3 as r3
        from backtester.candidates import PCS, IRON_CONDOR, CandidateSpec
        from backtester.chain_engine import ChainBacktest
        from data.nse_fo_archive import NseFoArchive
        market = r3.load_market(END)
        fb = {d.date(): float(v) for d, v in market["nifty_close"].items()}
        arch = NseFoArchive(index_fallback=fb, max_date=END)
        last = {}
        for e in sorted({e for v in arch._expiries_by_day.values() for e in v}):
            last[(e.year, e.month)] = max(last.get((e.year, e.month), e), e)
        monthly = set(last.values())
        spec = {"PCS": CandidateSpec("X_PCS", "X", PCS, 1.0, 300.0, "weekly", 13.0, 25.0),
                "IC": CandidateSpec("X_IC", "X", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0)}[name]
        cfg = r3.build_config(spec, START, END, lots=10, slippage=slip, capital_mode=False)
        df = pd.DataFrame(ChainBacktest(arch, market, cfg).run())
        df["pl"] = df["pnl"] / df["lots"]
        df["entry_date"] = pd.to_datetime(df["entry_date"])
        df["exp"] = pd.to_datetime(df["expiry"]).dt.date
        df["fill"] = df["entry_date"].dt.date
        df["target_monthly"] = df["exp"].isin(monthly)
        df["crosses_monthly"] = [any(a <= m < e for m in monthly) for a, e in zip(df["fill"], df["exp"])]
    else:
        df = pd.read_csv(f)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["target_monthly"] = df["target_monthly"].astype(bool)
    df["crosses_monthly"] = df["crosses_monthly"].astype(bool)
    df["excluded"] = df["target_monthly"] | df["crosses_monthly"]
    df["year"] = df["entry_date"].dt.year
    df["ym"] = df["entry_date"].dt.strftime("%Y-%m")
    assert df["entry_date"].min().date() >= START and df["entry_date"].max().date() <= END, "outside DEV window"
    return df


def run(draws, seed, rerun):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in STRUCTS:
        for slip in SLIPS:
            df = load_baseline(name, slip, rerun)
            pl = df["pl"].to_numpy()
            rng = np.random.default_rng(seed + 1)
            sanity = np.zeros(len(df), bool)
            sanity[rng.choice(len(df), size=int(round(0.77 * len(df))), replace=False)] = True
            arms = {
                "variant_skip_monthly_keep": ~df["excluded"].to_numpy(),
                "monthly_expiry_excluded_arm": df["excluded"].to_numpy(),
                "target_monthly_only_arm": df["target_monthly"].to_numpy(),
                "sanity_random_77pct_keep": sanity,
            }
            for arm, mask in arms.items():
                if mask.sum() < 2:
                    continue
                counts = df.loc[mask].groupby("year").size().to_dict()
                for mode in ("year_stratified", "month_block"):
                    means, sizes = resample_null(
                        pl, df["year"].to_numpy(), counts, draws, seed,
                        blocks=df["ym"].to_numpy() if mode == "month_block" else None)
                    r = compare(pl[mask].mean(), means)
                    rows.append({"struct": name, "slippage": slip, "arm": arm, "null": mode,
                                 "n_baseline": len(df), "n_arm": int(mask.sum()),
                                 "null_mean_n": float(sizes.mean()), "baseline_mean": float(pl.mean()), **r})
    pd.DataFrame(rows).to_csv(OUT / "priced_random_null.csv", index=False)
    with open(OUT / "priced_random_null.json", "w") as fh:
        json.dump({"window": [str(START), str(END)], "draws": draws, "seed": seed, "rows": rows}, fh, indent=1)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rows = run(a.draws, a.seed, a.rerun)
    print(f"{'struct':4} {'slip':4} {'arm':30} {'null':15} {'n':>4} {'real':>8} {'nullmu':>8} {'pctile':>6} {'p1s':>6}")
    for r in rows:
        print(f"{r['struct']:4} {r['slippage']:<4} {r['arm']:30} {r['null']:15} {r['n_arm']:>4} "
              f"{r['real_mean']:>8.1f} {r['null_mean']:>8.1f} {r['percentile']:>6.1f} {r['p_one_sided']:>6.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
