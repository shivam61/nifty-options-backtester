"""Hedge scorecard: a hedged variant against its unhedged baseline on the same entry dates.

Pairing: rows are matched on entry_date (per-date mean per-lot P&L in each table; dates present
in only one table are dropped). Both tables should already be stressed at the same cost level.

Reported:
  paired_diff_per_lot         mean of (hedged - baseline) per paired date, with a year-cluster bootstrap CI
  hedge_cost_pct_of_credit    mean hedge_cost_rs / mean credit_rs on the paired hedged rows
  p5_*, worst_*               baseline vs hedged tails, and the change
  tail_removed_per_lot        mean paired (hedged - baseline) over the baseline's worst 5% of dates
  hedge_cost_per_lot          mean hedge_cost_rs per paired date (per lot)
  decision                    DROP the hedge if hedge_cost_per_lot > tail_removed_per_lot, else KEEP
                              (N/A when the hedge costs nothing)

Decision rule (from the scorecard spec): drop a hedge whose cost exceeds the tail loss it removes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_eval.stats import DEFAULT_SEED, N_BOOT_DEFAULT, year_cluster_bootstrap
from strategy_eval.stress import per_lot


def _per_date(df: pd.DataFrame) -> pd.DataFrame:
    tmp = pd.DataFrame({
        "date": pd.to_datetime(df["entry_date"]).to_numpy(),
        "pl": per_lot(df, "pnl_net_rs"),
        "hedge_pl": df["hedge_cost_rs"].to_numpy(float) / df["lots"].to_numpy(float),
        "credit": df["credit_rs"].to_numpy(float),
        "lots": df["lots"].to_numpy(float),
    })
    return tmp.groupby("date").agg(pl=("pl", "mean"), hedge_pl=("hedge_pl", "mean"),
                                   credit=("credit", "mean"), lots=("lots", "mean"),
                                   n=("pl", "size")).reset_index()


def hedge_scorecard(hedged: pd.DataFrame, baseline: pd.DataFrame, *, tail_q: float = 5.0,
                    n_boot: int = N_BOOT_DEFAULT, seed: int = DEFAULT_SEED) -> dict:
    """Paired comparison of `hedged` against `baseline` on common entry dates. See module docstring."""
    h = _per_date(hedged).set_index("date")
    b = _per_date(baseline).set_index("date")
    common = h.index.intersection(b.index)
    if len(common) == 0:
        return {"n_pairs": 0, "decision": "INSUFFICIENT_DATA", "note": "no common entry dates"}
    h = h.loc[common]
    b = b.loc[common]
    diff = h["pl"].to_numpy() - b["pl"].to_numpy()
    years = pd.DatetimeIndex(common).year.to_numpy()
    ci = year_cluster_bootstrap(diff, years, n_boot=n_boot, seed=seed)

    credit_mean = float(h["credit"].mean())
    hedge_cost = float(h["hedge_pl"].mean())
    cost_pct = (hedge_cost / credit_mean * 100.0) if credit_mean > 0 else float("nan")

    bpl = b["pl"].to_numpy()
    hpl = h["pl"].to_numpy()
    p5_b, p5_h = float(np.percentile(bpl, tail_q)), float(np.percentile(hpl, tail_q))
    worst_b, worst_h = float(bpl.min()), float(hpl.min())
    tail_mask = bpl <= np.percentile(bpl, tail_q)
    tail_removed = float(diff[tail_mask].mean()) if tail_mask.any() else float("nan")

    if hedge_cost <= 1e-9:
        decision = "N/A (hedge costs nothing)"
    elif hedge_cost > tail_removed:
        decision = "DROP (hedge cost exceeds the tail loss it removes)"
    else:
        decision = "KEEP (tail loss removed exceeds hedge cost)"
    return {
        "n_pairs": int(len(common)),
        "paired_diff_per_lot": ci,
        "hedged_expectancy_per_lot": float(hpl.mean()),
        "baseline_expectancy_per_lot": float(bpl.mean()),
        "hedge_cost_per_lot": hedge_cost,
        "credit_per_lot": credit_mean,
        "hedge_cost_pct_of_credit": cost_pct,
        "tail_q_pct": tail_q,
        "p5_baseline": p5_b, "p5_hedged": p5_h, "p5_change": p5_h - p5_b,
        "worst_baseline": worst_b, "worst_hedged": worst_h, "worst_change": worst_h - worst_b,
        "tail_removed_per_lot": tail_removed,
        "decision": decision,
    }
