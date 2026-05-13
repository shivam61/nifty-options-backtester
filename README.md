# Nifty Options Backtester

A Python framework for backtesting and live trading Nifty 50 index options selling strategies with ML-powered regime adaptation, crash detection, and real-time market data integration.

**Target Market:** Indian derivatives (NSE)  
**Capital:** ₹5L INR  
**Lot Size:** 65  

## Features

### Backtesting & Analysis
- **Regime-Adaptive Strategies:** 8 strategies automatically selected based on VIX level
- **ML-Powered Entry/Exit:** Machine learning models for timing and strategy selection
- **Multi-Asset Crash Detection:** 2-tier crash detection system prevents trading during black swan events
- **Walk-Forward Validation:** Chronological train/test splits with no look-ahead bias
- **Multi-Expiry Selection:** Evaluates trades across multiple expiry dates for optimal time efficiency

### Live Trading
- **Real-Time Data:** Fyers API v3 integration for live spot, VIX, and option chain
- **Trade Monitoring:** ML-driven exit recommendations with live P&L tracking
- **Market Hours Detection:** Automatic fallback to historical data outside market hours
- **Combined Strategy:** Monthly (70%) + Weekly (30%) budget allocation with risk gates

### Risk Management
- **Circuit Breakers:** Blocks trading during extreme market conditions
- **Position Sizing:** ML confidence-based position sizing
- **Stop Losses:** Dynamic profit targets and stop losses
- **Cross-Track Limits:** Drawdown limits across monthly and weekly strategies

## Quick Start

### Installation

```bash
git clone <repository-url>
cd nifty-options-backtester
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Daily Workflow

1. **Generate Fyers Token** (required before 9:15 AM):
   ```bash
   python scripts/generate_fyers_token.py
   ```

2. **Monitor Active Trades:**
   ```bash
   python main.py --mode monitor
   ```

3. **Generate Trade Signal:**
   ```bash
   python main.py --mode signal-combined
   ```

### Backtesting

```bash
# Run basic backtest
python main.py --mode backtest --start 2025-10-01 --end 2026-04-16

# Compare strategies
python main.py --mode compare

# Optimize parameters
python main.py --mode optimize
```

## Documentation

- **[Quick Start Guide](docs/QUICKSTART.md)** - Installation and daily workflow
- **[Architecture Overview](docs/architecture/ARCHITECTURE.md)** - System design and components
- **[Monitor Workflow](docs/guides/MONITOR_WORKFLOW.md)** - Trade monitoring and management
- **[Fyers Integration](docs/fyers/INTEGRATION.md)** - API setup and usage
- **[AI Codebase Guide](docs/architecture/AGENTS.md)** - For AI agents working on this codebase
- **[Agent Memory](docs/AGENT_MEMORY.md)** - Decaying record of repo-specific pitfalls for Claude/Codex sessions
- **[Backtest Changelog](docs/analysis/BACKTEST_CHANGELOG.md)** - Optimization history

## Agent Automation

Enable repo-local hooks once per checkout:

```bash
git config core.hooksPath .githooks
```

The pre-commit hook refreshes and stages `graphify-out/`. For live updates while
editing, run `scripts/watch_graphify.sh`. To record or decay cross-agent lessons,
use `python3 scripts/agent_memory.py`.

## Project Structure

```
├── main.py                    # CLI entry point
├── main_weekly.py             # Weekly-only backtesting
├── main_combined.py           # Combined monthly + weekly
├── config.py                  # Strategy configuration
│
├── data/                      # Data fetchers and processors
│   ├── market_data.py        # Yahoo Finance + feature engineering
│   ├── fyers_live_data.py    # Live market data (Fyers API)
│   ├── option_chain.py       # NSE option chain
│   └── expiry_calendar.py    # Expiry date calculations
│
├── pricing/
│   └── black_scholes.py      # Option pricing + Greeks
│
├── strategies/                # Trading strategies
│   ├── base.py               # Base strategy classes
│   ├── multi_strategy.py     # 8 strategies + regime selection
│   ├── weekly_strategies.py  # Weekly gamma strategies
│   └── expiry_selector.py    # Multi-expiry evaluation
│
├── backtester/                # Backtesting engines
│   ├── engine.py             # Monthly backtest engine
│   ├── weekly_engine.py      # Weekly backtest engine
│   └── combined_engine.py    # Combined monthly + weekly
│
├── models/                    # ML models
│   ├── regime_classifier.py  # 4-regime classifier
│   ├── trade_learner.py      # Entry/exit/strategy ML
│   ├── weekly_entry_learner.py # Weekly entry timing
│   └── trade_monitor.py      # Live trade monitoring
│
├── signals/
│   └── generator.py          # Signal generation
│
├── analysis/
│   └── reporter.py           # Backtest reporting
│
├── exits/                     # Exit strategy implementations
│
├── pricing/                   # Option pricing models
│
├── tools/                     # Analysis & debugging tools
│   ├── comparison/           # Strategy comparison scripts
│   ├── debug/                # Debugging utilities
│   └── validation/           # Validation tools
│
├── scripts/                   # Setup & maintenance scripts
│   ├── generate_fyers_token.py
│   └── diagnose_live_prices.py
│
├── results/                   # Generated results (gitignored)
│   ├── backtests/            # Backtest reports & logs
│   └── logs/                 # Application logs
│
├── tests/                     # Test suite
│
└── docs/                      # Documentation
    ├── architecture/         # System design
    ├── guides/               # User guides
    ├── fyers/                # Fyers integration
    └── analysis/             # Analysis reports
```

## CLI Modes

| Mode | Description |
|------|-------------|
| `backtest` | Run full backtest with ML training |
| `signal` | Generate today's trade recommendation |
| `signal-combined` | Combined monthly + weekly signal |
| `compare` | Compare strategy configurations |
| `optimize` | Grid search for optimal parameters |
| `monitor` | Monitor active trades with ML exit recommendations |
| `add-trade` | Register a new trade for monitoring |
| `remove-trade` | Remove a completed trade |
| `list-trades` | List all active trades |
| `validate` | Run walk-forward validation |

## Strategy Overview

### Monthly Strategies (70% Budget)

| Strategy | VIX Range | Direction | Holding Period |
|----------|-----------|-----------|----------------|
| CalendarSpread | 0-15 | Long vega | 21-60d |
| PutCreditSpread | 15-18 | Bullish | 14-21d |
| BrokenWingButterfly | 22-30 | Neutral | 14-21d |
| RatioPutSpread | 22+ | Crash hedge | 14-21d |

### Weekly Strategies (30% Budget)

- Short DTE (4-11 days)
- Entry window: Monday/Tuesday only
- Gamma scalping focus
- Emergency exit if combined loss > 3%

## Machine Learning Models

- **Regime Classifier:** 4-regime classification (LOW_VOL/HIGH_VOL/CRASH/TRENDING)
- **Entry Model:** Win probability prediction with 52 features
- **Strategy Selector:** Best strategy recommendation per regime
- **Exit Model:** Should-exit prediction with confidence scores
- **Weekly Entry Model:** Weekly-specific entry timing

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover:
- Option pricing and Greeks
- Strategy entry/exit logic
- ML model training and prediction
- Trade P&L calculations
- Feature engineering
- Multi-expiry selection

## Requirements

- Python 3.9+
- pandas, numpy, scipy
- scikit-learn
- plotly (for charts)
- fyers-apiv3 (for live data)
- pytest (for testing)

See `requirements.txt` for complete list.

## Important Notes

### Fyers Token Management
- Token expires end of each trading day
- Must regenerate before 9:15 AM daily
- Symptom of expired token: "Please provide valid token" error

### Market Hours
- Trading: 9:15 AM - 3:30 PM IST (Mon-Fri)
- Fyers data used only during market hours
- Automatic fallback to NSE/historical data outside hours

### NSE Expiry Schedule (Changed 2024)
- Weekly: Every Monday
- Monthly: Last Monday of month

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `[BS*]` instead of `[LIVE]` prices | Regenerate Fyers token |
| "Please provide valid token" | Run `python scripts/generate_fyers_token.py` |
| Invalid symbol error | Verify expiry date is valid NSE expiry |
| Outside market hours warning | Normal - uses fallback data |

Run diagnostics: `python scripts/diagnose_live_prices.py`

## Contributing

This is a personal project for systematic options trading. Contributions, suggestions, and feedback are welcome.

## Disclaimer

This software is for educational and research purposes only. Options trading involves significant risk. Past performance does not guarantee future results. Always consult with a financial advisor before making investment decisions.

## License

MIT License - see LICENSE file for details
