# Next tasks: NIFTY hedged weekly option selling (edge search)

Written 2026-10-26. Read this first when planning. Each task has a goal, inputs, a done-when, and a gate. Do them in order; T1-T3 are blocked on quote-log data. Fund assumption: Rs 25,00,000, lot size 65, hedged (defined-risk) structures only, no naked futures or naked shorts.

## State at handoff
- Full-setup honest backtest (leave-one-year-out + walk-forward, 16 pre-registered rules, 2019-02-11..2026-10-16, EOD bhavcopy, no bid/ask) found **no validated edge**. Pass bar not met.
- Only candidate: IC09_200 (0.9 SD short strikes, 200-pt wings) when India VIX is 16-20. LOYO mean +409 Rs/lot/cycle at 1.5x slippage (CI +20..+1,001), picked in 7/8 folds. Walk-forward CI includes zero, BH q=0.144, worst-case marking of dropped cycles gives +108 (CI -380..+521). The VIX band was chosen post hoc.
- Trades ~87 of 396 cycles. Mean over all cycles ~Rs 90/lot/cycle; 12% CAGR at Rs 25L needs ~Rs 5,500 per cycle (~Rs 1,100/lot at 5 lots). At 20 lots CAGR is only 3.3%. Sizing cannot close the gap.
- Result sign depends on slippage: IC break-even ~0.4x the model, PCS ~2x. EOD data cannot resolve it. Only measured spreads can.
- 2024-26 data was reused by earlier scans, so it is not a clean holdout. The only clean test is forward paper-trading.
- Scratch work (not in git): `~/edge_explore/` (`fb_core.py`, `fb_run.py`, `fb_25l.py`, `prereg_full_backtest.md`, `results_full_backtest.md`, `_fb_results.pkl`). Copy what you need into the repo before relying on it.

## Standing rules
- Pre-register any new test before looking at outcomes. No new rules or thresholds after seeing results.
- Do not touch the holdout guard (`--allow-holdout`) without saying so.
- NSE archive (`~/nse_fo_archive`) is licence-restricted: never commit it.
- One machine logs quotes per day (dedupe key is per file). The systemd timer on the VM also logs.
- Subagent summaries are not evidence: the main agent re-runs numbers and tests before reporting.

## T0. Validate the quote logger's first sessions  (can start now)
- Goal: confirm the bid/ask mapping is right before trusting any spread.
- Do: after the first in-window runs, check `bid < ask` on most two-sided rows and `bid_qty`/`ask_qty` populated in `paper_trading/tracker/QUOTE_LOG.csv`. If blank or crossed, fix `parse_nse_chain` in `scripts/log_option_quotes.py` and add a test.
- Done when: a note in `paper_trading/QUOTE_LOGGING.md` says the mapping is confirmed on a live window snapshot.

## T1. Measure real spreads vs the cost model  (needs >= 5 trading dates in the log)
- Do: `.venv/bin/python scripts/summarize_quote_log.py`. Record the median and p90 of `half_spread_to_model` for structure legs, by moneyness bucket and VIX bucket (weight toward the strikes the 0.9 SD condor actually sells).
- Done when: a short report states the implied slippage multiplier with n, dates, and VIX regimes covered, against the break-evens (IC ~0.4x, PCS ~2x).
- Gate: below ~0.4x, condor survives costs; between 0.4x and 2x, only credit spreads can; above 2x, hedged weekly selling is closed out. Do not decide on fewer than 5 dates or a single VIX regime.

## T2. Re-run the backtest at measured cost  (needs T1)
- Do: pre-register, then re-run the same 16-rule LOYO + walk-forward harness with `m` set to the measured multiplier (plus 0.5x and 1.5x of it). No new rules.
- Done when: results state pass/fail per the original bar, including worst-case marking of dropped cycles, and the Rs 25L account simulation at 1, 2, 4, 5, 10, 20 lots.
- Gate: nothing passes -> record "no edge" and stop selling-only work. Only IC09_200|VIX 16-20 passes -> T3.

## T3. Forward paper-trade one frozen rule  (needs T2 pass, or user override)
- Rule frozen before starting: IC09_200 (0.9 SD shorts rounded to 50, 200-pt wings), enter only at VIX 16-20, hold to expiry, size <= 2% of capital (Rs 50,000) max loss per trade (about 4-5 lots).
- Do: log each signal, intended and actual fills against the live bid/ask, and expiry P&L. Use the existing paper_trading tracker. Add nothing that can place orders.
- Done when: >= 30 qualifying trades (about 2-3 years at ~1 in 4 cycles, so expect to extend or loosen nothing) or a pre-set stop-loss on cumulative P&L is hit.
- Gate: compare realized net per lot to the T2 estimate; CI lower bound > 0 before any real capital.

## T4. Independent replication of the backtest  (any time)
- Do: a second agent re-implements the LOYO fold selection and the pass-bar tests from `prereg_full_backtest.md` alone, without reading `fb_core.py`, then compares fold choices and headline numbers (+409, 7/8 folds, +108 worst case, BH q 0.144). Report mismatches.
- Done when: numbers agree or discrepancies are explained.

## T5. 12% CAGR route  (decision for the user, not an agent default)
- Selling-only variants top out far below 12% at Rs 25L. Candidate directions, each needs its own pre-registration:
  - Collar or covered-call overlay on a NIFTY ETF holding (reduces vol and drawdown; did not beat buy-and-hold in dev).
  - A different edge source (futures data download is parked; user wants hedged positions only).
- Done when: the user picks a direction or accepts that 12% is not supported.

## Housekeeping
- Keep `git status` clean on the repo; scratch stays in `~/edge_explore`.
- If the logger is changed, rerun `tests/test_log_option_quotes.py` (36 tests).
- Commit locally after each task; ask before pushing.
