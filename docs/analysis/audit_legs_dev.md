# Per-leg payoff audit, weekly NIFTY options, development window (H1-H3)

Pre-registration: `docs/preregistration_edge_search.md`. Development window 2019-02-11..2023-12-31 only. Script: `scripts/audit_legs.py`. Raw outputs: `/tmp/audit_legs/` (`cycles_legs.csv`, `cuts.csv`, `report.json`, `tables.md`).

**Units.** All payoffs are in NIFTY index points per unit of option premium, gross of costs, with no slippage and no bid/ask. Rs per lot = points x 65.

## Method

**Cycles.** Reused unchanged from `scripts/audit_vrp.weekly_cycles`. Fill is the session after each listed weekly expiry E, with the signal on E's close. The target is the nearest listed expiry with calendar DTE in [3, 8] from the fill. In the dev window these are Thursday weeklies, so the hold is about 6 DTE, one week. Spot and VIX are the repo NIFTY and India VIX closes at the fill. 250 cycles, fills 2019-02-15..2023-12-22.

**Legs.** For each cycle and each SD distance in {0.5, 0.7, 0.9, 1.1, 1.3, 1.5, 2.0}, the audit prices one short OTM put and one short OTM call at the fill. Strikes follow the engine rule in `audit_vrp._sd_strikes` (period vol = VIX/100/sqrt(252) x sqrt(DTE), rounded to 50, then snapped to a listed strike with a usable price). Premium is the archive settle at the fill, and the payoff is held to the expiry settle:
- put payoff = premium - max(0, K - S_T)
- call payoff = premium - max(0, S_T - K)

**Cut families and counts.**
- H1: put and call at 7 SD levels (14 cuts) plus put-minus-call at 7 levels (7 cuts) = **21 tested**.
- H2: put, call and strangle (0.9 SD) by 5 VIX buckets = **15 tested**.
- H2 tail view: put, call and strangle with the worst 5% of weeks removed = **3 descriptive**, not tested (see Weaknesses).
- H3: 4 power rows. These are not tests and are not in the Holm family.

Total cuts examined in this report: **39** (36 tested, 3 descriptive). Earlier `audit_vrp` displays (weekly straddle overall, 0.9 SD strangle overall, straddle by VIX bucket, monthly cadences) were examined before this run and are **not** in this family. If they are added to a single audit-wide family, it grows by at least 7 weekly cuts, and the adjusted p-values in this report would be larger.

**Inference.** For every cut:
- the mean with a year-cluster bootstrap CI and a moving-block CI (4-week circular blocks, chronological);
- two-sided bootstrap p-values for mean = 0 from both schemes;
- Holm step-down over the 36 tested cuts, applied separately to the block p-values and the year-cluster p-values.

Bootstrap: 10,000 resamples, fixed seeds. Ratios (fraction of premium kept) use pooled sums with a year-cluster CI and carry no p-value.

**Fill and expiry convention.** The fill is the session after expiry E, with the target expiry at DTE 3-8. Strikes are at 0.5-2.0 SD of the fill-day VIX move over the cycle's DTE.

## H1. Where the premium sits (points per unit; Holm over 21 tested cuts)

| cut | n | mean pts/unit (Rs/lot) | CI year | CI 4-wk block | p block | p block Holm | p year Holm | years>0 |
|---|---:|---:|---|---|---:|---:|---:|---:|
| put 0.5 SD | 250 | 10.67 (694) | [1.56, 24.54] | [-8.44, 25.81] | 0.2256 | 1.0000 | 1.0000 | 4/5 |
| call 0.5 SD | 250 | -1.07 (-69) | [-13.31, 12.84] | [-13.82, 10.76] | 0.8585 | 1.0000 | 1.0000 | 2/5 |
| put 0.7 SD | 250 | 7.28 (473) | [-2.21, 19.31] | [-9.80, 20.23] | 0.3505 | 1.0000 | 1.0000 | 4/5 |
| call 0.7 SD | 250 | -0.54 (-35) | [-10.26, 10.38] | [-10.86, 8.63] | 0.9131 | 1.0000 | 1.0000 | 2/5 |
| put 0.9 SD | 249 | 5.14 (334) | [-5.74, 16.52] | [-10.76, 16.03] | 0.4650 | 1.0000 | 1.0000 | 4/5 |
| call 0.9 SD | 249 | 0.86 (56) | [-6.68, 8.73] | [-7.50, 7.75] | 0.8297 | 1.0000 | 1.0000 | 3/5 |
| put 1.1 SD | 249 | 4.21 (273) | [-6.26, 13.40] | [-9.48, 13.38] | 0.4952 | 1.0000 | 1.0000 | 4/5 |
| call 1.1 SD | 249 | 1.45 (94) | [-5.40, 6.90] | [-5.35, 6.51] | 0.6508 | 1.0000 | 1.0000 | 4/5 |
| put 1.3 SD | 249 | 3.01 (196) | [-6.19, 10.30] | [-8.38, 10.16] | 0.5533 | 1.0000 | 1.0000 | 4/5 |
| call 1.3 SD | 250 | 1.32 (86) | [-4.29, 5.15] | [-3.88, 4.85] | 0.5784 | 1.0000 | 1.0000 | 4/5 |
| put 1.5 SD | 248 | 5.53 (359) | [3.10, 8.15] | [2.03, 8.32] | 0.0013 | **0.0455** | 0.0000 | 5/5 |
| call 1.5 SD | 249 | 1.54 (100) | [-2.30, 4.11] | [-2.34, 3.83] | 0.4511 | 1.0000 | 1.0000 | 4/5 |
| put 2.0 SD | 244 | 3.24 (211) | [0.27, 5.48] | [-1.10, 5.81] | 0.0736 | 1.0000 | 0.5332 | 4/5 |
| call 2.0 SD | 245 | 1.49 (97) | [0.04, 2.46] | [-0.18, 2.46] | 0.0538 | 1.0000 | 0.5332 | 4/5 |
| put minus call 0.5 SD | 250 | 11.74 (763) | [-5.28, 36.29] | [-14.57, 34.97] | 0.3446 | 1.0000 | 1.0000 | 3/5 |
| put minus call 0.7 SD | 250 | 7.82 (508) | [-5.12, 27.92] | [-14.00, 26.80] | 0.4466 | 1.0000 | 1.0000 | 2/5 |
| put minus call 0.9 SD | 248 | 3.95 (257) | [-7.23, 21.36] | [-14.59, 18.98] | 0.6441 | 1.0000 | 1.0000 | 1/5 |
| put minus call 1.1 SD | 248 | 2.44 (159) | [-10.36, 17.99] | [-13.21, 14.72] | 0.7288 | 1.0000 | 1.0000 | 3/5 |
| put minus call 1.3 SD | 249 | 1.78 (116) | [-10.16, 14.65] | [-10.77, 11.22] | 0.7541 | 1.0000 | 1.0000 | 4/5 |
| put minus call 1.5 SD | 248 | 3.99 (259) | [-0.24, 10.71] | [-0.65, 9.18] | 0.1061 | 1.0000 | 1.0000 | 4/5 |
| put minus call 2.0 SD | 241 | 1.73 (112) | [-2.36, 5.18] | [-3.21, 5.25] | 0.4271 | 1.0000 | 1.0000 | 4/5 |

Premium collected and fraction kept (pooled payoff / pooled premium, year-cluster CI):

| SD | put premium (pts) | put kept | put kept CI | call premium (pts) | call kept | call kept CI |
|---|---:|---:|---|---:|---:|---|
| 0.5 | 48.00 | 0.222 | [0.028, 0.506] | 41.51 | -0.026 | [-0.331, 0.275] |
| 0.7 | 34.18 | 0.213 | [-0.065, 0.583] | 24.91 | -0.022 | [-0.413, 0.369] |
| 0.9 | 24.28 | 0.212 | [-0.220, 0.718] | 14.70 | 0.059 | [-0.482, 0.565] |
| 1.1 | 17.70 | 0.238 | [-0.288, 0.808] | 8.80 | 0.165 | [-0.638, 0.749] |
| 1.3 | 13.04 | 0.231 | [-0.374, 0.844] | 5.67 | 0.233 | [-0.782, 0.886] |
| 1.5 | 9.82 | 0.563 | [0.301, 0.900] | 3.90 | 0.395 | [-0.571, 0.987] |
| 2.0 | 5.86 | 0.553 | [0.036, 1.000] | 2.29 | 0.651 | [0.015, 1.000] |

**H1 reading.**
- The put side collects more premium than the call side at every SD level: 24.3 vs 14.7 pts at 0.9 SD, about 1.65x. This is the skew, and it is a premium fact, not a test.
- The put side's realised payoff is not distinguishable from the call side. Put-minus-call is positive at all 7 levels, but the smallest raw block p is 0.106 (1.5 SD) and every Holm-adjusted p is 1.0.
- Only one of the 21 H1 cuts survives Holm: **put 1.5 SD**, mean 5.53 pts/unit (359 Rs/lot), adjusted p 0.046. The adjacent levels do not agree (1.3 SD 3.01, 2.0 SD 3.24, both with adjusted p 1.0). The 1.5 SD put is not the engine strike, which is 0.9 SD (5.14, adjusted p 1.0).
- The year-cluster p-values of 0.0000 for put 1.5 SD come from a bootstrap over 5 clusters and should be treated as indicative only.

## H2. Premium by VIX bucket and tail view (0.9 SD; Holm over 15 tested cuts)

Buckets use the fill-session VIX, as in `audit_vrp`. This is a descriptive bucket and not a signal-day filter (see Weaknesses).

| cut | n | mean pts/unit (Rs/lot) | CI year | CI 4-wk block | p block Holm | years>0 |
|---|---:|---:|---|---|---:|---:|
| VIX <13 put | 51 | 0.85 (55) | [-9.54, 14.56] | [-15.35, 13.51] | 1.0000 | 2/4 |
| VIX <13 call | 51 | -4.65 (-302) | [-22.71, 7.48] | [-20.73, 8.00] | 1.0000 | 2/4 |
| VIX <13 strangle | 51 | -3.80 (-247) | [-10.20, -1.43] | [-22.31, 12.46] | 1.0000 | 1/4 |
| VIX 13-16 put | 58 | 8.35 (543) | [3.34, 15.71] | [0.65, 14.24] | 0.5856 | 4/5 |
| VIX 13-16 call | 58 | 1.88 (122) | [-7.41, 11.04] | [-8.11, 9.02] | 1.0000 | 4/5 |
| VIX 13-16 strangle | 58 | 10.23 (665) | [5.02, 19.53] | [-0.11, 19.23] | 1.0000 | 5/5 |
| VIX 16-20 put | 68 | 13.85 (900) | [8.05, 24.47] | [1.74, 22.37] | 0.4686 | 5/5 |
| VIX 16-20 call | 68 | 11.37 (739) | [8.59, 16.21] | [5.32, 16.10] | 0.0216 | 5/5 |
| VIX 16-20 strangle | 68 | 25.23 (1640) | [17.75, 40.30] | [9.70, 36.62] | 0.0544 | 5/5 |
| VIX 20-25 put | 46 | 6.01 (391) | [-8.18, 23.96] | [-20.13, 26.05] | 1.0000 | 2/4 |
| VIX 20-25 call | 47 | 9.18 (596) | [-1.00, 22.55] | [-0.33, 18.04] | 1.0000 | 3/4 |
| VIX 20-25 strangle | 46 | 14.76 (960) | [-2.80, 33.35] | [-10.72, 34.95] | 1.0000 | 3/4 |
| VIX 25+ put | 26 | -17.97 (-1168) | [-47.85, 69.79] | [-149.34, 56.29] | 1.0000 | 3/4 |
| VIX 25+ call | 25 | -34.49 (-2242) | [-163.27, 2.44] | [-94.17, 11.43] | 1.0000 | 2/4 |
| VIX 25+ strangle | 25 | -57.73 (-3752) | [-124.34, 61.19] | [-179.53, 37.02] | 1.0000 | 2/4 |

**Tail view (descriptive, 0.9 SD, pts/unit).** The worst 5% is k = 13 weeks.

| side | mean, all weeks | tail mean (worst 13) | tail contribution to mean | ex-tail mean (descriptive) | worst week (fill) |
|---|---:|---:|---:|---:|---|
| put | 5.14 | -310.95 | -16.23 | 22.55 | 2020-03-06 |
| call | 0.86 | -208.17 | -10.87 | 12.38 | 2021-01-29 |
| strangle | 5.45 | -398.47 | -20.89 | 27.79 | 2020-03-06 |

The positive means are carried by the other 236 weeks. The worst 13 weeks contribute -16 pts/unit to the put mean and -21 to the strangle mean. The worst put week is 2020-03-06 (a COVID-period expiry move of about -13%), and the worst call week is 2021-01-29. The ex-tail CIs are not inference: removing the worst weeks in-sample makes a positive mean true by construction.

**H2 reading.**
- Premium is positive in VIX 13-25 and peaks in 16-20. The strangle means are 10.2 (13-16), 25.2 (16-20) and 14.8 (20-25). The 13-16 and 16-20 strangle means are positive in 5 of 5 years.
- The 16-20 bucket is the strongest raw result: call p = 0.0006 raw and Holm 0.022; strangle raw p = 0.0016 and Holm 0.054, which is not significant at 0.05 after correction.
- The VIX 25+ bucket is negative at -57.7 pts/unit for the strangle. It has only 25 weeks, and its CI spans zero widely.
- The VIX <13 strangle is -3.8, with a year-cluster CI of [-10.2, -1.4] but a block CI of [-22.3, 12.5]. Neither survives correction.

## H3. Power (not a test; 250 weekly observations)

Two-sided alpha 0.05, power 0.80. MDE = (z_{0.975} + z_{0.80}) x SE = 2.80 x SE. The block SE is the moving-block bootstrap SE of the mean. "Weeks for +8" is the count needed to detect +8 pts/unit, using the iid sd and, in the last column, scaled by the block design effect.

| series | n | mean | sd | sd (MAD, robust) | SE iid | MDE iid | SE block | MDE block | power at +8 (observed n) | weeks for +8 (iid) | weeks for +8 (block) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ATM straddle | 250 | 8.18 | 203.06 | 130.88 | 12.84 | 35.98 | 10.80 | 30.25 | 0.10 | 5057 | 3575 |
| short put 0.9 SD | 249 | 5.14 | 99.71 | 10.53 | 6.32 | 17.70 | 6.97 | 19.52 | 0.24 | 1220 | 1484 |
| short call 0.9 SD | 249 | 0.86 | 65.22 | 7.04 | 4.13 | 11.58 | 3.96 | 11.10 | 0.49 | 522 | 480 |
| strangle 0.9 SD | 248 | 5.45 | 115.45 | 16.61 | 7.33 | 20.54 | 7.33 | 20.52 | 0.19 | 1635 | 1633 |

**H3 reading.** At 250 weeks the audit cannot detect +8 pts/unit on any of the four series. The minimum detectable effect is 12-36 pts/unit (call 11.6, put 17.7, strangle 20.5, straddle 36.0 on the iid SE). Detecting +8 needs about 1,600 weeks for the 0.9 SD strangle and about 5,000 for the ATM straddle. The straddle variance is dominated by 2020 tails: the robust MAD scale is 131 against an sd of 203. The dev sample resolves only effects that are large relative to the tail dispersion.

## Weaknesses and guarantees

**Development-window guard.**
- The real archive is never passed to a loader. `scripts/audit_legs.py` builds `/tmp/audit_legs/dev_archive/daily/` as symlinks to the 1,205 daily files whose filename date is <= 2023-12-31, and points `NseFoArchive` at that view with `max_date=2023-12-31`. Files after the cut are never opened. A test (`test_dev_archive_view_never_opens_later_files`) checks this with a corrupt 2024 file.
- The archive parquet built from the view has dates 2019-02-11..2023-12-29. Maximum fill 2023-12-22, maximum expiry 2023-12-28.
- The script has no holdout flag. Any `--end` after 2023-12-31 raises before any data is opened.
- **Exception, not guaranteed:** `scripts/run_chain_backtest.load_market` reads the repo's cached full-history NIFTY and India VIX parquets, then clips to `--end`. The clip happens after the load, so 2024+ rows of those two series are read into memory. They are not used or printed. Avoiding this would need a change to the shared loader.
- **Repo-level issue, not touched:** `NseFoArchive.__init__` parses every daily file under `archive_dir` before applying `max_date`. The default path in `scripts/audit_vrp.py main()` and `scripts/run_chain_backtest.py` therefore loads 2024+ archive files. I did not run either on the real archive. The fix belongs in `data/nse_fo_archive.py`, which I did not change.

**Data.**
- 49 of 250 cycles (all 2019 expiries and 4 expiries in January 2020) have no archive index settle. The expiry settle there is the repo NIFTY close (`settle_src = close_fallback`). Results for 2019 are therefore on a different settle basis.
- Fills and premiums are end-of-day settle marks on the fill session. This is not the premium at an 11:00 entry, and there is no bid/ask. Gross payoffs are optimistic relative to a live fill.
- 19 leg-level skips (illiquid legs: no contracts and no OI, or no usable price). The cut `n` values show the effect, and the 2.0 SD put loses 6 weeks.

**Method.**
- The bucket uses fill-session VIX, the same as `audit_vrp`. The pre-registration says a live filter must use signal-day data only, so these buckets describe the premium regime and are not a tradable filter. A signal-day-VIX bucketing would be a new cut family.
- Year-cluster bootstrap with 5 clusters is coarse. Its p-values can be 0.0000 and are indicative only. The block results carry the inference.
- The Holm family treats adjacent SD levels as separate tests, which is conservative for their positive correlation.
- Tail cuts were moved out of the tested family: the ex-tail mean is positive by construction when computed in-sample.

## Reproduce

```
.venv/bin/python -m pytest tests/test_audit_legs.py tests/test_audit_vrp.py -q
.venv/bin/python -I scripts/audit_legs.py --out /tmp/audit_legs
```

Requires the repo market cache (`data/.cache`, linked from the main checkout) and `NSE_FO_ARCHIVE_DIR` (default `~/nse_fo_archive`). Runtime about 40 s. Writes `/tmp/audit_legs/{cycles_legs.csv, cuts.csv, report.json, tables.md}`.
