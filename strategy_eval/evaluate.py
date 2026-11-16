"""End-to-end evaluation: window, stress, metrics, sizing, hedge scorecard and the pass-rule verdict."""

from __future__ import annotations

import pandas as pd

from strategy_eval.hedge import hedge_scorecard
from strategy_eval.metrics import core_metrics, exit_reason_mix, per_year_table, sizing, vix_bucket_table
from strategy_eval.stats import DEFAULT_SEED, N_BOOT_DEFAULT, TestRegistry, resolve_registry
from strategy_eval.stress import HAIRCUTS_DEFAULT, SLIPPAGE_DEFAULT, stress_grid, stress_trades
from strategy_eval.verdict import (
    VERDICT_HAIRCUT, VERDICT_SLIPPAGE, apply_windows, evaluate_pass_rule,
)


def run_evaluation(candidate: pd.DataFrame, baseline: pd.DataFrame | None = None, *,
                   name: str = "candidate", capital: float = 2_500_000.0, risk_cap: float = 50_000.0,
                   allow_holdout: bool = False, registry: TestRegistry | None = None,
                   n_boot: int = N_BOOT_DEFAULT, seed: int = DEFAULT_SEED) -> dict:
    """Run every section of the evaluation on normalised tables. Returns a plain dict."""
    registry = resolve_registry(registry)     # None -> logs/eval_registry.json
    verdict = evaluate_pass_rule(candidate, baseline, allow_holdout=allow_holdout, registry=registry,
                                 name=name, n_boot=n_boot, seed=seed)
    cand_w, _ = apply_windows(candidate, allow_holdout)
    cand_v = stress_trades(cand_w, VERDICT_HAIRCUT, VERDICT_SLIPPAGE)
    result = {
        "name": name,
        "capital": capital,
        "risk_cap": risk_cap,
        "allow_holdout": allow_holdout,
        "verdict": verdict,
        "metrics": {
            "at_verdict_cost": core_metrics(cand_v),
            "at_1x": core_metrics(cand_w),
        },
        "stress_grid": stress_grid(cand_w, HAIRCUTS_DEFAULT, SLIPPAGE_DEFAULT).to_dict("records"),
        "per_year": per_year_table(cand_v).to_dict("records"),
        "vix_buckets": vix_bucket_table(cand_v),
        "exit_mix": exit_reason_mix(cand_v).to_dict("records"),
        "sizing": sizing(cand_v, capital, risk_cap),
        "scorecard": None,
        "base_haircut_pct": float(candidate["base_haircut_pct"].max()) if len(candidate) else 0.0,
        "registry": registry.to_dict(),
    }
    if baseline is not None:
        base_w, _ = apply_windows(baseline, allow_holdout)
        base_v = stress_trades(base_w, VERDICT_HAIRCUT, VERDICT_SLIPPAGE)
        if len(cand_v) and len(base_v):
            result["scorecard"] = hedge_scorecard(cand_v, base_v, n_boot=n_boot, seed=seed)
        result["baseline_metrics"] = {"at_verdict_cost": core_metrics(base_v)}
    return result
