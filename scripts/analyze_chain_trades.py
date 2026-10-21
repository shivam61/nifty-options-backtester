#!/usr/bin/env python3
"""Statistics for chain backtest trade files written by scripts/run_chain_backtest.py.

Input: one or more trades_x<mult>.json files (format {"trades": [...]}), or a directory
containing them. P&L is per lot (pnl_per_lot), which is the primary metric.

Per block (overall, by strategy, by exit reason, by entry-VIX bucket, by year, pre/post splits):
    n, expectancy per lot, median, win rate, average win/loss, payoff (avg win / avg loss),
    worst trade, 5th percentile, total per lot,
    bootstrap 95% CI of the mean from two resamplers (fixed seeds, reproducible):
        per-trade  : resample trades with replacement
        year-cluster: resample calendar years with replacement, keeping all trades of each year
    cumulative-P&L max drawdown per lot (trades ordered by exit_date, entry_date; peak includes 0).

Pre/post splits: every --split DATE (default 2024-04-04 and 2025-09-02) gives a pre/post pair
keyed by entry_date; --holdout DATE (default 2025-09-02) adds a dedicated holdout block
(entry_date >= DATE) and its complement.

Example:
    python scripts/analyze_chain_trades.py --trades /tmp/chain_out --out /tmp/chain_out/analysis.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

N_BOOT = 10_000
SEED_TRADE = 20261020
SEED_YEAR = 20261021
VIX_EDGES = [0.0, 13.0, 16.0, 20.0, 30.0, float("inf")]
VIX_LABELS = ["<13", "13-16", "16-20", "20-30", "30+"]
DEFAULT_SPLITS = ["2024-04-04", "2025-09-02"]
DEFAULT_HOLDOUT = "2025-09-02"


def collect_files(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "trades_x*.json"))))
        else:
            out.append(p)
    if not out:
        raise SystemExit("no trade files found")
    return out


def load_trades(path: str) -> pd.DataFrame:
    rows = json.load(open(path))["trades"]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ppl"] = df["pnl_per_lot"].astype(float)
    df["year"] = df["entry_date"].astype(str).str[:4].astype(int)
    df["vix_bucket"] = pd.cut(df["entry_vix"].astype(float), VIX_EDGES, labels=VIX_LABELS, right=False).astype(str)
    return df


def max_drawdown(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    d = df.sort_values(["exit_date", "entry_date"], kind="mergesort")
    cum = np.cumsum(d["ppl"].to_numpy(float))
    peak = np.maximum(np.maximum.accumulate(cum), 0.0)
    return float((cum - peak).min())


def boot_trade_ci(x: np.ndarray, seed: int) -> tuple[float, float]:
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(N_BOOT, len(x)))
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def boot_year_ci(x: np.ndarray, years: np.ndarray, seed: int) -> tuple[float, float]:
    uy = np.unique(years)
    if len(uy) < 2:
        return (float("nan"), float("nan"))
    sums = np.array([x[years == y].sum() for y in uy])
    cnts = np.array([(years == y).sum() for y in uy], dtype=float)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(uy), size=(N_BOOT, len(uy)))
    means = sums[picks].sum(axis=1) / cnts[picks].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def block(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    x = df["ppl"].to_numpy(float)
    wins = x[x > 0]
    losses = -x[x <= 0]
    lo_t, hi_t = boot_trade_ci(x, SEED_TRADE)
    lo_y, hi_y = boot_year_ci(x, df["year"].to_numpy(), SEED_YEAR)
    avg_win = float(wins.mean()) if len(wins) else None
    avg_loss = float(-losses.mean()) if len(losses) else None
    return {
        "n": int(len(x)),
        "exp_per_lot": round(float(x.mean()), 1),
        "median_per_lot": round(float(np.median(x)), 1),
        "win_rate_pct": round(float((x > 0).mean()) * 100, 1),
        "avg_win": round(avg_win, 1) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 1) if avg_loss is not None else None,
        "payoff": round(avg_win / -avg_loss, 2) if avg_win is not None and avg_loss not in (None, 0.0) else None,
        "worst": round(float(x.min()), 1),
        "p5": round(float(np.percentile(x, 5)), 1),
        "total_per_lot": round(float(x.sum()), 1),
        "ci95_trade_lo": round(lo_t, 1), "ci95_trade_hi": round(hi_t, 1),
        "ci95_year_lo": round(lo_y, 1), "ci95_year_hi": round(hi_y, 1),
        "years": int(df["year"].nunique()),
        "max_dd_per_lot": round(max_drawdown(df), 1),
    }


def analyze(df: pd.DataFrame, splits: list[str], holdout: str) -> dict:
    out: dict = {"overall": block(df)}
    out["by_strategy"] = {s: block(g) for s, g in df.groupby("strategy")}
    out["by_exit"] = {r: block(g) for r, g in df.groupby("exit_reason")}
    out["by_vix"] = {b: block(df[df["vix_bucket"] == b]) for b in VIX_LABELS}
    out["by_year"] = {str(y): block(g) for y, g in df.groupby("year")}
    splits_out = {}
    for s in splits:
        cut = date.fromisoformat(s).isoformat()
        splits_out[s] = {"pre": block(df[df["entry_date"].astype(str) < cut]),
                         "post": block(df[df["entry_date"].astype(str) >= cut])}
    out["splits"] = splits_out
    hcut = date.fromisoformat(holdout).isoformat()
    out["holdout"] = {"date": hcut,
                      "pre": block(df[df["entry_date"].astype(str) < hcut]),
                      "holdout": block(df[df["entry_date"].astype(str) >= hcut])}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", nargs="+", required=True, help="trade JSON files or a directory")
    ap.add_argument("--split", action="append", default=None,
                    help="pre/post split date YYYY-MM-DD (repeatable; default 2024-04-04 and 2025-09-02)")
    ap.add_argument("--holdout", default=DEFAULT_HOLDOUT, help="holdout start date (default %(default)s)")
    ap.add_argument("--out", type=Path, default=None, help="write the full analysis JSON here")
    a = ap.parse_args(argv)
    splits = a.split if a.split else list(DEFAULT_SPLITS)

    result = {"n_boot": N_BOOT, "seeds": {"trade": SEED_TRADE, "year": SEED_YEAR}, "runs": {}}
    for path in collect_files(a.trades):
        df = load_trades(path)
        name = Path(path).stem.replace("trades_", "")
        result["runs"][name] = {"file": str(path), **analyze(df, splits, a.holdout)}
        o = result["runs"][name]["overall"]
        print(f"{name}: n={o.get('n')} exp/lot={o.get('exp_per_lot')} "
              f"ci_trade=[{o.get('ci95_trade_lo')},{o.get('ci95_trade_hi')}] "
              f"ci_year=[{o.get('ci95_year_lo')},{o.get('ci95_year_hi')}] "
              f"payoff={o.get('payoff')} worst={o.get('worst')} p5={o.get('p5')} maxdd={o.get('max_dd_per_lot')}")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        json.dump(result, open(a.out, "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
