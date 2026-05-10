# Nifty Options Backtester - Architecture

## System Overview

A Python framework for backtesting and live trading Nifty 50 index options selling strategies with ML-powered regime adaptation and crash detection.

**Target Market:** Indian derivatives (NSE)  
**Capital:** ₹5L INR  
**Lot Size:** 65  
**Core Thesis:** Sell premium systematically using VIX regime adaptation, ML timing, and multi-asset crash detection.

## Architecture Diagram

```
main.py                    CLI entry point (10 modes)
├── config.py              BacktestConfig + MarketRegime dataclasses
├── data/
│   ├── market_data.py     Yahoo Finance fetcher, 100+ derived features, parquet cache
│   ├── option_chain.py    Live NSE/Groww option chain + OI analysis
│   ├── expiry_calendar.py Nifty monthly/weekly expiry date math
│   ├── fyers_live_data.py Live market data (Fyers API)
│   └── news_sentiment.py  Keyword NLP + price-action sentiment proxy
├── pricing/
│   └── black_scholes.py   European option pricing + Greeks + vol smile model
├── strategies/
│   ├── base.py            BaseStrategy ABC, Leg, Trade, TradeAction
│   ├── iron_condor.py     IronCondorStrategy, WidePutSpreadStrategy
│   ├── iron_condor_v2.py  IronCondorV2Strategy (asymmetric, OI-aware)
│   ├── multi_strategy.py  8 strategies + RegimeAdaptiveStrategy
│   ├── weekly_strategies.py Weekly gamma strategies
│   └── expiry_selector.py Multi-expiry evaluator
├── backtester/
│   ├── engine.py          BacktestEngine + SmartBacktestEngine
│   ├── combined_engine.py CombinedBacktestEngine (monthly + weekly)
│   ├── weekly_engine.py   WeeklyBacktestEngine
│   └── rolling_simulator.py  Rolling-window trade simulator
├── models/
│   ├── regime_classifier.py   4-regime GBM classifier
│   ├── trade_learner.py       Entry timing, strategy selection, P&L prediction
│   ├── regime_aware_learner.py Per-regime ML models
│   ├── weekly_entry_learner.py Weekly entry timing model
│   ├── strategy_evolver.py    Grid search over param combos
│   └── trade_monitor.py       Active trade monitoring + ML exits
├── signals/
│   └── generator.py       Rule-based signal generation
├── analysis/
│   └── reporter.py        Backtest reporting + Plotly HTML
└── tests/                 pytest test suite
```

## Key Design Decisions

### 1. Hybrid Rules + ML Architecture

- **Rules** provide safety guardrails: circuit breaker blocks trading during extreme events (crash_risk_v2 >= 0.80, multi-asset stress >= 0.80)
- **ML** optimizes within safe boundaries: picks best strategy from regime-eligible shortlist, times entries via win probability, manages exits adaptively
- **Flow:** `RegimeAdaptiveStrategy.get_eligible_strategies()` → ML picks best → `force_strategy_selection()` activates it

### 2. Walk-Forward Validation

- 60% train / 40% test split by chronological order (never shuffled)
- Exit model trains on evolved strategy simulations from training period
- Entry model trains on rolling-window simulator output from training period
- Both models only see data before test period — no look-ahead bias

### 3. Crash Detection (Two-Tier)

- **V1** (`crash_risk_score`): simple triple-stress flag (VIX accel + crude shock + drawdown)
- **V2** (`crash_risk_score_v2`): 6-component weighted score from 17yr forensic analysis:
  - Realized vol z-score
  - VRP collapse
  - Range expansion
  - Multi-asset stress sync
  - RSI oversold
  - Drawdown depth
  - **V2 is the production circuit breaker**

### 4. Black-Scholes as Historical Proxy

- No historical option chain data for Nifty before 2019
- BS pricing with VIX-based smile model (`iv_from_vix`) estimates historical premiums
- Smile model uses linear skew — OTM puts get higher IV
- This is an approximation; real backtests should use actual option chain data where available

### 5. Combined Strategy (Monthly + Weekly)

- **Monthly Track (70% budget):** Regime-adaptive strategies (14-39 DTE)
- **Weekly Track (30% budget):** Gamma scalping (4-11 DTE, Mon/Tue entries only)
- **Risk Gates:**
  - Simultaneous VIX cap: max 22.0 (both tracks blocked if exceeded)
  - Cross-track drawdown limit: 15% of capital
  - Emergency weekly exit: combined open loss > 3% of equity

## Data Flow

```
Yahoo Finance (16 tickers: ^NSEI, ^INDIAVIX, BZ=F, INR=X, GC=F, DX-Y.NYB, ...)
  → per-ticker parquet cache in data/.cache/
  → MarketDataFetcher.build_combined_dataset()
    → 100+ columns: raw prices + returns + technicals + cross-geo + crash features
      → FeatureExtractor.extract() selects 52 ML features
        → ML models (GradientBoosting, RandomForest ensemble)
```

## Strategy Zoo

| Strategy | VIX Range | Direction | Key Trait | Holding Period |
|----------|-----------|-----------|-----------|----------------|
| CalendarSpread | 0-15 | Long vega | Profits from IV expansion. Supports rolling. | 21-60d (with rolls) |
| DiagonalSpread | 10-22 | Mild bullish | Cross-expiry, cross-strike. Supports rolling. | 30-60d (with rolls) |
| BearCallSpread | 12-15 | Bearish/neutral | Overextended rallies | 14-21d |
| PutCreditSpread | 15-18 | Bullish | Sweet spot premium selling | 14-21d |
| VariableRatioIronFly | 15-25 | Neutral (asymmetric) | Tight put wing, wide call wing | 14-21d |
| BrokenWingButterfly | 22-30 | Neutral | Asymmetric, no upside risk | 14-21d |
| RatioPutSpread | 22+ | Crash hedge | 1:2 ratio, massive crash profits | 14-21d |
| Weekly strategies | N/A | Various | Short DTE gamma plays | 4-11d |

## Multi-Expiry Selection

The `ExpirySelector` evaluates each strategy across 2-3 upcoming expiries:

```
For each (strategy, expiry) pair:
  1. Price all legs via Black-Scholes
  2. Compute net credit, max loss, Greeks (θ, ν, Δ)
  3. Estimate win probability from strike distance in SD terms
  4. EV = credit × win_prob - max_loss × (1 - win_prob)
  5. Score = time_efficiency × theta_quality × (1 - txn_drag) + bonuses
```

Bonuses: longer DTE (fewer trades), vega-positive in low IV, theta quality.

## ML Models

| Model | Type | Purpose | Key Features |
|-------|------|---------|--------------|
| RegimeClassifier | GBM (4-class) | Labels LOW_VOL/HIGH_VOL/CRASH/TRENDING | VIX, drawdown, RSI, crash scores |
| TradeLearner.classifier | GBM+RF ensemble | Win probability per trade | 52 features across 8 groups |
| TradeLearner.regressor | GBM | Expected P&L prediction | Same 52 features |
| Per-strategy models | GBM (per strategy) | Win prob per specific strategy | Same 52 features |
| WeeklyEntryLearner | GBM | Weekly entry timing | Weekly-specific features |
| ExitStrategyEngine | GBM | Should-exit decision + predicted P&L | Market + trade-specific features |

## Feature Groups (52 Features Total)

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
| `signal-combined` | Combined monthly + weekly signal | Read (Yahoo + Fyers) |
| `compare` | Side-by-side strategy comparison | Read |
| `optimize` | Grid search for optimal parameters | Read |
| `evolve` | Parameter evolution per VIX regime | Read + cache write |
| `monitor` | ML-driven exit analysis for active trades | Read + JSON |
| `validate` | Walk-forward + permutation validation | Read |
| `add-trade` | Register a live trade for monitoring | JSON write |
| `remove-trade` | Remove a completed trade | JSON write |
| `list-trades` | Show all active trades | JSON read |

## Common Pitfalls

1. **`iv_from_vix` returns IV as percentage** (e.g., 18.5 means 18.5%), but `price_option` converts it internally via `sigma = iv / 100.0`. Don't double-convert.

2. **VIX is India VIX** (^INDIAVIX), not US VIX (^VIX). They move differently.

3. **Strategy names have canonical form:** `put_credit_spread`, `put_credit_wide`, `broken_wing_butterfly`, `calendar_spread`, `ratio_put_spread`. Use these exact strings.

4. **`Leg.is_short = True` means sold** (premium received at entry). P&L for short leg = `(entry_premium - current_premium) × quantity`.

5. **`Trade.net_credit`** is per-unit (not total). Multiply by `lots × lot_size` for total rupee value.

6. **Nifty strikes are rounded to nearest 50** (`round(price / 50) * 50`). This is NSE convention.

7. **Expiry calendar**: Nifty monthly expiry = last Monday of month (changed in 2024). Weekly expiry = every Monday.

## Testing

```bash
cd nifty-options-backtester
python -m pytest tests/ -v
```

Tests organized by module:
- `test_black_scholes.py` — pricing, Greeks, vol smile
- `test_strategies.py` — entry/exit logic, leg generation
- `test_models.py` — regime labeling, feature extraction
- `test_base.py` — Leg/Trade P&L math
- `test_data.py` — feature engineering, expiry calendar
- `test_multi_expiry.py` — diagonal spread, calendar roll, adjustments
