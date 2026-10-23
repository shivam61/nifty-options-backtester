# Project 2 pre-registration: hold-to-expiry defined-risk structure grid on real prices

Registered 2026-10-23, before any run. Status: NOT RUN. Commit this file first; do not edit hypotheses or rules after the first run (add a dated amendment instead).

## Why this is a new project
`docs/plans/PROFITABLE_STRATEGY_SEARCH.md` allowed at most two families and combinations only if both passed individually. F1 (hold to expiry) and F2 (VIX floor 13) both failed the pass rule at 1.5x (-10 and -183 Rs/lot, dev window, lots=10), so that plan ended at Step 5: "optional alternatives as a separate pre-registered project". This is that project. Inputs: the literature review (`reports/Option chain signals literature review.md`, rules R1 and R2; no paper full text was read, so treat it as a lead list) and the repo's own corrected-model results.

What the evidence says going in: gross edge at 10 lots is about +123 Rs/lot at 0x slippage; hold-to-expiry breaks even near 1.42x, the baseline near 0.44x, VIX>=13 near 0.80x (`BACKTEST_CHANGELOG.md`, 2026-10-21). Cost is the binding constraint, so a structure that needs fewer or cheaper fills can matter more than a signal. No source supports a chain signal that lifts expectancy enough to matter; none is registered here.

## Gate 0: measured cost (blocks everything below)
Run `scripts/log_option_quotes.py` on a machine that can reach NSE (cron in `paper_trading/QUOTE_LOGGING.md`), then `scripts/summarize_quote_log.py`.
- Minimum sample before reading the median: 30 snapshots on at least 10 distinct dates, covering both `vix_lt13` and `vix_ge13`.
- Rule: if the measured median multiplier on structure legs exceeds 1.42x (the best known break-even), stop. The weekly track is unsupported by construction; write it up.
- The measured value is passed to the evaluator as `--measured-multiplier`; an arm fails its cost gate if the multiplier exceeds that arm's own break-even.

## Confirmatory hypotheses (family size 4, Holm-adjusted, alpha 0.05)
Common settings: dev window 2019-02-11..2023-12-31 (`--end 2023-12-31`), lots=10, slippage 1.0 / 1.5 / 2.0, corrected cash-settlement and cost model (default), `--no-early-exits` (F1) on every arm. One parameter value per hypothesis, fixed now.

| ID | Arm | Command additions to F1 | Needs new code |
|----|-----|-------------------------|----------------|
| H1 | India VIX floor 13 | `--min-vix 13` | no (post-hoc combination of F1 and F2, which each failed alone; the 13 floor is in-sample from the Step 0 audit) |
| H2 | Put credit spread only | `--force-strategy weekly_pcs` | yes: `ChainConfig.force_strategy` |
| H3 | Fixed wing width 200 points (IC and PCS) | `--wing-width 200` | yes: `ChainConfig.wing_width` |
| H4 | Fixed wing width 500 points (IC and PCS) | `--wing-width 500` | yes: same option |

Comparator ("baseline" in the pass rule) = F1 alone, re-run in this project's dev window with identical settings. F1's own result is not a hypothesis here.

Pass rule (`scripts/evaluate_prereg_arms.py`, applied mechanically): at 1.5x the arm beats F1, expectancy > 0, year-cluster 95% CI lower bound > 0, at least ceil(0.8 x years) positive years; plus Holm-adjusted one-sided block-bootstrap p < 0.05 and the Gate 0 cost gate. An arm that lowers drawdown but leaves expectancy <= 0 fails.

Report with every result: break-even multiplier, n, the F1 standard deviation per trade, and the minimum detectable effect (about 2.8 x standard error). With roughly 200 development trades only large effects are detectable; a null here is not proof of no effect.

## Code to build before any run (defaults must not change results)
- `ChainConfig.force_strategy` (None | "weekly_pcs" | "weekly_ic"): bypass `select_weekly_strategy_name`; skip the signal if the forced structure's `should_enter` says no.
- `ChainConfig.wing_width` (None | int): replace the dynamic width in `WeeklyPutCreditSpread` and `WeeklyIronCondor` with the fixed value; same short strikes.
- Tests: defaults reproduce the existing outputs on the synthetic archive (`tests/test_chain_engine.py`, `tests/test_chain_arms.py`), and each option changes only what it should. Then confirm byte-identical baseline output on the real archive (-177 / -238 / -348 at 1.0x / 1.5x / 2.0x over 2019-02-11..2026-08-28) on the machine that has it. Do not run hypotheses until that check passes.

## Holdout (once)
Only arms with a confirmatory pass. Evaluate 2024-01-01..2026-08-28 once with `--allow-holdout`. Report two eras separately: 2024-01..2025-08 (Thursday expiries) and 2025-09-02 onward (Tuesday expiries). Adopt only if 1.5x expectancy > 0 in both eras and the point estimate holds. A pass in development that fails the holdout is retired with no retuning.

## Exploratory appendix (no holdout spend, cannot be promoted)
R3 side and delta diagnostic (P&L and expected shortfall of short legs by delta bucket, put vs call); wing-cost cap (skip if far-leg price exceeds 25% of credit); monthly cadence; margin-aware naked arm (needs a margin and liquidation model that does not exist yet); chain-IV and skew features.

## Gate 3: before any real money
A supported arm still needs a forward paper session with real bid/ask logged, agreeing with the backtest band, and the drawdown kill-switch active. The earlier model-priced CAGRs are not evidence of an edge.

## Not allowed
Adding arms after seeing results; changing a parameter value; re-running to choose among seeds or windows; using the 2024+ holdout for selection; reporting an arm without its F1 comparator and break-even.
