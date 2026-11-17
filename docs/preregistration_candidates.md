# Pre-registration: two new candidate families on NIFTY index options (A: defined-risk put credit spread at VIX 16-25; B: low-VIX long volatility at VIX < 13)

Date: 2026-11-17. Status: **frozen**. Written before any run on either family. No trade result, eval output, NSE archive
extract or scratchpad result was opened to write this document. Any change after the first run of a family voids
that family, unless it is a documented bug fix (see Section 9). Engine: real-price chain engine
(`backtester/chain_engine.py`, `data/nse_fo_archive.py`, `scripts/run_chain_backtest.py`), evaluation harness
`strategy_eval/` (`scripts/eval_strategy.py`), governed by `docs/preregistration_edge_search.md` and `docs/STRATEGY_EVAL.md`.

## 0. Background and what is already known (carried over, not re-tested here)

- Baseline weekly IC/PCS on real EOD settle prices is negative at 1.5x slippage (dev window, lots=10: -253 Rs/lot).
  Earlier results priced by Black-Scholes are not evidence.
- Corrected cost model (2026-10-21): cash settlement at expiry has no exit order; STT on exercised ITM long legs
  0.125% of intrinsic; date-aware rates in `backtester/nse_option_rates.py` (sources in `docs/COSTS_NSE_OPTIONS.md`).
- Premium audit, dev window 2019-02-11..2023-12-31, weekly, implied minus realised move by VIX bucket
  (ATM straddle, pts/unit gross): <13 -3.8, 13-16 +10.2, 16-20 +25.2, 20-25 +14.8, 25+ -57.7.
- The VIX bands used below are taken from this table. **That makes them post hoc and in-sample.** They cannot
  support a clean dev-window result. They are only admissible under the walk-forward split in Section 7.
- Entry-basis bias: EOD settle credit exceeds the intraday mid by about +1.3 pts/unit for iron condors (two days,
  n=2, not a CI). The PCS basis gap was directional and unmeasured. The bias for both families here is therefore
  **unquantified** and is not corrected (Section 8).
- 2024-2026 data was already seen by earlier scans (`docs/plans/NEXT_TASKS_EDGE_SEARCH.md`). It is not a clean holdout.

## 1. Economic hypotheses

- **A (put credit spread, VIX 16-25).** Index put skew makes OTM puts rich relative to realised downside. A defined-risk
  short put spread held to expiry harvests that premium, and the long wing caps the tail that killed the undefined
  structures. Reason it might fail: the gain is small (about +25 pts/unit gross in the 16-20 bucket) and the
  1.5x verdict cost may exceed it.
- **B (long strangle, VIX < 13).** When implied vol is near its floor, option premium is cheap relative to the
  realised moves that can follow a low-vol regime. A long strangle with debit = max loss buys that convexity. Reason it
  might fail: the dev table is negative for *short* premium at VIX < 13 (-3.8 pts/unit). That says nothing about the
  long side, which pays theta. The long-side expectancy has never been measured. Treat B as a hypothesis, not a finding.

## 2. Common conventions (apply to A and B)

- **Universe:** NIFTY index options only, from the NSE F&O archive. One underlying, no other symbols.
- **Signal day S:** each trading day that is a weekly expiry day (the expiring weekly). The VIX gate is evaluated on
  the **S close VIX**, the only information known at signal time.
- **Fill day F:** the next trading session after S. All strikes are selected and all legs are priced at the **F EOD
  settle** from the archive, as in the chain engine. No intraday fill is assumed.
- **Expiry:** the target expiry E is the weekly expiry after the one that expires on S (weekly cadence). DTE is
  measured from F. Weekly window: DTE in [3, 8]. Expiry days use the archive settlement value.
- **Strike convention:** period vol `sigma_T = spot_F * (VIX_S/100) * sqrt(DTE/252)`, with `spot_F` the F EOD
  NIFTY settle. Target strike = `spot_F -/+ k * sigma_T`, snapped to the nearest **listed** strike (50-pt grid).
  Both k and widths are fixed by the cell definitions in Sections 3 and 4.
- **Exit:** hold to expiry for every cell. No stop, no profit target, no breach stop, no early exit, no adjustment.
  Only the expiry settle closes the trade, at intrinsic value of the index settlement. Exit parameters are not part
  of the grid.
- **One position at a time per family.** If a trade is open, a new signal for the same family is skipped and counted.
- **Skipped signals** (VIX outside band, no listed strike, no expiry in window, missing data) are counted per cell in the
  report and are not trades.

## 3. Candidate A: defined-risk put credit spread, VIX 16-25

- **Legs:** sell 1 PE at K_s, buy 1 PE at K_l = K_s - W. Both one lot per lot unit (quantity = lots x 65).
- **Strike rule:** K_s = nearest listed strike to `spot_F - k * sigma_T`, using `k` from the grid.
- **Gate:** enter only if `16.0 <= VIX_S < 25.0` (half-open, to match the table's buckets 16-20 and 20-25). No other
  filter. The existing `should_enter` checks (5-day return, VIX change) are **not** used.
- **Grid (6 cells, declared):** k in {0.9, 1.1, 1.3} x W in {200, 300}.
  Cell IDs: `PCS_A_k09_w200`, `PCS_A_k09_w300`, `PCS_A_k11_w200`, `PCS_A_k11_w300`, `PCS_A_k13_w200`, `PCS_A_k13_w300`.
- **Max loss per unit** = W - credit. Credit is the net F EOD settle credit, per unit.
- **Entry and exit:** as Section 2. No stop.

## 4. Candidate B: long strangle at low VIX, debit defined risk

- **Legs:** buy 1 CE at K_c = nearest listed to `spot_F + k * sigma_T`, buy 1 PE at K_p = nearest listed to
  `spot_F - k * sigma_T`. All legs long. No short legs, no wings.
- **Gate:** enter only if `VIX_S < 13.0`. No other filter.
- **Cadence (2 values, declared):**
  - `weekly`: rule as Section 2 (expiry in DTE [3, 8] from F).
  - `monthly`: target expiry is the monthly expiry whose DTE from F is closest to 21 within [15, 28]. The
    strike rule uses `sigma_T` at that DTE. If no monthly expiry is in window, skip.
- **Grid (4 cells, declared):** k in {0.9, 1.3} x cadence in {weekly, monthly}.
  Cell IDs: `LS_B_k09_wk`, `LS_B_k09_mo`, `LS_B_k13_wk`, `LS_B_k13_mo`.
- **Debit and max loss:** max loss per unit = debit paid (premium of CE + PE at F settle plus entry costs).
  **The sizer and Gate 11 must treat B as debit:** risk per lot = debit x 65, with no credit offset and no width term.
  `Trade.max_loss` in `strategies/base.py` falls back to `|net_credit| x lots x lot_size x 5` when a trade has no
  short leg. For B, that is five times the debit and would undersize every trade. The B path must set max loss =
  debit x lots x lot_size explicitly, and a test must assert this before any B run.

## 5. Sizing (both families)

- Mode: `scripts/run_chain_backtest.py --capital-mode --capital-rs 500000 --risk-cap-pct 0.10 --margin-cap-pct 0.20
  --max-lots 30`, which requires `--lots 1` per trade as the engine does.
- Lots per trade = min of:
  - risk cap: `floor(0.10 x 5,00,000 / max_loss_per_lot)`, i.e. Rs 50,000 max loss,
  - margin cap: `floor(0.20 x 5,00,000 / margin_per_lot)`, i.e. Rs 1,00,000 margin,
  - 30 lots.
- **Margin proxy (not SPAN or exposure margin).** A: margin per lot = max loss per lot (width minus credit). B: margin
  per lot = debit per lot (premium paid, no offset). These are proxies and are stated as such in every report.
- **Verdict input is not the capital-aware lot count.** Verdicts use per-lot expectancy at **fixed lots = 10** (see
  Section 8 on lot dependence). Capital-mode runs are reported separately as account-level information (CAGR,
  drawdown, utilisation), with the lot counts stated.
- The kill switch in capital mode is informational for this pre-registration. It is not a verdict criterion.

## 6. Costs

- Model: the corrected cost model in Section 0 (Rs 20 per order plus 18% GST, STT per the date-aware rates, no exit
  order at cash settlement, exercised ITM long legs at 0.125% intrinsic STT). No haircut beyond what exists in the
  engine.
- **Verdict cost: 1.5x slippage.** Sensitivity at 0.0x, 0.5x, 0.75x, 1.0x and 2.0x is reported as information only.
- **The calibrated spread model is not used for any verdict** until its coverage is documented adequate. The
  quote log currently covers one clean in-window day for the condor legs (2026-10-28). That is not adequate.
- Known unmodelled costs: brokerage on exercised or expired contracts (open per `docs/plans/PROFITABLE_STRATEGY_SEARCH.md`
  Step 2). Report this as a limitation for B, which has long legs that can be exercised.

## 7. Evaluation procedure: walk-forward, registry, holdout

**Windows.** Train 2019-02-11..2021-12-31. Test 2022-01-01..2023-12-31. Holdout 2024-01-01 onward.
Every run uses `--end 2023-12-31` except the single holdout look. The dev window 2019-02-11..2023-12-31 is not used
as a verdict window for these families, because it contains the selection window.

**Step 1, train selection (2019-2021 only).** Evaluate every cell of both grids on the train window. Selection:
among cells with at least 30 train trades, choose the cell with the highest per-lot expectancy at 1.5x (lots = 10),
**one cell per family**. Ties go to the cell with the smaller `k` and then the smaller `W`, or `weekly` before `monthly`.
If no cell in a family has at least 30 train trades, the family is dead with verdict INSUFFICIENT_DATA. If the selected
cell has expectancy <= 0 at 1.5x, the family is dead and gets no test run.

**Step 2, test (2022-2023), one cut per family.** Run the selected cell only, with the verdict pass rule (Section 10).
Test is a **pass/fail gate**. A fail is final.

**Step 3, holdout (2024+), at most one look per surviving candidate.** Only a candidate that PASSES on test is
eligible. The look goes through `--allow-holdout`, which appends one row to `logs/holdout_ledger.json` before any
holdout trade is scored. The holdout end date is the last settlement date in the archive at the time of the look,
recorded in the ledger row. A holdout FAIL is final.

**Registry.** All cuts go to the shared file `logs/eval_registry.json` (`--registry logs/eval_registry.json`). Cut names
use the prefix `PREG_20261117_`. Counted cuts, all of them:
- 10 train cuts (one per grid cell, counted even though train is selection-only; this is conservative),
- at most 2 test cuts (one per family, selected cell only),
- at most 2 holdout looks (one per surviving candidate).

**Cut accounting.** The cap counts evaluation cuts (train cell, test, holdout verdict). The harness also writes
bookkeeping rows (walk-forward `selection` rows and `holdout_look` rows); those are logged and enter Holm, but they are
not additional evaluations and do not count against the cap.

**Hard cap: 14 registry cuts from this document.** A second test cut for a family, a test cut on a non-selected cell,
a second holdout look, or a re-run under a new `--name` is forbidden. The harness refuses a repeat `--name` with
changed data, and the rule is that a changed candidate needs a documented bug fix (Section 9), not a new name.

**Multiple testing.** Holm runs over every cut in the registry file, including cuts that predate this document. That is
the harness's rule, and it is conservative here. The deflated Sharpe ratio (`deflated_sharpe_grid`) uses N = 10 (the
full declared grid) and is reported as information only.

## 8. Known limitations (stated, not corrected)

1. **EOD settle marks only, no bid/ask.** Intraday stops would be worse, so no stops are in the grids.
2. **Entry-basis bias.** EOD settle versus intraday mid is about +1.3 pts/unit for condors (n=2 days). The A basis is
   unmeasured (PCS gap is directional). The B basis sign is unknown. None of this is corrected here. A PASS is
   therefore not a claim that the realised entry price matches the archive.
3. **Expiry-day marks** use intrinsic value of the index settlement, not an option settle price.
4. **Small samples.** VIX < 13 is a rare regime. B may not reach 30 trades on any cadence. A and B on the 2-year test
   window may also be thin. Samples are not estimated here (no data was looked at).
5. **Lot dependence.** Brokerage is flat per order, so per-lot Rs changes with lots: 1 lot and 10 lots give
   different per-lot numbers. Verdicts are on lots = 10. **Every reported number must state its lot count.** Anchors
   are at lots = 10.
6. **Two-cluster test bootstrap.** Test has 2 year-clusters, so a year-cluster 95% CI is not a valid interval.
   Resolved before any run by C3' in Section 10 (monthly-block bootstrap for test and holdout windows). Months within
   a year are still serially dependent, so the block CI remains optimistic; a test PASS is necessary, not sufficient.
7. **Reused data.** 2024-2026 was seen by earlier scans. A holdout PASS is weaker evidence than a clean one.
8. **Black-Scholes is not used** for any number in this document.

## 9. Changes after the first look

- Only a documented bug fix is allowed, and only after a family has been run. A fix must come with a note in
  `BACKTEST_CHANGELOG.md` and a reason.
- After a fix, the verdict is re-run from scratch. The old cut stays in `logs/eval_registry.json`, counted in Holm.
- No change to a threshold, cell, window, cost, cadence, or selection rule after the first look at a family.

## 10. Pass rule (verbatim C1-C5 from `docs/STRATEGY_EVAL.md`, with one declared adaptation)

Verdict cost: 1.5x slippage, no extra haircut. Lots = 10 for per-lot figures.

1. Beats the baseline at that cost (paired on common entry dates, mean difference > 0). Baseline = the default weekly
   IC/PCS chain baseline at 1.5x, on the same archive and the same entry dates.
2. Per-lot expectancy > 0.
3. Bootstrap 95% CI lower bound > 0 (10,000 draws, seed 20261111). Declared adaptation C3': test and holdout windows
   have fewer than 5 year-clusters, so the **monthly-block bootstrap** (`strategy_eval.monthly_block_bootstrap`) is the
   C3 interval for those windows. Fixed before any run.
4. At least 4 of 5 dev years positive.
5. Holm-adjusted one-sided t-test p < 0.05 over every cut in the registry.

**Declared adaptation of C4.** C4 says 4 of 5 years. The test window has 2 years and the holdout has 2024, 2025, and
2026 YTD (3 periods). Those counts cannot satisfy 4 of 5. For this document:
- test verdict: **C4' = both test years positive (2 of 2)**,
- holdout verdict: **C4' = every holdout calendar year positive** (2024, 2025, 2026 YTD).
C4' is stricter in proportion than C4. It is the only change to the rule text.

**Minimum trades.** Each window verdict needs at least 30 trades. Fewer than 30 gives **INSUFFICIENT_DATA**, not
"almost pass". A missing year, no baseline, or fewer than 30 paired trades also gives INSUFFICIENT_DATA.
Verdicts are `PASS`, `FAIL`, `INSUFFICIENT_DATA`, or `INDICATIVE_ONLY`. Any trade with `pricing_source='bs'` caps the verdict
at INDICATIVE_ONLY. None is expected here.

A test PASS requires C1 to C5 (with C3' and C4') all true. A holdout PASS requires the same. A test PASS is necessary
but not sufficient (Section 8, item 6), and only a holdout PASS can support paper trading.

**Implementation note (not a rule change).** `strategy_eval` currently hard-codes C4 as 4 of 5 dev years and C3 on the
year-cluster interval. Before any run, the harness must implement C3' and C4' for the test and holdout windows, with
tests, so the verdict code matches this section. A run made with a harness that does not match this section is void.

## 11. Decision table

| Outcome | Action |
|---|---|
| Family test verdict FAIL | Dead. No re-tuning, no other cell from that family, no holdout. |
| Family test verdict INSUFFICIENT_DATA | Not promoted and not tested again. Recorded as "untestable at this sample". |
| Family test verdict PASS | One holdout look on that candidate via the ledger. |
| Holdout FAIL | Dead. Recorded. |
| Holdout PASS | Forward paper-trading of that single frozen rule only (Section 12). |
| Nothing passes | Record **"no demonstrable edge at realistic costs"** for these two families. Logging stays data collection. |

## 12. What a PASS does and does not authorise

**Authorises:** forward paper-trading of one frozen rule, mirroring the T3 plan in `docs/plans/NEXT_TASKS_EDGE_SEARCH.md`.
Log each signal, intended fill (quote-log mid), achieved-proxy fill (sell at bid, buy at ask), and expiry settle. Nothing
places orders. Kill rule: cumulative paper loss of **Rs 15,000** (3% of Rs 5,00,000, the capital base of this document)
ends the test as FAIL. Horizon: 30 qualifying trades or 2028-10-31, whichever is first. Fewer than 30 trades by the end
date is INCONCLUSIVE, not PASS.

**Does not authorise:** live capital, any change to the frozen rule, a second cell, a combination of A and B, any
change to gates or costs, or any claim of 12% CAGR. The Rs 5,00,000 base used here differs from the Rs 25,00,000 in
the T3 plan. Confirm the base before any paper session starts.

## 13. Declared totals

- Grid cells: **10** (A: 6, B: 4).
- Registry cuts from this document: **at most 14** (10 train, 2 test, 2 holdout). Hard cap.
- Holm family: whole registry file, conservative.
- Deflated Sharpe N: **10**.
- Trade minimum per window: **30**.

## 14. Open items (left deliberately)

- The exact `margin_per_lot` formula for capital mode is taken as the proxy in Section 5. Confirm it matches what
  `ChainConfig` computes before running. Do not change it after a family is run.
- The archive end date for the holdout is set at the time of the look and recorded in the ledger. It is not fixed here.
- Whether the monthly cadence for B uses the same `sigma_T` convention as weekly is set by Section 4 and not tested
  independently.
