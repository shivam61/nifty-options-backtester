#!/usr/bin/env python3
"""
Monthly diagnostic audit runner.

Produces:
  - results/monthly_diagnostic_report/*
  - results/root_cause_summary.md
  - results/ablation_results.md

The audit runs a small set of monthly-only ablations against the current
combined backtest pipeline. It keeps the walk-forward schedule fixed and only
changes the monthly decision policy knobs.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester.combined_engine import CombinedBacktestEngine
from backtester.walk_forward import WalkForwardManager
from config import BacktestConfig, WeeklyBacktestConfig
from data.market_data import MarketDataFetcher
from strategies.multi_strategy import RegimeAdaptiveStrategy


RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
REPORT_DIR = RESULTS_DIR / "monthly_diagnostic_report"


def _build_engine(
    data: pd.DataFrame,
    monthly_config: BacktestConfig,
    weekly_config: WeeklyBacktestConfig,
    wf_manager: WalkForwardManager,
    *,
    entry_threshold: float,
    monthly_exit_min_hold_days: int = 0,
    monthly_exit_profit_target_scale: float = 1.0,
    monthly_exit_stop_loss_scale: float = 1.0,
    monthly_exit_trailing_arm_pct: float = 25.0,
    monthly_exit_trailing_drop_pct: float = 35.0,
    monthly_max_margin_per_trade_pct: float | None = None,
    monthly_max_risk_per_trade_pct: float | None = None,
    use_model_threshold: bool = True,
    rule_based: bool = False,
) -> CombinedBacktestEngine:
    cfg = replace(
        monthly_config,
        monthly_exit_min_hold_days=monthly_exit_min_hold_days,
        monthly_exit_profit_target_scale=monthly_exit_profit_target_scale,
        monthly_exit_stop_loss_scale=monthly_exit_stop_loss_scale,
        monthly_exit_trailing_arm_pct=monthly_exit_trailing_arm_pct,
        monthly_exit_trailing_drop_pct=monthly_exit_trailing_drop_pct,
        monthly_max_margin_per_trade_pct=(
            monthly_max_margin_per_trade_pct
            if monthly_max_margin_per_trade_pct is not None
            else monthly_config.monthly_max_margin_per_trade_pct
        ),
        monthly_max_risk_per_trade_pct=(
            monthly_max_risk_per_trade_pct
            if monthly_max_risk_per_trade_pct is not None
            else monthly_config.monthly_max_risk_per_trade_pct
        ),
        monthly_entry_threshold=entry_threshold,
    )
    strategy = RegimeAdaptiveStrategy(
        lots=cfg.max_lots,
        lot_size=cfg.lot_size,
        allow_bwb=not cfg.monthly_disable_bwb,
    )
    engine = CombinedBacktestEngine(
        data=data,
        monthly_config=cfg,
        weekly_config=weekly_config,
        monthly_strategy=strategy,
        exit_engine=None,
        entry_model=None,
        entry_threshold=entry_threshold,
        monthly_budget_pct=0.70,
        weekly_budget_pct=0.30,
        walk_forward_manager=wf_manager,
    )
    if not use_model_threshold:
        engine._monthly_model_threshold = lambda: None  # type: ignore[method-assign]
    if rule_based:
        engine.entry_model = None
        engine._monthly_model_threshold = lambda: None  # type: ignore[method-assign]
    return engine


def _flatten_report(name: str, result, diagnostics: dict[str, Any]) -> dict[str, Any]:
    td = diagnostics.get("trade_distribution", {})
    ed = diagnostics.get("exit_decomposition", {})
    af = diagnostics.get("acceptance_funnel", {})
    sz = diagnostics.get("sizing", {})
    model = diagnostics.get("model", {})
    yearly_pnl = td.get("yearly_pnl", {})
    years = len(yearly_pnl)
    positive_years = sum(1 for v in yearly_pnl.values() if v > 0)
    yearly_consistency = round(positive_years / years * 100, 1) if years else 0.0
    return {
        "variant": name,
        "trades": result.monthly_trades,
        "win_rate": result.monthly_win_rate,
        "total_pnl": result.monthly_pnl,
        "cagr": result.cagr_pct,
        "sharpe": result.sharpe_ratio,
        "calmar": result.calmar_ratio,
        "max_dd": result.max_drawdown_pct,
        "profit_factor": result.profit_factor,
        "avg_pnl_trade": td.get("avg_pnl", 0.0),
        "utilization": result.capital_utilization_pct,
        "yearly_consistency": yearly_consistency,
        "avg_final_lots": sz.get("avg_final_lots", 0.0),
        "winner_cut_early_pct": ed.get("winner_cut_early_pct", 0.0),
        "avg_realized_vs_max_attainable": ed.get("avg_realized_vs_max_attainable", 0.0),
        "accepted_rate": af.get("accepted_rate", 0.0),
        "near_miss_count": af.get("near_miss_count", 0),
        "threshold": model.get("calibration_buckets", []),
        "diagnostics": diagnostics,
    }


def _render_ablation_md(rows: list[dict[str, Any]]) -> str:
    header = [
        "# Monthly Ablation Results",
        "",
        "| Variant | Trades | Win% | P&L | CAGR | Sharpe | Calmar | MaxDD | PF | Avg P&L/Trade | Utilization | Yearly Consistency | Avg Lots |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines = list(header)
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['trades']} | {row['win_rate']:.1f}% | ₹{row['total_pnl']:,.0f} | "
            f"{row['cagr']:.2f}% | {row['sharpe']:.2f} | {row['calmar']:.2f} | {row['max_dd']:.1f}% | "
            f"{row['profit_factor']:.2f} | ₹{row['avg_pnl_trade']:,.0f} | {row['utilization']:.1f}% | "
            f"{row['yearly_consistency']:.1f}% | {row['avg_final_lots']:.1f} |"
        )
    return "\n".join(lines)


def _derive_root_cause(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    baseline = rows[0]
    td = baseline["diagnostics"].get("trade_distribution", {})
    ed = baseline["diagnostics"].get("exit_decomposition", {})
    af = baseline["diagnostics"].get("acceptance_funnel", {})
    sz = baseline["diagnostics"].get("sizing", {})
    model = baseline["diagnostics"].get("model", {})
    top_decile = td.get("score_decile_pnl", {}).get("10", 0.0)
    bottom_half = sum(v for k, v in td.get("score_decile_pnl", {}).items() if int(k) <= 5)
    threshold_buckets = model.get("calibration_buckets", [])
    best = max(rows, key=lambda r: r["total_pnl"])

    causes = []
    if sz.get("avg_final_lots", 0) <= 3:
        causes.append("Sizing is materially defensive: average monthly lots are low, so a reasonable edge is under-monetized.")
    if ed.get("winner_cut_early_pct", 0) >= 25 or ed.get("avg_realized_vs_max_attainable", 1.0) < 0.75:
        causes.append("Exit policy is truncating winners: realised P&L is capturing too little of observed favourable excursion.")
    if top_decile <= 0 or bottom_half < 0:
        causes.append("Score separation is weak: lower-score trades are not paying for themselves, and top-decile signals are not decisively positive.")
    if af.get("near_miss_count", 0) > 0 and af.get("accepted_rate", 0) < 50:
        causes.append("Thresholding is likely miscalibrated: there are many near misses around the cutoff, which suggests the gate needs calibration.")
    if len(threshold_buckets) and max((b.get("profit_factor", 0) for b in threshold_buckets if b.get("profit_factor") != "inf"), default=0) > 1.2:
        causes.append("A tighter threshold appears promising based on validation-fold sweep.")
    if not causes:
        causes.append("Monthly edge looks fragile after leakage-safe cleanup; the implementation may be fine but the edge is not strong enough.")

    conclusion = "Monthly ML edge is not robust"
    if best["total_pnl"] > baseline["total_pnl"] * 1.5 and best["profit_factor"] > baseline["profit_factor"]:
        conclusion = "Monthly should trade less, but better"
    elif sz.get("avg_final_lots", 0) <= 3 and best["avg_final_lots"] > baseline["avg_final_lots"]:
        conclusion = "Monthly should get smaller allocation"

    lines = [
        "# Root Cause Summary",
        "",
        f"Conclusion: **{conclusion}**",
        "",
        "## Ranked Causes",
    ]
    for idx, cause in enumerate(causes, 1):
        lines.append(f"{idx}. {cause}")
    lines += [
        "",
        "## Evidence",
        f"- Baseline monthly trades: {baseline['trades']}",
        f"- Baseline monthly P&L: ₹{baseline['total_pnl']:,.0f}",
        f"- Baseline avg final lots: {baseline['avg_final_lots']:.1f}",
        f"- Baseline winner cut early: {ed.get('winner_cut_early_pct', 0):.1f}%",
        f"- Baseline realized vs max attainable: {ed.get('avg_realized_vs_max_attainable', 0):.3f}",
        f"- Baseline acceptance rate: {af.get('accepted_rate', 0):.1f}%",
        f"- Best ablation: {best['variant']} with ₹{best['total_pnl']:,.0f} and {best['win_rate']:.1f}% WR",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run monthly diagnostic audit")
    parser.add_argument("--start", type=str, default="2009-01-01")
    parser.add_argument("--end", type=str, default=str(date.today()))
    parser.add_argument("--capital", type=float, default=500000.0)
    parser.add_argument("--weekly-lots", type=int, default=10)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    monthly_config = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
    )
    weekly_config = WeeklyBacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.weekly_lots,
    )

    fetcher = MarketDataFetcher(monthly_config.start_date, monthly_config.end_date)
    data = fetcher.build_combined_dataset()
    wf_manager = WalkForwardManager(
        data,
        monthly_config=monthly_config,
        weekly_config=weekly_config,
        include_monthly=True,
        include_weekly_entry=False,
        include_weekly_risk=False,
        train_on_cache_miss=False,
        retrain_interval_bars=21,
    )

    variants = [
        (
            "1. Baseline strict current monthly",
            dict(entry_threshold=monthly_config.monthly_entry_threshold, use_model_threshold=False),
        ),
        (
            "2. Strict + rolling retrain",
            dict(entry_threshold=monthly_config.monthly_entry_threshold, use_model_threshold=True),
        ),
        (
            "3. Rolling retrain + recalibrated threshold",
            dict(entry_threshold=0.55, use_model_threshold=False),
        ),
        (
            "4. + revised exit",
            dict(
                entry_threshold=monthly_config.monthly_entry_threshold,
                use_model_threshold=True,
                monthly_exit_min_hold_days=3,
                monthly_exit_profit_target_scale=1.15,
                monthly_exit_stop_loss_scale=0.95,
            ),
        ),
        (
            "5. + revised sizing",
            dict(
                entry_threshold=monthly_config.monthly_entry_threshold,
                use_model_threshold=True,
                monthly_max_margin_per_trade_pct=30.0,
                monthly_max_risk_per_trade_pct=25.0,
            ),
        ),
        (
            "6. Best combined fix",
            dict(
                entry_threshold=monthly_config.monthly_entry_threshold,
                use_model_threshold=True,
                monthly_exit_min_hold_days=3,
                monthly_exit_profit_target_scale=1.15,
                monthly_exit_stop_loss_scale=0.95,
                monthly_max_margin_per_trade_pct=30.0,
                monthly_max_risk_per_trade_pct=25.0,
            ),
        ),
        (
            "7. Reduced-frequency high-conviction monthly",
            dict(
                entry_threshold=0.58,
                use_model_threshold=False,
                monthly_exit_min_hold_days=3,
            ),
        ),
        (
            "8. Simplified rule-based monthly",
            dict(entry_threshold=monthly_config.monthly_entry_threshold, use_model_threshold=False, rule_based=True),
        ),
    ]

    rows: list[dict[str, Any]] = []
    baseline_diag: dict[str, Any] | None = None
    for label, params in variants:
        engine = _build_engine(
            data,
            monthly_config,
            weekly_config,
            wf_manager,
            entry_threshold=params["entry_threshold"],
            monthly_exit_min_hold_days=params.get("monthly_exit_min_hold_days", 0),
            monthly_exit_profit_target_scale=params.get("monthly_exit_profit_target_scale", 1.0),
            monthly_exit_stop_loss_scale=params.get("monthly_exit_stop_loss_scale", 1.0),
            monthly_exit_trailing_arm_pct=params.get("monthly_exit_trailing_arm_pct", 25.0),
            monthly_exit_trailing_drop_pct=params.get("monthly_exit_trailing_drop_pct", 35.0),
            monthly_max_margin_per_trade_pct=params.get("monthly_max_margin_per_trade_pct"),
            monthly_max_risk_per_trade_pct=params.get("monthly_max_risk_per_trade_pct"),
            use_model_threshold=params.get("use_model_threshold", True),
            rule_based=params.get("rule_based", False),
        )
        result = engine.run()
        diagnostics = result.diagnostics or engine.monthly_diagnostics.summary()
        row = _flatten_report(label, result, diagnostics)
        rows.append(row)
        if baseline_diag is None:
            baseline_diag = diagnostics
            engine.monthly_diagnostics.write_artifacts(REPORT_DIR)

    rows_sorted = rows
    (REPORT_DIR / "ablation_results.md").write_text(_render_ablation_md(rows_sorted))
    (REPORT_DIR / "ablation_results.json").write_text(json.dumps(rows_sorted, indent=2, default=str))
    root_cause_md = _derive_root_cause(baseline_diag or {}, rows_sorted)
    (REPORT_DIR / "root_cause_summary.md").write_text(root_cause_md)

    print(f"Monthly diagnostic artifacts written to {REPORT_DIR}")
    print(f"- {REPORT_DIR / 'monthly_diagnostic_report.md'}")
    print(f"- {REPORT_DIR / 'ablation_results.md'}")
    print(f"- {REPORT_DIR / 'root_cause_summary.md'}")


if __name__ == "__main__":
    main()
