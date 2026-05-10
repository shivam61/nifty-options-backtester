# Quick Start Guide

## Installation

```bash
cd nifty-options-backtester
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Daily Workflow

### 1. Morning Routine (Before 9:15 AM) - REQUIRED

Generate fresh Fyers access token:

```bash
python scripts/generate_fyers_token.py
```

Follow the prompts to authorize and paste the redirect URL.

### 2. Monitor Active Trades

```bash
python main.py --mode monitor
```

**Expected output during market hours:**
```
Fyers LIVE: Nifty 23,820.15 | VIX 20.49
Fetching live LTP for 2 option leg(s):
  ✓ NSE:NIFTY26APR23000PE: LTP=₹144.45 [LIVE]
  ✓ NSE:NIFTY26APR22500PE: LTP=₹77.20 [LIVE]
```

### 3. Generate Trade Signal

```bash
python main.py --mode signal
```

**Expected output:**
```
Market hours detected — attempting Fyers API...
Fyers LIVE: Nifty 23,821.80
✓ Fyers chain: 81 CE, 81 PE | Spot: 23,821.80
RECOMMENDED STRATEGY: Put Credit Spread
```

### 4. Combined Signal (Monthly + Weekly)

```bash
python main.py --mode signal-combined
```

Shows regime-adaptive monthly strategy (70% budget) + weekly gamma strategy (30% budget).

## Backtesting

### Run Basic Backtest

```bash
python main.py --mode backtest --start 2025-10-01 --end 2026-04-16
```

### Compare Strategies

```bash
python main.py --mode compare
```

### Optimize Parameters

```bash
python main.py --mode optimize
```

## Trade Management

### List Active Trades

```bash
python main.py --mode list-trades
```

### Add New Trade

```bash
python main.py --mode add-trade --trade-id my-trade \
  --leg "SELL 23000 PE 325 @ 143.50" \
  --leg "BUY 22500 PE 325 @ 76.45" \
  --entry-date 2026-04-13 \
  --expiry-date 2026-04-28
```

### Close Trade

```bash
python main.py --mode remove-trade --trade-id my-trade
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `[BS*]` instead of `[LIVE]` | Token expired | `python scripts/generate_fyers_token.py` |
| "Please provide valid token" | Token expired | Regenerate token |
| "Invalid symbol" error | Wrong expiry date | Update `active_trades.json` |
| Outside market hours warning | After 3:30 PM | Normal, uses NSE fallback |

### Diagnostic Tool

```bash
python scripts/diagnose_live_prices.py
```

Shows exactly what data is being fetched and if `[LIVE]` tags will appear.

## Important Notes

### Fyers Token Management
- **Expires:** End of each trading day
- **Generate:** Every morning before 9:15 AM
- **Symptoms:** "Please provide valid token" (code -15)

### Market Hours
- **Trading:** 9:15 AM - 3:30 PM IST (Mon-Fri)
- **Fyers used:** During market hours only
- **Fallback:** NSE/Groww outside market hours

### NSE Expiry Schedule
- **Weekly:** Every Monday
- **Monthly:** Last Monday of month

## Next Steps

- Read [Architecture Overview](./architecture/ARCHITECTURE.md) for system design
- See [Fyers Integration Guide](./fyers/INTEGRATION.md) for API details
- Check [Analysis Reports](./analysis/) for backtest results
