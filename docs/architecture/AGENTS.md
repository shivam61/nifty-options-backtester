# AGENTS.md — AI Codebase Guide

## Project Purpose

Nifty 50 index options **selling** strategy backtester + live signal generator.
Targets Indian derivatives market (NSE). Capital: ₹5L INR. Lot size: 65.

Core thesis: **sell premium systematically**, using VIX regime to pick the right
strategy, ML to time entries/exits, and multi-asset crash detection to stay out
during black-swan events.

## Architecture Overview

```
main.py                    CLI entry point (10 modes)
├── config.py              BacktestConfig + MarketRegime dataclasses
├── data/
│   ├── market_data.py     Yahoo Finance fetcher, 100+ derived features, parquet cache
│   ├── option_chain.py    Live NSE/Groww option chain + OI analysis
│   ├── expiry_calendar.py Nifty monthly/weekly expiry date math
│   └── news_sentiment.py  Keyword NLP + price-action sentiment proxy
├── pricing/
│   └── black_scholes.py   European option pricing + Greeks + vol smile model
├── strategies/
│   ├── base.py            BaseStrategy ABC, Leg, Trade, TradeAction, ExitReason, AdjustmentAction
│   ├── iron_condor.py     IronCondorStrategy, WidePutSpreadStrategy
│   ├── iron_condor_v2.py  IronCondorV2Strategy (asymmetric, OI-aware)
│   ├── multi_strategy.py  8 strategies + RegimeAdaptiveStrategy meta-strategy
│   └── expiry_selector.py Multi-expiry evaluator (ExpirySelector, ExpiryCandidate)
├── backtester/
│   ├── engine.py          BacktestEngine + SmartBacktestEngine (ML-driven exits)
│   └── rolling_simulator.py  Rolling-window trade simulator for ML training data
├── models/
│   ├── regime_classifier.py   4-regime GBM classifier (LOW_VOL/HIGH_VOL/CRASH/TRENDING)
│   ├── trade_learner.py       Entry timing, strategy selection, P&L prediction
│   ├── regime_aware_learner.py  Per-regime ML models
│   ├── strategy_evolver.py    Grid search over 1080 param combos × 4 regimes
│   ├── trade_monitor.py       Active trade monitoring + ML exit recommendations
│   └── model_validator.py     Walk-forward + permutation validation
├── signals/
│   └── generator.py       Rule-based signal generation + regime performance analysis
├── analysis/
│   └── reporter.py        Backtest reporting + Plotly HTML equity curve
└── tests/                 pytest test suite
```

## Key Design Decisions

### Hybrid Rules + ML Architecture
- **Rules** provide the safety guardrail: circuit breaker blocks all trading during
  extreme events (crash_risk_v2 >= 0.80, multi-asset stress >= 0.80, etc.)
- **ML** optimizes within safe boundaries: picks best strategy from regime-eligible
  shortlist, times entries via win probability, manages exits adaptively.
- Flow: `RegimeAdaptiveStrategy.get_eligible_strategies()` → ML picks best → 
  `force_strategy_selection()` activates it on the meta-strategy.

### Walk-Forward Validation
- 60% train / 40% test split by chronological order (never shuffled)
- Exit model trains on evolved strategy simulations from training period
- Entry model trains on rolling-window simulator output from training period
- Both models only see data before the test period — no look-ahead bias.

### Crash Detection (Two-Tier)
- **V1** (`crash_risk_score`): simple triple-stress flag (VIX accel + crude shock + drawdown)
- **V2** (`crash_risk_score_v2`): 6-component weighted score from 17yr forensic analysis:
  realized vol z-score, VRP collapse, range expansion, multi-asset stress sync,
  RSI oversold, drawdown depth. V2 is the production circuit breaker.

### Black-Scholes as Historical Proxy
- No historical option chain data exists for Nifty going back to 2009.
- BS pricing with a VIX-based smile model (`iv_from_vix`) is used to estimate
  historical premiums. The smile model uses linear skew — **OTM puts get higher IV**.
- This is an approximation. Real backtests should use actual option chain data
  where available (2019+).

## Data Flow

```
Yahoo Finance (16 tickers: ^NSEI, ^INDIAVIX, BZ=F, INR=X, GC=F, DX-Y.NYB, ...)
  → per-ticker parquet cache in data/.cache/
  → MarketDataFetcher.build_combined_dataset()
    → 100+ columns: raw prices + returns + technicals + cross-geo + crash features
      → FeatureExtractor.extract() selects 52 ML features from these
        → ML models (GradientBoosting, RandomForest ensemble)
```

## Strategy Zoo (multi_strategy.py)

| Strategy | VIX Range | Direction | Key Trait | Holding Period |
|----------|-----------|-----------|-----------|----------------|
| CalendarSpread | 0-15 | Long vega | Profits from IV expansion. **Supports rolling.** | 21-60d (with rolls) |
| DiagonalSpread | 10-22 | Mild bullish | Cross-expiry, cross-strike. **Supports rolling.** | 30-60d (with rolls) |
| BearCallSpread | 12-15 | Bearish/neutral | Overextended rallies | 14-21d |
| PutCreditSpread | 15-18 | Bullish | Sweet spot premium selling | 14-21d |
| VariableRatioIronFly | 15-25 | Neutral (asymmetric) | Tight put wing, wide call wing | 14-21d |
| BrokenWingButterfly | 22-30 | Neutral | Asymmetric, no upside risk | 14-21d |
| RatioPutSpread | 22+ | Crash hedge | 1:2 ratio, massive crash profits | 14-21d |

The `RegimeAdaptiveStrategy` selects among these based on VIX level + secondary
filters (trend, vol crush, momentum).

## Multi-Expiry Selection (strategies/expiry_selector.py)

Instead of locking into a single target DTE, the `ExpirySelector` evaluates each
eligible strategy across 2-3 upcoming monthly expiries:

```
For each (strategy, expiry) pair:
  1. Price all legs via Black-Scholes
  2. Compute net credit, max loss, Greeks (θ, ν, Δ)
  3. Estimate win probability from strike distance in SD terms
  4. EV = credit × win_prob - max_loss × (1 - win_prob)
  5. Score = time_efficiency × theta_quality × (1 - txn_drag) + bonuses
```

Bonuses: longer DTE (fewer trades), vega-positive in low IV, theta quality.
Enable via `SmartBacktestEngine(use_multi_expiry=True)`.

## Adjustment / Roll Framework

Strategies can now return `TradeAction.ADJUST` instead of `EXIT`. The engine
calls `strategy.should_adjust()` which returns an `AdjustmentAction`:

```python
@dataclass
class AdjustmentAction:
    action_type: str       # "roll_short", "roll_up", "roll_down", "add_hedge"
    legs_to_close: list    # indices into Trade.legs to close
    new_legs: list         # new Leg objects to add
    cost: float            # net debit/credit of the adjustment
    reasoning: str
```

`Trade.apply_adjustment(adj)` closes specified legs, adds new ones, increments
`roll_count`, and records the adjustment in `adjustment_history`.

Currently Calendar Spread and Diagonal Spread support rolling (max 2 rolls).

## ML Models Summary

| Model | Type | Purpose | Key Features |
|-------|------|---------|--------------|
| RegimeClassifier | GBM (4-class) | Labels LOW_VOL/HIGH_VOL/CRASH/TRENDING | VIX, drawdown, RSI, crash scores |
| TradeLearner.classifier | GBM+RF ensemble | Win probability per trade | 52 features across 8 groups |
| TradeLearner.regressor | GBM | Expected P&L prediction | Same 52 features |
| TradeLearner.strategy_classifier | GBM | Best strategy for conditions | Same 52 features |
| Per-strategy models | GBM (per strategy) | Win prob per specific strategy | Same 52 features |
| ExitStrategyEngine | GBM classifier + regressor | Should-exit decision + predicted final P&L | Market + trade-specific features |

## Feature Groups (FeatureExtractor)

1. **volatility** (7): VIX current/avg/change, VRP, Bollinger width
2. **momentum** (5): Nifty returns, RSI, SMA distance, overnight gap
3. **macro_global** (3): US 10Y yield, S&P 500 returns
4. **macro_india** (6): crude, USD/INR, Bank Nifty, crude×INR stress
5. **cross_geo** (9): DXY, EM ETF, Hang Seng, Europe, gold, India VIX premium
6. **composite** (5): sentiment proxy, contagion score, FII flow
7. **crash_detection** (6): VIX acceleration, crude shock, consecutive downs
8. **crash_v2** (11): VRP collapse, realized vol z-score, multi-asset stress

## CLI Modes

| Mode | Function | Read/Write |
|------|----------|------------|
| `backtest` | Full ML pipeline: train → backtest → report | Read (Yahoo) |
| `signal` | Today's regime-aware trade recommendation | Read (Yahoo + NSE) |
| `compare` | Side-by-side strategy comparison | Read |
| `optimize` | Grid search for optimal parameters | Read |
| `evolve` | Parameter evolution per VIX regime (1080 combos) | Read + cache write |
| `monitor` | ML-driven exit analysis for active trades | Read + JSON |
| `validate` | Walk-forward + permutation validation | Read |
| `add-trade` | Register a live trade for monitoring | JSON write |
| `remove-trade` | Remove a completed trade | JSON write |
| `list-trades` | Show all active trades | JSON read |

## Testing

Run tests with:
```bash
cd nifty-options-backtester
python -m pytest tests/ -v
```

Tests are organized by module:
- `tests/test_black_scholes.py` — pricing correctness, Greeks signs, vol smile
- `tests/test_strategies.py` — entry/exit logic, leg generation, regime selection
- `tests/test_models.py` — regime labeling, feature extraction
- `tests/test_base.py` — Leg/Trade P&L math, edge cases
- `tests/test_data.py` — feature engineering, expiry calendar, sentiment scoring
- `tests/test_multi_expiry.py` — diagonal spread, calendar roll, adjustment mechanics, ExpirySelector

## Common Pitfalls for AI Agents

1. **`iv_from_vix` returns IV as percentage** (e.g., 18.5 means 18.5%), but
   `price_option` converts it internally via `sigma = iv / 100.0`. Don't double-convert.

2. **VIX is India VIX** (^INDIAVIX), not US VIX (^VIX). They move differently.
   `vix_premium_over_us` tracks the spread.

3. **Strategy names have a canonical form** used as dict keys throughout:
   `put_credit_spread`, `put_credit_wide`, `broken_wing_butterfly`,
   `calendar_spread`, `ratio_put_spread`. Use these exact strings.

4. **`Leg.is_short = True` means sold** (premium received at entry).
   P&L for short leg = `(entry_premium - current_premium) × quantity`.

5. **`Trade.net_credit`** is per-unit (not total). Multiply by `lots × lot_size`
   for total rupee value.

6. **Feature names differ between `market_data.py` and `FeatureExtractor`.**
   The extractor maps raw column names to ML feature names (e.g.,
   `vix_change_5d` → `vix_pct_chg_5d`). Check the mapping in `extract()`.

7. **`RegimeAdaptiveStrategy._active_strategy`** is stateful — it remembers
   which sub-strategy was selected. Call `force_strategy_selection()` to override,
   or let `should_enter()` auto-select via `_select_strategy()`.

8. **Nifty strikes are rounded to nearest 50** (`round(price / 50) * 50`).
   This is NSE convention for index options.

9. **Expiry calendar**: Nifty monthly expiry = last Thursday of the month.
   Weekly expiry = every Thursday. The backtester uses monthly expiries only.

10. **`format_expiry_label` uses `%-d`** which is Linux/macOS only.
    On Windows, use `%#d` instead.
