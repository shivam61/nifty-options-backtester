# Paper Trading Risk Dashboard

**Last Updated**: [Date & Time]
**Phase 1 start**: Mon 2026-10-19 (forward-only). Entries before this date do not count.

---

## Account Status (Real-Time)

| Parameter | Current | Target | Status |
|-----------|---------|--------|--------|
| **Account Equity** | ₹[ ] | ₹25,00,000 (start) | [ ] |
| **Peak Equity (since restart)** | ₹[ ] | — | [ ] |
| **Cumulative P&L** | ₹[ ] | — | [ ] |
| **Daily P&L** | ₹[ ] | — | [ ] |
| **Account DD % (vs peak)** | [ ]% | < 15% (pause rule) | [ ] |
| **Account DD ₹ (vs peak)** | ₹[ ] | < ₹3,75,000 | [ ] |
| **Win Rate YTD** | [ ]% | >= 75% | [ ] |
| **Trades (Phase 1)** | [ ] | 0–20 | [ ] |

---

## Position Exposure

| Position | Entry Date | Entry Price | Current Price | Lots (as printed) | Unrealized P&L | Days Held | Stop Level (100% credit / short strike) |
|----------|-----------|------------|--------------|-----------|----------------|-----------|-------------|
| | | ₹ | ₹ | | ₹ | | |

**Total Open P&L**: ₹[ ]
**Margin Used (broker)**: ₹[ ] / ₹12,50,000 weekly budget
**Remaining Weekly Budget**: ₹[ ]

---

## Risk Alerts

### 🔴 Critical (Immediate Action)

- [ ] Account DD ≥ 15% of peak (₹3,75,000) → PAUSE ALL ENTRIES, close open positions, review
- [ ] Trade loss reached 100% of credit, or short strike breached → EXIT (per-trade stop)
- [ ] Broker platform down > 1 hour with an open position → exit via the web platform

**Action Required**: [ ] YES [ ] NO

### 🟡 Warning (Monitor Closely)

- [ ] Account DD 10–15% of peak → Review signals; no size change without owner approval
- [ ] Open trade near the short strike (per the broker screen) → Watch closely at 11:00 and 3:00 PM
- [ ] Signal SKIP streak (3 in a row) → Review the skip codes (review trigger, not a pause)
- [ ] Broker latency > 5 sec → Note in Deviation Log

**Status**: [ ] OK [ ] MONITORING

### 🟢 Normal Operating Range

- [ ] Account DD < 10% of peak
- [ ] Win rate >= 70% over last 5 trades
- [ ] Broker latency < 2 sec
- [ ] Margin utilization within the weekly budget

**Status**: [ ] GREEN

---

## Daily Checklist (Execute at 10:00 AM IST)

- [ ] Run the RESTART pre-flight (calendar, cache, models, Fyers session)
- [ ] Review overnight VIX from the previous close
- [ ] Check for NSE holiday or circular notices
- [ ] Verify account balance on the broker
- [ ] Review yesterday's trade outcome and open positions
- [ ] Set phone alarm for 11:00 AM (entry window opens)
- [ ] Confirm the stop level for any open trade

---

## Weekly Checkpoint (Every Friday, 4:00 PM)

**Week of**: [ ]

| Metric | Value | Target | Pass/Fail |
|--------|-------|--------|-----------|
| Trades | [ ] | 0–2 | [ ] |
| Skips (with codes) | [ ] | logged 100% | [ ] |
| Win Rate | [ ]% | >= 75% | [ ] |
| Net P&L | ₹[ ] | Track vs backtest | [ ] |
| Worst trade vs 100%-of-credit stop | ₹[ ] | Stop rule followed | [ ] |
| Account DD (vs peak) | [ ]% | < 15% | [ ] |
| Broker / data failures | [ ] | 0 | [ ] |

**Go/No-Go**: [ ] CONTINUE [ ] PAUSE (DD rule) [ ] REVIEW

**Notes**:

---

## Pause Rule and Review Triggers

**Pause rule (the only one)**: Account DD ≥ 15% of peak equity (₹3,75,000 from ₹25L).
Action: close open positions, pause all entries, investigate the backtest vs live gap.

**Review triggers (not automatic pauses; owner to confirm)**:
1. 3 consecutive losing trades → review the signals in detail
2. Win rate < 60% over the last 10 trades → review market regime
3. Broker or data failure > 1 hour → log in the Deviation Log and check the next signal run
4. Slippage vs the `[BS est]` credit > 50 bp on average → review fill timing

---

## Monthly Summary (Refresh End of Month)

**Month**: [ ]

| Week | Trades | Wins | Losses | Skips | Win % | Net P&L | Status |
|------|--------|------|--------|-------|-------|---------|--------|
| Week 1 | [ ] | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 2 | [ ] | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 3 | [ ] | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| Week 4 | [ ] | [ ] | [ ] | [ ] | [ ]% | ₹[ ] | [ ] |
| **Total** | **[ ]** | **[ ]** | **[ ]** | **[ ]** | **[ ]%** | **₹[ ]** | **[ ]** |

**Backtest Expected** (about 6 trades/year = 0.5/month average):
- Expected P&L: ₹14,764 (½ of ₹29,528)
- Expected Win Rate: 78%

**Actual vs Expected**:
- P&L: ₹[ ] vs ₹14,764 ([ ]% variance)
- Win %: [ ]% vs 78% ([ ]pp delta)

**Decision**: [ ] ON TRACK [ ] REVIEW [ ] PAUSE

---

## Escalation Matrix

| Scenario | Trigger | Action | Level |
|----------|---------|--------|-------|
| Mild Drawdown | DD 5–10% of peak | Review signals; no size change without owner | Yellow |
| Moderate Drawdown | DD 10–15% of peak | Review; prepare for pause | Orange |
| Pause Rule | DD ≥ 15% of peak (₹3,75,000) | PAUSE all entries, close open positions | Red |
| Win Rate Degradation | < 70% over 5 trades | Review signals | Yellow |
| Broker / Data Failure | > 1 hour with an open position | Exit via the web platform | Orange |
| Slippage Drift | > 75 bp avg vs `[BS est]` credit | Review fill timing | Yellow |
| Stop Breach | Loss = 100% of credit, or short strike breached | EXIT immediately | Per-trade rule |

---

## Contacts & Resources

**Broker Support**:
- Fyers Support: https://support.fyers.in/
- Fyers API Docs: https://docs.fyers.in/api/ (API server not operational)

**Backup Plans**:
- Emergency Exit: Manual via the broker's web platform
- Support Contact: [ ]

**Reference**:
- Restart runbook: paper_trading/RESTART_2026-10-19.md
- Backtest Report: docs/
- ML Model: data/.cache/entry_model_v4.pkl
- Strategy Rules: CLAUDE.md

---

**Dashboard Status**: [ ] LIVE [ ] INACTIVE
**Last Review**: [ ]
**Next Review**: [ ]
