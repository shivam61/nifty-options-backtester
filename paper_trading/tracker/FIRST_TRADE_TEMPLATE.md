# First Real Trade — Mon 2026-10-19 (Ready to fill in)

**Trade ID**: P1-001 (first real Phase 1 trade)
**Note**: The 2026-08-29 Iron Condor is a SIMULATED back-fill, excluded from Phase 1 counts. This template is for the first real trade only.
**If the signal says SKIP**: do not fill this in. Log a SKIP row in DAILY_LOG.csv with a reason code (RESTART_2026-10-19.md section c).

## Pre-Flight (before 11:00 IST; see RESTART section b)
- [ ] Holiday check: Tue 2026-10-20 closed (Dussehra, verified against NSE 2026-10-18); its weekly expiry moves to Mon 10-19
- [x] Models: weekly track accepted with risk engine OFF (owner decision 2026-10-19); monthly track not accepted
- [ ] Cache: `python3 -c "import json; m=json.load(open('data/.cache/manifest.json')); print(m.get('last_date', m) if isinstance(m, dict) else m)"` → last_date ____ (≥ 2026-10-16)
- [ ] `ASOF=2026-10-19 PYTHON=.venv/bin/python scripts/check_cache_health.sh` → exit 0
- [ ] Fyers session live (credential names present in `.env` or `.env.local`)
- [ ] Open weekly positions: 0

## Signal Execution (11:00–13:00 IST)
```
Command: python main.py --mode signal-combined --capital 2500000 --lots 30
Run once in the window. Read TRACK 2 (WEEKLY) and RISK ENGINE ASSESSMENT only.
Expected: weekly trade with expiry Tue 2026-10-27 (8 DTE, top edge of the 3–8 window). Premiums are [BS est].
```

## At Entry (fill in when the signal says ENTER)

| Field | Fill In |
|-------|---------|
| **Entry Time (IST)** | __:__ (11:00–13:00) |
| **Nifty Spot at entry** | ___,___ |
| **India VIX (signal)** | ___.__ |
| **Strategy (as printed)** | [ ] Put Credit Spread (VIX ≤ 16) [ ] Iron Condor (VIX > 16) |
| **Expiry (as printed)** | ____ (___ DTE; must be 3–8) |
| **Short Put Strike** | ___,___ PE (or N/A for IC: see below) |
| **Short Call Strike** | ___,___ CE (IC only) |
| **Broker Bid/Ask per leg** | ___/___ ; ___/___ |
| **Entry Fill (net credit, ₹/unit)** | ₹___.__ |
| **CLI [BS est] credit (for slippage)** | ₹___.__ |
| **Lots (as printed by signal)** | ___ (copy exactly) |
| **Margin blocked (broker)** | ₹___,___ |
| **Stop level (100% of credit)** | Loss of ₹___.__ per unit, or short-strike breach at ___ |
| **Profit target (PCS only, 75%)** | ₹___.__ per unit (IC: none) |
| **ML_Score (printed weekly Risk score)** | ___.__ (tail-risk; not a win probability; Phase 1 engine is OFF, so write NA) |

## Monitoring (daily, 11:00 and 3:00 PM IST)

| Day | Nifty | Distance to short strike | Status | Notes |
|-----|-------|--------------------------|--------|-------|
| Mon 10-19 | ___,___ | ___ | [ ] In range / [ ] Near / [ ] Breach | |
| Wed 10-21 | ___,___ | ___ | [ ] In range / [ ] Near / [ ] Breach | |
| Thu 10-22 | ___,___ | ___ | [ ] In range / [ ] Near / [ ] Breach | |
| Fri 10-23 | ___,___ | ___ | [ ] In range / [ ] Near / [ ] Breach | |
| Mon 10-26 | ___,___ | ___ | [ ] In range / [ ] Near / [ ] Breach | |
| Tue 10-27 | ___,___ | ___ | [ ] EXPIRED / [ ] Exit earlier | |

(Add rows for any day the trade is open. Tue 10-20 is an NSE holiday, verified 2026-10-18.)

## Exit (at rule trigger or expiry)

| Field | Value |
|-------|-------|
| **Exit Date** | ____ |
| **Exit Time (IST)** | __:__ |
| **Exit Reason** | [ ] profit_target [ ] stop_loss_100pct [ ] short_strike_breach [ ] max_hold [ ] expiry [ ] manual |
| **Exit fill (net debit, ₹/unit)** | ₹___.__ |
| **Brokerage** | ₹___ |
| **Net P&L** | ₹___,___ |
| **Days held (trading days)** | ___ |
| **vs Backtest Expected** | Expected ₹29,528 / Actual ₹___,___ |

## Post-Trade Logging

After exit, update:
1. `tracker/TRADES.csv`: add the entry row (27 columns; RESTART section d) and fill the exit fields
2. `tracker/DAILY_LOG.csv`: add a row for each trading day (15 columns; `Weekly_Trades_Executed` = 1 on entry day)
3. `PAPER_TRADING_JOURNAL.md`: note the outcome under Checkpoint 1 and add any deviation

## Sample Entry Row (for copy-paste into TRADES.csv; replace every placeholder)

```
P1-001,2026-10-19,11:42,23500PE/24600CE,14.1/14.6;13.2/13.8,28.1,<lots from signal>,<margin from broker>,iron_condor,17.3,<regime>,<risk score>,8,,,,,,,,,,,,"Entered 11:42 on printed lots",29528,
```

Note: the example row above is a placeholder. Do not treat its values as real.

---

**Key Metrics to Watch**:
- Fill within the broker bid/ask (no fills on `[BS est]` prices)
- Stop rule: exit at 100% of credit or on a short-strike breach
- PCS: take profit at 75% of max profit. IC: no profit target.
- Daily checks at 11:00 and 3:00 PM IST
