# MONTHLY Options: 80% Max Profit Booking Analysis

## Executive Summary

**Question:** Does the 80% max profit booking work better for MONTHLY options (15-45 DTE) compared to weekly?

**Answer:** **MIXED RESULTS** - Dramatically better for Put Credit Spreads, worse for Iron Condors.

## Key Finding: Strategy-Dependent Performance

Unlike weekly options where 80% booking degraded ALL strategies uniformly, monthly options show **strategy-specific** outcomes:

### Put Credit Spread (PCS): **SIGNIFICANTLY BETTER** ✓
- **+Rs.4.73M profit** (+33.6% more)
- **+1.99% CAGR** improvement
- **-26.5% drawdown** reduction (HUGE risk improvement)
- **+0.49 Sharpe** improvement
- **+2.6% win rate**
- More trades (495 vs 369), shorter holds (8.5 vs 12.1 days)

### Iron Condor (IC): **WORSE** ✗
- **-Rs.9.15M profit** (-19.7% less)
- **-1.62% CAGR** degradation
- But: **-5.5% drawdown** (better risk)
- **+0.46 Sharpe** (better risk-adjusted)
- **+10.5% win rate** (more consistent)
- More trades (388 vs 256), shorter holds (10.3 vs 17.8 days)

## Detailed Results

### Test Period: 2009-2026 (17 years)

#### Put Credit Spread (PCS)

| Metric | Original | 80% Max Profit | Winner |
|--------|----------|----------------|--------|
| **Total P&L** | Rs.14.09M | Rs.18.82M | **80% (+33.6%)** |
| **CAGR** | 21.56% | 23.55% | **80% (+1.99pp)** |
| **Max Drawdown** | 52.3% | 25.8% | **80% (-26.5pp)** |
| **Sharpe Ratio** | 0.16 | 0.65 | **80% (+0.49)** |
| **Win Rate** | 90.5% | 93.1% | **80% (+2.6%)** |
| **Profit Factor** | 1.29 | 1.42 | **80% (+0.13)** |
| **Avg Hold** | 12.1 days | 8.5 days | **80% (faster)** |
| **Total Trades** | 369 | 495 | 80% (more) |

**Score: 8/8 metrics improved**

#### Iron Condor (IC)

| Metric | Original | 80% Max Profit | Winner |
|--------|----------|----------------|--------|
| **Total P&L** | Rs.46.49M | Rs.37.35M | **Original (+24.5%)** |
| **CAGR** | 30.07% | 28.45% | **Original (+1.62pp)** |
| **Max Drawdown** | 15.4% | 9.9% | **80% (-5.5pp)** |
| **Sharpe Ratio** | 0.99 | 1.45 | **80% (+0.46)** |
| **Win Rate** | 79.7% | 90.2% | **80% (+10.5%)** |
| **Profit Factor** | 2.09 | 2.24 | **80% (+0.15)** |
| **Avg Hold** | 17.8 days | 10.3 days | **80% (faster)** |
| **Total Trades** | 256 | 388 | 80% (more) |

**Score: 5/8 metrics improved (but lost on the 2 most important: profit & CAGR)**

## Why the Difference?

### Put Credit Spread Benefits from 80% Logic

**1. Single-Sided Risk**
- PCS only has downside risk (one spread)
- Profit trajectory is cleaner - usually moves in one direction
- 80% trigger catches profit before reversals happen
- Downside: Limited by spread width

**2. Theta Decay Pattern**
- PCS benefits heavily from early theta decay
- First 10-15 days capture most profit
- Holding beyond 15 days adds little value but increases risk
- 80% logic captures this "sweet spot"

**3. Risk Management**
- Original PCS had 52.3% max drawdown (EXTREME)
- 80% booking cuts this to 25.8% (MUCH safer)
- Protects capital during market reversals
- More sustainable long-term

**4. More Opportunities**
- Shorter holds (8.5 vs 12.1 days) mean more trades
- Capital recycled faster (495 vs 369 trades)
- Compounds gains faster

### Iron Condor Hurt by 80% Logic

**1. Two-Sided Profit Zone**
- IC profits from range-bound markets
- Profit can fluctuate +/- as spot moves within range
- 80% trigger fires on normal profit oscillations
- Exits trades that would have recovered

**2. Premium Collection**
- IC collects premium from BOTH sides
- Higher absolute credit than PCS
- Leaving money on the table by exiting early
- Original avg P&L/trade: Rs.181K vs 80%: Rs.96K (**-46% per trade**)

**3. Time Value Maximization**
- IC benefits from holding closer to expiry
- Premium decay accelerates in final week
- 80% logic exits too early (10.3 vs 17.8 days)
- Misses the exponential theta decay phase

**4. Trade-off Analysis**
- 80% version: Lower profit BUT much higher Sharpe (1.45 vs 0.99)
- More consistent (90% win rate vs 80%)
- Better for risk-averse traders
- Original version: Higher absolute returns for aggressive traders

## Mathematical Insight

### Why Monthly ≠ Weekly

**Weekly Options (3-7 DTE):**
- High gamma, violent profit swings
- 20% pullback = normal intraday noise
- 80% trigger fires on false signals
- Result: Death by thousand paper cuts

**Monthly Options (15-45 DTE):**
- Lower gamma, smoother profit evolution
- 20% pullback = genuine profit deterioration
- 80% trigger captures meaningful signals
- Result: Strategy-dependent outcomes

### The Asymmetry

**PCS (One-sided spread):**
```
Profit trajectory: ———— (linear decay up to max profit)
80% trigger: Captures 80% before reversal risk
Win: Locks in gains, avoids catastrophic losses
```

**IC (Two-sided spread):**
```
Profit trajectory: ∿∿∿∿ (oscillates as spot moves in range)
80% trigger: Fires on normal oscillations
Loss: Exits winners prematurely, misses final theta burst
```

## Recommendation by Strategy

### Put Credit Spread: **ADOPT** 80% Max Profit Booking ✓

**Reasons:**
1. **+33.6% more profit** (Rs.4.73M over 17 years)
2. **Huge risk reduction** (-26.5% drawdown)
3. **Better risk-adjusted returns** (+0.49 Sharpe)
4. **More consistent** (+2.6% win rate)
5. **Faster capital recycling** (8.5 vs 12.1 day holds)

**Implementation:**
- Track max profit per unit during trade
- Exit when current profit ≤ 80% of max profit seen
- Keep original 50% profit target as primary exit
- 80% acts as a "profit protection" mechanism

### Iron Condor: **DO NOT ADOPT** (or use selectively) ✗

**Reasons:**
1. **-19.7% less profit** (Rs.9.15M loss over 17 years)
2. **Lower CAGR** (-1.62%)
3. **Much lower profit per trade** (-46% per trade)
4. **Exits too early** in range-bound markets

**Alternative Approach:**
- IF risk tolerance is low → Use 80% (better Sharpe, lower DD)
- IF maximizing returns → Keep original logic
- Consider 85% or 90% threshold instead of 80%

## Verdict by Objective

### Maximum Profit
- **PCS:** 80% Max Profit Booking ✓
- **IC:** Original Logic ✓

### Best Risk-Adjusted Returns (Sharpe)
- **PCS:** 80% Max Profit Booking ✓ (0.65 vs 0.16)
- **IC:** 80% Max Profit Booking ✓ (1.45 vs 0.99)

### Lowest Drawdown
- **PCS:** 80% Max Profit Booking ✓ (25.8% vs 52.3%)
- **IC:** 80% Max Profit Booking ✓ (9.9% vs 15.4%)

### Most Consistent (Win Rate)
- **PCS:** 80% Max Profit Booking ✓ (93.1% vs 90.5%)
- **IC:** 80% Max Profit Booking ✓ (90.2% vs 79.7%)

## Comparison: Weekly vs Monthly

| Strategy Type | Weekly Result | Monthly PCS | Monthly IC |
|--------------|---------------|-------------|------------|
| **80% Booking** | ✗ Worse | ✓ Much Better | ✗ Less Profit |
| **Profit Impact** | -Rs.23K | **+Rs.4.73M** | -Rs.9.15M |
| **CAGR Impact** | -0.01% | **+1.99%** | -1.62% |
| **Risk Impact** | No change | **-26.5% DD** | -5.5% DD |
| **Sharpe Impact** | -0.01 | **+0.49** | +0.46 |
| **Holding Period** | 2.1 days | 8.5 days | 10.3 days |

**Key Insight:** The 80% logic works when there's enough time for genuine profit deterioration signals (monthly), but fails when profit swings are just gamma noise (weekly).

## Final Recommendations

### For Put Credit Spread
**Implement 80% max profit booking immediately.**

Modified exit logic:
```python
def should_exit(trade, spot, vix, dte, max_profit_per_unit):
    # Original exits (50% profit, stops, etc.)
    if pnl_pct >= 50%:
        return EXIT
    
    # NEW: 80% max profit protection
    if max_profit_per_unit > 0 and pnl_per_unit > 0:
        if pnl_per_unit <= max_profit_per_unit * 0.80:
            return EXIT  # Lock in 80% of peak
    
    # Standard risk management...
```

Benefits:
- Captures most upside
- Protects against reversals
- Reduces catastrophic drawdowns
- Increases trade frequency

### For Iron Condor
**Keep original exit logic, or test 85-90% threshold.**

The IC needs more room to breathe due to:
- Two-sided profit zone
- Normal profit oscillations
- Late-stage theta acceleration

Consider:
- 85% threshold for moderate protection
- 90% threshold for minimal interference
- Or keep original 50% profit target

### Implementation Priority
1. **HIGH:** PCS with 80% max profit booking
2. **LOW:** IC - stick with original logic
3. **RESEARCH:** Test 85-90% thresholds for IC

---

**Bottom Line:**
- Weekly options: 80% logic FAILS (too noisy)
- Monthly PCS: 80% logic WINS BIG (better profit + risk)
- Monthly IC: 80% logic mixed (better risk, less profit)

The strategy-specific results suggest the 80% max profit booking is a powerful tool for **asymmetric strategies** (PCS) but problematic for **symmetric strategies** (IC) in monthly options.
