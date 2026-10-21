# Daily Operations Guide — Paper Trading Journal

> **2026-10-21 STATUS: the weekly track is NOT a validated candidate.** The real-price backtest is unsupported (pre-registered verdict NOT SUPPORTED; see `../BACKTEST_CHANGELOG.md`, 2026-10-21). Live paper logging is data collection only. Monday-expiry era statements are wrong; the NIFTY calendar was corrected in commit 97e6974. Premiums and figures in this file are Black-Scholes estimates unless marked otherwise.

**Purpose**: Step-by-step procedure for each trading day (CLI + manual CSV flow)
**Frequency**: Daily (Mon–Fri, 10:00 AM–4:30 PM IST, NSE trading days only)
**Time commitment**: ~15 min/day
**Scope**: Phase 1 = weekly track only. Forward-only from Mon 2026-10-19.

> **API status: NOT USABLE until fixed.** The REST API in `api/server.py` cannot start at HEAD. Every `curl localhost:8000/...` step from the earlier version of this guide has been replaced with the CLI command or a manual step below. Known issues: [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) section (f). The API docs (`../API_GUIDE.md`) are kept for reference and are not operational.

---

## Overview: Four Daily Touchpoints

| Time (IST) | Task | Duration | Tool |
|------|------|----------|------|
| **Before 11:00** | Pre-flight: calendar, cache, models, Fyers | 5 min | Manual + `check_cache_health.sh` |
| **11:00–13:00** | Run signal; if ENTER, take broker prices and enter | 5–10 min | `python main.py --mode signal-combined` + broker |
| **3:00–4:30 PM** | Monitor against exit rules; exit if hit | 5 min | Broker screen |
| **4:30 PM** | End-of-day CSV rows | 5 min | `tracker/*.csv` |

---

# MORNING: PRE-FLIGHT (before 11:00 AM)

**Goal**: Confirm the day is a trading day and the data and models are usable.
**Output**: Go to the entry window, or log a SKIP with a reason code.

## Step 1: Calendar and models (2 min)
- Confirm the day is an NSE trading day. **Tue 2026-10-20 is a holiday (Dussehra)**, verified against NSE's holiday master (2026-10-18). On a holiday the signal prints `market closed`.
- Confirm model acceptance (RESTART section a). Not accepted → SKIP `MODEL_NOT_ACCEPTED`.

## Step 2: Cache and credentials (2 min)

```bash
# Cache freshness (from main checkout, no network)
python3 -c "import json; m=json.load(open('data/.cache/manifest.json')); print(m.get('last_date', m) if isinstance(m, dict) else m)"

# Cache health (exit 0 = pass)
ASOF=2026-10-19 PYTHON=.venv/bin/python scripts/check_cache_health.sh

# Credential names only (never print values)
cut -d= -f1 .env .env.local
```

- Cache last_date < 2026-10-16 or health check fails → SKIP `DATA_STALE`.
- Fyers session not live → SKIP `FYERS_UNAVAILABLE` (you cannot take real prices).

## Step 3: Account status (2 min)
Read the last row of `tracker/DAILY_LOG.csv` and `tracker/ACCOUNT_STATE.csv`:
- Account DD vs peak (pause rule: ≥ 15%)
- Open positions (Phase 1 max = 1)

---

# MID-SESSION: SIGNAL, ENTRY, LOG (11:00–13:00 IST)

**Goal**: Run the signal once inside the window. Enter only if it says ENTER and you have real prices.

## Step 1: Run the signal

```bash
python main.py --mode signal-combined --capital 2500000 --lots 30
```

Read only:
- **TRACK 2 · WEEKLY**: strategy, expiry and DTE, lots, legs
- **RISK ENGINE ASSESSMENT**: regime, risk score, `BLOCKED:` line if any
- **CURRENT MARKET SNAPSHOT**: India VIX

Ignore TRACK 1 (monthly).

| Printed | Decision |
|---------|----------|
| `ENTRY WINDOW GATE` | Outside 11:00–13:00. Re-run inside the window, or SKIP `OUTSIDE_WINDOW`. |
| `Weekly track: SKIP` | SKIP (reason code from RESTART section c) |
| `declined entry` | SKIP `PCS_DECLINED` |
| `BLOCKED:` | SKIP `RISK_ENGINE_SKIP` |
| `No weekly expiry fits` | SKIP `DTE_OUT_OF_RANGE` |
| `SUGGESTED WEEKLY TRADE` | Go to Step 2 |

Expected expiry for a Mon 2026-10-19 entry: **Tue 2026-10-27, 8 DTE** (top edge of the 3–8 window; the Tue 10-20 expiry moves to Mon 10-19). The signal's premiums are labelled `[BS est]`.

## Step 2: Get real prices and place the order (3–5 min)

The signal does not place orders. This step is manual.

1. Open the Nifty options chain on the broker for the printed expiry.
2. Read bid and ask for every printed strike.
3. Place the IOC order at the real price for the printed lot count.
4. Record: entry time (HH:MM IST), fill per leg, bid/ask per leg, lot count.

**Do not use the `[BS est]` figures as fills.**

## Step 3: Log the trade (within 5 min)

Add one row to `tracker/TRADES.csv` (27 columns; field mapping in RESTART section d):

```
P1-001,2026-10-19,11:42,23500PE/24600CE,14.1/14.6;13.2/13.8,28.1,<lots from signal>,<margin from broker>,iron_condor,17.3,<regime>,<risk score>,8,,,,,,,,,,,,"Entered 11:42 on printed lots",29528,
```

- Leave exit fields blank until exit.
- `ML_Score` = the printed weekly `Risk score` (tail-risk, not a win probability). Write `NA` if no risk engine loaded.
- Add the DAILY_LOG row at 4:30 PM (`Weekly_Trades_Executed` = 1).

## Step 4: Verify

```bash
tail -2 paper_trading/tracker/TRADES.csv
```

Check: Trade_ID is new, Lots_Size matches the signal, Expiry_DTE is 3–8, Strategy matches VIX band.

---

# AFTERNOON: MONITORING & EXIT (3:00–4:30 PM IST)

**Goal**: Exit when a rule is hit. Otherwise hold.
**Check frequency**: Every 30 min from 3:00 PM (and at 12:30 PM if the trade was entered that morning).

## Exit rules (check each open trade)

| Rule | Trigger | Action |
|------|---------|--------|
| Stop (100% of credit) | Loss reaches 100% of credit collected | **EXIT NOW** |
| Stop (short strike) | Underlying breaches the short strike | **EXIT NOW** |
| Profit target (PCS only) | 75% of max profit reached | **EXIT** |
| IC profit target | None | Hold to rule below |
| IC max hold | 4 trading days (as printed by the signal; pending owner confirmation) | **EXIT** |
| Expiry day | Still open at 15:15 IST | **EXIT** |
| Manual | Judgement call (tail event, broker or data failure) | **EXIT**, log reason |

**There is no 3-day cap.** A Tuesday-to-Tuesday trade is about 5 trading days.

## Closing the trade

1. Close all legs on the broker. Note fills and time.
2. Update the TRADES.csv row: `Date_Exit`, `Exit_Time_IST`, `Exit_Price_Fill`, `Exit_Reason` (`profit_target`, `stop_loss_100pct`, `short_strike_breach`, `max_hold`, `expiry`, `manual`), `Days_Held` (trading days), `Gross_P&L_₹`, `Brokerage_₹`, `Net_P&L_₹`, `Win_Loss`, `P&L_vs_Max_Profit_%`, `Backtest_Deviation_%`.

---

# END-OF-DAY: LOGGING & WRAP-UP (4:30 PM IST)

## Step 1: Final account snapshot
From the broker: account equity, cumulative P&L, open positions (should be 0 after exit), VIX close.

## Step 2: Add the DAILY_LOG.csv row
15 columns, in order (RESTART section c). Example entry day:

```
2026-10-19,Monday,<equity>,<cum_pnl>,0,<VIX>,<regime>,1,1,0,0,<DD%>,<win%>,<avg_pnl>,"Entered 11:42; closed <time>"
```

Example skip day:

```
2026-10-19,Monday,2500000,0,0,<VIX>,<regime>,0,0,0,0,0,,,"SKIP PCS_DECLINED: <one-line reason>"
```

## Step 3: Deviation log
If the day was a skip or the trade deviated from the signal, add a row to the Deviation Log in `PAPER_TRADING_JOURNAL.md`.

## Step 4: End-of-day checklist
```
☐ No open positions (or the open one is logged)
☐ TRADES.csv has the entry (and exit, if closed)
☐ DAILY_LOG.csv has today's row
☐ ACCOUNT_STATE.csv updated only on a trade day
☐ Account DD < 15% of peak (pause rule)
☐ Deviation Log row added if needed
✓ DONE for the day
```

---

# HANDLING MISSED LOGGING (CATCH-UP)

If you miss logging, catch up the next trading morning, before the entry window.

- **Trade exit not logged**: get the fills from the broker's contract note, then update the TRADES.csv row for that trade.
- **Daily row missed**: add the row for that date from the broker figures. Log oldest → newest.
- **Never back-fill a trade you did not take.** Missed signals go in the Deviation Log.

---

# TROUBLESHOOTING

| Issue | Symptom | Fix |
|-------|---------|-----|
| Signal prints `[BS est]` only | Expected: premiums are estimates | Take broker prices (Step 2) |
| Cache stale | Health check fails or last_date < 2026-10-16 | Refresh via the owner's data refresh, then re-check; otherwise SKIP `DATA_STALE` |
| Signal shows a monthly trade | Expected in TRACK 1 | Ignore it; Phase 1 is weekly only |
| Expiry shows DTE 0 or 9+ | Out of window | SKIP `DTE_OUT_OF_RANGE`; do not force the expiry |
| Trade row wrong | Typo in TRADES.csv | Correct it in place; keep Trade_ID |
| API not responding | `curl` fails | Expected: API not usable. Use the CLI. |

---

# WEEKLY SUMMARY (Friday 4:00 PM)

- Count weekly trades and skips this week (from DAILY_LOG.csv)
- Net P&L and win rate (from TRADES.csv)
- Account DD vs peak
- Fill the weekly block in `tracker/RISK_DASHBOARD.md`
- Decision: continue, pause (DD rule), or review

---

# MONTHLY REVIEW (checkpoint dates in PAPER_TRADING_JOURNAL.md)

Fill `analysis/MONTHLY_ANALYSIS.md` from TRADES.csv and DAILY_LOG.csv: trade-by-trade review, win rate vs backtest (78%), P&L vs ₹29,528 average, largest win and loss, missed signals, deviations.

**Decision**: GO (continue Phase 1) · HOLD (more data) · STOP (investigate the backtest vs live gap)

---

# BEST PRACTICES

✓ **Log immediately.** Memory fades.
✓ **Run the signal once in the window.** Re-run only if the first run hit the gate.
✓ **Real prices only.** Never fill against `[BS est]`.
✓ **Use the printed lot count.** Do not resize.
✓ **Stop = 100% of credit or short-strike breach.** No exceptions.
✓ **Review every Friday.**

---

**Questions?** See [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) (procedure and reason codes) or [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) (rules).
