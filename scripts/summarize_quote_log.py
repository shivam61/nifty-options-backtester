#!/usr/bin/env python3
"""
Summarise paper_trading/tracker/QUOTE_LOG.csv: real half-spread vs the backtest slippage model.

For every two-sided quote, half_spread_to_model = half_spread / model_slip_unit, where
model_slip_unit is ChainBacktest._slip_unit at multiplier 1.0 (the chain engine's default). That
ratio is the implied slippage multiplier for that leg. The headline is the median of it over
structure legs (IC / PCS short, long and the ATM straddle legs). Neighbour strikes are reported
separately because they are not traded.

USAGE
    python scripts/summarize_quote_log.py
    python scripts/summarize_quote_log.py --log /path/to/QUOTE_LOG.csv --min-snapshots 30

Reference break-evens (multiples of the model's per-unit slippage) are taken from
BACKTEST_CHANGELOG.md "Settlement and cost-model correction; Step 2 re-run" (dev window
2019-02-11..2023-12-31, lots=10, cash settlement at expiry) and are NOT re-derived here.
Before that correction the table read 0.47 / 0.80 / 0.90; the hold-to-expiry value moved
because ~91% of its earlier shortfall was the settlement-model error. Read: a measured
multiplier below a threshold means the real cost is below the level at which that structure
stops being profitable on this model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "paper_trading" / "tracker" / "QUOTE_LOG.csv"

BREAK_EVEN = {
    "baseline (expiry-day exits)": 0.44,
    "VIX >= 13 subset": 0.80,
    "hold-to-expiry (F1)": 1.42,
}
STRUCTURE_ROLES = ("short", "long", "atm")
NUMERIC = ["strike", "bid", "ask", "half_spread", "model_slip_unit", "half_spread_to_model",
           "moneyness", "vix", "spot", "dte"]


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].replace("", np.nan), errors="coerce")
    return df


def _q(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {"n": 0, "median": np.nan, "mean": np.nan, "p90": np.nan}
    return {"n": int(len(s)), "median": float(s.median()), "mean": float(s.mean()),
            "p90": float(s.quantile(0.9))}


def summarize(df: pd.DataFrame) -> dict:
    ok = df[(df["quote_status"] == "ok") & df["half_spread_to_model"].notna()]
    struct = ok[ok["role"].isin(STRUCTURE_ROLES)]
    out = {
        "rows": int(len(df)),
        "snapshots": int(df["timestamp_ist"].nunique()) if len(df) else 0,
        "dates": int(pd.to_datetime(df["timestamp_ist"].str[:10], errors="coerce").nunique()) if len(df) else 0,
        "quote_status": df["quote_status"].value_counts().to_dict() if len(df) else {},
        "by_role": {r: _q(ok.loc[ok["role"] == r, "half_spread_to_model"]) for r in ("short", "long", "atm", "neighbour")},
        "by_role_half": {r: _q(ok.loc[ok["role"] == r, "half_spread"]) for r in ("short", "long", "atm", "neighbour")},
        "by_moneyness": {m: _q(ok.loc[ok["moneyness_bucket"] == m, "half_spread_to_model"])
                         for m in ("lt1pct", "1to2pct", "2to4pct", "gt4pct")},
        "structure_by_vix": {v: _q(struct.loc[struct["vix_bucket"] == v, "half_spread_to_model"])
                             for v in ("vix_lt13", "vix_ge13")},
        "structure_all": _q(struct["half_spread_to_model"]),
        "ratio_of_medians": (float(struct["half_spread"].median() / struct["model_slip_unit"].median())
                             if len(struct) else np.nan),
    }
    return out


def format_report(df: pd.DataFrame, min_snapshots: int = 20) -> str:
    if df.empty:
        return "QUOTE_LOG is empty (header only). Run scripts/log_option_quotes.py in the 11:00-13:00 IST window first."
    s = summarize(df)
    L = []
    L.append(f"rows {s['rows']}  snapshots {s['snapshots']}  distinct dates {s['dates']}")
    L.append("quote_status: " + ", ".join(f"{k}={v}" for k, v in sorted(s["quote_status"].items())))
    L.append("")
    L.append("half_spread_to_model (real half-spread / model per-unit slippage), two-sided quotes only")
    L.append(f"{'group':<26}{'n':>6}{'median':>10}{'mean':>10}{'p90':>10}")

    def line(label, q):
        f = lambda x: "-" if x != x else f"{x:.2f}x"  # noqa: E731
        L.append(f"{label:<26}{q['n']:>6}{f(q['median']):>10}{f(q['mean']):>10}{f(q['p90']):>10}")

    for r in ("short", "long", "atm", "neighbour"):
        line(f"role={r}", s["by_role"][r])
    for m in ("lt1pct", "1to2pct", "2to4pct", "gt4pct"):
        line(f"moneyness={m}", s["by_moneyness"][m])
    for v in ("vix_lt13", "vix_ge13"):
        line(f"structure legs {v}", s["structure_by_vix"][v])
    L.append("")
    sa = s["structure_all"]
    if sa["n"] == 0:
        L.append("No two-sided quotes on structure legs yet. No multiplier can be read.")
        return "\n".join(L)
    med_half = s["by_role_half"]
    L.append("structure legs (short/long/atm), all VIX:")
    L.append(f"  n={sa['n']}  median multiplier={sa['median']:.2f}x  mean={sa['mean']:.2f}x  p90={sa['p90']:.2f}x")
    L.append(f"  ratio of medians (median half / median model) = {s['ratio_of_medians']:.2f}x")
    L.append("  median real half-spread by role (Rs/unit): "
             + ", ".join(f"{r}={med_half[r]['median']:.2f}" for r in ("short", "long", "atm") if med_half[r]["n"]))
    L.append("")
    L.append("break-even axis (owner brief, multiples of model slippage):")
    for name, thr in BREAK_EVEN.items():
        side = "BELOW (cost tolerable)" if sa["median"] < thr else "ABOVE (cost too high)"
        L.append(f"  {name:<30} {thr:.2f}x  -> measured median {sa['median']:.2f}x is {side}")
    L.append("")
    if s["snapshots"] < min_snapshots:
        L.append(f"WARNING: only {s['snapshots']} snapshots (< {min_snapshots}). Treat the medians as indicative.")
    if s["dates"] < 5:
        L.append(f"WARNING: only {s['dates']} distinct dates. Intraday and day-of-week effects are not averaged out.")
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Summarise the real-quote log vs the slippage model.")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--min-snapshots", type=int, default=20)
    a = p.parse_args(argv)
    if not a.log.exists():
        print(f"No log at {a.log}. Nothing to summarise.")
        return 2
    print(format_report(load(a.log), a.min_snapshots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
