# First Trade — Mon Sep 8, 2026 (Ready to fill in)

**Trade #1 — Iron Condor**

## Pre-Signal Checklist (Before 11:00 AM IST)
- [ ] VIX data fetched — confirm < 18 for IC entry
- [ ] Nifty spot noted
- [ ] ₹12.5L capital confirmed available
- [ ] Fyers API authenticated + test order placed
- [ ] NSE option chain API available
- [ ] Exit rules reviewed: 50% max profit, 2× credit stop-loss

## Signal Execution (11:00–13:00 IST)
```
Command: python main.py --mode signal-combined
Time to run: Anytime 11:00–13:00 IST
Expected output: IC signal with Put/Call strikes, DTE=3
```

## At Entry (fill these in when signal comes)

| Field | Fill In |
|-------|---------|
| **Entry Time (IST)** | 11:__ AM (11:00–13:00) |
| **Nifty Spot at entry** | ___,___ |
| **India VIX** | ___.__ |
| **Short Put Strike** | ___,___ (target ~1.5σ OTM) |
| **Short Call Strike** | ___,___ (target ~1.5σ OTM) |
| **Entry Fill Price (put)** | ₹___.__ (credit collected) |
| **Entry Fill Price (call)** | ₹___.__ (credit collected) |
| **Total Credit Collected** | ₹___.__ (per lot) |
| **Bid-Ask Spread** | __/__ (actual observed) |
| **Lots Executed** | 65 |
| **Capital Deployed** | ₹12,50,000 |
| **Expiry Date** | Sep 8 / Sep 11 (TBD by system) |
| **DTE** | _ days |

## Monitoring (Sep 9–10, daily)

| Day | Nifty | Put Distance | Call Distance | Status | Notes |
|-----|-------|--------------|---------------|--------|-------|
| Sep 9 | ___,___ | +___ | +___ | [ ] In range / [ ] Near / [ ] Breach | |
| Sep 10 | ___,___ | +___ | +___ | [ ] In range / [ ] Near / [ ] Breach | |
| Sep 11 | ___,___ | +___ | +___ | [ ] EXPIRED ✓ / [ ] Breach | |

## Exit (At expiry or earlier)

| Field | Value |
|-------|-------|
| **Exit Date** | Sep 10 or Sep 11 (depends on target hit) |
| **Exit Time** | _:__ AM/PM |
| **Exit Reason** | [ ] Expired worthless [ ] 50% profit target [ ] Breach / Stop-loss |
| **Nifty at exit** | ___,___ |
| **Final Profit/Loss** | ₹___.__ (net after brokerage) |
| **Hold days** | _ days |
| **vs Backtest Expected** | Expected ₹29,528 / Actual ₹___,___ |

## Post-Trade Logging

After exit, update:
1. `TRADES.csv` — add entry row
2. `DAILY_LOG.csv` — add Sep 11 exit row
3. `PAPER_TRADING_JOURNAL.md` — note outcome under Checkpoint 1

## Sample Entry Row (for copy-paste into TRADES.csv)

```
1,2026-09-08,11:15,23500,27.5/28.5,27.9,65,1250000,iron_condor,10.68,LOW_VOL,0.68,3,2026-09-11,14:30,29.5,expired,3,___,₹125,0,₹___,WIN/LOSS,___,First IC trade - Sep 8 signal,29528,___
```

---

**Key Metrics to Watch:**
- Entry fill within ±0.5 pts of expected (slippage < 20 bp)
- Position stays in range for full 3 days (theta capture ~100%)
- Daily monitoring noon + 3 PM IST (check buffer to strikes)
