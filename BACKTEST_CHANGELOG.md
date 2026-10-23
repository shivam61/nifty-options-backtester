# Nifty Options Backtester — Baseline Backtest Changelog

**Current Status**: Rule-based entry/exit with LightGBM models (no ML ETL gate)  
**Latest Baseline**: Run #59 (2026-08-24)  
**CAGR**: 11.16% | **Sharpe**: 1.05 | **Max DD**: 6.9%

For complete historical context (Runs #3–#55), see [Archived Runs](docs/archive/ARCHIVED_RUNS.md).

---

## Run #56 — v8-50-50-split-tighter-monthly — [COMBINED]
**Date**: 2026-08-23 13:06  
**Git**: `636afd4`  
**Params**: 2009-01-01 to 2026-08-23 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.17% |
| Monthly P&L | ₹9,558 |
| Weekly P&L | ₹2,571,527 |
| Monthly Win Rate | 53.6% |
| Weekly Win Rate | 61.0% |
| Total P&L | ₹2,581,085 |
| Sharpe | 1.21 |
| Sortino | 2.43 |
| Calmar | 1.26 |
| Max Drawdown | 8.9% |
| Win Rate | 57.9% |
| Total Trades | 802 |
| Profit Factor | 2.89 |
| Best Trade | ₹132,274 |
| Worst Trade | ₹-41,186 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 343 |
| Weekly Trades | 459 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 25 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 47.8% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 27 | 5.9% | ₹-17,977 |
| Loss (-10k to 0) | 152 | 33.1% | ₹-2,870 |
| Small Win (0 to 10k) | 217 | 47.3% | ₹2,372 |
| Medium Win (10k to 25k) | 26 | 5.7% | ₹15,415 |
| Large Win (>= 25k) | 37 | 8.1% | ₹69,665 |
| Median | - | - | ₹442 |
| P10 / P90 | - | - | ₹-6,271 / ₹14,508 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2025-06-10 | weekly_ic | stop_loss | ₹132,274 |
| 2025-02-11 | weekly_ic | stop_loss | ₹124,406 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹119,524 |
| 2025-02-04 | weekly_ic | stop_loss | ₹113,177 |
| 2025-01-09 | weekly_ic | trailing_delta | ₹106,188 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-41,186 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-30,462 |
| 2021-01-27 | weekly_pcs | stop_loss | ₹-26,708 |
| 2022-08-30 | weekly_ic | stop_loss | ₹-25,364 |
| 2023-01-25 | weekly_ic | dte_limit | ₹-24,226 |


---
## Run #57 — exp1_75w_25m — [COMBINED]
**Date**: 2026-08-23 17:14  
**Git**: `ff96b3e`  
**Params**: 2009-01-01 to 2026-08-23 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 7.95% |
| Monthly P&L | ₹-31,275 |
| Weekly P&L | ₹1,392,204 |
| Monthly Win Rate | 43.0% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹1,360,929 |
| Sharpe | 0.90 |
| Sortino | 1.81 |
| Calmar | 1.14 |
| Max Drawdown | 6.9% |
| Win Rate | 54.9% |
| Total Trades | 295 |
| Profit Factor | 5.34 |
| Best Trade | ₹131,981 |
| Worst Trade | ₹-37,307 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 193 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 7 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 27.7% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 10 | 9.8% | ₹-16,621 |
| Loss (-10k to 0) | 13 | 12.7% | ₹-4,623 |
| Small Win (0 to 10k) | 56 | 54.9% | ₹3,844 |
| Medium Win (10k to 25k) | 8 | 7.8% | ₹15,917 |
| Large Win (>= 25k) | 15 | 14.7% | ₹85,059 |
| Median | - | - | ₹3,299 |
| P10 / P90 | - | - | ₹-9,706 / ₹57,687 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2025-06-10 | weekly_ic | stop_loss | ₹131,981 |
| 2025-02-11 | weekly_ic | stop_loss | ₹128,047 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹122,206 |
| 2025-02-04 | weekly_ic | stop_loss | ₹120,703 |
| 2025-01-09 | weekly_ic | trailing_delta | ₹107,336 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-37,307 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-22,721 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-19,188 |
| 2024-09-12 | weekly_ic | trailing_delta | ₹-15,822 |
| 2025-04-04 | weekly_pcs | stop_loss | ₹-15,183 |


---
## Run #58 — v9-etl-tuned-cached-models — [COMBINED]
**Date**: 2026-08-24 03:35  
**Git**: `b74f24c`  
**Params**: 2009-01-01 to 2026-08-24 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 6.22% |
| Monthly P&L | ₹-9,623 |
| Weekly P&L | ₹919,159 |
| Monthly Win Rate | 51.4% |
| Weekly Win Rate | 76.5% |
| Total P&L | ₹909,537 |
| Sharpe | 0.91 |
| Sortino | 1.72 |
| Calmar | 0.90 |
| Max Drawdown | 6.9% |
| Win Rate | 57.6% |
| Total Trades | 413 |
| Profit Factor | 3.36 |
| Best Trade | ₹91,844 |
| Worst Trade | ₹-37,307 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 311 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 11 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 42.6% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 6 | 5.9% | ₹-17,575 |
| Loss (-10k to 0) | 18 | 17.6% | ₹-4,613 |
| Small Win (0 to 10k) | 55 | 53.9% | ₹2,942 |
| Medium Win (10k to 25k) | 10 | 9.8% | ₹13,853 |
| Large Win (>= 25k) | 13 | 12.7% | ₹62,100 |
| Median | - | - | ₹2,399 |
| P10 / P90 | - | - | ₹-8,389 / ₹33,109 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-24 | weekly_ic | stop_loss | ₹91,844 |
| 2026-04-21 | weekly_ic | stop_loss | ₹89,299 |
| 2026-05-12 | weekly_ic | stop_loss | ₹89,134 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹87,236 |
| 2025-08-28 | weekly_ic | stop_loss | ₹76,953 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-37,307 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-22,721 |
| 2025-04-04 | weekly_pcs | stop_loss | ₹-12,668 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-11,588 |
| 2024-09-12 | weekly_ic | trailing_delta | ₹-10,611 |


---
## Run #59 — v10-no-etl-gate-ruledbased — [COMBINED]
**Date**: 2026-08-24 03:37  
**Git**: `b74f24c`  
**Params**: 2009-01-01 to 2026-08-24 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.16% |
| Monthly P&L | ₹27,999 |
| Weekly P&L | ₹2,546,922 |
| Monthly Win Rate | 53.3% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹2,574,922 |
| Sharpe | 1.05 |
| Sortino | 2.23 |
| Calmar | 1.62 |
| Max Drawdown | 6.9% |
| Win Rate | 59.2% |
| Total Trades | 417 |
| Profit Factor | 4.47 |
| Best Trade | ₹200,787 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 315 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 11 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 43.1% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 20 | 19.6% | ₹-24,141 |
| Loss (-10k to 0) | 3 | 2.9% | ₹-4,408 |
| Small Win (0 to 10k) | 29 | 28.4% | ₹5,839 |
| Medium Win (10k to 25k) | 25 | 24.5% | ₹12,308 |
| Large Win (>= 25k) | 25 | 24.5% | ₹102,638 |
| Median | - | - | ₹9,772 |
| P10 / P90 | - | - | ₹-19,430 / ₹110,320 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2026-04-21 | weekly_ic | stop_loss | ₹178,786 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-40,823 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2025-04-04 | weekly_pcs | stop_loss | ₹-25,241 |


---
## Run #60 — exp2_dynamic_vix_full — [COMBINED]
**Date**: 2026-08-29 13:48  
**Git**: `0b586b1`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.07% |
| Monthly P&L | ₹31,388 |
| Weekly P&L | ₹3,011,760 |
| Monthly Win Rate | 52.0% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹3,043,147 |
| Sharpe | 0.98 |
| Sortino | 1.57 |
| Calmar | 1.96 |
| Max Drawdown | 6.2% |
| Win Rate | 63.4% |
| Total Trades | 227 |
| Profit Factor | 5.76 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 125 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 13 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 18.7% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,642 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 24 | 23.5% | ₹6,383 |
| Medium Win (10k to 25k) | 27 | 26.5% | ₹11,299 |
| Large Win (>= 25k) | 28 | 27.5% | ₹110,602 |
| Median | - | - | ₹10,168 |
| P10 / P90 | - | - | ₹-21,996 / ₹141,841 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-40,823 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #61 — exp3_vix_5band — [COMBINED]
**Date**: 2026-08-29 14:07  
**Git**: `927b52b`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.99% |
| Monthly P&L | ₹28,717 |
| Weekly P&L | ₹2,969,871 |
| Monthly Win Rate | 49.3% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹2,998,589 |
| Sharpe | 0.99 |
| Sortino | 1.89 |
| Calmar | 1.89 |
| Max Drawdown | 6.3% |
| Win Rate | 58.5% |
| Total Trades | 313 |
| Profit Factor | 5.61 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 211 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 13 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 29.7% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,575 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 24 | 23.5% | ₹6,344 |
| Medium Win (10k to 25k) | 27 | 26.5% | ₹11,299 |
| Large Win (>= 25k) | 28 | 27.5% | ₹109,089 |
| Median | - | - | ₹10,168 |
| P10 / P90 | - | - | ₹-21,996 / ₹141,841 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-40,823 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #62 — last_week_sep5_update — [COMBINED]
**Date**: 2026-09-05 15:34  
**Git**: `a617ce1`  
**Params**: 2026-08-25 to 2026-09-05 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.98% |
| Monthly P&L | ₹34,368 |
| Weekly P&L | ₹2,971,537 |
| Monthly Win Rate | 52.8% |
| Weekly Win Rate | 75.7% |
| Total P&L | ₹3,005,906 |
| Sharpe | 0.98 |
| Sortino | 1.57 |
| Calmar | 1.95 |
| Max Drawdown | 6.1% |
| Win Rate | 63.2% |
| Total Trades | 228 |
| Profit Factor | 5.50 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 125 |
| Weekly Trades | 103 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 13 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 18.9% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 22 | 21.4% | ₹-25,690 |
| Loss (-10k to 0) | 3 | 2.9% | ₹-2,690 |
| Small Win (0 to 10k) | 24 | 23.3% | ₹6,383 |
| Medium Win (10k to 25k) | 26 | 25.2% | ₹11,336 |
| Large Win (>= 25k) | 28 | 27.2% | ₹110,602 |
| Median | - | - | ₹10,062 |
| P10 / P90 | - | - | ₹-23,793 / ₹141,454 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-40,823 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #63 — pre_fix_repro_run60 — [COMBINED]
**Date**: 2026-10-13 18:03  
**Git**: `4bbf488`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.07% |
| Monthly P&L | ₹31,388 |
| Weekly P&L | ₹3,007,944 |
| Monthly Win Rate | 52.0% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹3,039,332 |
| Sharpe | 0.98 |
| Sortino | 1.57 |
| Calmar | 1.96 |
| Max Drawdown | 6.2% |
| Win Rate | 63.4% |
| Total Trades | 227 |
| Profit Factor | 5.76 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 125 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 13 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 18.7% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,642 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 25 | 24.5% | ₹6,389 |
| Medium Win (10k to 25k) | 26 | 25.5% | ₹11,336 |
| Large Win (>= 25k) | 28 | 27.5% | ₹110,602 |
| Median | - | - | ₹10,083 |
| P10 / P90 | - | - | ₹-21,996 / ₹141,841 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-40,823 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #64 — ctrl_B_old_pkls_repaired_cache — [COMBINED]
**Date**: 2026-10-18 05:21  
**Git**: `4ea9fb5`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.06% |
| Monthly P&L | ₹31,011 |
| Weekly P&L | ₹3,008,077 |
| Monthly Win Rate | 53.7% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹3,039,088 |
| Sharpe | 0.97 |
| Sortino | 1.54 |
| Calmar | 1.93 |
| Max Drawdown | 6.3% |
| Win Rate | 64.4% |
| Total Trades | 225 |
| Profit Factor | 5.78 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 123 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 19 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 18.2% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,858 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 24 | 23.5% | ₹6,418 |
| Medium Win (10k to 25k) | 27 | 26.5% | ₹11,299 |
| Large Win (>= 25k) | 28 | 27.5% | ₹110,602 |
| Median | - | - | ₹10,168 |
| P10 / P90 | - | - | ₹-21,996 / ₹141,841 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-45,348 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #65 — ctrl_B2_old_pkls_repaired_plus_features — [COMBINED]
**Date**: 2026-10-18 05:37  
**Git**: `78fddb0`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.06% |
| Monthly P&L | ₹31,011 |
| Weekly P&L | ₹3,008,077 |
| Monthly Win Rate | 53.7% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹3,039,088 |
| Sharpe | 0.97 |
| Sortino | 1.54 |
| Calmar | 1.93 |
| Max Drawdown | 6.3% |
| Win Rate | 64.4% |
| Total Trades | 225 |
| Profit Factor | 5.78 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 123 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 19 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 18.2% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,858 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 24 | 23.5% | ₹6,418 |
| Medium Win (10k to 25k) | 27 | 26.5% | ₹11,299 |
| Large Win (>= 25k) | 28 | 27.5% | ₹110,602 |
| Median | - | - | ₹10,168 |
| P10 / P90 | - | - | ₹-21,996 / ₹141,841 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-45,348 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #66 — ctrl_C_retrained_no_risk_engine — [COMBINED]
**Date**: 2026-10-18 08:57  
**Git**: `df8912b`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.98% |
| Monthly P&L | ₹0 |
| Weekly P&L | ₹2,995,460 |
| Monthly Win Rate | 0.0% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹2,995,460 |
| Sharpe | 0.97 |
| Sortino | 0.94 |
| Calmar | 1.93 |
| Max Drawdown | 6.2% |
| Win Rate | 77.5% |
| Total Trades | 102 |
| Profit Factor | 6.48 |
| Best Trade | ₹201,158 |
| Worst Trade | ₹-53,255 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 0 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 0 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 30.1% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 21 | 20.6% | ₹-25,791 |
| Loss (-10k to 0) | 2 | 2.0% | ₹-2,443 |
| Small Win (0 to 10k) | 24 | 23.5% | ₹6,418 |
| Medium Win (10k to 25k) | 27 | 26.5% | ₹11,348 |
| Large Win (>= 25k) | 28 | 27.5% | ₹110,054 |
| Median | - | - | ₹10,168 |
| P10 / P90 | - | - | ₹-21,996 / ₹138,311 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-04-21 | weekly_ic | stop_loss | ₹201,158 |
| 2026-05-12 | weekly_ic | stop_loss | ₹200,787 |
| 2026-06-02 | weekly_ic | stop_loss | ₹188,819 |
| 2025-11-06 | weekly_ic | trailing_delta | ₹174,662 |
| 2025-06-10 | weekly_ic | stop_loss | ₹165,023 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-53,255 |
| 2025-01-02 | weekly_ic | stop_loss | ₹-51,656 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-45,348 |
| 2026-02-13 | weekly_pcs | stop_loss | ₹-38,710 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-38,187 |


---
## Run #67 — ctrl_C_retrained — [COMBINED]
**Date**: 2026-10-18 08:57  
**Git**: `df8912b`  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 6.96% |
| Monthly P&L | ₹0 |
| Weekly P&L | ₹1,089,394 |
| Monthly Win Rate | 0.0% |
| Weekly Win Rate | 77.5% |
| Total P&L | ₹1,089,394 |
| Sharpe | 1.03 |
| Sortino | 1.01 |
| Calmar | 2.33 |
| Max Drawdown | 3.0% |
| Win Rate | 77.5% |
| Total Trades | 102 |
| Profit Factor | 7.90 |
| Best Trade | ₹90,480 |
| Worst Trade | ₹-21,359 |

### Engine Stats
| Stat | Count |
|------|------:|
| Monthly Trades | 0 |
| Weekly Trades | 102 |
| Cross-track DD Blocks | 0 |
| Weekly VIX Gate Blocks | 0 |
| Weekly Open Cap Blocks | 0 |
| Emergency Weekly Exits | 0 |
| Capital Utilization | 29.8% |

### Weekly Trade Distribution
| Bucket | Count | Share | Avg P&L |
|--------|------:|------:|--------:|
| Large Loss (< -10k) | 6 | 5.9% | ₹-14,326 |
| Loss (-10k to 0) | 17 | 16.7% | ₹-4,234 |
| Small Win (0 to 10k) | 56 | 54.9% | ₹3,287 |
| Medium Win (10k to 25k) | 6 | 5.9% | ₹13,909 |
| Large Win (>= 25k) | 17 | 16.7% | ₹57,634 |
| Median | - | - | ₹3,147 |
| P10 / P90 | - | - | ₹-6,309 / ₹44,431 |

### Weekly Top Winners
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2025-02-04 | weekly_ic | stop_loss | ₹90,480 |
| 2026-05-12 | weekly_ic | stop_loss | ₹89,134 |
| 2025-06-10 | weekly_ic | stop_loss | ₹82,417 |
| 2025-01-09 | weekly_ic | trailing_delta | ₹80,455 |
| 2026-06-02 | weekly_ic | stop_loss | ₹75,414 |

### Weekly Top Losers
| Exit Date | Strategy | Exit Reason | P&L |
|-----------|----------|-------------|----:|
| 2026-07-08 | weekly_pcs | stop_loss | ₹-21,359 |
| 2024-07-26 | weekly_ic | stop_loss | ₹-15,388 |
| 2026-04-24 | weekly_pcs | stop_loss | ₹-13,670 |
| 2024-09-12 | weekly_ic | trailing_delta | ₹-13,216 |
| 2026-01-08 | weekly_pcs | stop_loss | ₹-12,167 |


## 2026-10-19 — Correction: weekly exit repricing bug (all prior weekly results overstated)
`CombinedBacktestEngine._process_weekly_exit` re-selected the weekly strategy every day from the current `nifty_return_5d`, so an open Iron Condor could be repriced by `WeeklyPutCreditSpread.update_premiums` (all legs as puts). 305 open-trade-days mismatched in the 17-year run; 40 of 102 trades affected. Fix: exit uses the strategy the trade was entered with (`_weekly_strategy_for_trade`).
| Run (2009-01-01..2026-08-29, engine OFF, cache-only) | Trades | CAGR | MaxDD | Sharpe | PF | Weekly P&L |
|---|---|---|---|---|---|---|
| Pre-fix (Run C repro) | 102 | 11.98% | 6.2% | 0.97 | 6.48 | Rs2,995,460 |
| Post-fix | 94 | 0.35% | 15.6% | 0.10 | 1.11 | Rs30,806 |
| Post-fix + dte_check_at_signal | 42 | -0.84% | 15.0% | -0.48 | 0.33 | Rs-67,819 |
Pre-fix 11.98%, Run #60 12.07% and the 17.97% what-if are not valid performance figures. Source: whatif_work/exitfix (runA/runB/runC logs + JSON).


## 2026-10-21 — Correction: model-priced weekly results are not evidence of an edge
Black-Scholes pricing overstates weekly entry credit, including after 2019. Model median entry credit is 31 Rs/unit against a real NSE settle of 21.

**Repricing of the BS backtest (R1):** 179 priceable trades repriced at real NSE settle gave **-170 Rs/lot** (year-cluster CI -391..+60), against +349 Rs/lot under the model. Source: `~/whatif_work/realprice/repricing_summary.json`.

**Real-price chain engine (commit 9877dca):** `backtester/chain_engine.py` + `data/nse_fo_archive.py` price NIFTY option legs from the NSE F&O bhavcopy archive. Window 2019-02-11..2026-08-28, one lot, EOD settle marks, liquidity filter (a leg with 0 contracts and 0 OI is skipped).

| Slippage | Trades | Expectancy (Rs/lot) |
|---|---:|---:|
| 1.0x | 330 | -177 |
| 1.5x | 326 | -238 |
| 2.0x | 322 | -348 |

- Year-cluster 95% CI at 1.5x: [-475, -46].
- At 1.0x: IC -172, PCS -183.
- By year: 2024 +172, 2025 +267, 2022 -541, 2026 -945.
- Pre-registered verdict: **NOT SUPPORTED**. Outputs in `~/whatif_work/chain/out/`.
- Caveats: EOD marks only, no bid/ask. Intraday stops would be worse. No sizing or kill-switch is modelled.
- On expiry day the archive `settle` is the index settlement value, not an option price. The engine prices expiry-day marks at intrinsic.

**Expiry calendar (commit 97e6974):** there was no Monday-expiry era. NIFTY weekly and monthly expiries were Thursday through 2025-08-28 and Tuesday from 2025-09-02. Any statement of a Monday era is wrong.

**Status:** the earlier model-priced results (11.98% and 12.07% CAGR, the 17.97% what-if, the 6.05% era-aware run, Rs334/lot) are **not evidence of an edge**. The weekly track is not a validated candidate. Live paper logging is data collection only.

## 2026-10-21 — Pre-registered structural alternatives on the real-price engine (development window only)
Arms (default off; `scripts/run_chain_backtest.py --pcs-put-sd 1.2 | --no-breach-stop | --ic-hold-to-expiry`), development window 2019-02-11..2023-12-31, slippage 1.5x, per-lot expectancy (year-cluster CI, 5 clusters = weak):
| Run | n | Rs/lot | CI year |
|---|---:|---:|---|
| baseline | 201 | -325 | [-498, -175] |
| A: PCS short strike at 1.2 SD | 192 | -371 | [-479, -259] |
| B: no close-based strike-breach stop | 201 | -325 (identical; the breach stop is redundant with the credit stop) | |
| C: ICs held to expiry | 203 | -158 | [-220, -90] |
Pre-registered rule (beats baseline AND > 0 AND CI lower bound > 0): no arm passes; C narrows the loss only. The 2024+ holdout was NOT evaluated, by design (no arm passed). No parameter tuning was done.

## 2026-10-21 — Step 0 (dev window 2019-02-11..2023-12-31): cost decomposition and premium audit
Per-lot net expectancy of the baseline weekly IC/PCS on real EOD settle prices (CostModel: Rs20/order brokerage; slippage multiplier on the model's per-unit slippage):
| lots \ slippage | 0x | 0.5x | 0.75x | 1.0x | 1.5x |
|---|---:|---:|---:|---:|---:|
| 1 | -4 | -145 | -207 | -262 | -325 |
| 5 | +112 | -29 | -88 | -145 | -266 |
| 10 | +113 | -14 | -74 | -129 | -250 |
| 30 | +70 | -62 | -130 | -189 | -291 |
- Fees are small once lots scale (lots=30, 1.0x: gross +54, entry slippage -117, exit slippage -121, fees -6). Slippage assumptions dominate the verdict; real bid/ask is the missing input.
- Premium audit (weekly, n=250): mean implied move 1.644% vs realised 1.588%; implied > realised in 61.6% of weeks; ATM straddle gross +8.2 pts/unit (CI crosses zero); 0.9 SD strangle +5.4 pts/unit. By VIX: <13 -3.8, 13-16 +10.2, 16-20 +25.2, 20-25 +14.8, 25+ -57.7. Monthly (n=57): implied 3.19% vs realised 3.28%, no premium.
- Gate G0 (stop only if 30-lot <=1.0x clearly negative AND implied <= realised): implied > realised on the traded weekly cadence, so CONTINUE.
- Accounting notes: capital-protection stop is a fixed Rs20,000, so it binds at ~Rs667/lot at 30 lots (per-lot metric not lot-invariant); fees are charged on entry-credit notional only (immaterial); 1.0x here is harsher than the old engine's 0.75x entry scale.
- VRP tercile and VIX-bucket cuts are in-sample candidates for Step 1, not evidence. No 2024+ data was used.

## 2026-10-21 — Step 2 (dev window 2019-02-11..2023-12-31, lots=10): pre-registered families F1/F2
Per-lot net expectancy (Rs), lots=10:
| Family | 0x | 0.5x | 0.75x | 1.0x | 1.5x | break-even slippage |
|---|---:|---:|---:|---:|---:|---:|
| Baseline (capital stop scaled per lot) | +126 | -14 | -74 | -129 | -251 | 0.47x |
| F1 defined-risk hold to expiry (`--no-early-exits`) | +144 | +72 | +28 | -16 | -105 | 0.91x |
| F2 VIX floor 13 (`--min-vix 13`) | +241 | +81 | +15 | -45 | -181 | 0.81x |
- Pre-registered pass rule (beats baseline at 1.5x AND > 0 AND year-cluster CI lower bound > 0 AND >= 4/5 positive dev years): F1 FAILS (-105, CI [-300,+79], 2/5 years), F2 FAILS (-181, CI [-395,+36], 2/5 years). Holdout not evaluated.
- The capital-protection stop now scales with lots (`ChainConfig.capital_protection_per_lot`, default True; `--fixed-capital-protection` restores the old fixed Rs20,000). It is not what makes results lot-dependent; flat per-order brokerage is.
- Caveat for F1: cash-settled expiry has no exit order, but the engine still charges exit slippage and brokerage; a rough what-if without them gives about -7 per lot at 1.5x (approximation, not a pass). The settlement model should be corrected and decided before any holdout look.
- F2's 13 floor is in-sample (derived from the Step 0 audit); a pass could only be confirmed on the holdout.

## 2026-10-21 — Settlement and cost-model correction; Step 2 re-run (dev window, lots=10)
- Cash settlement at expiry now has no exit order (no exit slippage, no exit brokerage); STT on exercised ITM long legs at 0.125% of intrinsic; date-aware STT/exchange rates (`backtester/nse_option_rates.py`, `docs/COSTS_NSE_OPTIONS.md`, sources cited). Legacy behaviour is reproducible with `--legacy-settlement --legacy-costs` (byte-identical to the previous outputs, including the three full-period files).
- Per-lot net expectancy (Rs), dev window 2019-02-11..2023-12-31, lots=10, corrected model:
| slip | baseline | F1 hold to expiry | F2 VIX>=13 |
|---|---:|---:|---:|
| 0 | +123 | +149 | +238 |
| 0.5x | -17 | +106 | +78 |
| 0.75x | -76 | +78 | +13 |
| 1.0x | -133 | +49 | -50 |
| 1.5x | -253 | -10 | -183 |
- Break-even slippage multiplier: baseline ~0.44x, F1 ~1.42x, F2 ~0.80x. About 91% of F1's earlier shortfall was the settlement-model error.
- Pre-registered rule at 1.5x (beats baseline AND > 0 AND year-cluster CI lower bound > 0 AND >= 4/5 positive years): F1 FAILS (-10; year CI [-218, +189]; 3/5 years), F2 FAILS (-183; 2/5 years). Holdout not evaluated.
- Open: brokerage on expired/exercised contracts (Rs20/order) is not modelled; exchange/exercise-STT history for 2019-2022 and pre-2020-07 stamp duty are proxies.

## 2026-10-23 — Project 2 pre-registered; quote-log break-evens corrected
- `docs/plans/PROJECT2_STRUCTURE_PREREG.md` registered before any run: four hold-to-expiry arms (VIX floor 13, PCS-only, fixed wings 200 / 500), comparator F1, Holm family of 4, Gate 0 on measured real/model slippage. NOT RUN. Needs two engine options (`force_strategy`, `wing_width`) built with default-unchanged tests first.
- `scripts/evaluate_prereg_arms.py` applies the pass rule mechanically (dev window only unless `--allow-holdout`).
- `scripts/summarize_quote_log.py` break-even axis updated from 0.47 / 0.80 / 0.90 to 0.44 / 0.80 / 1.42 (corrected settlement and cost model). No backtest numbers changed.
