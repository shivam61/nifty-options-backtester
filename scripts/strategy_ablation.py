#!/usr/bin/env python3
"""
Strategy Ablation Study — isolate the contribution of each strategy.

Runs the backtest multiple times with different strategy subsets to measure
the marginal value of each strategy type. Results are logged to
BACKTEST_CHANGELOG.md and printed as a comparison table.

Usage:
    python scripts/strategy_ablation.py                       # Full ablation (5 configs)
    python scripts/strategy_ablation.py --quick               # Just PCS-only vs all
    python scripts/strategy_ablation.py --start 2019-01-01    # OOS only
    python scripts/strategy_ablation.py --use-multi-expiry    # With multi-expiry
"""
import argparse
import sys
import os
import json
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BacktestConfig
from data.market_data import MarketDataFetcher
from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from models.strategy_evolver import StrategyEvolver
from models.regime_aware_learner import RegimeAwareLearner
from backtester.engine import SmartBacktestEngine
from models.trade_monitor import ExitStrategyEngine
from strategies.multi_strategy import RegimeAdaptiveStrategy

ABLATION_CONFIGS = {
    "A: put_credit_spread only": {
        "strategies": ["put_credit_spread"],
        "description": "Simplest baseline — only sell put spreads",
    },
    "B: PCS + calendar": {
        "strategies": ["put_credit_spread", "calendar_spread"],
        "description": "Add the top performer — calendar spread",
    },
    "C: PCS + calendar + BWB": {
        "strategies": ["put_credit_spread", "calendar_spread", "broken_wing_butterfly"],
        "description": "Add asymmetric butterfly for VIX 18-22",
    },
    "D: PCS + calendar + BWB + ratio": {
        "strategies": ["put_credit_spread", "calendar_spread",
                       "broken_wing_butterfly", "ratio_put_spread"],
        "description": "Add tail-risk harvester for VIX 22+",
    },
    "E: All active (current)": {
        "strategies": ["put_credit_spread", "put_credit_wide", "calendar_spread",
                       "broken_wing_butterfly", "ratio_put_spread"],
        "description": "Current production config (all 5 strategies)",
    },
}

QUICK_CONFIGS = {
    "A: put_credit_spread only": ABLATION_CONFIGS["A: put_credit_spread only"],
    "E: All active (current)": ABLATION_CONFIGS["E: All active (current)"],
}


def run_ablation_config(
    config_name: str,
    allowed_strategies: list[str],
    data,
    config: BacktestConfig,
    exit_engine,
    entry_model,
    target_dte: int = 21,
    use_multi_expiry: bool = False,
) -> dict:
    """Run a single ablation config and return metrics."""
    strategy = RegimeAdaptiveStrategy(
        lots=config.max_lots,
        lot_size=config.lot_size,
        allowed_strategies=allowed_strategies,
    )
    engine = SmartBacktestEngine(
        strategy, data, config, target_dte,
        exit_engine=exit_engine,
        entry_model=entry_model,
        entry_threshold=0.55,
        compound=True,
        use_multi_expiry=use_multi_expiry,
    )
    result = engine.run()

    per_strategy = {}
    for t in result.trades:
        name = getattr(t, "strategy", "unknown")
        if name not in per_strategy:
            per_strategy[name] = {"trades": 0, "wins": 0, "pnl": 0}
        per_strategy[name]["trades"] += 1
        per_strategy[name]["pnl"] += t.total_pnl
        if t.total_pnl > 0:
            per_strategy[name]["wins"] += 1

    return {
        "config": config_name,
        "strategies_allowed": allowed_strategies,
        "total_trades": result.total_trades,
        "win_rate": round(result.win_rate, 1),
        "cagr_pct": round(result.cagr_pct, 2),
        "total_pnl": round(result.total_pnl),
        "total_return_pct": round(result.total_return_pct, 2),
        "sharpe": round(result.sharpe_ratio, 2),
        "sortino": round(result.sortino_ratio, 2),
        "calmar": round(result.calmar_ratio, 2),
        "max_drawdown_pct": round(result.max_drawdown_pct, 1),
        "profit_factor": round(result.profit_factor, 2),
        "avg_pnl_per_trade": round(result.avg_pnl_per_trade),
        "per_strategy": per_strategy,
    }


def print_comparison(results: list[dict]) -> None:
    """Print a formatted comparison table."""
    print(f"\n{'='*100}")
    print(f"  STRATEGY ABLATION COMPARISON")
    print(f"{'='*100}")

    header = f"{'Config':<35} {'Trades':>7} {'Win%':>6} {'CAGR':>7} {'Total P&L':>14} {'Sharpe':>7} {'MaxDD':>7} {'PF':>6} {'Calmar':>7}"
    print(f"\n{header}")
    print(f"{'-'*100}")

    for r in results:
        line = (
            f"{r['config']:<35} "
            f"{r['total_trades']:>7} "
            f"{r['win_rate']:>5.1f}% "
            f"{r['cagr_pct']:>6.2f}% "
            f"₹{r['total_pnl']:>12,} "
            f"{r['sharpe']:>7.2f} "
            f"{r['max_drawdown_pct']:>6.1f}% "
            f"{r['profit_factor']:>5.2f} "
            f"{r['calmar']:>7.2f}"
        )
        print(line)

    print(f"\n{'='*100}")

    if len(results) >= 2:
        baseline = results[0]
        best = max(results, key=lambda r: r["cagr_pct"])
        print(f"\n  MARGINAL VALUE ANALYSIS (vs {baseline['config']}):")
        print(f"  {'-'*80}")
        for r in results[1:]:
            delta_cagr = r["cagr_pct"] - baseline["cagr_pct"]
            delta_dd = r["max_drawdown_pct"] - baseline["max_drawdown_pct"]
            delta_trades = r["total_trades"] - baseline["total_trades"]
            delta_pnl = r["total_pnl"] - baseline["total_pnl"]
            print(
                f"  {r['config']:<35} "
                f"CAGR: {delta_cagr:+.2f}pp  "
                f"DD: {delta_dd:+.1f}pp  "
                f"Trades: {delta_trades:+d}  "
                f"P&L: ₹{delta_pnl:+,}"
            )

    print(f"\n  STRATEGY-LEVEL DETAIL (per config):")
    print(f"  {'-'*80}")
    for r in results:
        print(f"\n  {r['config']}:")
        for sname, stats in sorted(r["per_strategy"].items(), key=lambda x: -x[1]["pnl"]):
            wr = round(100 * stats["wins"] / stats["trades"], 1) if stats["trades"] else 0
            print(f"    {sname:<30} {stats['trades']:>4} trades  {wr:>5.1f}% WR  ₹{stats['pnl']:>+12,.0f}")

    print(f"\n{'='*100}")


def save_ablation_results(results: list[dict], use_multi_expiry: bool, config: BacktestConfig) -> None:
    """Save results to ablation_results.jsonl."""
    outpath = Path(__file__).resolve().parent.parent / "ablation_results.jsonl"
    from datetime import datetime
    record = {
        "timestamp": datetime.now().isoformat(),
        "period": f"{config.start_date} to {config.end_date}",
        "capital": config.initial_capital,
        "multi_expiry": use_multi_expiry,
        "configs": results,
    }
    with open(outpath, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"\n  Results saved to {outpath}")


def main():
    parser = argparse.ArgumentParser(description="Strategy Ablation Study")
    parser.add_argument("--start", type=str, default="2009-01-01")
    parser.add_argument("--end", type=str, default=str(date.today()))
    parser.add_argument("--capital", type=float, default=500000)
    parser.add_argument("--lots", type=int, default=15)
    parser.add_argument("--dte", type=int, default=21)
    parser.add_argument("--use-multi-expiry", action="store_true", default=False)
    parser.add_argument("--quick", action="store_true", default=False,
                        help="Only run PCS-only vs All (2 configs instead of 5)")
    args = parser.parse_args()

    config = BacktestConfig(
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        initial_capital=args.capital,
        max_lots=args.lots,
    )

    configs = QUICK_CONFIGS if args.quick else ABLATION_CONFIGS

    print(f"\n{'='*100}")
    print(f"  STRATEGY ABLATION STUDY")
    print(f"  Period: {config.start_date} to {config.end_date}")
    print(f"  Capital: ₹{config.initial_capital:,.0f} | Lots: {config.max_lots}")
    print(f"  Configs to test: {len(configs)}")
    print(f"  Multi-expiry: {args.use_multi_expiry}")
    print(f"{'='*100}")

    print(f"\n[1/{len(configs)+2}] Fetching market data...")
    fetcher = MarketDataFetcher(config.start_date, config.end_date)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days")

    print(f"\n[2/{len(configs)+2}] Training shared ML models (reused across all configs)...")
    train_cutoff = int(len(data) * 0.6)
    train_data = data.iloc[:train_cutoff]

    exit_engine = ExitStrategyEngine()
    cached_evolved = StrategyEvolver.load_from_cache()
    if cached_evolved:
        exit_engine.train_from_simulations(cached_evolved, verbose=False)
    else:
        from models.strategy_evolver import StrategyEvolver as SE
        se = SE(train_data, lots=config.max_lots, lot_size=config.lot_size)
        evolved = se.evolve(target="sharpe", entry_every_n_days=10, verbose=False)
        exit_engine.train_from_simulations(evolved, verbose=False)

    sim_cfg = SimConfig(lots=config.max_lots, lot_size=config.lot_size, entry_every_n_days=3)
    sim = RollingWindowSimulator(train_data, config=sim_cfg)
    sim_trades = sim.simulate_all()
    entry_model = RegimeAwareLearner()
    entry_model.train(sim_trades, train_data, verbose=False)

    results = []
    for i, (name, cfg) in enumerate(configs.items(), 1):
        step = i + 2
        print(f"\n[{step}/{len(configs)+2}] Running: {name}")
        print(f"  Strategies: {cfg['strategies']}")
        print(f"  {cfg['description']}")

        r = run_ablation_config(
            name, cfg["strategies"], data, config,
            exit_engine, entry_model, args.dte, args.use_multi_expiry,
        )
        results.append(r)
        print(f"  -> CAGR: {r['cagr_pct']:.2f}% | Trades: {r['total_trades']} | "
              f"Win: {r['win_rate']:.1f}% | P&L: ₹{r['total_pnl']:,}")

    print_comparison(results)
    save_ablation_results(results, args.use_multi_expiry, config)


if __name__ == "__main__":
    main()
