#!/usr/bin/env python3
"""
Slippage & friction stress test for the combined monthly+weekly backtest.

Runs 4 CostModel scenarios against a single 17yr market-data load, then
prints a comparison table showing how CAGR, Sharpe, Max DD, and P&L degrade
as execution friction increases.

Scenarios (all run with mid-session fill proxy — nifty_mid_session + 0.75× slip scale)
---------
  S0  baseline   base_slip=0.30, vix_scale=0.04  (production defaults × 0.75 mid-session)
  S1  mild       base_slip=0.50, vix_scale=0.06  (+67% base slip vs baseline)
  S2  moderate   base_slip=0.75, vix_scale=0.08  (+150% base slip; illiquid / expiry day)
  S3  severe     base_slip=1.20, vix_scale=0.12  (+300% base slip; crisis wide-bid blowout)

Fixed costs (STT, exchange, stamp, SEBI, brokerage, GST) are held constant across
all scenarios — only the variable bid-ask slippage component changes.

Usage
-----
    python scripts/slippage_stress_test.py
    python scripts/slippage_stress_test.py --capital 1000000 --start 2015-01-01
"""

import argparse
import copy
import sys
import os
from datetime import date
from dataclasses import replace

# Make sure repo root is on path when run from scripts/
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config import BacktestConfig, WeeklyBacktestConfig, CostModel
from backtester.combined_engine import CombinedBacktestEngine
from backtester.production_rules import ProductionRulesConfig
from data.market_data import MarketDataFetcher
from models.regime_aware_learner import RegimeAwareLearner
from models.trade_monitor import ExitStrategyEngine
from models.weekly_risk_engine import load_risk_engine
from strategies.multi_strategy import RegimeAdaptiveStrategy


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "S0 baseline",
        "desc": "current defaults (0.30 + 0.04×VIX)",
        "base_slippage_per_unit": 0.30,
        "slippage_vix_scale": 0.04,
    },
    {
        "name": "S1 mild",
        "desc": "+67% slip (0.50 + 0.06×VIX)",
        "base_slippage_per_unit": 0.50,
        "slippage_vix_scale": 0.06,
    },
    {
        "name": "S2 moderate",
        "desc": "+150% slip (0.75 + 0.08×VIX)",
        "base_slippage_per_unit": 0.75,
        "slippage_vix_scale": 0.08,
    },
    {
        "name": "S3 severe",
        "desc": "+300% slip (1.20 + 0.12×VIX)",
        "base_slippage_per_unit": 1.20,
        "slippage_vix_scale": 0.12,
    },
]


# ── Cost at typical conditions (VIX=16, 4-leg trade, 1 lot) ──────────────────

def slip_example(sc: dict, vix: float = 16.0, legs: int = 4) -> float:
    """Slippage per unit × legs at a representative VIX level."""
    base = sc["base_slippage_per_unit"]
    scale = sc["slippage_vix_scale"]
    per_unit = base + max(0, vix - 15) * scale
    return per_unit * legs  # total slip charge per share across all legs


# ── Engine runner (reuses pre-loaded data and models) ────────────────────────

def run_scenario(sc: dict, data, config: BacktestConfig, wc: WeeklyBacktestConfig,
                 entry_model, exit_engine, weekly_risk_engine) -> dict:
    """Run one cost scenario. Returns a flat dict of key metrics."""

    # Clone cost models with modified slippage — all other cost components unchanged
    m_cost = replace(
        config.cost_model,
        base_slippage_per_unit=sc["base_slippage_per_unit"],
        slippage_vix_scale=sc["slippage_vix_scale"],
    )
    w_cost = replace(
        wc.cost_model,
        base_slippage_per_unit=sc["base_slippage_per_unit"],
        slippage_vix_scale=sc["slippage_vix_scale"],
    )

    # Deep-copy configs so they don't bleed between scenarios
    m_cfg = copy.copy(config)
    m_cfg.cost_model = m_cost

    w_cfg = copy.copy(wc)
    w_cfg.cost_model = w_cost

    strategy = RegimeAdaptiveStrategy(
        lots=m_cfg.max_lots,
        lot_size=m_cfg.lot_size,
        allow_bwb=not m_cfg.monthly_disable_bwb,
    )

    engine = CombinedBacktestEngine(
        data=data,
        monthly_config=m_cfg,
        weekly_config=w_cfg,
        monthly_strategy=strategy,
        exit_engine=exit_engine,
        entry_model=entry_model,
        weekly_risk_engine=weekly_risk_engine,
        entry_threshold=m_cfg.monthly_entry_threshold,
        monthly_budget_pct=0.50,
        weekly_budget_pct=0.50,
        cross_track_dd_pct=0.15,
        vix_simultaneous_cap=25.0,
        production_rules=ProductionRulesConfig(
            dd_kill_pct=0.20,
            dd_recovery_pct=0.16,
            dd_cooldown_days=3,
            block_events=True,
            enforce_no_naked=True,
            enforce_hedge_ratio=True,
            max_spread_width_pct=3.0,
        ),
        walk_forward_manager=None,
    )

    r = engine.run()
    return {
        "scenario":        sc["name"],
        "desc":            sc["desc"],
        "slip_4leg_vix16": slip_example(sc),
        "cagr_pct":        r.cagr_pct,
        "sharpe":          r.sharpe_ratio,
        "calmar":          r.calmar_ratio,
        "max_dd_pct":      r.max_drawdown_pct,
        "total_pnl":       r.total_pnl,
        "monthly_pnl":     r.monthly_pnl,
        "weekly_pnl":      r.weekly_pnl,
        "monthly_wr":      r.monthly_win_rate,
        "weekly_wr":       r.weekly_win_rate,
        "monthly_trades":  r.monthly_trades,
        "weekly_trades":   r.weekly_trades,
        "profit_factor":   r.profit_factor,
    }


# ── Comparison table printer ──────────────────────────────────────────────────

def print_table(rows: list[dict]) -> None:
    baseline = rows[0]

    # Header
    print()
    print("━" * 110)
    print(f"  {'SLIPPAGE STRESS TEST':^106}")
    print("━" * 110)
    hdr = (
        f"  {'Scenario':<14} {'Slip/leg*':<11} {'CAGR':>7} {'Δ CAGR':>8} "
        f"{'Sharpe':>7} {'Calmar':>7} {'Max DD':>7} "
        f"{'Total P&L':>12} {'Monthly P&L':>12} {'Weekly P&L':>12} {'PF':>5}"
    )
    print(hdr)
    print("  " + "─" * 106)
    for r in rows:
        d_cagr = r["cagr_pct"] - baseline["cagr_pct"]
        print(
            f"  {r['scenario']:<14} ₹{r['slip_4leg_vix16']:>6.2f}/sh   "
            f"{r['cagr_pct']:>6.2f}%  {d_cagr:>+6.2f}%  "
            f"{r['sharpe']:>6.2f}  {r['calmar']:>6.2f}  "
            f"{r['max_dd_pct']:>6.1f}%  "
            f"₹{r['total_pnl']:>10,.0f}  ₹{r['monthly_pnl']:>10,.0f}  ₹{r['weekly_pnl']:>10,.0f}  "
            f"{r['profit_factor']:>4.2f}"
        )
    print("  " + "─" * 106)
    print(f"  * Slip/leg = total bid-ask slippage per share for a 4-leg trade at VIX 16")

    # Trade counts (separate block — easier to read)
    print()
    print("  Trade counts & win rates")
    print("  " + "─" * 60)
    print(f"  {'Scenario':<14} {'M-trades':>9} {'M-WR':>6} {'W-trades':>9} {'W-WR':>6}")
    print("  " + "─" * 60)
    for r in rows:
        print(
            f"  {r['scenario']:<14} {r['monthly_trades']:>9} {r['monthly_wr']:>5.0f}%"
            f"  {r['weekly_trades']:>9} {r['weekly_wr']:>5.0f}%"
        )
    print("━" * 110)

    # Verdict
    viable = [r for r in rows if r["cagr_pct"] > 0]
    if viable:
        last = viable[-1]
        print(f"\n  ✓  Strategy stays positive through {last['scenario']}  "
              f"(CAGR {last['cagr_pct']:.2f}%)")
        broken = [r for r in rows if r["cagr_pct"] <= 0]
        if broken:
            print(f"  ✗  Turns negative at {broken[0]['scenario']}  "
                  f"(CAGR {broken[0]['cagr_pct']:.2f}%)")
        # CAGR headroom to zero from baseline
        headroom = baseline["cagr_pct"]
        print(f"\n  CAGR headroom to breakeven from baseline: {headroom:.2f} ppts")
    else:
        print("  ✗  All scenarios negative — friction exceeds alpha even at baseline")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Slippage stress test")
    parser.add_argument("--capital", type=float, default=500_000,
                        help="Initial capital (default 500000)")
    parser.add_argument("--start", type=str, default="2009-01-01",
                        help="Backtest start date YYYY-MM-DD (default 2009-01-01)")
    parser.add_argument("--end", type=str, default=None,
                        help="Backtest end date YYYY-MM-DD (default today)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    config = BacktestConfig(
        start_date=start,
        end_date=end,
        initial_capital=args.capital,
    )
    wc = WeeklyBacktestConfig(
        start_date=start,
        end_date=end,
        initial_capital=args.capital,
    )

    # ── Load data once ──
    print("\n[1/3] Fetching market data...")
    fetcher = MarketDataFetcher(start, end)
    data = fetcher.build_combined_dataset()
    print(f"  Loaded {len(data)} trading days ({start} → {end})")

    # ── Load model caches once ──
    print("\n[2/3] Loading model caches...")
    exit_engine = entry_model = weekly_risk_engine = None
    for label, loader in [
        ("exit",        lambda: ExitStrategyEngine.load(data)),
        ("entry",       lambda: RegimeAwareLearner.load(data)),
        ("weekly-risk", lambda: load_risk_engine(data)),
    ]:
        try:
            if label == "exit":
                exit_engine = loader()
            elif label == "entry":
                entry_model = loader()
            else:
                weekly_risk_engine = loader()
            print(f"  ✓ {label} model loaded")
        except FileNotFoundError:
            print(f"  ✗ {label} cache missing — run `python main.py --mode evolve` first")
        except Exception as e:
            print(f"  ✗ {label} cache error: {type(e).__name__}: {e}")

    # ── Run scenarios ──
    print(f"\n[3/3] Running {len(SCENARIOS)} scenarios...")
    results = []
    for i, sc in enumerate(SCENARIOS, 1):
        print(f"  [{i}/{len(SCENARIOS)}] {sc['name']} — {sc['desc']} ...", end="", flush=True)
        row = run_scenario(sc, data, config, wc, entry_model, exit_engine, weekly_risk_engine)
        results.append(row)
        print(f"  CAGR {row['cagr_pct']:.2f}%  Sharpe {row['sharpe']:.2f}  "
              f"Max DD {row['max_dd_pct']:.1f}%")

    # ── Print summary ──
    print_table(results)


if __name__ == "__main__":
    main()
