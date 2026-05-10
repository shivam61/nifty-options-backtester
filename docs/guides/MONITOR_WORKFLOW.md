# Trade Monitoring Guide

## Overview

The monitor mode provides ML-driven exit recommendations for active trades using live Fyers data during market hours.

## Features

- **Live Market Data:** Real-time option prices via Fyers API during market hours (9:15 AM - 3:30 PM IST)
- **ML Exit Predictions:** Should-exit recommendations with confidence scores
- **P&L Tracking:** Real-time unrealized P&L with [LIVE] tags
- **Exit Analysis:** Predicted final P&L if holding to expiry
- **Fallback Mode:** Uses Black-Scholes pricing outside market hours

## Usage

### View All Active Trades

```bash
python main.py --mode monitor
```

**Sample Output (Market Hours):**

```
Fyers LIVE: Nifty 23,820.15 | VIX 20.49
Fetching live LTP for 2 option leg(s):
  ✓ NSE:NIFTY26APR23000PE: LTP=₹144.45 [LIVE]
  ✓ NSE:NIFTY26APR22500PE: LTP=₹77.20 [LIVE]

═══════════════════════════════════════════════════
TRADE: 8thaprl
═══════════════════════════════════════════════════
  SELL 23000 PE  ₹144.45  [LIVE]
  BUY 22500 PE   ₹77.20   [LIVE]
  Entry: 2026-04-08 | Expiry: 2026-04-28 (20 DTE)
  Unrealized P&L: -₹8,775 (-2.74%) [LIVE]
  
  ML Exit Analysis:
    Should exit: NO (confidence: 68%)
    Predicted final P&L if hold: +₹12,450 (+3.89%)
    Reasoning: Current drawdown acceptable for DTE remaining
```

**Sample Output (Outside Market Hours):**

```
Outside market hours — using Black-Scholes pricing

TRADE: 8thaprl
  SELL 23000 PE  ₹142.30  [BS*]
  BUY 22500 PE   ₹75.85   [BS*]
  Unrealized P&L: -₹8,225 (-2.57%) [BS*]
```

### Monitor Specific Trade

```bash
python main.py --mode monitor --trade-id 8thaprl
```

## Adding New Trades

```bash
python main.py --mode add-trade --trade-id my-trade-id \
  --leg "SELL 23000 PE 325 @ 143.50" \
  --leg "BUY 22500 PE 325 @ 76.45" \
  --entry-date 2026-04-13 \
  --expiry-date 2026-04-28
```

### Leg Format

```
<ACTION> <STRIKE> <TYPE> <QUANTITY> @ <ENTRY_PREMIUM>
```

- **ACTION:** SELL or BUY
- **STRIKE:** Integer strike price (e.g., 23000)
- **TYPE:** PE (put) or CE (call)
- **QUANTITY:** Number of contracts (e.g., 325)
- **ENTRY_PREMIUM:** Price paid/received per contract (e.g., 143.50)

### Example Multi-Leg Trades

**Put Credit Spread:**
```bash
--leg "SELL 23000 PE 325 @ 143.50" \
--leg "BUY 22500 PE 325 @ 76.45"
```

**Iron Condor:**
```bash
--leg "SELL 23500 CE 325 @ 85.20" \
--leg "BUY 24000 CE 325 @ 42.10" \
--leg "SELL 22500 PE 325 @ 95.30" \
--leg "BUY 22000 PE 325 @ 48.60"
```

## Removing Trades

When a trade is closed or expires:

```bash
python main.py --mode remove-trade --trade-id 8thaprl
```

## Trade Storage

Active trades are stored in `data/.cache/active_trades.json`:

```json
{
  "8thaprl": {
    "entry_date": "2026-04-08",
    "expiry_date": "2026-04-28",
    "legs": [
      {
        "action": "SELL",
        "strike": 23000,
        "option_type": "PE",
        "quantity": 325,
        "entry_premium": 143.5
      },
      {
        "action": "BUY",
        "strike": 22500,
        "option_type": "PE",
        "quantity": 325,
        "entry_premium": 76.45
      }
    ]
  }
}
```

## ML Exit Model

The exit model uses:
- **Market features:** VIX change, trend, momentum
- **Trade-specific features:** Days held, unrealized P&L %, DTE remaining
- **Regime features:** Current regime classification

**Exit Recommendation Logic:**
1. Predict should-exit probability
2. Predict final P&L if holding to expiry
3. Compare current unrealized P&L vs predicted final P&L
4. Recommend exit if:
   - High exit probability (>70%) AND
   - Current P&L is near predicted final P&L (within 20%) OR
   - Large drawdown with low recovery probability

## Token Management

### Daily Token Generation (REQUIRED)

Before market hours (9:15 AM):

```bash
python scripts/generate_fyers_token.py
```

### Check Token Status

```bash
python scripts/refresh_fyers_token.py
```

### Token Troubleshooting

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Please provide valid token" | Expired token | Regenerate token |
| `-15` error code | Invalid/expired token | Regenerate token |
| `[BS*]` prices during market hours | Token expired | Regenerate token |
| All prices show `[LIVE]` | Token valid ✓ | No action needed |

## Market Hours

- **Trading Hours:** 9:15 AM - 3:30 PM IST (Mon-Fri)
- **Fyers Active:** During trading hours only
- **Fallback:** Black-Scholes pricing outside hours

## Diagnostics

### Full Diagnostic Check

```bash
python scripts/diagnose_live_prices.py
```

Shows:
- Token status
- Fyers API connectivity
- Option symbol validation
- LTP fetch success/failure
- Monitor mode simulation

### Sample Diagnostic Output

```
[1] Token status
  ✓ Token file exists
  ✓ Token is valid (expires: 2026-04-16 23:59:59)

[5] Fyers option quotes
  API status: ok
  NSE:NIFTY26APR23000PE
    lp=144.45  bid=143.50  ask=145.40  ✓ VALID

[6] Simulating analyze_trade lookup
  SELL 23000 PE:
    will use LIVE? -> YES ✓
    ltp from dict: 144.45
    Would show [LIVE] tag
```

## Best Practices

1. **Generate token daily** before market hours
2. **Monitor trades during market hours** for most accurate P&L
3. **Use ML exit recommendations** as guidance, not commands
4. **Document exit decisions** to improve the model over time
5. **Update trades.json** immediately after closing positions

## Troubleshooting

### No [LIVE] Tags Appearing

```bash
# Check token
python scripts/refresh_fyers_token.py

# Regenerate if expired
python scripts/generate_fyers_token.py

# Run diagnostics
python scripts/diagnose_live_prices.py
```

### Wrong Expiry Date

Edit `data/.cache/active_trades.json` and correct the `expiry_date` field. Use correct NSE expiry format (last Monday of month for monthly, every Monday for weekly).

### Invalid Symbol Error

Verify:
1. Strike is valid NSE strike (multiple of 50)
2. Expiry date is valid NSE expiry (Monday)
3. Option type is PE or CE (not PUT/CALL)

## Related Documentation

- [Fyers Integration Guide](../fyers/INTEGRATION.md) - Detailed API setup
- [Quick Start](../QUICKSTART.md) - Basic usage
- [Architecture](../architecture/ARCHITECTURE.md) - System design
