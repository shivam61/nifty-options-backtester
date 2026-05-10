# Open Interest & Volume Display Enhancement

## Overview

Enhanced the monitor to display **Open Interest (OI)**, **Volume**, and **Bid-Ask spreads** for each leg of your active trades. This provides crucial market depth information to make better exit decisions.

## What Was Added

### 1. Data Collection
- Fetches OI, volume, bid, and ask prices directly from Fyers API
- Stores this data alongside LTP for each option leg
- Falls back gracefully when data is not available

### 2. Enhanced Display
The monitor now shows:
- **Open Interest**: Total contracts outstanding (indicates liquidity)
- **Volume**: Contracts traded today (indicates activity)
- **Bid-Ask Spread**: Shows market depth and transaction costs
- **Source**: Whether data is LIVE from Fyers or estimated

### 3. Smart Layout
- Displays OI/Volume columns when live data is available
- Compact display when only BS estimates are available
- Separate bid-ask spread section for detailed market depth

## Example Output

### With Live Fyers Data:

```
  LEGS:
    Action Strike Type    Qty      Entry        Current      Leg P&L         OI     Volume  Src
    ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    SELL 23000 PE         325  ₹  139.55 ₹   45.20 ₹   +30,664     45,231     12,450  [LIVE]
    BUY  22500 PE         325  ₹   86.75 ₹   22.10 ₹   +21,011     32,145      8,320  [LIVE]
    
  BID-ASK SPREADS:
    SELL 23000 PE        Bid: ₹  44.90  Ask: ₹  45.50  Spread: ₹ 0.60 (1.3%)
    BUY  22500 PE        Bid: ₹  21.85  Ask: ₹  22.35  Spread: ₹ 0.50 (2.3%)
```

### Without Live Data (Market Closed):

```
  LEGS:
    Action Strike Type    Qty      Entry  Current (est)      Leg P&L  Src
    ───────────────────────────────────────────────────────────────────────
    SELL 23000 PE         325  ₹  139.55 ₹   45.20 ₹   +30,664   [BS]
    BUY  22500 PE         325  ₹   86.75 ₹   22.10 ₹   +21,011   [BS]
    [BS]  = Black-Scholes estimate (no live chain available)
```

## What The Metrics Tell You

### Open Interest (OI)
- **High OI**: Good liquidity, easier to enter/exit
- **Low OI**: Poor liquidity, wider bid-ask spreads
- **Increasing OI**: New positions being built (bullish/bearish)
- **Decreasing OI**: Positions being closed (profit-taking or stop-loss)

**Example**: If your short 23000 PE has OI of 45,231, it means there are 45,231 contracts outstanding at this strike - good liquidity!

### Volume
- **High Volume**: Active trading today, fresh price discovery
- **Low Volume**: Stale prices, may have execution risk
- **Volume > OI**: Heavy intraday activity (day trading)
- **Volume << OI**: Low activity (prices may not reflect true value)

**Example**: Volume of 12,450 on OI of 45,231 means ~28% of open positions traded today - healthy activity.

### Bid-Ask Spread
- **Narrow Spread** (< 1%): High liquidity, low transaction cost
- **Wide Spread** (> 2%): Poor liquidity, high transaction cost
- **Spread matters more** when closing positions (you're crossing the spread)

**Example**: 1.3% spread on your short leg means you'd lose ~₹0.60 per contract due to spread if you close now.

## Trading Insights

### When to Use This Data

1. **Exit Decisions**
   - Wide spreads → Wait for better liquidity before exiting
   - High volume + price drop → Real selling pressure (not just spread)
   - Low OI on long leg → May have trouble exiting at shown price

2. **Risk Assessment**
   - OI building at your short strike → More traders betting against you
   - Volume spike → Something changed (news, technical level)
   - Widening spreads → Liquidity drying up (higher exit risk)

3. **Optimal Exit Timing**
   - Exit when spreads are tight (high volume periods)
   - Avoid exiting during low liquidity (first/last 15 min)
   - Monitor if your short strike is seeing OI buildup

### Red Flags to Watch

🚨 **High OI at your short strike** → Many traders expect price to reach here
🚨 **Low volume on high price movement** → Price may not be real (wide spread)
🚨 **Bid-ask spread > 3%** → High transaction cost, wait for better liquidity
🚨 **OI dropping + price rising (for shorts)** → Short covering, bullish signal

## Technical Implementation

### Files Modified

1. **`main.py`** (3 changes)
   - Added `_fyers_live_oi_vol` dict to store OI/volume data
   - Pass `fyers_oi_vol` parameter to `analyze_trade()`
   - Enhanced `_print_exit_recommendation()` to display OI/volume

2. **`models/trade_monitor.py`** (2 changes)
   - Added `fyers_oi_vol` parameter to `analyze_trade()` method
   - Store OI/volume/bid/ask in `per_leg_pnl` dict for each leg

### Data Flow

```
Fyers API
    ↓
_fyers_live_oi_vol dict: {(strike, type) → {oi, volume, bid, ask}}
    ↓
analyze_trade(fyers_oi_vol=_fyers_live_oi_vol)
    ↓
per_leg_pnl: [{..., "oi": 45231, "volume": 12450, "bid": 44.90, "ask": 45.50}]
    ↓
_print_exit_recommendation() → Display in table
```

### Backward Compatibility

✅ Works with live Fyers data (shows OI/volume)
✅ Works without Fyers (shows only price estimates)
✅ Works with NSE/Groww fallback (price only, no OI)
✅ Existing trades and functionality unchanged

## Usage

No changes needed! The enhanced display appears automatically when you run:

```bash
python main.py --mode monitor
```

### When You'll See OI/Volume:
- ✅ Market hours (9:15 AM - 3:30 PM)
- ✅ Valid Fyers token
- ✅ Trade legs found in Fyers option chain

### When You Won't See It:
- Market closed (only BS estimates available)
- Expired Fyers token (shows warning + BS estimates)
- Expiry not matching Fyers chain (uses BS with live spot)

## Example Trading Scenario

### Scenario: Put Credit Spread Management

**Your Position:**
- SELL 23000 PE @ ₹139.55 (325 qty)
- BUY 22500 PE @ ₹86.75 (325 qty)
- Net Credit: ₹17,160

**Monitor Shows:**

```
SELL 23000 PE:  LTP ₹45.20  |  OI: 45,231  |  Vol: 12,450  |  Spread: 1.3%
BUY  22500 PE:  LTP ₹22.10  |  OI: 32,145  |  Vol:  8,320  |  Spread: 2.3%

Current P&L: +60.2% of max profit = ₹+51,675
```

**Analysis:**
1. ✅ **High OI on both legs** → Good liquidity, can exit anytime
2. ✅ **Healthy volume** → Prices are fresh and reliable
3. ✅ **Narrow spreads** → Low transaction cost to exit (~₹300 total)
4. ✅ **P&L at 60%** → Good profit capture

**Decision**: Exit now if risk/reward favors locking profits. Transaction cost is minimal due to tight spreads and high liquidity.

## Benefits

1. **Better Exit Timing**: See when liquidity is good vs poor
2. **Risk Awareness**: Know if market is betting against your position
3. **Cost Transparency**: See transaction costs before exiting
4. **Confidence**: Make decisions with full market depth information
5. **Professional Grade**: Same data professional traders use

## Future Enhancements

Potential additions:
- **OI Change**: Show OI change from yesterday (bullish/bearish indicator)
- **PCR (Put-Call Ratio)**: For the entire strike range
- **Max Pain**: Most likely expiry price based on OI
- **IV (Implied Volatility)**: For each leg
- **Greeks**: Delta, gamma, theta, vega per leg
- **Historical Charts**: OI and volume trends over time

## Related Documentation

- [Token Expiry Reminder](TOKEN_EXPIRY_REMINDER.md) - Keep your Fyers token fresh
- [Monitor Workflow](MONITOR_WORKFLOW.md) - How the monitor works
- [Fyers Integration](FYERS_COMPLETE.md) - Complete Fyers setup guide

---

**Last Updated**: April 15, 2026
**Feature Status**: ✅ Active and Working
**Tested**: Market hours with live Fyers data
