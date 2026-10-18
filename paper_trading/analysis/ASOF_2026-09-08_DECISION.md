# As-Of Signal Decision: Tue 2026-09-08 11:30 IST (RETROSPECTIVE)

> Historical record (2026-09-08 replay on the pre-repair cache); superseded by the 2026-10-18 cache repair - do not use for live decisions.

> **RETROSPECTIVE, MODEL-ESTIMATED. NOT A LIVE TRADE RECORD.**
> This is a replay of the signal engine with the clock pinned to 2026-09-08 11:30 IST and data cut off at 2026-09-04. No real option chain or fills were used. Any premium or P&L implied here would be Black-Scholes estimates. Nothing in this file is a paper trade.

## 1. Verdict

| Track | Verdict | Basis |
|-------|---------|-------|
| Weekly (Put Credit Spread) | **SKIP** (no entry) | Strategy `should_enter` declined at VIX 10.7, 5d -1.1%. Rule-based gate (no weekly risk engine cache). |
| Monthly | **INDETERMINATE → no-trade** | Printed `AVOID` (quality 45.2%, conf 9.5%) is not trustworthy: macro cache columns are corrupted (Section 5). |
| Net | **No entry. Capital stays ₹25L.** | Both tracks blocked; monthly block is a data-integrity block, not a model judgement. |

The dashboard line "Weekly track: ELIGIBLE" is only the pre-strategy eligibility flag. It conflicts with the SKIP outcome printed one section earlier and is not the decision.

## 2. Inputs (data cut-off 2026-09-04, as printed)

| Input | Value |
|-------|-------|
| Nifty 50 | 23,897.70 |
| India VIX | 10.68 |
| US VIX | 14.53 |
| S&P 500 | 7,718.60 |
| US 10Y | 4.78% |
| Crude | $96.28 |
| Gold | $4,429.80 |
| USD/INR | 94.49 |
| Bank Nifty | 57,369.65 |
| Detected regime | LOW_VOL |
| Capital / budgets | ₹25,00,000 / ₹12.5L weekly / ₹12.5L monthly |
| Expiries listed | Weekly Sep 15 (DTE 7), Weekly Sep 22 (DTE 14), Monthly Sep 29 (DTE 21) |

Data is 4 days old at the simulated time. The Sep 4 macro values were printed from the cache and were not independently checked against a source.

## 3. Gate-by-gate

| # | Gate | Result | Evidence |
|---|------|--------|----------|
| 1 | Entry window 11:00–13:00 IST | PASS | 11:30 IST |
| 2 | Entry model loaded | PASS (with warning) | `entry_model_v4.pkl`, 15d old; sklearn 1.8.0 pickle loaded under 1.9.0 |
| 3 | Weekly risk engine (ETL gate) | N/A, rule-based used | `weekly_risk_engine_v2.pkl` missing |
| 4 | Monthly signal quality | Printed AVOID, **not valid** | quality 45.2%, conf 9.5%; inputs corrupted |
| 5 | Weekly strategy `should_enter` | **FAIL → SKIP** | PCS declined at VIX 10.7, 5d -1.1% |
| 6 | Simultaneous VIX cap | PASS | Cap printed 22.0; current 10.7, both tracks allowed |
| 7 | Cross-track DD limit (15% = ₹3.75L) | Not triggered | No open position in tracker (Trade 1 closed 2026-09-01) |
| 8 | Emergency weekly exit (>3% combined loss) | N/A | No open position |

## 4. Why SKIP (weekly)

- The Put Credit Spread `should_enter` declined at VIX 10.7 with a 5-day move of -1.1%. The printout does not show the threshold that was missed, so the exact failed condition is not confirmed here.
- Per the code (verified by parent), weekly PCS applies at VIX ≤ 16. An Iron Condor would need higher VIX, so no IC is generated at VIX 10.68. The earlier Trade #1 "IC" is therefore not a rule-consistent setup.
- The weekly decision uses price and VIX only, so it is unaffected by the macro-column corruption.

## 5. Data-integrity blocker (must fix before any monthly decision)

- **Evidence:** `crude == us_vix`, `usdinr == dxy`, and `nifty_bank == sp500` on 100% of rows through 2026-08-21. Values are correct only from 2026-08-24.
- **Printed artifacts:** "Crude oil surging (691.8% in 20d)", "EM SELLOFF (EEM -98.4%)", "CRUDE + INR DOUBLE STRESS (3.07)", "DXY + CRUDE DOUBLE PRESSURE (3.4)".
- **Impact:** monthly quality and confidence, the monthly warnings, and the monthly features of the ML model (global CV AUC 0.696) were built on corrupted history. The AUC is therefore not evidence of model quality.
- **Required fix:**
  1. Repair the ticker-to-column mapping in `data/market_data.py` (not edited in this task).
  2. Delete the affected parquet cache in `data/.cache/` and rebuild.
  3. Retrain: `nohup python3 main.py --mode evolve > logs/evolve_$(date +%Y%m%d_%H%M).log 2>&1 &`
  4. Re-run the as-of replay and compare.

## 6. Metadata

- **Command:** wrapper `/tmp/claude-1001/-home-shivamguptanit-github-nifty-options-backtester/911343f5-a57f-4a5e-b680-863e35040db3/scratchpad/asof_signal.py`. It pins `datetime` to 2026-09-08 11:30 IST, sets `MARKET_DATA_CACHE_ONLY=1`, and runs `main.py --mode signal-combined --end 2026-09-04 --capital 2500000`. The wrapper lives outside the repo.
- **Output:** `/tmp/claude-1001/-home-shivamguptanit-github-nifty-options-backtester/911343f5-a57f-4a5e-b680-863e35040db3/scratchpad/asof_signal_stdout.txt`
- **Model files:**
  - `data/.cache/entry_model_v4.pkl`, dated 2026-08-23
  - `data/.cache/exit_model.pkl`, dated 2026-08-23
  - `data/.cache/weekly_risk_engine_v2.pkl`, **missing**
- **Warnings:**
  - sklearn 1.8.0 pickles (LabelEncoder, _SigmoidCalibration, CalibratedClassifierCV) loaded under sklearn 1.9.0. Results may be unreliable until retrained or the version is pinned.
  - `data starts 2009-01-02 but 2009-01-01 was requested`.
- **Training window (as printed):** 2009-01-01 to 2026-09-04, 4,337 trading days, 19,044 trades. The per-regime table prints 0 trades and 0.000 accuracy for every regime. This is a display artifact and was not investigated further.

## 7. Journal status

| Item | Status |
|------|--------|
| Calendar facts (weekly expiry Tuesday since 2025-09-01; Sep 8 is Tuesday; Sep 11 is not an expiry) | Trustworthy |
| Capital and budget split (₹25L, 50/50) | Trustworthy as configuration |
| Sep 4 market snapshot | Printed values, pending source check |
| Weekly SKIP decision (price/VIX only) | Trustworthy for this replay |
| Monthly AVOID / warnings / ML AUC | **Not trustworthy** (corrupted macro columns) |
| Trade #1 (Aug 29 IC) | **SIMULATED back-fill, not live.** No real fills. Lots field inconsistent (65 units = 1 lot). Exit fill 28.1 inconsistent with expired-worthless. Deviation figures conflict (+4.5% vs -95.5%). Excluded from Phase 1. |
| ACCOUNT_STATE.csv +₹1,328 equity | **Simulated.** Should not count toward Phase 1. The file has no Notes column, so it was left unchanged. |
| DAILY_LOG.csv rows 2026-08-29 to 2026-09-04 | Tagged `[SIMULATED back-fill; not live]`. |

Real trades taken to date: **0**.

## 8. Next steps

- [ ] Fix macro ticker-to-column mapping in `data/market_data.py`
- [ ] Delete the affected parquet cache and rebuild
- [ ] Retrain with `nohup python3 main.py --mode evolve ...` (Section 5)
- [ ] Rebuild `weekly_risk_engine_v2.pkl`, or confirm the rule-based weekly gate is intended
- [ ] Resolve the sklearn 1.8.0 vs 1.9.0 mismatch (pin the version or retrain)
- [ ] Reconcile the simultaneous VIX cap: 22.0 printed vs 25.0 in CLAUDE.md
- [ ] Re-run the as-of replay for 2026-09-08 and compare with this memo
- [ ] Start forward-only logging at the next live signal window (11:00–13:00 IST). Log every SKIP as well as every entry.
- [ ] Checkpoint 1 (2026-09-29) has passed with 0 real trades. Checkpoint 2 (2026-10-29) cannot be a real pass/fail with 0 live trades. Re-define it as a data-collection review.
- [ ] Decide whether "3-day holds" in the journal still applies. A Tuesday entry to a Tuesday expiry is a 5-trading-day hold, which conflicts with the "max 3 trading days" rule. Not changed in this pass.
