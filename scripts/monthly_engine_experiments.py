#!/usr/bin/env python3
"""
Monthly engine experiment matrix.

Runs the monthly-only backtest under a set of controlled variants so we can
compare:
  - sleeve pruning
  - regime-aware reranking
  - sizing relaxation
  - gate relaxation

The script uses the same walk-forward model schedule as main.py and writes a
compact markdown report to results/monthly_engine_experiments.md.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtester.engine import SmartBacktestEngine
from backtester.walk_forward import WalkForwardManager
from config import BacktestConfig
from data.market_data import MarketDataFetcher
from strategies.multi_strategy import RegimeAdaptiveStrategy


REPORT_PATH = Path(__file__).resolve().parent.parent / "results" / "monthly_engine_experiments.md"


def _regime_from_vix(vix: float) -> str:
    if vix < 14:
        return "LOW_VOL"
    if vix < 18:
        return "TRENDING"
    if vix < 25:
        return "HIGH_VOL"
    return "CRASH"


def _trade_rows(trades: list) -> list[dict]:
    rows = []
    for t in trades:
        rows.append({
            "strategy": getattr(t, "strategy", None) or getattr(t, "strategy_name", "unknown"),
            "entry_vix": getattr(t, "entry_vix", 0.0),
            "exit_vix": getattr(t, "exit_vix", 0.0),
            "holding_days": getattr(t, "holding_days", 0),
            "pnl": getattr(t, "total_pnl", 0.0),
        })
    return rows


def _per_strategy_metrics(trades: list) -> dict[str, dict]:
    buckets = defaultdict(list)
    for row in _trade_rows(trades):
        buckets[row["strategy"]].append(row)
    out = {}
    for strategy, rows in buckets.items():
        pnls = np.array([r["pnl"] for r in rows], dtype=float)
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        gross_win = wins.sum() if len(wins) else 0.0
        gross_loss = abs(losses.sum()) if len(losses) else 1.0
        out[strategy] = {
            "trades": len(rows),
            "pnl": round(float(pnls.sum())),
            "win_rate": round(float((pnls > 0).mean() * 100), 1) if len(pnls) else 0.0,
            "avg_hold": round(float(np.mean([r["holding_days"] for r in rows])), 1) if rows else 0.0,
            "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else float("inf"),
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["pnl"], reverse=True))


def _regime_matrix(trades: list) -> dict[str, dict]:
    matrix = defaultdict(lambda: defaultdict(lambda: {"trades": 0, "pnl": 0.0}))
    for row in _trade_rows(trades):
        regime = _regime_from_vix(row["entry_vix"])
        cell = matrix[regime][row["strategy"]]
        cell["trades"] += 1
        cell["pnl"] += row["pnl"]
    return {
        regime: {
            strategy: {"trades": stats["trades"], "pnl": round(stats["pnl"], 0)}
            for strategy, stats in sorted(strategy_map.items(), key=lambda kv: kv[1]["pnl"], reverse=True)
        }
        for regime, strategy_map in matrix.items()
    }


def _variant_configs(base: BacktestConfig) -> list[tuple[str, BacktestConfig, dict]]:
    weak_baseline = BacktestConfig(**{
        **base.__dict__,
        "monthly_enable_regime_rerank": False,
        "monthly_high_vol_scale": 0.65,
        "monthly_trending_scale": 0.85,
        "monthly_crash_scale": 0.35,
        "monthly_confidence_low_scale": 0.80,
        "monthly_confidence_neutral_scale": 1.00,
        "monthly_confidence_high_scale": 1.20,
        "monthly_dd_scale_1": 1.00,
        "monthly_dd_scale_2": 0.75,
        "monthly_dd_scale_3": 0.50,
        "monthly_dd_scale_4": 0.25,
    })
    return [
        (
            "1. Baseline current monthly",
            weak_baseline,
            {"allow_bwb": True},
        ),
        (
            "2. Baseline minus BWB",
            BacktestConfig(**{
                **weak_baseline.__dict__,
                "monthly_disable_bwb": True,
            }),
            {"allow_bwb": False},
        ),
        (
            "3. Sleeve reranking only",
            BacktestConfig(**{
                **weak_baseline.__dict__,
                "monthly_enable_regime_rerank": True,
            }),
            {"allow_bwb": True},
        ),
        (
            "4. Rerank + moderate HIGH_VOL sizing",
            BacktestConfig(**{
                **weak_baseline.__dict__,
                "monthly_enable_regime_rerank": True,
                "monthly_high_vol_scale": 0.85,
                "monthly_confidence_low_scale": 0.95,
                "monthly_dd_scale_2": 0.90,
                "monthly_dd_scale_3": 0.70,
            }),
            {"allow_bwb": True},
        ),
        (
            "5. Rerank + calibrated gate relaxation",
            BacktestConfig(**{
                **weak_baseline.__dict__,
                "monthly_enable_regime_rerank": True,
                "monthly_entry_threshold": 0.46,
            }),
            {
                "allow_bwb": True,
                "crash_risk_v2_block": 0.85,
                "multi_asset_stress_block": 0.85,
                "correction_50d_block": -18.0,
                "vix_accel_block": 60.0,
                "crude_shock_block": 35.0,
            },
        ),
        (
            "6. Rerank + prune + sizing",
            BacktestConfig(**{
                **weak_baseline.__dict__,
                "monthly_enable_regime_rerank": True,
                "monthly_disable_bwb": True,
                "monthly_high_vol_scale": 0.85,
                "monthly_confidence_low_scale": 0.95,
                "monthly_dd_scale_2": 0.90,
                "monthly_dd_scale_3": 0.70,
            }),
            {"allow_bwb": False},
        ),
    ]


def run_variant(label: str, config: BacktestConfig, strategy_kwargs: dict, data: pd.DataFrame) -> dict:
    wf_manager = WalkForwardManager(
        data,
        monthly_config=config,
        include_monthly=True,
        train_on_cache_miss=False,
        retrain_interval_bars=21,
    )
    strategy = RegimeAdaptiveStrategy(
        lots=config.max_lots,
        lot_size=config.lot_size,
        allow_bwb=strategy_kwargs.get("allow_bwb", True),
        crash_risk_v2_block=strategy_kwargs.get("crash_risk_v2_block", 0.80),
        multi_asset_stress_block=strategy_kwargs.get("multi_asset_stress_block", 0.80),
        correction_50d_block=strategy_kwargs.get("correction_50d_block", -15.0),
        vix_accel_block=strategy_kwargs.get("vix_accel_block", 50.0),
        crude_shock_block=strategy_kwargs.get("crude_shock_block", 30.0),
    )
    engine = SmartBacktestEngine(
        strategy,
        data,
        config,
        target_dte=21,
        entry_threshold=config.monthly_entry_threshold,
        walk_forward_manager=wf_manager,
    )
    result = engine.run()
    diagnostics = dict(result.diagnostics or {})
    return {
        "label": label,
        "result": result,
        "diagnostics": diagnostics,
        "per_strategy": _per_strategy_metrics(result.trades),
        "regime_matrix": _regime_matrix(result.trades),
    }


def _render_markdown(rows: list[dict]) -> str:
    lines = [
        "# Monthly Engine Experiment Matrix",
        "",
        "| Variant | CAGR | P&L | MaxDD | Sharpe | Calmar | Trades | Capital Util | Flat Days | Avg Lots |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        r = row["result"]
        d = row["diagnostics"]
        lines.append(
            f"| {row['label']} | {r.cagr_pct:.2f}% | ₹{r.total_pnl:,.0f} | {r.max_drawdown_pct:.1f}% | "
            f"{r.sharpe_ratio:.2f} | {r.calmar_ratio:.2f} | {r.total_trades} | "
            f"{d.get('capital_utilization_pct', 0):.1f}% | {d.get('flat_days_pct', 0):.1f}% | {d.get('avg_lots', 0):.1f} |"
        )
    lines.append("")
    for row in rows:
        r = row["result"]
        d = row["diagnostics"]
        lines.extend([
            f"## {row['label']}",
            "",
            f"- CAGR: {r.cagr_pct:.2f}%",
            f"- Total P&L: ₹{r.total_pnl:,.0f}",
            f"- Max DD: {r.max_drawdown_pct:.1f}%",
            f"- Sharpe: {r.sharpe_ratio:.2f}",
            f"- Calmar: {r.calmar_ratio:.2f}",
            f"- Trades: {r.total_trades}",
            f"- Capital utilization: {d.get('capital_utilization_pct', 0):.1f}%",
            f"- Flat days: {d.get('flat_days_pct', 0):.1f}%",
            f"- Avg lots: {d.get('avg_lots', 0):.1f}",
            "",
            "### Per-sleeve",
        ])
        for sname, stats in row["per_strategy"].items():
            lines.append(
                f"- {sname}: {stats['trades']} trades, ₹{stats['pnl']:,.0f}, "
                f"{stats['win_rate']:.1f}% WR, PF {stats['profit_factor']:.2f}, hold {stats['avg_hold']:.1f}d"
            )
        lines.append("")
        lines.append("### Regime x Sleeve")
        for regime, strategy_map in row["regime_matrix"].items():
            lines.append(f"- {regime}:")
            for sname, stats in strategy_map.items():
                lines.append(f"  - {sname}: {stats['trades']} trades, ₹{stats['pnl']:,.0f}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monthly engine experiment matrix")
    parser.add_argument("--start", type=str, default="2009-01-01")
    parser.add_argument("--end", type=str, default=str(date.today()))
    parser.add_argument("--capital", type=float, default=500_000)
    parser.add_argument("--lots", type=int, default=15)
    args = parser.parse_args()

    base = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.lots,
    )

    print(f"Fetching market data for {base.start_date} to {base.end_date}...")
    fetcher = MarketDataFetcher(base.start_date, base.end_date)
    data = fetcher.build_combined_dataset()
    print(f"Loaded {len(data)} rows")

    variants = _variant_configs(base)
    results = []
    for label, cfg, strategy_kwargs in variants:
        print(f"Running {label}...")
        results.append(run_variant(label, cfg, strategy_kwargs, data))

    markdown = _render_markdown(results)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(markdown)
    print(f"\nSaved report to {REPORT_PATH}")

    print(f"\n{'Variant':<34} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8} {'Calmar':>8} {'Trades':>8} {'Util%':>8}")
    print(f"{'-'*86}")
    for row in results:
        r = row["result"]
        d = row["diagnostics"]
        print(
            f"{row['label']:<34} {r.cagr_pct:>7.2f}% {r.max_drawdown_pct:>7.1f}% {r.sharpe_ratio:>8.2f} "
            f"{r.calmar_ratio:>8.2f} {r.total_trades:>8} {d.get('capital_utilization_pct', 0):>7.1f}%"
        )


if __name__ == "__main__":
    main()
