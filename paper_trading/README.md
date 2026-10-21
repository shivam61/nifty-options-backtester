# Paper Trading Journal & Tracking System

> **2026-10-21 STATUS: the weekly track is NOT a validated candidate.** The real-price backtest is unsupported (pre-registered verdict NOT SUPPORTED; see `../BACKTEST_CHANGELOG.md`, 2026-10-21). Live paper logging is data collection only. Monday-expiry era statements are wrong; the NIFTY calendar was corrected in commit 97e6974. Premiums and figures in this file are Black-Scholes estimates unless marked otherwise.

**Status**: Restarting forward-only on Mon 2026-10-19 (see [RESTART_2026-10-19.md](./RESTART_2026-10-19.md))
**Initial Capital**: ₹25,00,000 (CLI `--capital 2500000`)
**Strategy**: Weekly PCS/IC only. No fixed hold period; exits by rule.
**Baseline Model**: Run #66 (11.98% CAGR, 78% weekly win rate; reference Run #60 12.07%)
**Phase**: 1 — Validation (6 months)
**API status**: NOT USABLE until fixed. Use the CLI and the manual CSV flow.

---

## Overview

This is a complete paper trading tracking system for validating the Phase 4 baseline backtest (Run #60) against live market conditions. The system is designed to capture every trade, measure slippage, validate signals, and provide clear go/no-go decision criteria for advancing to Phase 2 (adding monthly trading).

**Zero real paper trades exist.** Trade #1 (2026-08-29 IC) is a SIMULATED back-fill and is excluded from every count.

### What's Inside

```
paper_trading/
├── README.md                        ← You are here
├── RESTART_2026-10-19.md           ← Start here for the Mon 10-19 restart
├── PAPER_TRADING_JOURNAL.md        ← Main journal with checkpoints and rule changes
├── QUICK_REFERENCE.md              ← Laminated cheat sheet (print this)
├── tracker/
│   ├── TRADES.csv                  ← Every trade logged here (27 columns)
│   ├── DAILY_LOG.csv               ← End-of-day / skip-day snapshot (15 columns)
│   └── RISK_DASHBOARD.md           ← Risk monitoring template
├── analysis/
│   └── MONTHLY_ANALYSIS.md         ← Month-end detailed review
├── journal/
│   └── [TRADE_NOTES_YYYY_MM.txt]  ← Free-form daily notes
└── logs/
    └── [API_LOGS_YYYY_MM_DD.log]  ← Technical execution logs (API not operational)
```

---

## Quick Start

### 1. Account Setup
- [ ] Open Fyers account funded with ₹25L (or the capital you run with)
- [ ] Get Fyers credentials (names in `.env` or `.env.local`; never commit values)
- [ ] Set up 2FA & withdraw-disable mode

### 2. System Initialization
- [ ] Verify the models and cache per RESTART section (a) and (b)
- [ ] Print QUICK_REFERENCE.md (keep on desk during trading)
- [ ] Set calendar reminders for weekly checkpoints (Fridays 4 PM) and the Mon 10-19 pre-flight

### 3. Pre-Trading Checklist
- [ ] Read RESTART_2026-10-19.md (about 10 min)
- [ ] Read QUICK_REFERENCE.md (trading rules, 5 min)
- [ ] Run the signal once to see the output format: `python main.py --mode signal-combined --capital 2500000 --lots 30`

### 4. Go Live
- [ ] Trade weekly PCS/IC only (monthly paused; ignore TRACK 1 output)
- [ ] Take real broker bid/ask for every fill (the signal's premiums are `[BS est]`)
- [ ] Log every entry and exit in TRADES.csv within 5 min of execution
- [ ] Log the day in DAILY_LOG.csv at 4:30 PM (every trading day, including skips)

---

## File-by-File Guide

### RESTART_2026-10-19.md
**Purpose**: One-page runbook for a fresh session or operator
**Key Sections**: status snapshot, pre-flight checklist for Mon 10-19, SKIP logging with reason codes, ENTRY field mapping, exit rules, known gaps

### PAPER_TRADING_JOURNAL.md
**Purpose**: Central journal with checkpoints, rule-change table and decision criteria
**Update Frequency**: At each checkpoint (30 and 60 days from 2026-10-19, then as set)
**Key Sections**:
- Account overview (₹25L; weekly budget ₹12.5L)
- Trading rules (stop = 100% of credit or short-strike breach)
- Rule changes vs the original template (2026-10-19)
- Checkpoints (rebased to the 2026-10-19 restart)
- Deviation log (skips and deviations)
- Go/no-go decision criteria for Phase 2

### QUICK_REFERENCE.md
**Purpose**: Laminated trading cheat sheet
**Key Sections**: entry checklist, exit rules, risk limits, trade log example, escalation, common mistakes

### TRADES.csv
**Purpose**: Master log of every trade (entry → exit)
**Update Frequency**: At entry, and again at exit
**Columns**: 27 fields (see RESTART section d for the mapping)

**How to Use**:
1. At entry: Trade_ID, Date_Entry, Entry_Time_IST, Strike_Entry, Bid_Ask_Entry, Entry_Price_Fill, Lots_Size (as printed by the signal), Expiry_DTE, Strategy
2. At exit: Date_Exit, Exit_Time_IST, Exit_Price_Fill, Exit_Reason, Days_Held, Gross/Net P&L, Win_Loss
3. Calculate P&L_vs_Max_Profit_% and Backtest_Deviation_%

### DAILY_LOG.csv
**Purpose**: Daily account snapshot, one row per trading day (also on skip days)
**Update Frequency**: Every trading day at 4:30 PM
**Columns**: 15 fields (see RESTART section c)

### RISK_DASHBOARD.md
**Purpose**: Risk monitoring template (updated daily, reviewed weekly)
**Key Sections**: account status, open position, alerts, daily checklist, weekly checkpoint, the single pause rule

### MONTHLY_ANALYSIS.md
**Purpose**: Detailed month-end review (backtest vs live)
**Update Frequency**: Once per month
**Key Sections**: summary, trade-by-trade review, deviations, backtest vs live table, go/no-go

---

## Capital Allocation

| Allocation | Amount | Purpose |
|----------|--------|---------|
| **Weekly budget** | ₹12,50,000 (50%) | Phase 1 strategy (the CLI budget split) |
| **Monthly budget** | ₹12,50,000 (50%, paused) | Not used in Phase 1 |

**Capital Usage**:
- One open weekly trade at a time in Phase 1
- Lot count is set by the signal: weekly lots = max(1, int(`--lots` × 0.5)). With `--lots 30` that is 15 (weekly risk engine OFF in Phase 1). Copy the printed count.
- Margin per trade: from the broker's margin calculator (the CLI does not print margin)

---

## Key Metrics & Targets

### Phase 1 Success Criteria (6 months)

| Metric | Backtest | Live Target | Status |
|--------|----------|-------------|--------|
| **Trades** | 6/year | 6–8 trades | [ ] |
| **Win Rate** | 78% | >= 75% | [ ] |
| **Avg P&L/Trade** | ₹29,528 | >= ₹25,000 | [ ] |
| **Total P&L** | ₹177k/year | Track vs backtest | [ ] |
| **Worst weekly loss** | ₹-53,255 | Stop rule (100% of credit / short strike) governs; no ₹ cap | [ ] |
| **Max Account DD** | 6.2% | < 15% (pause rule) | [ ] |
| **Slippage vs BS estimate** | n/a | Logged for every fill | [ ] |

**Decision Criteria**:
- ✅ GO to Phase 2 if: 10+ trades, >= 75% win rate, < 12% DD
- ⚠️ HOLD if: 5–10 trades, 70–75% win rate, < 12% DD
- ❌ STOP if: Win rate < 60%, DD ≥ 15%, data or broker failures

---

## Daily Routine (Sample Day)

### 10:00 AM IST — Pre-flight
- Run the RESTART pre-flight (calendar, cache, models, Fyers credentials)
- Read yesterday's DAILY_LOG row and open positions

### 11:00 AM–1:00 PM IST — Signal and entry window
- Run `python main.py --mode signal-combined --capital 2500000 --lots 30` once
- Read the weekly track only
- If ENTER: take broker bid/ask, place IOC, log the entry in TRADES.csv
- If SKIP: log the reason code in DAILY_LOG.csv

### 3:00 PM IST — Monitoring
- Check the open weekly trade against the exit rules (stop, profit target, expiry, max hold)
- Overnight holds are normal in Phase 1; exit only when a rule is hit

### 4:30 PM IST — End of day
- Update DAILY_LOG.csv (every trading day)
- Update TRADES.csv exit fields if closed
- Add a Deviation Log row for any skip or deviation

---

## Monthly Review Cadence

| Frequency | Task | Output |
|-----------|------|--------|
| **Daily** | Log entry/exit in TRADES.csv; DAILY_LOG row at 4:30 PM | Trade and account record |
| **Weekly (Fri 4 PM)** | Fill RISK_DASHBOARD checkpoint | Weekly status |
| **Monthly (End)** | Complete MONTHLY_ANALYSIS.md | Detailed review |
| **Checkpoints** | Go/no-go per PAPER_TRADING_JOURNAL.md | Continue/Pause/Phase 2 |

---

## Escalation Protocol

### 🟡 Yellow Alert (Caution)
**Trigger**: DD 5–10% of peak, or win rate < 75% over 5 trades
**Action**: Review the signals and fills of the last trades. No size change without owner approval.

### 🔴 Red Alert (STOP: the only pause rule)
**Trigger**: Account DD ≥ 15% of peak (₹3,75,000 from ₹25L)
**Action**: Close open positions, pause all entries, review with owner

**Review triggers** (not automatic pauses; owner to confirm): 3 consecutive losses; win rate < 60% over 10 trades.

---

## Phase Transition Decision (Month 6)

### Go to Phase 2 (Add Monthly)? ✅
- ✅ 10+ weekly trades with >= 75% win rate
- ✅ Avg P&L >= ₹25k/trade
- ✅ Account DD < 12%
- ✅ Backtest vs live deviation < 30%
- ✅ Broker and data flow stable (zero outages that affected a trade)
- ✅ Phase 5 monthly improvements deployed (ML threshold 0.55–0.60)

### Hold (Collect More Data)? ⏸️
- 5–10 trades, 70–75% win rate, DD < 12%

### Stop (Investigate Issue)? ❌
- Win rate < 60%, OR DD ≥ 15%, OR repeated broker or data failures

---

## Files Checklist

- [ ] RESTART_2026-10-19.md (restart runbook)
- [ ] PAPER_TRADING_JOURNAL.md (main journal with checkpoints)
- [ ] QUICK_REFERENCE.md (trading cheat sheet, print this)
- [ ] TRADES.csv (every trade logged)
- [ ] DAILY_LOG.csv (daily snapshot, including skips)
- [ ] RISK_DASHBOARD.md (risk status)
- [ ] MONTHLY_ANALYSIS.md (month-end review template)

---

## Support & Resources

**If Something Goes Wrong**:

1. **Broker platform down with an open position**: Use the broker's web platform, close manually, log `Exit_Reason = manual`
2. **Fill quality poor**: Skip that trade, log the deviation
3. **Profit target not filling**: Exit at the nearest bid and record the slippage
4. **Account DD ≥ 15%**: Pause entries (the pause rule); do not panic-trade
5. **Model signal wrong**: Log it, continue Phase 1, use for later model work

**Contacts**:
- Fyers Support: https://support.fyers.in/
- Questions on backtest: docs/BACKTEST_COMBINED_MODE.md

---

## Last Notes

**This is validation work, not profit-chasing.**

- Goal: Confirm the backtest holds in live market conditions
- Acceptable variance: ±30% from backtest
- Acceptable win rate: >= 75% (vs 78% backtest)
- Unacceptable: Win rate < 60%, DD ≥ 15%, repeated data or broker failures

**If live results don't match backtest within 6 months, there's work to do.** This is diagnostic, not business as usual.

---

**Start Date**: 2026-10-19 (forward-only; Phase 1 counts start here)
**Target End Date (Month 6)**: 2027-04-19
**Status**: Restart pending the Mon 10-19 pre-flight. Weekly-track model acceptance recorded (risk engine OFF).
