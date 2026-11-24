# Pre-registration, round 4: round-3 cells with a leak-free ML exit gate, 0.3x slippage bar (7 cells)

Date: 2026-11-19. Status: **FROZEN** on author approval (2026-11-19), at the commit that records this line. No round-4 cell has been run.
Rules not restated here come from `docs/preregistration_round3.md` (Sections 0, 2, 4) and `docs/preregistration_round2.md`.

## 0. What is new, and what has already been seen

- **Exit gate.** The existing ML exit model (`models/trade_monitor.py`, `ExitStrategyEngine`) gates exits on top of hold-to-expiry. Candidate mode got an opt-in hook (commit f10ff78, default off, anchors unchanged).
- **Model:** `logs/ml_cutoff_2021/exit_model.pkl`, trained by `scripts/train_ml_cutoff.py --end 2021-12-31`. `period_metadata.train_end` is 2021-12-31 and no later row enters training. The model is trained on Black-Scholes-priced synthetic trades, not on archive trades. The repo cache models (`data/.cache`, `data/.cache_seed`) were trained through 2026 and are **never used** in this round.
- **Gate rule, fixed, no sweep:** exit when model probability >= 0.75 and trade P&L < -15% of credit (`ml_gate_adapters` defaults), checked at EOD while dte > 0. Marks are EOD settle.
- **Slippage bar (author decision, 2026-11-19): 0.3x of model slippage is the pass bar; 1.0x is reported as sensitivity.** Round 3 used 1.0x as the bar. Evidence for 0.3x: measured half-spread median Rs 0.075 against model Rs 0.539 (ratio 0.137, IQR 0.09-0.23, 3 dates, 11:00-13:00 only, no VIX<13). 0.3x sits above the measured ratio. It is not confirmed by production fills, which do not exist. A cell that passes only at 0.3x and fails at 1.0x is reported as such.
- **Already seen before this document (disclosure):** a leaky-model descriptive sweep on the dev window (2019-2023, 1.0x, model trained through 2026): the gate lowered Sharpe on R1, T1, W1, and raised it on M2, M3 (25 and 15 trades), S1 (23 trades), with M1 worse. These are in-sample looks at the same dev data. They motivated nothing in the cell list below, which is the round-3 list unchanged, but the held-out test window has been seen twice for these cells (round 3 verdicts and that sweep). The test window is therefore weaker evidence than in round 3; only the holdout (2024+) is unseen by the cutoff model, and it is partly seen by earlier scans.

## 1. Hypothesis

Round-3 cells hold to expiry and take the full tail. An exit gate trained only on pre-2022 data may cut tail losses on some structures. It fails if it exits trades that would recover (as the leaky sweep suggested on weekly cells), or if the synthetic training distribution does not transfer to archive marks.

## 2. Cells

The seven round-3 cells M1, M2, M3, S1, T1, R1, W1, with the exact round-3 parameters (Section 3 table of `docs/preregistration_round3.md`), plus the exit gate. No other values may be run. Cell names `G_M1` ... `G_W1`.

All other conventions as round 3: `strike_basis="signal_close"`, `max_loss_basis="fill_plus_fees"`, `expiry_brokerage=True`, `skip_zero_contract_legs=True`, `max_concurrent=1`, Rs 25,00,000 equity-based sizing, `risk_cap_pct=0.05`, `margin_cap_pct=0.20`, `kill_dd_pct=0.20` absorbing. Tier 1 per-lot verdict at lots=10; Tier 2 capital-mode on test.

## 3. Evaluation, budget and pass rule

- Windows: train 2019-02-11..2021-12-31 (in-sample for the exit model), test 2022-01-01..2023-12-31, holdout 2024+ (partly seen; one look only for a test PASS, `logs/holdout_ledger.json`).
- Train: all 7 cells once at 0.3x (registered at run time). Test: only train survivors (per-lot expectancy > 0 at 0.3x and n >= 30), maximum 3 test cuts. Holdout: at most 1 look.
- **Declared budget: 7 train + 3 test + 1 holdout = 11 cuts.** Registry goes from 30 to at most 41. Holm over the whole registry, so the bar is higher than in round 3. Extra looks (1.0x sensitivity, capital runs) are logged in `logs/round4/EXTRA_LOOKS.md` before they are read.
- Pass rule: Tier 1 C1-C5 with C3', C4' unchanged, verdict slippage 0.3x. Tier 2 (capital mode, test, 0.3x, Rs 25L): CAGR >= 12%, max drawdown <= 12%, Sharpe >= 0.8. A cell must also have per-lot expectancy > 0 at 1.0x before any paper trading is proposed.
- **Gate-off comparison:** each surviving cell is also run gate-off at the same slippage and window, reported beside the verdict (not a cut, logged as an extra look), so the gate's effect is separable from the cheaper slippage.
- `INSUFFICIENT_DATA` below 30 trades; the monthly cells and S1 will probably land there (15-25 trades on dev). That is a valid result.
- No re-tuning, no second cell, no threshold sweep, no rename after a fail. A documented bug fix is the only exception, with a dated addendum before re-run.

## 4. Known limitations

- Exit model trained on Black-Scholes synthetic trades (BS overstates credit); thresholds 0.75 and -15% were tuned elsewhere. The training frame is unlagged while the gate scores a frame with non-India columns lagged one row (possible train/score mismatch, flagged by the training run).
- The C1 baseline is gate-off at the cell's own strike basis: C1 compares to the round-3 baseline and is not like-for-like with the gated cells.
- Power is low (Round 3 Section 0). 0.3x is a cheaper bar than the one round 3 used, so round-4 results are not comparable with round-3 results.
- EOD marks, no bid/ask; margin proxy is max loss, not SPAN; one crash regime in dev.

## 5. What a PASS authorises

Same as round 3 Section 6: a holdout PASS supports paper trading with quote logging over at least 4 weeks; not live capital. Tier 2 PASS is required to claim the 12-18% goal, with the return source stated.

## 6. Pre-run engine work (recorded before any run)

1. `ROUND4_CELLS` / `get_round4_cell` wrapping the round-3 specs with the gate flag, field tests against Section 2.
2. `scripts/run_round4.py` (phase guards from `run_round3.py`): `--exit-model` fixed to `logs/ml_cutoff_2021/exit_model.pkl`, refuses any path under `data/.cache*`, 0.3x default verdict slippage, train cuts registered at run time as `ROUND4_train|<cell>`, `logs/round4/EXTRA_LOOKS.md` before any extra run.
3. Verify anchors -133.5 / -253.2 at lots=10 still hold and the registry hash is unchanged by the build.

## 7. Addendum (2026-11-19): author-authorised holdout look, deviation from Section 3

Test phase gave no PASS (G_T1 -691.2, G_R1 -289.4, G_W1 -686.5 Rs/lot at 0.3x, n=36/61/41; Tier 2 CAGR -3.7/-2.9/-3.0%), so Section 3 keeps the holdout sealed. The author explicitly ordered one holdout look for G_T1 anyway (motivation: train-window utilisation sweep showed 14.3% CAGR at 40% risk cap). This is a rule deviation, not a PASS-triggered look. Scope: G_T1 only, clean model, 0.3x, lots=10 (Tier 1) plus capital mode at the declared 5% cap, window 2024-01-01..last archive day. One look; no re-run, no other cell. Logged as extra look in `logs/round4/EXTRA_LOOKS.md`. Result cannot upgrade the verdict to PASS (test failed); it is descriptive evidence.

Results (2026-11-21, same addendum). Test 2022-2023 at 0.3x with the clean model: G_T1 n=36 -691.2/lot, G_R1 n=61 -289.4/lot, G_W1 n=41 -686.5/lot; Tier 2 capital mode CAGR -3.7/-2.9/-3.0%. Holdout 2024-01-01..2026-11-16, G_T1 only, 0.3x: n=46 (15 ML exits), +23.5 Rs/lot at lots=10; capital mode (Rs 25L, 5% cap) CAGR -0.15%, MaxDD 3.3%, Sharpe -0.05. **No edge found in round 4.** The holdout look was an author-ordered deviation and is descriptive only.
Descriptive screens afterwards (dev window, no registry writes, `scripts/explore_*.py`, `scripts/priced_random_null.py`, `scripts/reality_check.py`): skip-monthly-expiry, 1-2 DTE IC, event-skip, VIX-trend. Priced random-entry null: skip-monthly p 0.09-0.22 vs random same-size subsets. White Reality Check over 42 cells: best-variant p 0.29, Hansen SPA 0.52, minimum Holm-adjusted p 1.0. None distinguishable from chance.
