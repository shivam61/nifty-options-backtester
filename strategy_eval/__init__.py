"""Strategy-agnostic evaluation of option-selling strategies against the pre-registered pass rule.

Layers (import from here):
  schema     normalised trade table (columns, validation, CSV/pickle/JSON readers)
  adapters   chain-engine, run69-style and H9-style outputs -> normalised table
  stress     pure rescoring under credit haircut and slippage multipliers
  metrics    expectancy, payoff, tails, drawdown, per-year, exit mix, sizing and implied CAGR
  stats      year-cluster bootstrap, non-overlapping t-test, Holm, TestRegistry, year consistency
  hedge      hedged-vs-baseline scorecard
  verdict    pass rule with the BS cap and the development/holdout guard
  evaluate   run_evaluation(): all sections in one call
  report     markdown and JSON output

CLI: scripts/eval_strategy.py. Documentation: docs/STRATEGY_EVAL.md.
"""

from strategy_eval.adapters import (
    defined_max_loss_per_unit, from_chain_trades, from_h9_frame, from_run69_trades, load_trades,
)
from strategy_eval.evaluate import run_evaluation
from strategy_eval.hedge import hedge_scorecard
from strategy_eval.holdout_ledger import LedgerError, append_holdout_look, read_ledger
from strategy_eval.metrics import core_metrics, exit_reason_mix, per_year_table, sizing, vix_bucket_table
from strategy_eval.report import render_markdown, write_report
from strategy_eval.schema import (
    REQUIRED_COLUMNS, SchemaError, TRADE_COLUMNS, normalize, read_normalized, validate,
)
from strategy_eval.stats import (
    DEFAULT_REGISTRY_PATH, TestRegistry, deflated_sharpe_grid, deflated_sharpe_ratio, expected_max_sharpe,
    holm_adjust, monthly_block_bootstrap, resolve_registry, white_reality_check, year_cluster_bootstrap,
    year_consistency,
)
from strategy_eval.stress import stress_grid, stress_trades
from strategy_eval.verdict import DEV_END, DEV_START, evaluate_pass_rule

__all__ = [
    "REQUIRED_COLUMNS", "TRADE_COLUMNS", "SchemaError", "normalize", "validate", "read_normalized",
    "defined_max_loss_per_unit", "from_chain_trades", "from_h9_frame", "from_run69_trades", "load_trades",
    "stress_trades", "stress_grid", "core_metrics", "per_year_table", "exit_reason_mix", "sizing",
    "vix_bucket_table", "TestRegistry", "DEFAULT_REGISTRY_PATH", "resolve_registry",
    "holm_adjust", "year_cluster_bootstrap", "monthly_block_bootstrap", "year_consistency",
    "expected_max_sharpe", "deflated_sharpe_ratio", "deflated_sharpe_grid", "white_reality_check",
    "append_holdout_look", "read_ledger", "LedgerError",
    "hedge_scorecard", "evaluate_pass_rule", "DEV_START", "DEV_END", "run_evaluation", "render_markdown",
    "write_report",
]
