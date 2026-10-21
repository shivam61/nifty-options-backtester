# Paper Trading Setup Checklist

> **2026-10-21 STATUS: the weekly track is NOT a validated candidate.** The real-price backtest is unsupported (pre-registered verdict NOT SUPPORTED; see `../BACKTEST_CHANGELOG.md`, 2026-10-21). Live paper logging is data collection only. Monday-expiry era statements are wrong; the NIFTY calendar was corrected in commit 97e6974. Premiums and figures in this file are Black-Scholes estimates unless marked otherwise.

**Objective**: Get ready for the forward-only restart on **Mon 2026-10-19**
**Initial Capital**: ₹25,00,000 (CLI `--capital 2500000`; weekly budget ₹12,50,000)
**Strategy**: Weekly PCS/IC only (monthly paused)
**Start Date**: Mon 2026-10-19 (Phase 1 counts start here)
**API status**: ⚠️ NOT USABLE until fixed. Use the CLI and the manual CSV flow. Known issues: [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) section (f).

---

## Week 1: Setup & Preparation

### Day 1: Read Documentation (2 hours)
- [ ] Read `paper_trading/RESTART_2026-10-19.md` (runbook, 10 min)
- [ ] Read `paper_trading/README.md` (overview, 15 min)
- [ ] Read `PAPER_TRADING_JOURNAL.md` (rules, rule-change table, checkpoints, 30 min)
- [ ] Read `QUICK_REFERENCE.md` (trading cheat sheet, 20 min)
- [ ] Print DAILY_CHECKLIST.md and QUICK_REFERENCE.md (laminate if possible)
- [ ] Skim all CSV templates (5 min)

**Checkpoint**: Understand the framework. Ask clarifying questions now.

### Day 2–3: Broker Account Setup (4 hours)
- [ ] Open Fyers account (or confirm the existing one) with the capital to run (₹25L per the CLI)
  - Contact: https://fyers.in/
  - Required: PAN, Aadhaar, bank account
  - Account type: Individual (not corporate)
  - Segment: F&O (derivatives)

- [ ] Set up 2FA (SMS + email)
- [ ] Enable withdrawal disable mode (security)
- [ ] Confirm the Fyers credential names are in `.env` or `.env.local` (`cut -d= -f1 .env .env.local`; never print values)
- [ ] Deposit capital (may take 1–2 business days)

**Checkpoint**: Account funded, credentials present, broker platform login works.

### Day 4: Verify Models & Data
- [ ] Check baseline models exist:
  ```bash
  ls -la data/.cache/entry_model_v4.pkl  # RegimeAwareLearner (monthly track)
  ls -la data/.cache/exit_model.pkl      # ExitStrategyEngine
  ```
  Both files should be present. Models were retrained 2026-10-18; the weekly track is **accepted with the weekly risk engine OFF** (owner decision 2026-10-19). The monthly track is not accepted (under investigation).

- [ ] Run the cache health check (exit 0 required):
  ```bash
  ASOF=2026-10-19 PYTHON=.venv/bin/python scripts/check_cache_health.sh
  ```

- [ ] Review backtest baseline (Run #60):
  - Read: docs/BACKTEST_COMBINED_MODE.md
  - Confirm: 12.07% CAGR, 78% win rate, ₹29,528 avg P&L/trade

- [ ] Verify capital allocation plan:
  - Weekly budget: ₹12,50,000 (50%)
  - Monthly: ₹12,50,000 (50%, paused in Phase 1)

**Checkpoint**: Models and cache confirmed, allocation verified.

### Day 5–7: Broker & Signal Testing (6 hours)

The REST API is not usable. Test the CLI signal and the broker platform.

**Test 1: Signal dry run (outside the entry window is fine; it will print the gate)**
```bash
python main.py --mode signal-combined --capital 2500000 --lots 30
```
- [ ] Read the output: weekly track, expiry line, lots, legs, `[BS est]` premiums
- [ ] Confirm you can find each field RESTART section (d) asks for

**Test 2: Broker platform**
- [ ] Log in to the Fyers web/app and open the Nifty options chain
- [ ] Read bid/ask for a few strikes and note the spread
- [ ] Place and cancel a practice order (small quantity, far from market) to confirm IOC and cancel work

**Test 3: Broker latency**
- [ ] Time 5 order-to-fill or order-to-cancel round trips and note the average
- [ ] Target: under 2 seconds from order placement to confirmation

**Checkpoint**: Signal output readable, broker platform usable, latency logged.

### Day 5–7: Set Up Tracking

- [ ] CSV headers checked: TRADES.csv (27 columns), DAILY_LOG.csv (15 columns); data rows untouched
- [ ] PAPER_TRADING_JOURNAL.md: checkpoint dates confirmed (2026-11-18, 2026-12-18)

- [ ] Create calendar reminders:
  - 10:00 AM (weekdays): "Pre-flight" (RESTART section b)
  - 11:00 AM (weekdays): "Run the signal, 11:00–13:00 window"
  - 4:30 PM (weekdays): "Log the day (DAILY_LOG.csv, every trading day)"
  - 4:00 PM (Fridays): "Weekly checkpoint"
  - 1st of each month: "MONTHLY_ANALYSIS.md review"

- [ ] Set up notifications:
  - Email alert if account DD > 10% of peak
  - Alert at DD 15% (pause rule)
  - Test alerts with dummy events

**Checkpoint**: All templates ready, reminders set, alerts active.

---

## Week 2: Rules Review & Simulation

### Day 8–9: Deep Dive Rules (3 hours)

**Entry Rules**:
- [ ] Memorize the entry checklist (QUICK_REFERENCE.md)
  - [ ] Pre-flight passed (calendar, cache, models, Fyers)
  - [ ] Signal run once, inside 11:00–13:00 IST
  - [ ] Weekly track says a trade (not SKIP); no `BLOCKED:` line
  - [ ] Expiry 3–8 DTE
  - [ ] Real broker bid/ask for every strike
  - [ ] No other open weekly position

**Exit Rules**:
- [ ] PCS: profit target = 75% of max profit → EXIT
- [ ] IC: no profit target
- [ ] Stop = 100% of credit collected, or short-strike breach → EXIT immediately
- [ ] Expiry day → EXIT by 15:15 IST
- [ ] IC max hold 4 trading days (as printed; pending owner confirmation). **No 3-day cap.**
- [ ] Manual only for tail events or broker failure

**Risk Limits**:
- [ ] Per-trade: stop rule above. **No ₹ cap per trade** (worst backtest weekly loss ₹−53,255 is above the old ₹50k cap)
- [ ] Account pause: DD ≥ 15% of peak (₹3,75,000)
- [ ] Concurrent open weekly positions: 1

**Escalation Protocol** (print & tape on monitor):
- [ ] 🟡 Yellow: DD 5–10% of peak. Review signals; no size change without owner approval.
- [ ] 🔴 Red: DD ≥ 15%. Pause entries and review.

### Day 9–10: Simulate 3 Trades (2 hours)

**Simulation 1: Low VIX Entry (PCS)**
- Scenario: VIX = 15, Tuesday weekly expiry 5 DTE
- Signal: Put Credit Spread (VIX ≤ 16)
- Simulated credit: ₹85 per unit (lots as printed by the signal; assume 15)
  - Max profit: ₹85 × 65 × 15 = ₹82,875 (per lot count assumed)
  - Profit target (75%): ₹62,156
  - Stop (100% of credit): loss of ₹85 per unit
- Simulate exit: spread decays to ₹20 next day → exit at 75% target
- Log: simulate entry in TRADES.csv (a practice sheet, not the real file)
- Q: Would you have taken this? Why/why not?

**Simulation 2: High VIX Entry (IC)**
- Scenario: VIX = 20, Tuesday weekly expiry 3 DTE
- Signal: Iron Condor (VIX 16–25)
- Simulated credit: ₹55 per unit (assume 15 lots)
  - Max profit: ₹55 × 65 × 15 = ₹53,625
  - No profit target (IC)
  - Stop (100% of credit): loss of ₹55 per unit
- Simulate exit: short strike breached on day 2 → stop
- Q: How would you handle a breach that is still within the stop?

**Simulation 3: Tail Event**
- Scenario: Entered at ₹80, mid-trade VIX spikes; short strike breached
- Action: Exit immediately at the stop rule, accept the loss, log deviation
- Q: Did the loss exceed 100% of credit? If yes, why (gap, fill delay)?

**Checkpoint**: Can execute the entry and exit rules from the card? Ready to trade live.

### Day 10–11: Broker Rehearsal (2 hours)

- [ ] Rehearse 5 practice orders on the broker platform (small size, far from market; cancel)
- [ ] Practice trade logging on paper: 3 simulated trades into a scratch sheet (not TRADES.csv)
- [ ] Test error handling:
  - Close the broker app mid-session, recover via the web platform
  - Test manual order cancellation

**Checkpoint**: Comfortable with the broker platform, logging fast and accurate.

### Day 12–14: Final Review & Launch Prep (3 hours)

- [ ] Reread RESTART_2026-10-19.md and QUICK_REFERENCE.md (laminated)
- [ ] Reread the entry checklist (can do from memory?)
- [ ] Reread exit rules (PCS 75%; stop 100% of credit / short strike; no 3-day cap)
- [ ] Reread the pause rule (DD ≥ 15%)
- [ ] Verify all files in place:
  ```bash
  ls paper_trading/{README.md, RESTART_2026-10-19.md, QUICK_REFERENCE.md, PAPER_TRADING_JOURNAL.md}
  ls paper_trading/tracker/{TRADES.csv, DAILY_LOG.csv, RISK_DASHBOARD.md}
  ls paper_trading/analysis/MONTHLY_ANALYSIS.md
  ```

- [ ] Final equipment check:
  - [ ] Monitor setup (QUICK_REFERENCE laminated and visible)
  - [ ] Internet stable
  - [ ] Phone charged (broker app + alerts ready)
  - [ ] Notebook for manual notes (backup if no time to log)

- [ ] Pre-launch review (internal or with mentor):
  - [ ] Discuss backtest baseline
  - [ ] Discuss entry/exit rules and the rule-change table
  - [ ] Discuss the pause rule
  - [ ] Agree on check-in cadence (weekly call?)

**Checkpoint**: Ready for live trading. All systems GO.

---

## Launch Week: Live Trading Begins

### Mon 2026-10-19 (Restart day)
- [ ] 10:00 AM: Pre-flight (RESTART section b), including the holiday and expiry check
- [ ] 11:00 AM–1:00 PM: Run the signal once; enter if ENTER, else log a SKIP
- [ ] 4:30 PM: Log the day (DAILY_LOG.csv), even if no trade
- [ ] Evening: Reflect on the first day

### Tue 2026-10-20
- [ ] NSE holiday (Dussehra), verified against NSE's holiday master on 2026-10-18. No trading; the signal prints `market closed`.
- [ ] Log the day as HOLIDAY if you want the gap visible (optional)

### Wed 2026-10-21 – Fri 2026-10-23
- [ ] 10:00 AM: Pre-flight
- [ ] 11:00 AM–1:00 PM: Run signal; enter or SKIP
- [ ] 4:30 PM: Log the day
- [ ] Friday 4:00 PM: Weekly checkpoint

### After Week 1
- [ ] Review: How many signals? How many trades? How many skips and why?
- [ ] Confidence: Are the rules clear? Any changes needed? (Log them in the rule-change table with owner approval.)
- [ ] Continue for 6 months (or until the Phase 2 decision)

---

## Go/No-Go Decision Points (from the restart)

### Day 30 (2026-11-18)
**Check**:
- [ ] Trades executed: 0–2 (expected)
- [ ] Win rate: >= 70% (early data)
- [ ] Account DD: < 5%
- [ ] Fill quality: real broker prices logged for every fill

**Decision**:
- ✅ Continue Phase 1
- ⏸️ Hold if poor data → Collect more trades
- ❌ Stop if DD ≥ 15% → Investigate

### Day 60 (2026-12-18)
**Check**:
- [ ] Trades executed: 2–3 total
- [ ] Win rate: >= 75%
- [ ] Backtest variance: < 30%

**Decision**:
- ✅ Proceed (Phase 1 continues)
- ⏸️ Extend Phase 1 if marginal
- ❌ Stop if criteria not met

### Day 180 (about 2027-04-19)
**Check**:
- [ ] Trades executed: 6–8 total
- [ ] Win rate: >= 75%
- [ ] Account DD: < 12%
- [ ] Backtest variance: < 30%

**Decision**:
- ✅ **GO TO PHASE 2**: Add monthly trading (per the journal's allocation rules)
- ⏸️ **HOLD**: Collect 3 more months of data
- ❌ **STOP**: Investigate backtest vs live gap, pause trading

---

## Contacts & Resources

| Item | Details |
|------|---------|
| **Fyers Support** | https://support.fyers.in/ |
| **Fyers API Docs** | https://docs.fyers.in/api/ (API server not operational) |
| **Backtest Report** | docs/BACKTEST_COMBINED_MODE.md |
| **ML Model** | data/.cache/entry_model_v4.pkl |
| **Emergency Broker** | [Backup broker, if any] |
| **Personal Contact** | [Your name, phone, email] |

---

## Final Checklist (Before Live)

- [ ] Account funded (₹25L per CLI, or the capital you run with)
- [ ] Broker platform tested (order, cancel, latency logged)
- [ ] Signal dry run read and understood
- [ ] All templates ready (TRADES.csv 27 columns, DAILY_LOG.csv 15 columns)
- [ ] QUICK_REFERENCE laminated & visible
- [ ] Alerts set (email, DD 10% and 15%)
- [ ] Rules memorized (entry, exit, pause, rule-change table)
- [ ] Calendar reminders active
- [ ] 3 simulated trades done
- [ ] Model acceptance recorded in RESTART section (a)
- [ ] Ready to trade!

---

**Prepared By**: System
**Date Prepared**: 2026-10-18
**Target Live Date**: Mon 2026-10-19 (pending pre-flight)
**Status**: [ ] Ready [ ] Not Yet [ ] Completed
