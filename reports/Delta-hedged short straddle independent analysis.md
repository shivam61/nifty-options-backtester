# Delta-hedged short straddle: independent analysis (model-based, development window)

Written 2026-10-25. Script: `scripts/dh_straddle_model_study.py` (reproduces every number below; about one minute).

## 1. The premise I could not verify
You described a short straddle with a daily futures delta hedge as the first structure to pass a pre-registered rule. I found no such result. The repo has no futures hedge in the chain engine, `BACKTEST_CHANGELOG.md` on both branches records no straddle pass, and `origin/main`'s `docs/preregistration_edge_search.md` and `docs/analysis/audit_legs_dev.md` (2026-10-24) say no candidate has passed. If the result exists, please send the file, branch or run output and I will check it against this. Everything below is built independently and does not rely on it.

## 2. What this analysis is, and is not
- **Model-based, not the NSE archive** (the archive is not in this environment). Black-Scholes at sigma = k x India VIX, one ATM straddle sold at each weekly cycle's fill close, hedged with futures (spot as the proxy) at every daily close, held to cash settlement at expiry.
- **Development window only**, 2019-02-11 to 2023-12-31. 255 weekly cycles (253 usable), last expiry 2023-12-28. No 2024+ dates are used.
- **Pre-set primary spec** (chosen before running): 10 lots, whole-lot hedges, slippage 1.0x of the repo model, futures half-spread 0.5 point, brokerage Rs20 per order + GST, sell-side STT, exchange fees. Everything else is a labelled sensitivity.
- **Calibration against your real-price audit.** k is set so the mean straddle premium equals the audit's mean implied move (1.644%). That gives k = 0.889, so weekly ATM implied vol is about 11% below India VIX. Check: my cycles give a mean realised move of 1.583% against the audit's 1.588%, and the unhedged straddle gross edge is +602 Rs/lot against the audit's +8.18 points per unit (about 532 Rs/lot). The cycle construction and the calibration agree with the real-price data.

## 3. Result at the primary spec (Rs per lot per week)
| | Hedged | Unhedged |
|---|---:|---:|
| Mean net | **+1,070** | +579 |
| Median / win rate | +1,989 / 64.4% | |
| Std dev | 6,824 | 13,412 |
| 5th percentile / worst week | -11,942 / -37,979 | worst -79,738 |
| Max cumulative drawdown | -109,870 | -160,952 |
| Year-cluster 95% CI | [353, 1,703] | [-280, 1,448] |
| 4-week block 95% CI | [-9, 1,986] | [-1,138, 2,083] |
| One-sided block p (mean <= 0) | 0.026 | |
| Positive years | 4/5 (2020 is -309) | 4/5 |
| Weekly Sharpe, annualised | 1.13 | |

By year (hedged): 2019 +1,506, 2020 -309, 2021 +1,313, 2022 +854, 2023 +2,052. Walk-forward split with no tuning: 2019-21 +811, 2022-23 +1,447.

Hedging halves the variance, halves the worst week and doubles the mean. Costs take about a quarter of the gross edge at mid (1,391 to 1,070).

## 4. Where it worked
- **Calm weeks where realised movement was below implied.** Win rate 64%, median +1,989. The edge is the audit's implied-over-realised gap (about 3.5% of premium) restated; it is not a new source of edge.
- **Cost structure.** ATM legs are the tightest in the chain and carry the largest premium, so the modelled round trip costs about 320 Rs/lot a week (slippage ~92, fees and hedging ~228) against ~1,390 gross. Iron condors and spreads lose most of their edge to costs on the real-price runs.
- **VIX buckets (hedged, n):** <13 +1,615 (52); 13-16 +1,978 (59); 16-20 -376 (69); 20-25 +3,157 (47); 25+ -2,010 (26, sd 12,792). Standard errors are 600 to 2,500, so these are noise. They also disagree with the audit's unhedged strangle, which was best at 16-20. No VIX filter is supported.

## 5. Where it did not
Worst weeks (net per lot): 2020-03-20 -37,979 (VIX 67; option leg +27,151, futures leg -64,925, a whipsaw); 2021-01-29 -21,000 (9.25% move); 2020-03-13 -20,695; 2020-03-06 -19,345; 2020-04-03 -19,132; 2021-04-09 -17,545 (only a 1.7% move, futures leg -17,094). A daily hedge does not remove gamma or jump risk. A hedge at the daily close is also not executable in a limit-move week.

## 6. How much of it is real: placebos
- Flipping the hedge sign gives a futures leg of exactly -697, the mirror of +697. That is expected for a position linear in the hedge, and it shows the hedge leg is a real directional contribution.
- Removing the sample's drift (0.056% per day) cuts the futures leg from +697 to +316, so about 55% of it was the 2019-2023 bull market. Net falls from 1,070 to 732. The futures leg's year-cluster CI is [-77, 1,452], so its remainder is not distinguishable from zero.
- Daily lag-1 autocorrelation is -0.039, so the gain is not short-term momentum.
- Honest read: roughly 600 Rs/lot of the option-leg edge, plus an uncertain amount from hedging.

## 7. Sensitivities (net Rs/lot, hedged)
| Change | Net | Year CI | Block CI |
|---|---:|---|---|
| Slippage 0x / 1.0x / 1.5x / 2.0x | 1,163 / 1,070 / 1,024 / 978 | lows 477 / 353 / 291 / 229 | lows +97 / -9 / -58 / -110 |
| Lots 1 / 3 / 10 / 30 | 605 / 976 / 1,070 / 1,077 | 1 lot: [-220, 1,471] | |
| Futures half-spread 0 / 0.25 / 0.5 / 1 / 2 pts | 1,126 / 1,098 / 1,070 / 1,014 / 902 | | |
| Hedge vol -10% / +10% | 1,106 / 1,146 | | |
| k (implied/VIX) 0.90 / 0.95 / 1.00 / 1.05 / 1.10 | 1,249 / 2,147 / 3,042 / 3,848 / 4,696 | | |

The decisive sensitivity is k. Each +0.01 adds about 180 Rs/lot. Extrapolating, the edge is gone near k = 0.83, only about 7% below the calibrated 0.889. A single lot cannot be hedged properly because the futures lot equals the option lot; at least 3 lots are needed.

## 8. Against the repo's pass rule (model-based)
At 1.5x slippage: beats the unhedged straddle, expectancy +1,024, year-cluster CI lower bound +291, 4 of 5 positive years. On the year-cluster rule it passes at 1.0x, 1.5x and 2.0x. It fails the stricter 4-week block CI (lower bound -9 at 1.0x, -58 at 1.5x). That is a model result calibrated to one audit statistic whose own CI crosses zero, and it ran about 20 variants, so it is a lead, not a pass.

## 9. Limits
Black-Scholes at one flat vol; spot instead of futures (no basis, roll or margin cost); hedges at closing prices; no bid/ask beyond the repo slippage model; no margin or SPAN model (undefined risk needs large margin); settlement at the closing price; the k calibration rests on one audit number. Undefined-risk exposure conflicts with the system's defined-risk design and its kill-switch (worst week -38k per lot, so 10 lots lose -380k in one week).

## 10. How to leverage it, in order
1. **Pre-register an archive test (Project 3)** before running: unhedged ATM straddle held to expiry, the same hedged daily with NIFTY futures settle (needs futures data; the options archive does not have it), and a defined-risk iron-fly with wings. Same dev window, pass rule, Holm family, and the 2024+ holdout once. Needs a hedge option and a margin model in the chain engine.
2. **Check the key assumption cheaply.** On the archive, measure actual weekly ATM implied vol against India VIX. If the ratio is below about 0.83, the edge disappears.
3. **Measure real ATM spreads.** The quote logger already records `ATM_STRADDLE` rows; run it and read the ATM median multiplier.
4. **Size to the worst week**, not the mean: choose lots so the worst modelled week stays within a fixed fraction of capital. Prefer the iron-fly variant if the edge survives paying for wings.
5. **Do not** trade it live, use 0.889 as a fact, hedge a single lot, or add a VIX filter from section 4.

Verdict: a credible candidate with a real mechanism, but not established. It rests on the same unresolved implied-versus-realised gap the audit found, with a bull-market tailwind and fat tails.
