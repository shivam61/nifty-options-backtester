# Plan: find out whether any index-option-selling strategy is profitable on real prices, before production

## Context
Owner rule: no paper/production until a backtest shows a working strategy. State on `main` (e92dfd8, clean, pushed):
- Real-price engine on the NSE F&O archive (`backtester/chain_engine.py`, `data/nse_fo_archive.py`, `~/nse_fo_archive`, NIFTY options only,
  2019-02-11..2026-10-16, internal-use/never committed). Baseline weekly IC/PCS, 1 lot, EOD settle marks, 2019-02..2026-08:
  -177 / -238 / -348 Rs/lot at slippage 1.0x / 1.5x / 2.0x. Dev window 2019-02..2023-12 at 1.5x: baseline -325; arms A (PCS 1.2 SD) -371,
  B (no breach stop) -325 (no-op), C (IC hold to expiry) -158. Pre-registered rule: none passed; holdout 2024+ not used for arm selection.
- The earlier BS-priced results (10-12% CAGR) are not evidence (BS overstates entry credit ~Rs9/unit).
New insight from the code map (must be tested before concluding): fixed costs dominate the 1-lot metric. `CostModel` (config.py:7-44):
brokerage is Rs20 PER ORDER (not per lot) + 18% GST, STT 0.0625% on sell premium. For a 4-leg IC at ~Rs21/unit credit, 1 lot, fees are ~Rs190
(14% of the Rs1,365 credit) and slippage ~Rs156 round trip (11%); total ~25% of credit. At the live plan's 30 lots the per-lot brokerage falls to
~Rs6. The "-55 at zero slippage" extrapolation implies gross edge around +Rs135/lot before fees; at 30 lots and 1.0x slippage that would be
roughly break-even (unverified arithmetic). So the 1-lot verdict may overstate the cost drag; it may still be negative. Verify, do not assume.
Standing rules: subagents implement, main thread verifies diffs and re-extracts numbers before commit; commit + push per unit; one heavy job at a time;
durable work in `~/whatif_work`; no tuning toward old numbers; pre-registered rules fixed before runs; ask before expensive runs or promotion.

## Step 0 - Decompose the loss and measure the premium (cheap; DEV WINDOW 2019-02-11..2023-12-31 ONLY)
Pre-registered purpose: decide whether there is anything to harvest. No holdout spend.
 a. Cost decomposition of the baseline at lots = 1, 5, 10, 30 and slippage = 0, 0.5, 0.75, 1.0, 1.5 (cheap runs via `scripts/run_chain_backtest.py --lots N
    --slippage ...`, `--end 2023-12-31`): gross premium captured, fees, slippage, stops, per lot. Confirm `_fee_rs` (chain_engine.py:134) scales brokerage per
    order and percentage fees with lots (and note it charges STT on the entry credit only; real STT also applies to the exit premium when selling-to-close;
    fix or flag).
 b. Variance-risk-premium audit from the archive (new script `scripts/audit_vrp.py`, derived from `NseFoArchive`: ATM straddle at each weekly fill day from
    `underlying` + `listed_strikes` + `price`): implied move (straddle/spot) vs realised move to expiry, by VIX bucket and year; hold-to-expiry unhedged
    straddle gross P&L; also the same for 21-DTE monthly. Output: is implied > realised on average, and where.
 c. Report a gross-edge-by-regime table (VIX buckets <13, 13-16, 16-20, 20-25; VRP = VIX - 20d realised vol, already in `data/market_data.py:518-545`).
Gate G0: if (a) at 30 lots and <=1.0x slippage is still clearly negative AND (b) implied <= realised on the dev window, STOP: no premium to harvest; write up
(Step 5). Otherwise continue.

## Step 1 - Choose at most TWO pre-registered families (dev window only), decided after Step 0
Candidates, in priority order (each is a parameter/option on the engine, defaults unchanged):
 1. Cost-aware sizing: evaluate at realistic lots (10-30); no code change, only the metric basis. (Part of Step 0; becomes the new baseline.)
 2. No credit-multiple stop (defined-risk spreads, hold to expiry): extension of arm C to PCS and removal of the credit stop; extends `WeeklyExitArms`
    (strategies/weekly_strategies.py) with `credit_stop=True`.
 3. Regime filter on VRP / VIX bucket decided from Step 0(c) (one threshold fixed from the dev window before the holdout is looked at), implemented as a
    gate in `ChainBacktest.run` (chain_engine.py:~431) using `vol_risk_premium` passed through the engine's market frame.
 4. Monthly ~21-DTE cadence: needs `NseFoArchive.weekly_expiries` horizon parameter (nse_fo_archive.py:~202), a cadence option in `ChainBacktest` (signal on
    monthly expiry day) and `ChainConfig` DTE window; archive already contains monthly expiries.
 5. Wider-wing / larger-credit structures (short strangle with far-OTM hedges, 3-4 legs): needs a new strategy class and `_structure_ok` relaxation
    (chain_engine.py:251-265) and a structure-specific exit policy.
 Selection rule: pick the family that Step 0 indicates (e.g. VRP positive only in some buckets -> 3; fee-dominated -> 1+2; term-structure -> 4); never run
 more than 2 families. Combinations only if both individually pass.

## Step 2 - Development-window evaluation (pre-registered)
Metric: per-lot expectancy at lots=10 (realistic fee burden) at slippage 0.75x/1.0x/1.5x, per-trade and year-cluster CIs (5 clusters = weak, so also require a
positive expectancy in at least 4 of 5 dev years and a max drawdown of cumulative P&L no worse than 2x the average monthly P&L... set the exact drawdown bar
before running). Passes development only if at 1.5x it beats baseline AND is > 0 AND year-cluster lower bound > 0 AND the year-consistency bar holds.

## Step 3 - Holdout (once)
Only for passing arms: evaluate on 2024-01-01..2026-08-28 exactly once (baseline holdout numbers are already known, so the holdout is clean only for NEW arms).
Adopt only if 1.5x expectancy > 0 and the point estimate holds in both 2024-25 and 2026 YTD; otherwise "not supported".

## Step 4 - ML decision layer (only after a supported structure)
Train on real-price counterfactual labels from `ChainBacktest` (daily entry candidates, 5-day horizon to enlarge the sample, purged yearly walk-forward),
compare with the supported rule, always-trade and never-trade; same adoption rule.

## Step 5 - Decision / production gate
- Supported arm: forward paper session with real bid/ask logged (calibrates slippage); production only after the paper results agree with the backtest band.
- Nothing supported: stop selling index premium on this engine; document; optional alternatives (Bank Nifty/FINNIFTY need a re-download of the archive with
  a symbol-parameterised `fetch_nifty_options.py` filter ~25 min; buying-vol / event structures) as a separate pre-registered project.

## Critical files
`backtester/chain_engine.py`, `data/nse_fo_archive.py`, `scripts/run_chain_backtest.py`, `scripts/analyze_chain_trades.py`, `strategies/weekly_strategies.py`
(`WeeklyExitArms`), `backtester/weekly_exit_policy.py`, `config.py` (`CostModel`), `data/market_data.py` (VRP columns); new `scripts/audit_vrp.py`.

## Verification
- Tests for every new option (defaults reproduce -177/-238/-348 byte-for-byte; extend `tests/test_chain_arms.py`, `tests/test_chain_engine.py`).
- Main thread re-extracts metrics from saved trade JSONs; confirm no run touches 2024+ before Step 3 (use `--end 2023-12-31`; note NseFoArchive.build_cache loads all files).
- Commit + push each unit; BACKTEST_CHANGELOG entry per decision; keep disk free (>2GB) and never leave full repo copies in the scratchpad.

## Follow-on
Project 2 (separate pre-registration, per Step 5): `docs/plans/PROJECT2_STRUCTURE_PREREG.md`.
