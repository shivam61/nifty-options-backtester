# Combined Backtest Mode (`--mode backtest-combined`)

## Overview

The `--mode backtest-combined` is a new backtest pipeline that simultaneously runs both **monthly** and **weekly** option strategies on shared capital, exactly mirroring the live `--mode signal-combined` flow.

## What's New

### CLI Usage

```bash
python main.py --mode backtest-combined                    # Default (17yr history)
python main.py --mode backtest-combined --run-label "v4-testing"  # With label
```

### Mode Availability

The `backtest-combined` mode is now available in the CLI alongside the existing modes:

- `--mode backtest` - Single monthly strategy backtest (existing)
- `--mode backtest-combined` - **NEW** Combined monthly + weekly backtest
- `--mode signal` - Live monthly signal generation
- `--mode signal-combined` - Live combined strategy signal generation

## Architecture

The combined backtest pipeline follows the same flow as `signal-combined`:

### 1. **Capital Allocation (70/30 split)**

```
Initial Capital: ₹500,000
├─ Monthly Track:    70% (₹350,000)
└─ Weekly Track:     30% (₹150,000)
```

### 2. **Monthly Track (70% Budget)**

- **Entry**: ML-powered via `RegimeAwareLearner` (v4 model)
- **Exit Strategy**: VIX-adaptive stops, trailing stops, ML-based exits
- **Strategies**: Multi-strategy selection (IronCondor, PutCreditSpread, CalendarSpread, BrokenWingButterfly)
- **Position Sizing**: 3-layer adaptive sizing (margin-based, volatility targeting, ML confidence scaling)

### 3. **Weekly Track (30% Budget)**

- **Entry**: Rule-based (Mon/Tue entries, 3-7 DTE) with VIX gating
- **Exit Strategy**: Tighter, faster exits (typically 1-2 DTE)
- **Strategies**: Put Credit Spread, Iron Condor
- **Quality Gate**: Weekly entry model filtering (if available)

### 4. **Cross-Track Risk Management**

- **Combined DD Breaker**: Stops new entries if combined drawdown exceeds 15%
- **Monthly Loss Blocks**: Blocks weekly entries if monthly track down > 2%
- **Open Position Cap**: Limits total open combined loss to 4% of capital
- **VIX Safety Gate**: Blocks simultaneous entries if VIX > 22

## Output Example

```
================================================================================
  COMBINED MONTHLY + WEEKLY BACKTEST — ML PIPELINE
  Period: 2009-01-01 to 2026-04-17
  Budget: Monthly 70% (₹350,000) + Weekly 30% (₹150,000)
================================================================================

[1/5] Fetching market data...
  Loaded 4238 trading days

[2/5] Loading exit model...
  Loaded exit model from cache (0d old)

[3/5] Loading monthly entry model...
  Loaded entry model v4 from cache (0d old)

[4/5] Loading weekly entry model...
  Weekly entry model not available — using rule-based entry

[5/5] Running combined backtest (monthly 70% + weekly 30%)...

  ================================================================================
  COMBINED BACKTEST RESULTS
  ================================================================================

  Monthly Track (70% budget):
    Trades: 337 | Win Rate: 70% | P&L: ₹1,174,144 | Avg Hold: 8d

  Weekly Track (30% budget):
    Trades: 651 | Win Rate: 82% | P&L: ₹12,532,853 | Avg Hold: 2d

  Combined Results:
    Total Trades: 988 | Overall Win Rate: 78%
    Total P&L: ₹13,706,997 | CAGR: 22.02%
    Max DD: 5.2% | Sharpe: 2.24 | Calmar: 4.27
    Profit Factor: 5.15

  Risk Management Gates:
    Cross-track DD blocks: 0
    Weekly VIX gate blocks: 144
    Weekly open position cap blocks: 0
    Emergency weekly exits: 0

  Capital Utilization: 64.6%
```

## Logging

Results are automatically logged to:

1. **`backtest_runs.jsonl`** - Structured JSON records (for analysis/comparison)
2. **`BACKTEST_CHANGELOG.md`** - Human-readable markdown summary

### JSON Entry Example

```json
{
  "timestamp": "2026-04-17T00:18:45.692653",
  "git_hash": "unknown",
  "label": "v4-testing",
  "mode": "backtest-combined",
  "metrics": {
    "cagr_pct": 22.02,
    "total_pnl": 13706997,
    "monthly_pnl": 1174144,
    "weekly_pnl": 12532853,
    "monthly_win_rate": 70.3,
    "weekly_win_rate": 82.3,
    "sharpe": 2.24,
    "max_drawdown_pct": 5.2
  },
  "engine_stats": {
    "monthly_trades": 337,
    "weekly_trades": 651,
    "cross_track_dd_blocks": 0,
    "weekly_vix_gate_blocks": 144
  }
}
```

## Comparison: Backtest vs Signal-Combined

| Aspect | backtest | backtest-combined | signal-combined |
|--------|----------|-------------------|-----------------|
| Monthly track | ✓ | ✓ | ✓ |
| Weekly track | ✗ | ✓ | ✓ |
| Capital split | N/A | 70/30 | 70/30 |
| Historical test | ✓ | ✓ | N/A (Live) |
| Data requirements | Market data | Market data | Live prices |
| Logging | Yes | Yes | No |

## Common Use Cases

1. **Before Deploying Signal-Combined to Live**
   ```bash
   python main.py --mode backtest-combined --run-label "pre-prod-validation"
   ```

2. **Comparing Single vs Combined Performance**
   ```bash
   # Single monthly strategy
   python main.py --mode backtest --run-label "monthly-only"
   
   # Combined monthly + weekly
   python main.py --mode backtest-combined --run-label "combined-70-30"
   ```

3. **Tuning Capital Allocation**
   - Run backtest-combined with current 70/30 split
   - Analyze monthly_pnl vs weekly_pnl in logs
   - Adjust split if one track significantly outperforms

4. **Validating New ML Models**
   ```bash
   python main.py --mode backtest-combined --run-label "v4-vs-v3"
   ```

## Technical Details

### Files Modified

- **`main.py`**
  - Added `--mode backtest-combined` to CLI options
  - Added `run_backtest_combined()` function (~120 lines)
  - Updated `log_backtest_run()` to handle combined result objects
  - Updated `_append_changelog_entry()` to format combined metrics

### Files Used (No Changes)

- `backtester/combined_engine.py` - CombinedBacktestEngine (existing)
- `config.py` - BacktestConfig, WeeklyBacktestConfig
- `models/regime_aware_learner.py` - Entry model
- `models/trade_monitor.py` - Exit model
- `strategies/multi_strategy.py` - RegimeAdaptiveStrategy
- `data/fetcher.py` - MarketDataFetcher

## Performance Expectations

Based on 17-year backtest (2009-2026):

- **CAGR**: ~22% (depends on capital, capital split, VIX regime)
- **Win Rate**: ~78% combined (70% monthly, 82% weekly)
- **Sharpe**: 2.24 (attractive risk-adjusted returns)
- **Max Drawdown**: ~5.2% (tight risk management)
- **Trades/Year**: ~150 (highly active, typical for short-dated options)

## Troubleshooting

### Error: "Weekly entry model not available"

This is **expected** and non-critical. The backtest will use rule-based weekly entry instead of ML-gated.

### Error: "Exit model not found"

Run `--mode backtest` or `--mode evolve` first to generate the exit model cache.

### High capital utilization (>80%)

Indicates aggressive sizing or strong market conditions. Consider:
- Reducing `--lots` parameter
- Checking VIX-driven scaling in PositionSizer

## Next Steps

- **Compare Results**: Run both `--mode backtest` and `--mode backtest-combined` with same parameters to isolate weekly track contribution
- **Tune 70/30 Split**: Try different capital allocations by modifying `monthly_budget_pct` parameter in `run_backtest_combined()`
- **Deploy to Live**: Once validated, the `signal-combined` mode is ready for live execution

