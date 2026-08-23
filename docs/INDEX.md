# Documentation Index

## Getting Started

- **[Quick Start Guide](QUICKSTART.md)** - Installation, daily workflow, and basic commands
- **[README (Root)](../README.md)** - Project overview and feature summary

## Architecture

- **[Architecture Overview](architecture/ARCHITECTURE.md)** - System design, data flow, and key components
- **[AI Codebase Guide](architecture/AGENTS.md)** - For AI agents working on this codebase

## Guides

- **[Trade Monitoring Guide](guides/MONITOR_WORKFLOW.md)** - Active trade monitoring, ML exit recommendations, and trade management

## Fyers Integration

- **[Integration Guide](fyers/INTEGRATION.md)** - Complete Fyers API setup and usage
- **[Integration Summary](fyers/INTEGRATION_SUMMARY.md)** - Quick reference for Fyers integration
- **[Quick Reference](fyers/QUICK_REFERENCE.md)** - Code examples and common patterns

## Analysis & Results

- **[Backtest Changelog](../BACKTEST_CHANGELOG.md)** - Optimization history and performance improvements (auto-appended after every run)
- **[Weekly Exit Redesign Log](analysis/WEEKLY_EXIT_REDESIGN_LOG.md)** - Decision record for the weekly exit overhaul and rejected paths
- **[Optimization Log](analysis/OPTIMIZATION_LOG.md)** - Detailed optimization log
- **[Position Sizing Decisions](analysis/POSITION_SIZING_DECISIONS.md)** - Position sizing methodology
- **[OI Volume Display](analysis/OI_VOLUME_DISPLAY.md)** - Open interest and volume analysis

### Historical Decision Records (Archive)

Closed experiments and "why we didn't do X" reasoning — not current reference material:

- **[Archive Index](archive/README.md)** - Index of all archived documents
- `archive/EXIT_STRATEGY_ANALYSIS.md` — Rejected flat 80% profit-lock exit rule
- `archive/HYBRID_BACKTEST_RESULTS.md` — Fixed 85% target vs hybrid approach
- `archive/EXIT_PRIORITY_COMPARISON_FINDINGS.md` — Exit ordering comparison (identical outcome)
- `archive/OPTIMAL_THRESHOLDS_ANALYSIS.md` — 85% profit target selection
- `archive/BACKTEST_COMPARISON_WITH_85_RULE.md` — 85% rule decision record
- `archive/MONTHLY_EXIT_STRATEGY_ANALYSIS.md` — Monthly exit strategy comparison

## Quick Links by Use Case

### I want to...

**Start using the system:**
1. Read [Quick Start Guide](QUICKSTART.md)
2. Set up Fyers: [Integration Guide](fyers/INTEGRATION.md)
3. Run your first backtest: See [Quick Start](QUICKSTART.md#backtesting)

**Monitor live trades:**
1. Read [Monitor Workflow Guide](guides/MONITOR_WORKFLOW.md)
2. Generate token: `python scripts/generate_fyers_token.py`
3. Run monitor: `python main.py --mode monitor`

**Understand the system architecture:**
1. Read [Architecture Overview](architecture/ARCHITECTURE.md)
2. Review [AI Codebase Guide](architecture/AGENTS.md) for detailed component info

**Analyze backtest results:**
1. Start with [Backtest Changelog](../BACKTEST_CHANGELOG.md) (root, auto-appended)
2. Review active analyses in [analysis/](analysis/) folder
3. Run your own: `python main.py --mode backtest`

**Use Fyers API:**
1. Read [Integration Guide](fyers/INTEGRATION.md) for setup
2. Check [Quick Reference](fyers/QUICK_REFERENCE.md) for code examples
3. Use [Integration Summary](fyers/INTEGRATION_SUMMARY.md) for troubleshooting

**Contribute or modify code:**
1. Read [Architecture Overview](architecture/ARCHITECTURE.md)
2. Read [AI Codebase Guide](architecture/AGENTS.md) for design patterns
3. Run tests: `python -m pytest tests/ -v`

## Document Structure

```
docs/
├── QUICKSTART.md                    # Getting started guide
├── INDEX.md                         # This file
├── BACKTEST_COMBINED_MODE.md        # Combined monthly+weekly backtest reference
├── architecture/
│   ├── ARCHITECTURE.md              # System architecture
│   └── AGENTS.md                    # AI codebase guide
├── guides/
│   └── MONITOR_WORKFLOW.md          # Trade monitoring guide
├── fyers/
│   ├── INTEGRATION.md               # Fyers API integration
│   ├── INTEGRATION_SUMMARY.md       # Fyers summary
│   └── QUICK_REFERENCE.md           # Fyers code examples
├── analysis/
│   ├── WEEKLY_EXIT_REDESIGN_LOG.md  # Weekly redesign decision record (active)
│   ├── OPTIMIZATION_LOG.md
│   ├── POSITION_SIZING_DECISIONS.md
│   └── OI_VOLUME_DISPLAY.md
└── archive/
    ├── README.md                    # Index — historical decision records
    ├── EXIT_STRATEGY_ANALYSIS.md
    ├── HYBRID_BACKTEST_RESULTS.md
    ├── EXIT_PRIORITY_COMPARISON_FINDINGS.md
    ├── OPTIMAL_THRESHOLDS_ANALYSIS.md
    ├── BACKTEST_COMPARISON_WITH_85_RULE.md
    └── MONTHLY_EXIT_STRATEGY_ANALYSIS.md
```

## External Resources

- **Fyers API Docs:** https://myapi.fyers.in/docs/
- **NSE Option Chain:** https://www.nseindia.com/option-chain
- **India VIX:** https://www.nseindia.com/products-services/indices-india-vix

## Contributing

When adding new documentation:
1. Place it in the appropriate subdirectory
2. Update this index
3. Add cross-references in related docs
4. Use relative links for internal references

## Need Help?

- Check [Quick Start](QUICKSTART.md#troubleshooting) for common issues
- Run diagnostics: `python scripts/diagnose_live_prices.py`
- Review [Fyers Troubleshooting](fyers/INTEGRATION.md#troubleshooting)
