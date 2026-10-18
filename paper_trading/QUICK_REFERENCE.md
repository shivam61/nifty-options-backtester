# Paper Trading Quick Reference Guide

**Account**: ₹25,00,000 (weekly budget ₹12,50,000) | **Strategy**: Weekly PCS/IC only | **Phase**: 1 (Validation), forward-only from Mon 2026-10-19

> **API: NOT USABLE until fixed.** Use the CLI and the CSVs. See [RESTART_2026-10-19.md](./RESTART_2026-10-19.md).

---

## Entry Checklist (11:00–13:00 IST)

- [ ] Pre-flight passed (calendar, cache, models, Fyers) — RESTART section b
- [ ] Signal run once: `python main.py --mode signal-combined --capital 2500000 --lots 30`
- [ ] Weekly track says a trade (not SKIP); no `BLOCKED:` line
- [ ] Expiry is 3–8 DTE (expected Tue 2026-10-27 for a Mon 10-19 entry)
- [ ] Real broker bid/ask taken for every printed strike
- [ ] No other open weekly position

**If ALL checked ✓**: place the IOC order for the **lot count the signal printed**.
**If any fails**: log a SKIP row with the reason code.

---

## Exit Rules (the only exits)

### Profit Target
- **PCS: 75% of max profit** → close when hit
- **IC: no profit target**

### Stop Loss (the only stop)
- **100% of credit collected**, or **price breaches the short strike** → close immediately
- No ₹ cap per trade. The backtest's worst weekly loss (₹−53,255) is above the old ₹50k cap, so none is enforced.

### Expiry
- **Expiry day**: close all open legs by 15:15 IST

### Max Hold
- **IC: 4 trading days** (as printed by the signal; pending owner confirmation)
- **PCS: min hold 2 trading days** (as printed)
- **There is no 3-day cap.**

---

## Trade Log Example (TRADES.csv fields)

```
Trade ID: P1-001
Date Entry: 2026-10-19
Entry Time: 11:42 IST
Strategy: iron_condor (VIX 17.3 > 16)
Strikes: 23500PE / 24600CE (short legs, from signal)
Bid/Ask: per leg, from broker
Entry Price (net credit, ₹/unit): from broker fill
Lots: <as printed by signal>
Capital Deployed: <margin from broker>
Signal VIX: 17.3
ML_Score: <printed weekly Risk score; not a win probability>
Expiry DTE: 8 (Tue 2026-10-27)
Stop: 100% of credit or short-strike breach
Profit target: none (IC)
Backtest expected P&L: ₹29,528
```

---

## Risk Limits

| Limit | Amount | If Breached |
|-------|--------|------------|
| Per-trade stop | 100% of credit, or short-strike breach | EXIT immediately |
| Account pause (only pause rule) | DD ≥ 15% of peak (₹3,75,000) | Close open positions, pause entries, review |
| Concurrent open weekly trades | 1 | Wait for exit |

---

## Signal Strategy by VIX Band (as printed)

| India VIX | Weekly strategy | Notes |
|-----------|-----------------|-------|
| ≤ 16 | Put Credit Spread (`put_credit_spread`) | PCS can still decline entry (`PCS_DECLINED`) |
| > 16 | Iron Condor (`iron_condor`) | Signal's VIX gates still apply (weekly SKIP lines) |

The signal's own gates decide whether a trade is allowed. Do not override them.

---

## Premiums and Fills

- The signal's premiums are **Black-Scholes estimates** (`[BS est]`).
- **Real bid/ask from the broker is the only basis for a fill.**
- Log slippage: compare the actual credit with the printed `[BS est]` credit.
- Abort the order if the broker's price is far outside the printed estimate and no longer meets the signal's rules. Log the SKIP as `FYERS_UNAVAILABLE` or as a deviation.

---

## Weekly Checklist (Every Friday 4 PM)

- [ ] Count weekly trades and skips this week
- [ ] Calculate win %: wins / (wins + losses)
- [ ] Sum net P&L this week
- [ ] Biggest single loss (compare with the 100%-of-credit stop; no ₹ cap)
- [ ] Account DD vs peak (pause rule: ≥ 15%)
- [ ] Compare with backtest expectations
- [ ] Log any broker or data failures in the Deviation Log

**Decision**: Continue Phase 1, pause (DD rule), or review.

---

## Escalation Protocol

**🟡 Yellow (monitor closely)**
- DD 5–10% of peak
- Win rate < 75% over 5 trades

→ **Action**: review the last trades' signals; no size change without owner approval

**🔴 Red (STOP: the only pause rule)**
- Account DD ≥ 15% of peak (₹3,75,000)

→ **Action**: close open positions, pause all entries, review with owner

Review triggers (not automatic pauses, owner to confirm): 3 consecutive losses; win rate < 60% over 10 trades.

---

## Monthly Milestones (Target)

| Milestone | Target | Expected |
|-----------|--------|----------|
| **Trades** | 0–2 per month | About 6 per year in backtest |
| **Win Rate** | ≥ 75% | Compare with 78% backtest |
| **Net P&L** | Track vs backtest | Backtest average ₹29,528 per trade |
| **Winning avg** | Per the PCS 75% target or the IC outcome | Record in TRADES.csv |
| **Slippage** | Logged for every fill | Compare with the `[BS est]` credit |

---

## Backtest vs Live Comparison

**Backtest (Run #60)**:
- Win Rate: 78%
- Avg Profit/Trade: ₹29,528
- Worst weekly loss: ₹−53,255
- Holding: about 3 days on average (backtest statistic; not a rule)

**Live (Phase 1 goal)**:
- Win Rate: ≥ 75%
- Avg Profit/Trade: ≥ ₹25,000
- Live results within 30% of backtest over 10 trades (acceptance criterion)

---

## Common Mistakes to Avoid

1. ❌ **Entering outside 11:00–13:00 IST**
   → The signal's window gate is the rule. Re-run inside the window.

2. ❌ **Resizing the lot count**
   → Copy the lot count the signal printed. The engine sizes weekly lots as max(1, int(`--lots` × 0.5)). With `--lots 30` that is 15, with no risk scaling (risk engine OFF in Phase 1).

3. ❌ **Filling at `[BS est]` prices**
   → Use the broker's bid/ask.

4. ❌ **Not exiting at the profit target (PCS)**
   → 75% of max profit: take it.

5. ❌ **Holding through the stop**
   → 100% of credit or short-strike breach: exit.

6. ❌ **Entering without capital**
   → Wait for margin to free up.

7. ❌ **Trading monthly positions in Phase 1**
   → Phase 1 is weekly only. Ignore TRACK 1 output.

8. ❌ **Not logging in real time**
   → Log immediately after each fill and exit.

---

## Emergency Exit Procedure

**If the broker platform or data feed goes down with an open position:**

1. Use the broker's web platform (backup).
2. Exit all open legs manually.
3. Log the trade in TRADES.csv with the actual fills and `Exit_Reason = manual`.
4. Log the incident in DAILY_LOG.csv notes.
5. Do not re-enter until the platform is stable for 15+ minutes.

---

## Contact & Resources

| Resource | Link | Purpose |
|----------|------|---------|
| Fyers API Docs | https://docs.fyers.in/api/ | Technical reference (API not operational here) |
| Restart runbook | [RESTART_2026-10-19.md](./RESTART_2026-10-19.md) | Pre-flight, skip codes, entry mapping |
| Backtest Results | docs/BACKTEST_CHANGELOG.md | Historical performance |
| ML Model | data/.cache/entry_model_v4.pkl | Entry model (monthly track) |

---

**Last Updated**: 2026-10-19 (restart)
**Print this. Keep it handy during the 11:00–13:00 IST window.**
