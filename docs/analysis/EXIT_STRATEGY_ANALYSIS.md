# Exit Strategy Comparison: 80% Max Profit Booking Analysis

## Executive Summary

**Question:** Would adding an additional check to book profits when they drop to 80% of max profit improve backtest results?

**Answer:** **NO** - The 80% max profit booking degrades performance slightly across all key metrics.

## Approach Tested

### Original Exit Logic
- Exit at 50% profit target (profit = 50% of credit collected)
- Trailing stop: Exit if profit drops 25% from a 30% peak
- Stop loss at 100% of credit
- DTE exit at 1 day remaining

### Modified Exit Logic (80% Max Profit Booking)
- All original exits PLUS
- **NEW:** Track maximum profit per unit during trade lifetime
- **NEW:** Exit if current profit drops to 80% of the max profit seen
- Example: If max profit reaches Rs.100/unit, exit when it drops to Rs.80/unit

## Backtest Results

### Test Period: 2020-01-01 to 2026-04-16 (6+ years)

| Metric | Original | 80% Max Profit | Difference |
|--------|----------|----------------|------------|
| **Total Trades** | 257 | 257 | Same |
| **Total P&L** | Rs.6,604,925 | Rs.6,581,887 | **-Rs.23,038** |
| **CAGR** | 53.82% | 53.74% | **-0.08%** |
| **Sharpe Ratio** | 2.60 | 2.59 | **-0.01** |
| **Max Drawdown** | 3.1% | 3.1% | Same |
| **Win Rate** | 83.7% | 83.3% | **-0.4%** |
| **Profit Factor** | 9.28 | 9.24 | **-0.04** |
| **Avg P&L/Trade** | Rs.25,700 | Rs.25,610 | **-Rs.90** |
| **Avg Hold Days** | 2.2 | 2.1 | -0.1 (slightly faster) |

### Test Period: 2009-01-01 to 2026-04-16 (17+ years)

| Metric | Original | 80% Max Profit | Difference |
|--------|----------|----------------|------------|
| **Total Trades** | 642 | 642 | Same |
| **Total P&L** | Rs.14,305,082 | Rs.14,282,044 | **-Rs.23,038** |
| **CAGR** | 22.32% | 22.31% | **-0.01%** |
| **Sharpe Ratio** | 1.70 | 1.70 | Same |
| **Max Drawdown** | 3.1% | 3.1% | Same |
| **Win Rate** | 82.1% | 81.9% | **-0.2%** |
| **Profit Factor** | 8.95 | 8.93 | **-0.02** |
| **Avg P&L/Trade** | Rs.22,282 | Rs.22,246 | **-Rs.36** |

## Key Findings

### 1. Consistent Underperformance
- The 80% max profit booking approach underperformed across **BOTH** test periods
- Degradation is small but consistent: ~Rs.23K less profit in both periods
- No improvement in any key risk/return metric

### 2. Score: 0/6 Metrics Improved
- CAGR: WORSE (-0.01% to -0.08%)
- Sharpe Ratio: WORSE or SAME
- Max Drawdown: SAME (no reduction)
- Win Rate: WORSE (-0.2% to -0.4%)
- Profit Factor: WORSE (-0.02 to -0.04)
- Sortino Ratio: WORSE or SAME

### 3. Why It Doesn't Help

**Problem:** Premature Exits
- Weekly options have very short holding periods (average 1.8-2.2 days)
- Profit trajectories are choppy due to high gamma exposure
- 80% trigger causes exits during minor profit pullbacks
- Misses the final profit run-up that often happens close to expiry

**Original Exit Logic Already Effective**
- 50% profit target captures substantial gains
- Trailing stop (30% peak → 25% drop) handles profit protection
- Stop losses at underlying strike breach prevent major losses
- Combination already optimized for weekly gamma dynamics

### 4. Trade-by-Trade Impact

Looking at specific metrics:
- **Best Trade:** 80% approach captured Rs.246K vs Rs.206K (better by Rs.40K)
  - This is ONE trade where early exit avoided a reversal
- **Overall:** Lost Rs.23K across 257/642 trades
  - Many small losses from premature exits overwhelm the rare win

## Conclusion

**The 80% max profit booking check DEGRADES performance.**

### Why?
1. **Too Aggressive:** Exits too early, leaving profit on the table
2. **Noise Sensitivity:** Reacts to normal profit fluctuations in high-gamma trades
3. **No Risk Reduction:** Doesn't improve max drawdown or worst trade
4. **Lower Win Rate:** Causes more losing trades (exiting profit that later recovers)

### Recommendation
**Do NOT adopt the 80% max profit booking logic.**

Stick with the original exit strategy:
- 50% profit target
- Trailing stop (30% peak → 25% drop)
- 100% stop loss
- Strike breach exits

This combination is already well-tuned for weekly options gamma dynamics.

## Historical Files Created

1. `strategies/weekly_strategies_max_profit.py` - Modified strategies with 80% max profit logic
2. `backtester/weekly_engine_max_profit.py` - Modified engine that tracks max profit
3. `compare_exit_strategies.py` - Comparison script to run both versions

These first two files were later retired after the weekly exit redesign was
adopted as the default. See `WEEKLY_EXIT_REDESIGN_LOG.md` for the active path.

## How to Reproduce

```bash
cd /Users/shivam.gupta/cursor/dsp-repos/nifty-options-backtester
source .venv/bin/activate

# Run comparison from 2020
python -m tools.comparison.compare_exit_strategies --start 2020-01-01

# Run full history comparison
python -m tools.comparison.compare_exit_strategies --start 2009-01-01
```

## Mathematical Insight

The 80% max profit booking is fundamentally:
```
Exit if: current_profit <= 0.80 * max_profit_seen
```

This creates a **ratchet effect** where any 20% pullback from peak triggers exit.

For weekly options with 2-day average hold:
- Intraday profit swings of 20-30% are NORMAL due to gamma
- 80% trigger fires on routine volatility, not true profit deterioration
- Result: Death by a thousand paper cuts (many small premature exits)

The original trailing stop (30% peak → 25% drop) is more appropriate:
- Only triggers after reaching 30% profit first (filters out noise)
- Allows 25% drawdown from peak (not from current level)
- More robust to gamma-induced choppiness

---

**Verdict:** Simple idea, but makes performance worse. Current exit logic is superior.
