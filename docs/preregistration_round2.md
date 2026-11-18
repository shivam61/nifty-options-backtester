# Pre-registration, round 2: hedged NIFTY weekly option-selling families C, D, E (+ combination F)

Date: 2026-11-18. Status: **FROZEN** on author approval (2026-11-18), at the commit that adds this file. No run of
any family C, D, E or F has happened. The only real-archive run since round 1 was a mechanics smoke test (train window,
throwaway `SMOKE_*` cells, no P&L read, registry hash unchanged `a716e18d90bb`). Engine: `backtester/chain_engine.py` candidate mode
with the opt-in features added on branch `feat/strategy-eval-harness` (exits, overlap, equity sizing, IC/CCS, entry filter).
Governed by `docs/STRATEGY_EVAL.md` and the rules of `docs/preregistration_candidates.md` unless stated here.

## 0. Goal and known facts

- Goal: a hedged (defined-risk) NIFTY option-selling approach with 12-18% yearly return and bounded drawdown, from Rs 25L start capital.
- Carried over, not re-tested: A and B failed (`docs/preregistration_candidates_results.md`); real-price baseline is negative at 1.5x slippage; premium
  audit by VIX bucket (implied minus realised, pts/unit): <13 -3.8, 13-16 +10.2, 16-20 +25.2, 20-25 +14.8, 25+ -57.7.
- VIX bands below come from that table. They are post hoc and in-sample, admissible only under the walk-forward split in Section 6.
- 2024-2026 was seen by earlier scans. The holdout is not clean. A holdout PASS alone does not authorise live trading (Section 10).
- Realised half-spread measured Rs 0.075/unit median against model slippage Rs 0.539 (ratio 0.137, 3 dates, 11:00-13:00 only, no VIX<13).
  The model at 1.0x therefore sits above measured spreads. It is not confirmed by production fills; none exist.

## 1. Hypotheses

- **C (put credit spread with exits).** Round 1 held to expiry and lost to the tail (worst trade 15.6x credit). Closing at a profit target and cutting at a stop
  may keep the premium and clip the tail. Fails if EOD-checked stops gap through, so exits do not cap the loss.
- **D (hedged iron condor).** Selling both sides collects put skew and call premium with both tails capped by wings. Fails if the call side has
  negative expectancy (audit shows premium only in 16-25) and costs of four legs eat the credit.
- **E (VRP-gated put credit spread).** The premium exists when implied vol is above realised vol. Gating entry on VIX minus 20-day realised vol removes
  low-premium days. Fails if the gate only reduces trade count without raising per-trade expectancy.
- **F (combination).** Two survivors with different payoffs may raise return per unit of drawdown. Only built if two cells survive train.

## 2. Conventions (all families)

- Universe NIFTY index options, NSE F&O archive. Signal day S = weekly expiry day, VIX read at S close. Fill day F = next session, strikes and prices
  at F EOD settle. Weekly DTE window [3, 8]. Strike target spot_F -/+ k x sigma_T, sigma_T = spot_F x VIX_S/100 x sqrt(DTE/252), snapped to nearest listed strike.
- `max_concurrent=1`, `signal_cadence="expiry_day"` for every cell. Overlap is out of scope for round 2 (the signal weekday would add a free parameter).
- **Zero-contract rule (author decision):** if any leg of the entry has 0 contracts traded on F, the whole trade is skipped, reason `zero_contract_leg`, counted per cell.
  This needs a small engine change before any run (Section 11).
- Exits checked at EOD settle marks only. A gap through a stop fills at that day's mark. Exit costs and slippage use the existing exit path.

## 3. Cells (declared grid, no other values)

All width W = 300 index points, put/call offset k = 1.0 sigma_T, long wing at k-side distance W. Not tuned: k and W are single values.

| Cell | Structure | VIX gate | Extra rule | Exit |
|---|---|---|---|---|
| C1 | PCS | [13, 25) | none | profit target 50% of credit, stop 2x credit |
| C2 | PCS | [13, 25) | none | profit target 75% of credit, stop 1.5x credit |
| D1 | IC (hedged) | [16, 25) | none | profit target 50%, stop 2x credit |
| D2 | IC (hedged) | [16, 25) | none | hold to expiry |
| E1 | PCS | [13, 25) | VIX - RV20 >= 2 vol points | hold to expiry |
| E2 | PCS | [13, 25) | VIX - RV20 >= 4 vol points | hold to expiry |

RV20 = annualised stdev of the last 20 daily close-to-close log returns of NIFTY, known at S close (no look-ahead; checked by a leak test).
Cells differ from round 1 A (exits, band, condor, gate), so none is a re-run of A under a new name.

## 3b. Combination F

Built only if at least two cells have per-lot expectancy > 0 on train and neither has a dead-family flag. F = the two best by train expectancy per lot,
equal capital split, run once on test. No weights, no extra cells.

## 4. Sizing and capital (author decision)

- Start capital Rs 25,00,000. Equity-based sizing at each entry from current equity (`equity_based_sizing=True`), capital mode on.
  Lots = floor(min(risk_cap_pct x equity / max_loss_per_lot, margin_cap_pct x equity / margin_per_lot, max_lots)). Allocation rescales with equity up and down.
- Fixed values, not grid-searched: `risk_cap_pct=0.05` (proposed), `margin_cap_pct=0.20`, `max_lots=` engine default, `kill_dd_pct=0.20` absorbing, no re-arm.
  Per-lot verdict (Tier 1) is evaluated at lots=10 as in round 1 so it stays comparable.

## 5. Costs

Corrected cost model of `docs/COSTS_NSE_OPTIONS.md`. Slippage multiplier **1.0x is the pass bar**. 0.5x and 1.5x are reported as sensitivity. A candidate must also
have expectancy > 0 at 1.5x before any paper trading is proposed.

## 6. Evaluation procedure

- Dev window 2019-02-11..2023-12-31. Train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024-01-01 onward.
- Train: all six cells once. Test: only train survivors (per-lot expectancy > 0 at 1.0x and n >= 30), max 3 test cuts incl. F. Holdout: at most 1 look, only for a test PASS,
  logged in `logs/holdout_ledger.json`. A holdout FAIL is final.
- Every verdict cut auto-registers in `logs/eval_registry.json`. Holm runs over the whole registry (the 12 round-1 cuts plus these), so each cut raises the bar.
- **Declared budget: 6 train + 3 test + 1 holdout = 10 cuts, hard cap.** No re-tuning, no second cell, no rename after a fail. A documented bug fix is the only exception, recorded in a dated
  addendum before the affected cell is re-run.

## 7. Pass rule

- **Tier 1 (edge exists):** verbatim C1-C5 of `docs/STRATEGY_EVAL.md` with the test/holdout adaptations C3', C4' of round 1 Section 10, at 1.0x slippage.
- **Tier 2 (meets the goal), test window, capital mode, 1.0x, Rs 25L:** CAGR >= 12%, max drawdown <= 12%, daily-return Sharpe >= 0.8 (rf 0).
  *Floors confirmed by the author.* Report both tiers for every cell. Tier 1 only = "edge, below goal".
- `INSUFFICIENT_DATA` below 30 trades. Any model-priced trade caps the verdict at `INDICATIVE_ONLY`.

## 8. Known limitations (stated, not corrected)

- EOD settle fills, no bid/ask; entry-basis bias unquantified. Stops and targets are EOD-checked, so intraday breaches are invisible.
- About 40-80 trades per cell per window: low power, one crash regime in dev. Tier 2 on about 2 test years is a weak estimate of drawdown.
- Spot and VIX before 2024-07 come from the Yahoo cache, option marks from the NSE archive.
- SEBI 2024 changes (weekly expiry limits, margins, STT) fall mostly after the dev window; the holdout is the only post-change data and is partly seen.
- Capital-mode kill switch is absorbing: after a trip no more entries. It can end a run early and flatter or hurt CAGR; the trip date is reported.
- Margin proxy equals max loss per lot, not exchange SPAN.

## 9. Changes after the first look

None allowed except a documented bug fix with a dated addendum (Section 6).

## 10. What a PASS does and does not authorise

A holdout PASS on Tier 1 supports paper trading only, with quote logging (`scripts/log_option_quotes.py`) over at least 4 weeks at several VIX levels, then recalibration.
It does not authorise live capital. Tier 2 PASS is required to claim the 12-18% goal.

## 11. Pre-run engine work (recorded before any run, not a result-driven change)

1. Add opt-in `skip_zero_contract_legs` in candidate mode (default False, so existing results are unchanged) and the `zero_contract_leg` skip reason; test-first.
2. Add the RV20 entry filter (via `candidate_entry_filter`) with a leak test.
3. Add a runner for cells C1-F1 in `scripts/run_candidates.py` or a sibling script; verify anchors -133.5 / -253.2 at lots=10 still hold.

## 12. Open items for the author

- Resolved: author approved Tier 2 floors (CAGR 12%, MaxDD 12%, Sharpe 0.8) and risk_cap_pct 0.05 as drafted.
- Resolved: overlapping weeklies out of scope for round 2.
