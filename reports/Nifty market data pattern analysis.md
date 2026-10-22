# Nifty Market Data Pattern Analysis — Exploratory Statistics for Options Selling

**Date:** 2026-10-22
**Scope:** Exploratory, read-only statistical analysis of this repo's own cached market data. No files under `data/`, `models/`, `strategies/`, `backtester/`, `config.py`, `main.py` or `tests/` were modified. Analysis scripts live in the agent's scratchpad; this file is the only output written into the repo.

---

## 0. Data availability — read this before the findings

**Real NSE F&O option-chain data (bid/ask, open interest, IV surface) is NOT available in this environment.**

- `echo $NSE_FO_ARCHIVE_DIR` → empty.
- The default fallback path `~/nse_fo_archive` does not exist on this machine.
- `data/nse_fo_archive.py` (the module that reads the licensed bhavcopy archive used by `backtester/chain_engine.py`) therefore has no archive to read here.

Everything below is an analysis of the **underlying index / VIX / macro daily OHLC data** already cached in `data/.cache/` (seeded from `data/.cache_seed/`, 2009-01-02 → 2026-10-12, 4,361 trading days) via `MarketDataFetcher.build_combined_dataset()` — the same engineered 100+-column dataset `models/trade_learner.py`'s `FeatureExtractor` consumes. This is a proxy for option behavior (via Black-Scholes / `iv_from_vix()`), not direct evidence from real option prices. Per `CLAUDE.md`'s own documented finding, the project's real-price chain-engine backtest (`backtester/chain_engine.py`, licensed NSE bhavcopy 2019–2026) already found weekly premium-selling **NOT SUPPORTED** on real settlement prices (expectancy −177 to −348 Rs/lot). Nothing below overturns that; it stays in the realm of "does the underlying/VIX data show a statistically real pattern," which is a necessary but not sufficient condition for a tradeable options edge.

**Environment setup performed (read-only w.r.t. the codebase):**
- `bash scripts/bootstrap_cache.sh` → copied the 16 ticker parquets + models from `data/.cache_seed/` into `data/.cache/`.
- `bash scripts/check_cache_health.sh` → **PASS on all 23 integrity/range checks**; the only failure was the expected, documented one: `last date fresh FAIL — last=2026-10-12 asof=2026-10-22 business_days_stale=8 (max 5)`. This is the known seed-staleness condition described in `CLAUDE.md`, not a data-quality problem; it was not addressed further since it's out of scope.
- No system Python environment with the required scientific stack existed (no `.venv`, no `scipy`/`scikit-learn`/`pyarrow`/`yfinance` installed). `pip install pyarrow scipy scikit-learn yfinance` was run to make `MarketDataFetcher.build_combined_dataset()` and basic statistical tests (`scipy.stats`) runnable; nothing in `requirements.txt` was changed, and `MARKET_DATA_CACHE_ONLY=1` was set so the loader never touched the network.
- Loaded via `MarketDataFetcher(date(2009,1,1), date(2026,10,12)).build_combined_dataset()` → 4,361 rows × 103 columns, integrity line: `15/15 guarded columns, no identical or default-filled series (0 default-filled)`.

---

## 1. Method, applied uniformly

- **Chronological train/test split**, not k-fold or shuffled (shuffling a time series leaks the future into the past). Train = first 70% of days (2009-01-02 → 2021-06-25, n=3,052). Test = last 30% (2021-06-28 → 2026-10-12, n=1,309).
- Any threshold used to bucket a continuous variable (VIX terciles, gap-size percentile, S&P move percentile) was **computed on train only** and applied unchanged to test — this is the actual out-of-sample check, not just "does train look good."
- Every pattern reports **both periods' point estimates, sample size (n), and a p-value** (Welch's t-test for group differences, one-way ANOVA across >2 groups, Pearson + Spearman correlation with Fisher-z 95% CI).
- **Multiple-comparisons correction:** 52 p-value-bearing tests were run. Bonferroni-corrected α = 0.05/52 ≈ **0.00096**. A result is only called "statistically significant after correction" if its p-value clears that bar; anything between 0.05 and 0.00096 is explicitly flagged as uncorrected/suggestive.
- **Overlapping-window caveat (applies to Patterns 3, 4, 5's forward-RV legs, and 6):** forward realized-vol targets (`fwd_rv_5d/10d/20d`) and multi-day return windows (`nifty_return_5d/20d`) are rolling sums/std over overlapping days. Consecutive rows are therefore not independent observations — the effective sample size for those specific tests is smaller than the raw row count by roughly a factor of the window length. This inflates t/F-statistics and understates true p-values. Patterns built on same-day or 1-day-lag quantities (day-of-week, expiry-day indicator, overnight gap → next-day return, month-of-year, cross-asset 1-day lag) do **not** have this problem — they're ordinary daily observations.
- **Vol-regime confound:** the test period (mostly 2021–2026) has structurally lower average VIX than the train period (mostly 2009–2021, which includes the GFC-aftermath and COVID crash) — see the month-by-month `mean_vix` columns in the raw results, train ≈ 18–23, test ≈ 13–18. Any *magnitude* comparison across the split (not within a single period) is therefore confounded by the broader secular vol decline, not only by the specific pattern tested. P-values computed *within* each period are not affected by this, but cross-period magnitude deltas should be read with that in mind.
- Raw script and full JSON output: `/tmp/claude-0/-home-user-nifty-options-backtester/c6f7863e-7032-510d-9e6e-998f8525a36b/scratchpad/analysis.py` and `.../scratchpad/results.json` (scratchpad only, not in the repo).

---

## 2. Findings

### Pattern 1 — Day-of-week effect in realized volatility
**Method:** One-way ANOVA of `|daily return|` across Mon–Fri, train and test separately; Friday-vs-Monday Welch t-test.
**Result:** Monday is the highest-vol day and Tuesday/Wednesday the lowest, in **both** periods:

| Day | Train mean \|ret\| | Test mean \|ret\| |
|---|---|---|
| Mon | 0.966% | 0.716% |
| Tue | 0.784% | 0.579% |
| Wed | 0.769% | 0.569% |
| Thu | 0.818% | 0.608% |
| Fri | 0.847% | 0.683% |

ANOVA: train F=4.64, p=0.00099 (just **misses** the Bonferroni bar of 0.00096); test F=3.28, p=0.011 (does not clear Bonferroni). Friday-vs-Monday alone: train p=0.048 (uncorrected-significant only), test p=0.53 (not significant).
**Sample size:** ~600–880 days per weekday per period.
**Verdict: SUGGESTIVE.** The *ranking* (Monday highest, Tue/Wed lowest) is consistent across two non-overlapping 8–16-year windows, which is reassuring, but the formal significance is borderline and does not survive strict multiple-testing correction in either period taken alone. Economically this is the textbook "weekend gap-risk accrues into Monday" effect (Monday's close-to-close return spans ~2.5 calendar days of news vs. 1 for other days), not something specific to NSE microstructure.
**Lookahead/overfitting risk:** Low — day-of-week is known before the trade, no leakage possible. Risk is in multiple-comparisons: this was 1 of 8 pattern families and ~15 of the 52 tests involve weekday groupings.

### Pattern 2 — Weekly-expiry-day proximity effect (vol compression/expansion near expiry)
**Method:** Welch t-tests of `|return|` on the expiry day itself vs. all other days, and the day after expiry vs. other days; ANOVA across `days_to_next_weekly_expiry` buckets (0–4), train/test.
**Result:**
- Expiry day vs. other days: **no difference** — train p=0.63, test p=0.69, full-sample p=0.49.
- Day after expiry vs. other days: p=0.076 (not significant).
- Days-to-expiry bucket ANOVA: train p=0.00086 (**barely clears** Bonferroni) but driven by an anomalous bucket (3 days out, 0.906% mean |ret| vs. ~0.71–0.76% for 0/1/2 days out) with no monotonic structure; test ANOVA p=0.027 does not clear Bonferroni, and the pattern is not the same shape as train (bucket "4 days out" has n=53 in the full sample — a rare case, not a reliable regime).
**Sample size:** 894 expiry days vs. 3,466 non-expiry days (full sample).
**Verdict: NOT SUPPORTED.** There is no reliable realized-vol signature on or around the weekly expiry day in the **underlying index's own daily returns**. This directly answers the prompt's question #1 for the "expiry day itself" sub-case: nothing detectable here. (This doesn't rule out expiry-day effects in the option chain itself — pinning, gamma, OI unwind — which this environment cannot test without the archived chain data.)

### Pattern 3 — India VIX vs. subsequent realized volatility (volatility risk premium)
**Method:** `vix − forward_realized_vol(5d / 20d)`, one-sample t-test vs. 0, both periods; VIX-regime bucketing (terciles from train) and its effect on the VRP; correlation of VIX level with the forward-RV target.
**Result:** VIX overstates subsequent realized vol, consistently, by a large and highly significant margin:

| Horizon | Train mean gap | Train t, p | Test mean gap | Test t, p |
|---|---|---|---|---|
| 5d | +4.65 pts | t=30.3, p≈1.3e-176 | +3.22 pts | t=20.1, p≈1.9e-78 |
| 20d | +3.62 pts | t=28.4, p≈3.7e-157 | +2.30 pts | t=21.0, p≈1.4e-84 |

VIX is above forward realized vol on **79–87% of days** in every period/bucket checked. VIX level also strongly rank-orders forward 20d realized vol (Pearson r=0.70 train, r=0.64 test, both p≈0; Spearman confirms, ~0.66–0.69). By VIX-regime tercile (cutoffs computed on train: 15.92 / 20.71), the premium is *larger* in the high-VIX tercile in train (low 1.91 / mid 2.88 / high 6.00) and the same ranking direction holds in test but much flatter and on a thin high-VIX bucket (low 2.11 / mid 2.45 / high 3.40, n=107).
**Sample size:** ~3,050 (train) / ~1,290–1,310 (test) per test; VIX-regime buckets ~870–1,040 each in train, 107–865 in test (test "high VIX" bucket is thin — note the caveat below).
**Overlapping-window caveat applies** (forward RV is a rolling 5/20-day statistic) — even conservatively derating the effective N by the full window length (÷5 or ÷20), the t-statistics (30, 28, 20, 21) remain far above any conventional significance threshold, so this finding survives that correction comfortably.
**Verdict: EXPLOITABLE, but already captured.** This is a real, large, out-of-sample-replicated volatility risk premium on the index/VIX series — it directly corroborates (not contradicts) the "central open question" framing in `BACKTEST_CHANGELOG.md`. However, `FeatureExtractor` already encodes exactly this via `vol_risk_premium` → `iv_minus_rv_premium`, plus `vrp_change_5d`/`vrp_negative` (crash_v2 group) and the whole `iv_rv_term_spread*` family (strategy_selection group). **No new feature is needed here.** The one nuance *not* currently distinguished is the VIX-regime-conditional size of the premium (bigger in high-VIX days, at least in-sample) — see §3 priority list.
**Why this doesn't contradict the chain-engine's NOT SUPPORTED verdict:** a real VRP in the underlying's realized-vol terms says nothing about whether it survives bid/ask spread, BS-vs-real-settle mispricing (documented: BS overstates weekly credit, model median 31 Rs/unit vs. real NSE settle 21 Rs/unit), and tail/gap risk on short premium. Those frictions are exactly what the chain engine measured and found erase the edge.

### Pattern 4 — Autocorrelation / mean-reversion vs. momentum in weekly & monthly returns
**Method:** Pearson/Spearman correlation of prior 5d/20d return with the *next* non-overlapping 5d/20d return; big-move-quintile (train-derived cutoffs) vs. mid-quintile comparison.
**Result:** Essentially zero and inconsistent in sign between periods.

| | Train r (Pearson) | Test r (Pearson) |
|---|---|---|
| Weekly (5d→5d) | +0.0085, p=0.64 | −0.0127, p=0.65 |
| Monthly (20d→20d) | −0.0114, p=0.53 | −0.0719, p=0.0098 |

Big-down-week vs. mid-week forward return: train diff +0.31pp (p=0.055, uncorrected-marginal only), test diff +0.09pp (p=0.57, not significant) — direction (mild reversion after big down weeks) is consistent but weak and does not replicate with significance out-of-sample.
**Verdict: NOT SUPPORTED.** No usable linear momentum or mean-reversion signal in weekly/monthly Nifty returns at the index level — correlations are near zero, flip sign between the two tested windows, and the one period/test pair that shows a p<0.01 result (monthly, test) is not supported in train and has the overlapping-window inflation problem working against it, not for it. This matches intuition: if the index itself had exploitable serial correlation at this horizon, it would show up robustly and it does not.

### Pattern 5 — Overnight gap predicting next-session volatility and intraday continuation
**Method:** Correlation of `|overnight_gap_pct|` with next-day `|return|` and with forward 5d realized vol; large-gap (train p90 cutoff = 0.814%) vs. rest Welch t-test; gap-direction continuation rate (sign of gap vs. sign of same-day close-to-open-to-close return) vs. 50% via binomial test.
**Result — all four legs replicate and strengthen out-of-sample:**

| Test | Train | Test |
|---|---|---|
| corr(\|gap\|, next-day \|ret\|) | r=0.150, p=9.3e-17 | r=0.217, p=1.9e-15 |
| corr(\|gap\|, fwd 5d RV) | r=0.225, p=3.0e-36 | r=0.261, p=1.1e-21 |
| Large gap (≥0.81%) vs. rest, next-day \|ret\| | 1.12% vs. 0.80%, t=4.30, **p=2.3e-5** | 0.98% vs. 0.60%, t=4.44, **p=1.9e-5** |
| Gap-direction continuation rate vs. 50% | 65.1%, n=3,035, **p=5.0e-63** | 68.8%, n=1,309, **p=4.0e-43** |

All four clear the Bonferroni bar (0.00096) comfortably in both periods, and three of the four effects are *stronger* in the test period, not weaker — the opposite of typical overfitting decay.
**Sample size:** full train/test row counts above; large-gap bucket ~306 (train) / 118 (test) events.
**Verdict: EXPLOITABLE.** A large overnight gap reliably predicts (a) elevated next-day realized move and (b) elevated 5-day forward realized vol, and the day's own gap tends to continue intraday (close-to-close) rather than mean-revert. `nifty_overnight_gap_pct` already exists as a raw feature the GBM sees, but **the nonlinear "big gap → vol-expansion regime" threshold effect is not explicitly engineered** — the model has to learn that nonlinearity itself from a single raw magnitude feature, which a tree-based GBM can do but a hard flag would make this an explicit, auditable rule.

### Pattern 6 — VIX-vs-its-own-SMA(10) ("term structure proxy") incremental value beyond spot VIX
**Method:** True out-of-sample residual test — fit `fwd_rv_10d ~ vix_level` on train only, apply that fitted line to test, then correlate the *test residuals* with `vix_vs_sma_ratio` (an existing feature, not something new).
**Result:** `vix_vs_sma_ratio` alone correlates with forward 10d RV (train r=0.256, test r=0.261, both significant), and critically, the **held-out test residual correlation is r=0.120, p=1.4e-5** — clears Bonferroni, meaning this feature adds real information beyond spot VIX even on data the "model" (here, a 1-variable OLS fit) never saw.
**Verdict: Confirms an existing feature; not a new pattern.** `vix_vs_sma_ratio` is already in `FeatureExtractor`'s `volatility` group. This result is useful as *validation* that the feature earns its place (don't drop it in any future feature-pruning pass), not as something to add.

### Pattern 7 — Cross-asset lead-lag: prior-session US move → next Nifty overnight gap
**Method:** Correlation of 1-day % change in S&P 500 / US VIX / crude / USD-INR with the **next** Nifty `overnight_gap_pct`; large-S&P-move (train p10/p90 cutoffs) vs. rest Welch t-test.
**Result:** Strong, and strengthens out-of-sample:

| Predictor (prior session) | Train r | Test r |
|---|---|---|
| S&P 500 1d % chg | +0.385, p≈3.0e-108 | +0.507, p≈1.6e-86 |
| US VIX 1d % chg | −0.364, p≈2.0e-96 | −0.435, p≈2.0e-61 |
| Crude 1d % chg | +0.191, p≈1.8e-26 | −0.074, p=0.0073 (sign flips, weak) |
| USD-INR 1d % chg | +0.030, p=0.097 (n.s.) | +0.015, p=0.58 (n.s.) |

Large S&P drop (≤ train p10 = −1.10%) → next Nifty gap mean −0.40% (train) / −0.48% (test) vs. ≈+0.10–0.13% for the rest, both legs **p<1e-15** in both periods. Large S&P rally shows the symmetric positive effect, also p<1e-15 both periods. Crude and USD-INR show no reliable relationship.
**Verdict: Statistically real but NOT exploitable for this system's actual decision point — flagged explicitly to avoid a false "new feature" recommendation.** The combined engine enters trades in the **11:00–13:00 IST window**, which is *after* the Nifty open and therefore after the overnight gap has already happened and is already fully observable as `overnight_gap_pct` (an existing feature). Predicting a gap from yesterday's S&P/VIX move is mechanically almost the same information the system already has in hand by the time it decides anything, just arriving a few hours earlier. There is no incremental entry-timing value in adding "yesterday's S&P return" as a feature for an 11am decision when the thing it predicts is already known by 9:15am. The one place this *could* still matter is a genuinely different decision point this system doesn't currently have: an **end-of-day / overnight-hold risk gate** — e.g., trimming or hedging an open position the evening before a known high-risk US session (FOMC, big S&P move already in progress after Indian close) rather than waiting for the Indian-market gap to realize the next morning. That's a distinct feature/use-case from what was asked to test here, so it's listed as a separate, lower-priority idea below rather than folded into this pattern's verdict.

### Pattern 8 — Month-of-year / fiscal calendar seasonality
**Method:** ANOVA of `|return|` across the 12 calendar months, train/test; specific pre-registered hypotheses for February (Union Budget month) and March (Indian fiscal year-end).
**Result:** Overall month ANOVA is significant and clears Bonferroni in **both** periods (train F=4.05, p=6.4e-6; test F=4.82, p=2.5e-7). The specific hypotheses:

| Hypothesis | Train | Test |
|---|---|---|
| Feb (Budget month) vs. rest | 0.86% vs. 0.83%, t=0.43, p=0.67 (n.s.) | 0.67% vs. 0.63%, t=0.62, p=0.53 (n.s.) |
| **March (fiscal year-end) vs. rest** | 1.10% vs. 0.81%, t=3.32, **p=0.0010** (borderline, just misses 0.00096) | 0.89% vs. 0.61%, t=4.13, **p=7.1e-5** (clears Bonferroni) |

March is the single highest-|return| month of all twelve in **both** the train and test month-by-month tables independently (not just in the pooled hypothesis test) — i.e. this isn't one lucky comparison out of 12, it's the same month ranking first twice on non-overlapping data.
**Verdict: SUGGESTIVE → EXPLOITABLE.** March fiscal-year-end elevated volatility is real, replicates out-of-sample, and clears strict multiple-testing correction in the more recent (test) half of the data. The February "Budget month" folk belief is **NOT SUPPORTED** at the month-aggregate level in this data (a sharper, single-day-around-Budget-date test might behave differently, but that's a different, narrower hypothesis than what was tested here and not something this analysis can resolve without hand-curating Budget dates).

---

## 3. Verdict summary

| # | Pattern | Verdict | OOS checked? | Clears Bonferroni (0.00096)? |
|---|---|---|---|---|
| 1 | Day-of-week (Monday high vol) | SUGGESTIVE | Yes, consistent ranking | No (train 0.00099, test 0.011) |
| 2 | Weekly-expiry-day proximity | NOT SUPPORTED | Yes | No |
| 3 | VIX overstates realized vol (VRP) | EXPLOITABLE (already captured) | Yes, strongly | Yes (by orders of magnitude) |
| 3b | VRP size varies by VIX regime | SUGGESTIVE only | Thin OOS bucket (n=107) | Not formally tested as single stat |
| 4 | Weekly/monthly return autocorrelation | NOT SUPPORTED | Yes | No |
| 5 | Large overnight gap → vol expansion + continuation | EXPLOITABLE | Yes, strengthens OOS | Yes, all 4 legs |
| 6 | VIX-vs-SMA incremental value | Confirms existing feature | Yes (true residual OOS test) | Yes |
| 7 | Prior-session US move → next Nifty gap | Real but not exploitable *for entry timing* (redundant with already-known gap by 11am) | Yes | Yes (but flagged as not decision-useful here) |
| 8a | Month seasonality (Feb Budget) | NOT SUPPORTED | Yes | No |
| 8b | Month seasonality (March FY-end) | SUGGESTIVE → EXPLOITABLE | Yes, same ranking twice | Test: yes; Train: borderline miss |

**Multiple-comparisons reminder:** 52 tests were run against a target α of 0.05; at that rate roughly 2–3 "p<0.05" results would be expected by chance alone even if nothing were real. The patterns called EXPLOITABLE above (3, 5, 8b) all clear the much stricter Bonferroni bar in at least one period and show consistent direction/ranking in the other — that's the standard this report held them to before using the word "exploitable."

---

## 4. Prioritized next steps

1. **Add an explicit "post-large-gap vol expansion" threshold flag (Pattern 5).** `FeatureExtractor`'s `crash_v2` group already includes `gap_magnitude_avg_5d` (a rolling 5-day average of `|overnight_gap_pct|`) and `intraday_dd_expanding_3d`, so the raw signal is partially there — but a rolling *average* smooths out exactly the nonlinear threshold effect this analysis found (the jump happens once a single day's gap crosses roughly the 90th percentile, ≈0.81% in train; it is not a smoothly increasing function of the 5-day average). Concretely: add one new feature to `crash_v2` (or a small new "feature group 9") such as `large_gap_flag_p90` — 1 if *today's* (or yesterday's, for a next-day-risk framing) `overnight_gap_abs` exceeds a trailing-window 90th-percentile threshold, 0 otherwise — plus optionally `gap_continuation_signed` (sign of gap × sign of same-day return) to capture the ~65–69% continuation-rate effect. This is the strongest, most directly actionable, already-OOS-validated new signal in this analysis. Test via `--mode ablation` after adding it, comparing to the current feature-set baseline (AUC 0.696).
2. **Test a March-specific (or "days until fiscal-year-end expiry") sizing dial (Pattern 8b).** Before touching `FeatureExtractor`, the cheaper first step is a rule in `CombinedBacktestEngine` / position sizer: reduce size or widen strikes for trades whose holding period overlaps the last two weeks of March. This is a calendar rule, not a feature the GBM needs to learn, so it belongs in the backtester/sizing layer, not the ML layer. Validate with a dedicated train/test split (e.g. hold out 2024-2026 March specifically) before enabling in production — one more out-of-sample check than performed here, since this report only split the whole sample once.
3. **Investigate the VIX-regime-conditional VRP size (Pattern 3b) properly before acting on it.** The in-sample (train) result that the VIX-overstatement gap is *largest* in high-VIX regimes is interesting (it would argue against derating size specifically because VIX is high, since the forecast-bias direction isn't getting worse) but the out-of-sample "high VIX" bucket here was thin (n=107) and much flatter than train. This is a hypothesis for a dedicated, better-powered study (e.g., pull in more recent high-VIX episodes specifically, or bootstrap CI on the regime-conditional means) — not yet something to wire into sizing.
4. **Do not act on Pattern 7 (cross-asset lead-lag) as an entry-timing feature** — it's statistically real but redundant with information the system already has by its 11am–1pm entry window. If there's appetite for a genuinely new use case, the correct framing is an **overnight-hold risk gate** evaluated at the *prior* day's close (not at entry) — e.g., "trim or avoid adding weekly exposure into a session where US markets just moved >1 std dev," which is a different decision point from anything in the current pipeline and would need its own design, not a `FeatureExtractor` addition.
5. **Pattern 1 (day-of-week) is worth a cheap, low-risk test but not a redesign.** Given it's borderline on strict correction, the lowest-risk next step is simply checking whether `RegimeAwareLearner`'s existing GBM already implicitly captures the Monday effect through correlated features (e.g. a Monday trade is more likely to have a stale multi-day-old VIX reading) before adding an explicit day-of-week dummy. If `--mode ablation` shows no change in AUC from the existing feature set already handling it, no action is needed.
6. **Patterns 2 and 4 (expiry-day vol signature, weekly/monthly autocorrelation) can be closed out as negative results** — no further feature work is warranted on the index-level data for either. (Pattern 2's "no signature in the index's own realized vol" doesn't rule out a signature in option *prices/OI* around expiry, which would require the NSE F&O archive this environment doesn't have.)
