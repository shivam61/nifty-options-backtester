# Phase 1B: paper-trade the hold-to-expiry candidate (data collection, no capital)

Registered 2026-10-23. First possible entry: Mon 2026-10-26, 11:00-13:00 IST. Runs alongside, and does not replace, Phase 1 (`RESTART_2026-10-19.md`) and the quote logger.

**Status of the candidate:** not validated. The real-price backtest failed the pass rule (hold-to-expiry, 1.5x slippage: -10 Rs/lot, dev window). Project 2 (`docs/plans/PROJECT2_STRUCTURE_PREREG.md`) is registered and unrun. This protocol collects real-fill and spread experience; it does not test profitability.

## What it can and cannot tell you
- About one trade a week, so about 12 trades in 12 weeks. That sample cannot show an edge, a loss rate or an expectancy. Do not quote P&L from it as evidence.
- It can show: real bid/ask at the legs, fill prices against mid, whether the 11:00-13:00 window fills, whether the DTE window and calendar behave, and how the structure marks day to day.

## Rules (fixed, same as arm F1 in the backtests)
1. **Signal and structure:** run `python main.py --mode signal-combined --capital 2500000 --lots 30` once in the window and read TRACK 2 (weekly). Ignore TRACK 1 (monthly). Structure comes from `select_weekly_strategy_name`: iron condor if India VIX is inside the IC band and the 5-day Nifty move is under 2% in absolute value, otherwise put credit spread. Entry days Mon/Tue only; expiry 3-8 DTE.
2. **Entry:** use real bid/ask from the broker screen, never the printed [BS est] premiums. Limit order at mid, then step toward the touch; record every attempt and the fill per leg. A skip is logged with its reason code (see the runbook).
3. **Exit:** none before expiry. The trade is cash-settled at expiry. Ignore the profit target, credit-multiple stop, trailing exit, `--mode monitor` scores and the DTE exit. Only the account drawdown kill-switch may close early (logged as `KILL_SWITCH`).
4. **One position at a time**, as in Phase 1.
5. **No arms:** do not apply the VIX floor, put-only or wing-width variants (H1-H4). They are backtest-only until Project 2 is evaluated.

## Logging
- `tracker/TRADES.csv`: one row per trade, Notes must start with `PHASE1B hold-to-expiry`. Fill the bid/ask columns from the screen. Keep Phase 1 and Phase 1B rows distinguishable.
- `tracker/DAILY_LOG.csv`: daily mark and the date the baseline rule would have exited (for comparison only, not acted on).
- Quote logger in parallel on the same machine (11:00-13:00 IST, every 10 minutes, cron in `QUOTE_LOGGING.md`). Run `scripts/summarize_quote_log.py` weekly; the headline median multiplier feeds Gate 0 of Project 2.

## Stop conditions
Stop and review if: a rule is broken (log it, do not repair history); the kill-switch fires; the measured median real/model multiplier exceeds 1.42x after 30 snapshots on 10 dates; or Project 2 returns a clear fail for the F1 base.

## Do not
Take real orders from this protocol; size above the paper capital; edit earlier rows; treat Phase 1B results as the holdout.
