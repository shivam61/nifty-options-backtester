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

