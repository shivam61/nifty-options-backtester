# Daily Trading Checklist — Quick Reference Card

> **2026-10-21 STATUS: the weekly track is NOT a validated candidate.** The real-price backtest is unsupported (pre-registered verdict NOT SUPPORTED; see `../BACKTEST_CHANGELOG.md`, 2026-10-21). Live paper logging is data collection only. Monday-expiry era statements are wrong; the NIFTY calendar was corrected in commit 97e6974. Premiums and figures in this file are Black-Scholes estimates unless marked otherwise.

**Print this page and keep it on your desk during trading hours.**
**Phase 1 is WEEKLY ONLY. Ignore the monthly track output. Forward-only from Mon 2026-10-19.**
**REST API: NOT USABLE until fixed (see RESTART_2026-10-19.md section f). Use the CLI and the CSVs below.**
**Full procedure and reason codes: [RESTART_2026-10-19.md](./RESTART_2026-10-19.md)**

---

## ⏰ MORNING: PRE-FLIGHT (before 11:00 IST)

### 1️⃣ Pre-flight (5 min)
- [ ] Today is a trading day (NSE holiday check; Tue 2026-10-20 Dussehra is closed, verified)
- [ ] Cache healthy: `ASOF=$(date +%F) PYTHON=.venv/bin/python scripts/check_cache_health.sh` (exit 0)
- [ ] Fyers session live (`cut -d= -f1 .env .env.local` shows the credential names)
- [ ] Models: weekly track accepted with the risk engine OFF (RESTART section a). Not accepted → SKIP `MODEL_NOT_ACCEPTED`.
- [ ] Open positions = 0 (Phase 1 max = 1 weekly position)

### 2️⃣ Account Status (1 min)
- [ ] Last row of `tracker/DAILY_LOG.csv` and `tracker/ACCOUNT_STATE.csv` read
- [ ] Account DD < 15% of peak (pause rule)

---

## 🚀 ENTRY WINDOW: 11:00–13:00 IST

### 1️⃣ Run the signal (once; re-run only if it hit the window gate)
```bash
python main.py --mode signal-combined --capital 2500000 --lots 30
```
- Read **TRACK 2 · WEEKLY** and the **RISK ENGINE ASSESSMENT** only. Ignore TRACK 1 (monthly).
- Note the **Lots** count and the expiry line (must be 3–8 DTE; expected Tue 2026-10-27 for a Mon 10-19 entry).

| Printed line | Decision |
|--------------|----------|
| `Weekly track: SKIP` | Log SKIP row (code from RESTART section c) |
| `BLOCKED:` under RISK ENGINE | SKIP `RISK_ENGINE_SKIP` |
| `declined entry` | SKIP `PCS_DECLINED` |
| `No weekly expiry fits` | SKIP `DTE_OUT_OF_RANGE` |
| `SUGGESTED WEEKLY TRADE` | Proceed to the broker |

### 2️⃣ Get real prices (the signal's premiums are `[BS est]`)
- [ ] Broker bid/ask for every printed strike, on the same expiry
- [ ] Wait for a fill inside the window; use IOC
- [ ] Record each leg's fill and time

### 3️⃣ Log the trade by hand (within 5 min)
- [ ] `tracker/TRADES.csv`: new row, 27 columns (RESTART section d)
- [ ] `Lots_Size` = the lot count the signal printed (do not resize)
- [ ] `Strategy` = `put_credit_spread` (VIX ≤ 16) or `iron_condor`

---

## 👁️ AFTERNOON: 3:00–4:30 PM IST (check every 30 min)

| Check | Action |
|-------|--------|
| Loss reaches 100% of credit collected | **EXIT NOW** (stop) |
| Price breaches the short strike | **EXIT NOW** (stop) |
| PCS reaches 75% of max profit | **EXIT** (profit target). IC has no profit target. |
| Expiry day, 15:15 IST | **EXIT** if still open |
| IC held 4 trading days (CLI printed max hold) | **EXIT** (as printed; pending owner confirmation) |

When you exit: record the exit row in `TRADES.csv` (`Exit_Reason` = `profit_target`, `stop_loss_100pct`, `short_strike_breach`, `max_hold`, `expiry`, or `manual`).

---

## 📝 END-OF-DAY: 4:30 PM IST

- [ ] Account equity and cumulative P&L recorded (from broker)
- [ ] `tracker/DAILY_LOG.csv`: one row for the day (15 columns; RESTART section c/d)
- [ ] `tracker/TRADES.csv`: entry and exit rows complete, if a trade happened
- [ ] `tracker/ACCOUNT_STATE.csv`: updated only on a real trade day (leave unchanged on a SKIP)
- [ ] Deviation Log row added in `PAPER_TRADING_JOURNAL.md` for any skip or deviation
- [ ] Account DD < 15%? (If not: pause rule applies, see below)

---

## 🔄 CATCH-UP (missed logging)

Log oldest → newest, one row per day, before the next signal run. Use the actual broker figures for the date. Do not back-fill a trade you did not take.

---

## 🚨 HARD STOPS (the only ones)

| Trigger | Action |
|---------|--------|
| **Stop per trade**: loss = 100% of credit, or short strike breached | EXIT immediately. (This is the only stop rule.) |
| **Account DD ≥ 15%** of peak equity (₹3,75,000 from ₹25L) | Close open positions, pause all entries, review. (This is the only pause rule.) |

There is no per-trade ₹ cap. The backtest's worst weekly loss (₹−53,255) is above the old ₹50k cap.

---

## 📊 WEEKLY REVIEW (Friday 4:00 PM)

- [ ] Fill the weekly block in `tracker/RISK_DASHBOARD.md` from TRADES.csv and DAILY_LOG.csv
- [ ] Trades this week / win rate / net P&L / account DD
- [ ] Decision: [ ] Continue [ ] Pause (DD rule) [ ] Review

---

## 📈 MONTHLY REVIEW (Checkpoint dates in PAPER_TRADING_JOURNAL.md)

Fill `analysis/MONTHLY_ANALYSIS.md` from TRADES.csv. Compare with backtest (78% win rate; ₹29,528 average per trade). Decide GO / HOLD / STOP per the journal.

---

## 🎯 ENTRY RULES

✓ Entry any time 11:00–13:00 IST while the signal says ENTER
✓ Weekly expiry 3–8 DTE (expected Tue 2026-10-27 for a Mon 10-19 entry)
✓ Real broker bid/ask taken for every leg (no fills on `[BS est]` prices)
✓ Lots = the count the signal printed
✓ One open weekly position at a time (Phase 1)

## 🎯 EXIT RULES

✓ **PCS: 75% of max profit** → EXIT
✓ **Stop: 100% of credit, or short strike breached** → EXIT immediately
✓ **Expiry day: close by 15:15 IST**
✓ **IC: max hold 4 trading days** (as printed by the signal; pending owner confirmation)
✓ There is **no 3-day cap**

---

## 🕐 TIME SUMMARY

| Time | Action | Duration |
|------|--------|----------|
| **10:00 AM** | Pre-flight + account status | 5 min |
| **11:00–13:00** | Run signal, get broker prices, enter if ENTER | 5–10 min |
| **3:00–4:30 PM** | Monitor exit rules every 30 min | 5 min |
| **4:30 PM** | End-of-day logging | 5 min |

---

**Laminate this page. Keep on desk.**
