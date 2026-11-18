# Pre-registration, round 3: monthly and filtered hedged NIFTY option-selling cells (7 cells)

Date: 2026-11-18. Status: **FROZEN** on author approval (2026-11-18), at the commit that adds this version. No round-3 cell has been run on
the real archive. The only real-archive use since round 2 was mechanics smoke tests on throwaway `SMOKE_*` cells (train window, no P&L read, registry unchanged).
Candidate list and rationale: `docs/strategy_candidates_round3.md`. Rules not restated here come from `docs/preregistration_round2.md` and `docs/STRATEGY_EVAL.md`.

## 0. What changed since round 2 (audit-driven, all opt-in, defaults keep old results)

- **Entry basis:** strikes and sigma_T use the NIFTY close on signal day S (`strike_basis="signal_close"`), not the fill-day close. Legs are still priced at F settle. Round 1-2 used the F close, which a real entry does not know; the audit found it flatters. Round-3 numbers are not comparable with round 1-2 numbers.
- **Max loss** for credit structures = wing width minus the credit actually received after entry slippage, plus round-trip fees (`max_loss_basis="fill_plus_fees"`). Used for sizing and records.
- **Expiry brokerage** Rs 20 + GST per expiring leg is charged (`expiry_brokerage=True`), a conservative assumption.
- **Zero-contract legs:** any entry leg with 0 contracts skips the trade, as in round 2.
- **Registry:** now 21 cuts (the 6 round-2 train cuts were registered retroactively; 4-6 extra round-2 test-window outputs are noted in `logs/round2/EXTRA_LOOKS.md`, not cuts).
- **Known lenient pass-rule parts (author kept the rule unchanged):** the one-sided t-test (about 12-15% false-pass on this payoff shape) and the monthly-block CI (about 8% false lower-bound > 0). The joint rule false-passes about 3-5% because Holm over a growing registry is conservative. At 41-111 trades the rule detects an edge of about Rs 250-190 per lot with 80% power for a single cut, and higher with a larger registry. A real edge of Rs 50-150 per lot will usually be missed. A "no edge" verdict means "no large edge".

## 1. Hypotheses (mechanism first; the cell list was fixed from `docs/strategy_candidates_round3.md`, not from round-3 results)

- **M1, M2 monthly hedged iron condor.** About 4x the credit per trade against the same fixed costs, 12 trades a year. Fails if a gap inside 4 weeks costs more than the premium.
- **M3 monthly put credit spread.** Same, put-skew only. Fails on crash months (2020).
- **S1 post-spike put credit spread.** Premium is richest right after volatility falls from a spike; this also removes the VIX 25+ losses. Fails if the sample (a handful of events) is too small or volatility keeps rising.
- **T1 term-structure gate.** Weekly implied move not above the monthly implied move (contango) marks calm; backwardation marks stress. Fails if the proxy is noisy.
- **R1 trend-selected spread.** Sell put spreads above the 50-day average, call spreads below it. Fails on whipsaws.
- **W1 wide weekly iron condor.** Strikes at 1.5 sigma, wide wings; lower hit-rate cost. Fails if the credit is too small after costs.

## 2. Common conventions

- NIFTY index options only. Signal day S, fill day F = next session, legs priced at F EOD settle, slippage multiplier 1.0 (pass bar), sensitivity 0.5x and 1.5x reported but never verdict cuts.
- `max_concurrent=1`, hold to expiry (no exits in round 3), `strike_basis="signal_close"`, `max_loss_basis="fill_plus_fees"`, `expiry_brokerage=True`, `skip_zero_contract_legs=True`.
- Weekly cells: signal on weekly expiry days, weekly DTE window [3, 8]. Monthly cells: signal on the monthly expiry day, target monthly expiry with DTE window [15, 28] closest to 21 (about a quarter of monthly signals drop at fill; counted as skips).
- sigma_T = spot_S x (VIX_S / 100) x sqrt(DTE / 252), strike = nearest listed strike to spot_S -/+ k x sigma_T.
- Capital and sizing as round 2 Section 4: Rs 25,00,000, equity-based sizing, `risk_cap_pct=0.05`, `margin_cap_pct=0.20`, `kill_dd_pct=0.20` absorbing. Tier 1 verdict at lots=10.

## 3. Cells (declared values, no other values may be run)

| Cell | Structure | Cadence | k | Width W | VIX gate | Extra rule |
|---|---|---|---|---|---|---|
| M1 | IC (hedged) | monthly | 1.0 | 400 | [13, 25) | none |
| M2 | IC (hedged) | monthly | 1.3 | 400 | [13, 25) | none |
| M3 | PCS | monthly | 1.0 | 400 | [13, 25) | none |
| S1 | PCS | weekly | 1.0 | 300 | [13, 35) | post-spike: max VIX over last 20 sessions through S >= 25 and VIX_S <= 0.80 x that max |
| T1 | PCS | weekly | 1.0 | 300 | [13, 25) | term-structure: weekly ATM straddle implied-move proxy <= monthly proxy at S close |
| R1 | trend-selected PCS/CCS | weekly | 1.0 | 300 | [13, 25) | PCS if NIFTY close_S > SMA50 through S, else CCS |
| W1 | IC (hedged) | weekly | 1.5 | 400 | [16, 25) | none |

VIX bands come from the dev-window premium audit and are in-sample (round 2 Section 0 applies). Cell parameters are single values.

## 3b. Combination

At most one combination test cut, built only if two cells survive train and their daily-P&L correlation on train is below 0.7. Equal capital split, no weights. If no pair
qualifies, no combination is run.

## 4. Evaluation, budget and pass rule

- Windows: train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024+ (partly seen; a holdout PASS alone authorises paper trading only).
- Train: all 7 cells once. Test: only train survivors (per-lot expectancy > 0 at 1.0x and n >= 30), maximum 3 test cuts including a combination. Holdout: at most 1 look, only for a test PASS, logged in `logs/holdout_ledger.json`.
- **Declared budget: 7 train + 3 test + 1 holdout = 11 cuts.** Registry goes from 21 to at most 32. All train runs are registered at run time through `scripts/` (kind train). Any extra test-window run, including sensitivity runs, is recorded in `logs/round3/EXTRA_LOOKS.md` before it is read.
- Pass rule: Tier 1 verbatim C1-C5 with C3', C4' (unchanged from round 2). Tier 2 (capital mode, test window, 1.0x, Rs 25L): CAGR >= 12%, max drawdown <= 12%, Sharpe >= 0.8.
- Reported beside each verdict, not part of it: the mean-zero bootstrap p (`scripts/random_entry_null.py`; tests mean > 0 only, not entry timing) and the source label of any return (premium, collateral yield, market return).
- `INSUFFICIENT_DATA` below 30 trades; S1 and the monthly cells are likely to land here (about 10-35 trades per train window). That outcome is a valid result.
- No re-tuning, no second cell, no rename after a fail. A documented bug fix is the only exception, with a dated addendum before re-run.

## 5. Known limitations (stated, not corrected)

- EOD settle fills, no bid/ask. Slippage 1.0x is above the measured half-spread (ratio 0.137 on 3 dates) but is not confirmed by production fills.
- Entry-basis bias against an intraday mid is unquantified. Spot and VIX before 2024-07 come from Yahoo. Archive expiry index equals Yahoo close on every comparable expiry.
- Low power at these trade counts (Section 0). One crash regime in dev. Margin proxy equals max loss per lot, not exchange SPAN.
- Term-structure proxy uses the last listed monthly expiry per month in the archive listing; it depends on the listing horizon.
- A pass on test is necessary, not sufficient; the monthly-block CI is optimistic.

## 6. What a PASS does and does not authorise

A holdout PASS supports paper trading with quote logging over at least 4 weeks at several VIX levels. It does not authorise live capital. A Tier 2 PASS is required to claim the 12-18% goal, and the return source must be stated.

## 7. Pre-run engine work (recorded before any run)

1. Declare `ROUND3_CELLS` and `get_round3_cell` in `backtester/candidates.py` exactly per the Section 3 table, with field-by-field tests against this document.
2. Add `scripts/run_round3.py` (phase guard copied from `run_round2.py`) that registers train cuts at run time and writes `logs/round3/EXTRA_LOOKS.md` entries for any extra window run.
3. Verify anchors -133.5 / -253.2 at lots=10 still hold and the registry hash is unchanged by the build.
