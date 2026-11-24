# Results: pre-registered candidates A and B

Run 2026-11-17 under `docs/preregistration_candidates.md` (frozen, with Section 15 disclosures).
Real NSE F&O archive, chain engine, lots = 10, verdict cost 1.5x slippage (files generated at 1.0x, stressed by the harness).
Registry: 12 recorded cuts (10 train, 1 selection, 1 test). The holdout (2024+) was **not opened**; no ledger row exists.

## Outcome by decision table (Section 11)

| Family | Result | Action |
|---|---|---|
| B (long strangle, VIX < 13) | **INSUFFICIENT_DATA**: 13 (weekly) and 3 (monthly) train trades per cell, minimum 30 | Dead, untestable at this sample. No test, no holdout. |
| A (put credit spread, VIX 16-25) | Selected `PCS_A_k09_w300` on train; **test verdict FAIL** | Dead. No re-tuning, no holdout. |

Nothing passed. Recorded conclusion: **no demonstrable edge at realistic costs for these two families.**

## Family A detail

Train 2019-02-11..2021-12-31 (per lot at 1.5x): k0.9/w200 +101.8, **k0.9/w300 +138.8 (selected, n=76)**, k1.1/w200 +44.4,
k1.1/w300 -0.1, k1.3/w200 -102.5, k1.3/w300 -116.0. Selected-cell train p = 0.35, deflated-Sharpe p = 0.53 over 6 cells:
the train result was not distinguishable from noise.

Test 2022-01-01..2023-12-31, selected cell only (n = 41, win rate 85.4%, context only):

| Criterion | Result |
|---|---|
| C1 beats baseline (paired, 34 dates) | PASS: candidate -170.8 vs baseline -722.5 Rs/lot |
| C2 expectancy > 0 | FAIL: -391.5 Rs/lot |
| C3' monthly-block 95% CI lower > 0 | FAIL: [-1711, +647] over 11 months |
| C4' every test year positive | FAIL: 1 of 2 |
| C5 Holm p < 0.05 | FAIL: raw p 0.71 |

Shape: win rate 85% but payoff ratio 0.12 (avg win / avg loss); worst trade is 15.6x the credit; breakeven win rate 89.2%.
The train-to-test swing (+139 to -391) is what a noise-selected cell looks like. C1 passed only because the default
baseline is worse (-722), which is not evidence for A.

## Limitations carried over
EOD settle marks only, no bid/ask; test window is 1.2 years and 41 trades; the VIX bands came from the dev-window table
(post hoc); the calibrated spread model was not used. Lot count for every number above: 10.

## What this does and does not say
It says these two specific, pre-declared rule sets showed no edge on this archive at 1.5x costs. It does not say no
NIFTY options strategy can work, and it authorises nothing: no paper trading, no live capital.
