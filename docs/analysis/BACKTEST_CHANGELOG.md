# Backtest Improvement Log

Structured log of every optimisation round: what changed, why, and the exact
before/after numbers so we can track trajectory and catch regressions.

---

## Decision Lock — Weekly Exit Redesign (2026-04-17)

Current default weekly logic is documented in
[WEEKLY_EXIT_REDESIGN_LOG.md](WEEKLY_EXIT_REDESIGN_LOG.md).

Summary:

- adopted redesigned weekly exits as default
- removed legacy weekly dynamic `profit_target` behavior from the combined path
- retired the old weekly max-profit experiment files

Full-range combined impact (`2009-01-01` → `2026-04-17`):

| Metric | Legacy Combined | Current Default | Delta |
|--------|----------------:|----------------:|------:|
| Total P&L | ₹4,421,439 | ₹4,672,871 | +₹251,432 |
| CAGR | 14.56% | 14.90% | +0.34pp |
| Max DD | 11.1% | 10.8% | -0.3pp |
| Sharpe | 1.73 | 1.78 | +0.05 |
| Weekly P&L | ₹2,641,540 | ₹2,892,780 | +₹251,240 |

Do not reopen the deleted weekly `80% max profit booking` path without a new
hypothesis and fresh validation criteria.

---

## Run #1 — Baseline with Multi-Expiry (pre-fix)

**Date**: 2026-04-08
**Command**: `python main.py --use-multi-expiry`
**Period**: 2009-01-01 → 2026-04-08 (17.3 years) | Capital: ₹500,000

### Result

| Metric              | Value       |
|---------------------|-------------|
| Total P&L           | ₹62,210     |
| Total Return        | 12.44%      |
| CAGR                | 0.68%       |
| Win Rate            | 43.4%       |
| Trades              | 327         |
| Avg Return/Trade    | -0.49%      |
| Expectancy          | ₹190/trade  |
| Profit Factor       | 1.01        |
| Max Drawdown        | 71.9%       |
| Sharpe              | 5.01        |
| Calmar              | 0.01        |
| Avg Holding Days    | 9.8         |

### Strategy Breakdown

| Strategy                    | Trades | Win% | Total P&L     | Avg P&L  | Sharpe |
|-----------------------------|--------|------|---------------|----------|--------|
| calendar_spread             | 59     | 81%  | +₹957,956     | +₹16,237 | 2.04   |
| put_credit_spread           | 57     | 79%  | +₹641,607     | +₹11,256 | 2.86   |
| bear_call_spread            | 27     | 48%  | +₹53,606      | +₹1,985  | 0.17   |
| diagonal_spread             | 48     | 31%  | -₹212,484     | -₹4,427  | -2.56  |
| **variable_ratio_iron_fly** | **136**| **15%** | **-₹1,378,476** | **-₹10,136** | **-0.61** |

### Diagnosis

1. `variable_ratio_iron_fly` consumed 42% of all trades at 15% WR, losing ₹1.38M
2. `diagonal_spread` at 31% WR losing ₹212K
3. Winners (calendar+put_credit+bear_call = +₹1.65M) wiped out by losers (-₹1.59M)
4. ExpirySelector bypassed `_select_strategy` rule logic, using pure EV heuristic
5. EV heuristic favoured high-credit ATM strategies (iron fly) — wrong scoring
6. Sub-strategy `should_enter()` never called after `force_strategy_selection`
7. ML entry model only binary go/no-go; no per-strategy discrimination

---

## Run #2 — Fix: Remove iron fly, restrict diagonal, fix engine flow

**Date**: 2026-04-08
**Commit scope**: `engine.py`, `multi_strategy.py`, `expiry_selector.py`

### Changes Made

#### `backtester/engine.py` — Multi-expiry architecture fix
- **Before**: ExpirySelector evaluated ALL eligible strategies × expiries and picked
  the highest-scoring combo via `force_strategy_selection`, bypassing rule-based
  `_select_strategy` and the sub-strategy's `should_enter()` gate.
- **After**: `_select_strategy` (proven rule-based picker) chooses the strategy first.
  ExpirySelector only optimises which expiry to use for that strategy. Sub-strategy's
  `should_enter()` is called as final confirmation gate.
- **Also**: Trade creation block guarded by `should_enter_trade` flag to prevent
  creating trades when strategy/substrategy vetoes.

#### `strategies/multi_strategy.py` — Strategy eligibility cleanup
- **Removed from all eligible lists and `_select_strategy`**:
  - `variable_ratio_iron_fly` — 15% WR, -₹1.38M. ATM straddle = max gamma risk.
    BS model overestimates its win probability; real-world gap risk destroys it.
  - `diagonal_spread` — 11% WR (in intermediate run), -₹1.85M. BS model cannot
    price term structure (near vs far expiry IV), skew dynamics, or roll slippage.
- **Updated VIX zone mapping**:
  - VIX < 12: `[calendar_spread]` only
  - VIX 12-15: `[calendar_spread, put_credit_spread, bear_call_spread]`
  - VIX 15-18: `[put_credit_spread, calendar_spread, bear_call_spread]`
  - VIX 18-22: `[put_credit_spread, broken_wing_butterfly, bear_call_spread]`
  - VIX 22-30: `[ratio_put_spread, broken_wing_butterfly, put_credit_spread]`
  - VIX 30+: `[ratio_put_spread, put_credit_spread]`
- **`_select_strategy` updated**: Calendar spread preferred in VIX 12-15 (replaces
  diagonal). Iron fly removed from VIX 15-22 selection paths.

#### `strategies/expiry_selector.py` — Performance-aware scoring
- **Added `STRATEGY_WIN_RATE_PRIORS`**: Historical win rates per strategy used to
  anchor the scoring (60% historical WR + 40% theoretical estimate).
- **Blended EV calculation**: `EV = credit × blended_WP - max_loss × (1 - blended_WP)`
  instead of relying purely on theoretical `_estimate_win_prob`.
- **ATM strike distance penalty**: -0.3 penalty when short strikes are < 2% OTM,
  discouraging ATM-heavy strategies that have higher gamma/gap risk.
- **Reasoning enriched**: Candidates that have historically strong WR (≥70%) get
  explicit reasoning note.

### Result

| Metric              | Before (Run #1) | After (Run #2) | Delta        |
|---------------------|-----------------|----------------|--------------|
| Total P&L           | ₹62,210         | **₹11,881,153**| +₹11,818,943 |
| Total Return        | 12.44%          | **2,376.23%**  | +2,363.8pp   |
| CAGR                | 0.68%           | **20.43%**     | +19.75pp     |
| Win Rate            | 43.4%           | **64.5%**      | +21.1pp      |
| Trades              | 327             | 220            | -107         |
| Expectancy          | ₹190/trade      | **₹54,005**    | +₹53,815     |
| Profit Factor       | 1.01            | **3.32**       | +2.31        |
| Max Drawdown        | 71.9%           | **14.5%**      | -57.4pp      |
| Sharpe              | 5.01            | 3.66           | -1.35        |
| Calmar              | 0.01            | **1.41**       | +1.40        |
| Avg Holding Days    | 9.8             | 12.9           | +3.1         |

### Strategy Breakdown (After)

| Strategy                 | Trades | Win% | Total P&L      | Avg P&L   | Sharpe |
|--------------------------|--------|------|----------------|-----------|--------|
| calendar_spread          | 69     | 81%  | +₹7,858,030    | +₹113,884 | 1.96   |
| broken_wing_butterfly    | 31     | 39%  | +₹2,667,692    | +₹86,055  | 1.08   |
| put_credit_spread        | 108    | 61%  | +₹1,162,843    | +₹10,767  | 0.50   |
| ratio_put_spread         | 12     | 67%  | +₹192,588      | +₹16,049  | 1.40   |

**All four active strategies are profitable. No losers in the mix.**

### Yearly Performance (After)

| Year | Trades | Win% | P&L          |
|------|--------|------|--------------|
| 2009 | 12     | 83%  | +₹377,700    |
| 2010 | 14     | 50%  | -₹67,151     |
| 2011 | 9      | 33%  | -₹163,888    |
| 2012 | 14     | 57%  | +₹76,820     |
| 2013 | 14     | 50%  | +₹165,242    |
| 2014 | 13     | 85%  | +₹328,312    |
| 2015 | 15     | 40%  | +₹127,069    |
| 2016 | 13     | 62%  | +₹125,895    |
| 2017 | 12     | 92%  | +₹405,588    |
| 2018 | 6      | 50%  | +₹24,686     |
| 2019 | 19     | 58%  | +₹223,200    |
| 2020 | 10     | 60%  | +₹456,838    |
| 2021 | 13     | 54%  | -₹281,228    |
| 2022 | 13     | 69%  | +₹901,980    |
| 2023 | 11     | 73%  | +₹707,689    |
| 2024 | 16     | 81%  | +₹2,687,349  |
| 2025 | 13     | 85%  | +₹4,474,523  |
| 2026 | 3      | 100% | +₹1,310,530  |

### Key Learnings

- **Strategy selection > strategy diversity.** Fewer strategies with proven WR (>40%)
  beats having many strategies where bad ones destroy alpha.
- **Rule-based strategy picking outperforms heuristic EV scoring** because the EV
  heuristic favoured high-credit (= high-risk) strategies like ATM straddles.
- **Sub-strategy `should_enter()` is critical.** Bypassing it created trades in
  conditions the strategy itself would have rejected.
- **BS model limitations**: Cannot accurately price (a) ATM gamma risk for iron fly,
  (b) term structure for diagonal spreads. Strategies that depend on these should not
  be in systematic backtests until the pricing model is upgraded.
- **Compounding amplifies mistakes.** With 71.9% max DD, the compounding engine
  was betting large on losers. After fix, 14.5% max DD keeps compounding healthy.

### Files Modified

| File | Lines Changed | Nature |
|------|--------------|--------|
| `backtester/engine.py` | ~40 | Architecture: multi-expiry flow restructured |
| `strategies/multi_strategy.py` | ~50 | Strategy eligibility + selection rules |
| `strategies/expiry_selector.py` | ~40 | Performance priors, blended scoring |
| `tests/test_multi_expiry.py` | ~10 | Test expectations updated for new eligibility |

---

## Intermediate Run — Iron fly removed, diagonal still active

**Date**: 2026-04-08 (between Run #1 and Run #2)

This intermediate run confirmed diagonal_spread was equally toxic:

| Metric    | Baseline | Iron fly removed | Final (both removed) |
|-----------|----------|------------------|----------------------|
| CAGR      | 0.68%    | -2.40%           | **20.43%**           |
| Win Rate  | 43.4%    | 41.1%            | **64.5%**            |
| Max DD    | 71.9%    | 79.9%            | **14.5%**            |

Diagonal spread went from 48 trades/31% WR (when iron fly was present and absorbing
VIX 15-22 trades) to **118 trades/11% WR** once iron fly was removed — it expanded
to fill the vacuum and performed even worse. This confirmed the BS term-structure
pricing limitation.

---

## Pending Investigations / Future Runs

- [ ] **Retrain ML model on actual strategy outcomes** — current model trained on
      simple credit spread simulations, not the multi-leg strategies actually traded
- [ ] **Add term-structure model** — enable diagonal/calendar cross-expiry pricing
      with proper near/far IV differentiation
- [ ] **Walk-forward strategy selection** — instead of fixed eligible lists, use
      rolling 2-year performance to dynamically weight strategies
- [ ] **Drawdown-based position sizing** — reduce lots after consecutive losses
      instead of pure equity-based compounding
- [ ] **Bear call spread analysis** — not selected in Run #2 (0 trades). Investigate
      if `_select_strategy` conditions are too restrictive for it
- [ ] **Out-of-sample validation** — current 17y backtest includes training period.
      Run pure OOS test on 2019-2026 test window only

---

## Run #3 — bear_call removed + 12 strategy features

**Date**: 2026-04-08
**Label**: `bear_call removed + 12 strategy features`
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15 | Multi-expiry: True

### Changes from Run #2

1. **Dropped `bear_call_spread`** from all VIX-zone eligible lists and `_select_strategy`
   (produced 0 trades in Run #2 — dead code).
2. **Added 12 strategy-aware ML features** to `FeatureExtractor` and `MarketDataFetcher`:
   - IV term structure: `iv_rv_term_spread`, `iv_rv_term_spread_5d_chg`, `iv_rv_term_spread_z`
   - IV skew: `iv_skew_proxy`, `iv_skew_proxy_z`
   - Theta/Vega: `theta_quality`, `vega_regime`, `vega_regime_5d_chg`
   - Market context: `institutional_hedge_proxy`, `nifty_distance_from_sma20_pct`,
     `vix_volatility_10d`, `regime_stability_10d`
3. **Updated `STRATEGY_WIN_RATE_PRIORS`** in `expiry_selector.py` to reflect active
   strategies only (calendar, PCS, BWB, put_credit_wide).

### Key Metrics

| Metric | Run #2 | Run #3 | Delta |
|--------|-------:|-------:|------:|
| CAGR | 20.43% | **21.38%** | +0.95pp |
| Total P&L | ₹11,881,153 | **₹13,673,020** | +₹1,791,867 (+15%) |
| Total Return | 2,376.2% | **2,734.6%** | +358pp |
| Win Rate | 64.5% | 64.6% | +0.1pp |
| Trades | 220 | 240 | +20 |
| Expectancy | ₹54,005 | **₹56,971** | +₹2,966/trade |
| Sharpe | 3.66 | **3.69** | +0.03 |
| Sortino | — | **4.57** | (new) |
| Max Drawdown | 14.5% | 17.1% | +2.6pp (worse) |
| Calmar | 1.41 | 1.25 | -0.16 (worse) |
| Profit Factor | 3.32 | 2.81 | -0.51 (worse) |

### Strategy Breakdown

| Strategy | Trades (R2→R3) | Win% | P&L (R2→R3) | Avg P&L (R2→R3) |
|----------|:--------------:|-----:|:-----------:|:---------------:|
| calendar_spread | 69→62 | 81%→85.5% | ₹7,858K→₹7,980K (+₹122K) | ₹113K→₹129K |
| broken_wing_butterfly | 31→31 | 39%→38.7% | ₹2,668K→**₹3,516K** (+₹848K) | ₹86K→**₹113K** |
| put_credit_spread | 108→135 | 61%→60.7% | ₹1,163K→**₹1,946K** (+₹783K) | ₹10.8K→₹14.4K |
| ratio_put_spread | 12→12 | 67%→66.7% | ₹193K→₹231K (+₹38K) | ₹16K→₹19.3K |

### Engine Stats

| Stat | Count |
|------|------:|
| ML Entries | 1,012 |
| ML Skips | 1,185 |
| Circuit Breaker Blocks | 108 |
| Smart Exits | 140 |
| Rule Exits | 100 |
| Multi-expiry Selections | 793 |

### New Feature Importance (CRASH regime)

The 12 new features are already contributing to regime models:
- `regime_stability_10d` — 6.2% importance in CRASH regime (3rd most important)
- `vix_volatility_10d` — 5.4% importance in CRASH regime (5th most important)

### Key Learnings

- **All four strategies improved** their absolute P&L. No strategy lost money.
- **Broken wing butterfly** gained ₹848K (+32%) on the same trade count — the new
  features helped the ML model time entries better for this asymmetric payoff strategy.
- **PCS took 27 more trades** and earned ₹783K more — new features gave the model
  confidence to enter trades it previously skipped.
- **Max DD increased 14.5%→17.1%** because more PCS trades created wider loss streaks.
  Still below the 20% acceptable threshold.
- **Profit factor declined 3.32→2.81** — ratio metric diluted by more trades, but
  absolute profit grew 15%.

### Files Modified

| File | Lines Changed | Nature |
|------|--------------|--------|
| `strategies/multi_strategy.py` | ~20 | Removed bear_call from eligible lists |
| `strategies/expiry_selector.py` | ~10 | Updated STRATEGY_WIN_RATE_PRIORS |
| `data/market_data.py` | ~50 | 12 new strategy-aware features |
| `models/trade_learner.py` | ~40 | FeatureExtractor strategy_selection group |

---

## Cumulative Trajectory

| Metric | Run #1 (baseline) | Run #2 (fix) | Run #3 (features) |
|--------|------------------:|-------------:|------------------:|
| CAGR | 0.68% | 20.43% | **21.38%** |
| Total P&L | ₹62K | ₹11.88M | **₹13.67M** |
| Win Rate | 43.4% | 64.5% | **64.6%** |
| Max DD | 71.9% | 14.5% | 17.1% |
| Sharpe | 5.01 | 3.66 | **3.69** |
| Trades | 327 | 220 | 240 |

---

## Pending Investigations / Future Runs

- [ ] **Retrain ML model on actual strategy outcomes** — current model trained on
      simple credit spread simulations, not the multi-leg strategies actually traded
- [ ] **Add term-structure model** — enable diagonal/calendar cross-expiry pricing
      with proper near/far IV differentiation
- [ ] **Walk-forward strategy selection** — instead of fixed eligible lists, use
      rolling 2-year performance to dynamically weight strategies
- [ ] **Drawdown-based position sizing** — reduce lots after consecutive losses
      instead of pure equity-based compounding
- [x] ~~**Bear call spread analysis**~~ — removed in Run #3 (0 trades, dead code)
- [ ] **Out-of-sample validation** — current 17y backtest includes training period.
      Run pure OOS test on 2019-2026 test window only

---
## Run #4
**Date**: 2026-04-08 20:46  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 21.38% |
| Total Return | 2734.6% |
| Total P&L | ₹13,673,020 |
| Sharpe | 3.69 |
| Sortino | 4.57 |
| Calmar | 1.25 |
| Max Drawdown | 17.1% |
| Win Rate | 64.6% |
| Total Trades | 240 |
| Profit Factor | 2.81 |
| Avg P&L/Trade | ₹56,971 |
| Best Trade | ₹1,396,315 |
| Worst Trade | ₹-683,020 |
| Max Consec Wins | 14 |
| Max Consec Losses | 10 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1012 |
| ML Skips | 1185 |
| Circuit Breaker Blocks | 108 |
| Smart Exits | 140 |
| Rule Exits | 100 |
| Multi-expiry Selections | 793 |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 135 | 60.7% | ₹1,946,304 | ₹14,417 |
| adaptive:calendar_spread | 62 | 85.5% | ₹7,979,681 | ₹128,705 |
| adaptive:broken_wing_butterfly | 31 | 38.7% | ₹3,515,881 | ₹113,416 |
| adaptive:ratio_put_spread | 12 | 66.7% | ₹231,154 | ₹19,263 |


---
## Run #5
**Date**: 2026-04-08 21:16  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 7.19% |
| Total Return | 231.7% |
| Total P&L | ₹1,158,442 |
| Sharpe | 4.38 |
| Sortino | 3.96 |
| Calmar | 1.05 |
| Max Drawdown | 6.9% |
| Win Rate | 69.3% |
| Total Trades | 228 |
| Profit Factor | 3.20 |
| Avg P&L/Trade | ₹5,081 |
| Best Trade | ₹39,125 |
| Worst Trade | ₹-44,396 |
| Max Consec Wins | 14 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 921 |
| ML Skips | 1134 |
| Circuit Breaker Blocks | 102 |
| Smart Exits | 128 |
| Rule Exits | 100 |
| Multi-expiry Selections | 735 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 735 |
| Avg Final Lots | 7.4 |
| Avg Vol-Target Lots | 47.6 |
| Avg Kelly Lots | 9.0 |
| Avg Regime Scale | 0.771x |
| Avg DD Scale | 0.997x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 128 | 60.9% | ₹86,613 | ₹677 |
| adaptive:calendar_spread | 61 | 85.2% | ₹963,116 | ₹15,789 |
| adaptive:broken_wing_butterfly | 27 | 70.4% | ₹95,711 | ₹3,545 |
| adaptive:ratio_put_spread | 12 | 75.0% | ₹13,002 | ₹1,083 |


---
## Run #6
**Date**: 2026-04-08 21:33  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 16.60% |
| Total Return | 1317.3% |
| Total P&L | ₹6,586,329 |
| Sharpe | 3.35 |
| Sortino | 2.61 |
| Calmar | 0.95 |
| Max Drawdown | 17.5% |
| Win Rate | 67.7% |
| Total Trades | 232 |
| Profit Factor | 2.70 |
| Avg P&L/Trade | ₹28,389 |
| Best Trade | ₹578,370 |
| Worst Trade | ₹-683,020 |
| Max Consec Wins | 11 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 944 |
| ML Skips | 1165 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 133 |
| Rule Exits | 99 |
| Multi-expiry Selections | 744 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 744 |
| Avg Final Lots | 34.7 |
| Avg Base Lots | 39.7 |
| Avg Kelly Scale | 1.16x |
| Avg Regime Scale | 0.805x |
| Avg DD Scale | 0.833x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 130 | 60.0% | ₹583,642 | ₹4,490 |
| adaptive:calendar_spread | 62 | 83.9% | ₹5,458,640 | ₹88,043 |
| adaptive:broken_wing_butterfly | 28 | 64.3% | ₹518,955 | ₹18,534 |
| adaptive:ratio_put_spread | 12 | 75.0% | ₹25,092 | ₹2,091 |


---
## Run #7
**Date**: 2026-04-08 22:03  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 16.33% |
| Total Return | 1260.5% |
| Total P&L | ₹6,302,772 |
| Sharpe | 3.69 |
| Sortino | 3.63 |
| Calmar | 1.09 |
| Max Drawdown | 15.0% |
| Win Rate | 67.7% |
| Total Trades | 235 |
| Profit Factor | 3.20 |
| Avg P&L/Trade | ₹26,820 |
| Best Trade | ₹433,778 |
| Worst Trade | ₹-358,585 |
| Max Consec Wins | 14 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 976 |
| ML Skips | 1180 |
| Circuit Breaker Blocks | 105 |
| Smart Exits | 138 |
| Rule Exits | 97 |
| Multi-expiry Selections | 765 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 765 |
| Avg Final Lots | 26.4 |
| Avg Base Lots | 31.9 |
| Avg Confidence Scale | 1.196x |
| Avg Regime Scale | 0.804x |
| Avg DD Scale | 0.788x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹606,551 | ₹4,527 |
| adaptive:calendar_spread | 61 | 85.2% | ₹4,561,323 | ₹74,776 |
| adaptive:broken_wing_butterfly | 28 | 57.1% | ₹1,078,371 | ₹38,513 |
| adaptive:ratio_put_spread | 12 | 75.0% | ₹56,526 | ₹4,710 |


---
## Run #8 — v2 quality-filter: calibrated GBM + feature pruning + percentile labels
**Date**: 2026-04-08 22:27  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 15.04% |
| Total Return | 1023.2% |
| Total P&L | ₹5,116,058 |
| Sharpe | 3.51 |
| Sortino | 3.28 |
| Calmar | 0.86 |
| Max Drawdown | 17.5% |
| Win Rate | 63.4% |
| Total Trades | 331 |
| Profit Factor | 1.99 |
| Avg P&L/Trade | ₹15,456 |
| Best Trade | ₹702,403 |
| Worst Trade | ₹-439,568 |
| Max Consec Wins | 12 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1489 |
| ML Skips | 318 |
| Circuit Breaker Blocks | 93 |
| Smart Exits | 221 |
| Rule Exits | 110 |
| Multi-expiry Selections | 1033 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 1033 |
| Avg Final Lots | 26.0 |
| Avg Base Lots | 40.6 |
| Avg Confidence Scale | 1.004x |
| Avg Regime Scale | 0.747x |
| Avg DD Scale | 0.766x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 178 | 59.0% | ₹-381,203 | ₹-2,142 |
| adaptive:ratio_put_spread | 61 | 57.4% | ₹189,298 | ₹3,103 |
| adaptive:calendar_spread | 60 | 88.3% | ₹4,315,487 | ₹71,925 |
| adaptive:broken_wing_butterfly | 32 | 53.1% | ₹992,475 | ₹31,015 |


---
## Run #9 — v2_tuned: stricter threshold (0.58) + PCS penalty + regime AUC gate + 50th pctl labels
**Date**: 2026-04-08 22:41  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 0.74% |
| Total Return | 13.5% |
| Total P&L | ₹67,504 |
| Sharpe | 1.42 |
| Sortino | 0.32 |
| Calmar | 0.07 |
| Max Drawdown | 11.2% |
| Win Rate | 68.4% |
| Total Trades | 19 |
| Profit Factor | 1.58 |
| Avg P&L/Trade | ₹3,553 |
| Best Trade | ₹25,646 |
| Worst Trade | ₹-32,061 |
| Max Consec Wins | 6 |
| Max Consec Losses | 2 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 38 |
| ML Skips | 3889 |
| Circuit Breaker Blocks | 112 |
| Smart Exits | 7 |
| Rule Exits | 12 |
| Multi-expiry Selections | 35 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 35 |
| Avg Final Lots | 11.3 |
| Avg Base Lots | 12.8 |
| Avg Confidence Scale | 1.007x |
| Avg Regime Scale | 0.94x |
| Avg DD Scale | 0.971x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:calendar_spread | 11 | 100.0% | ₹160,109 | ₹14,555 |
| adaptive:put_credit_spread | 8 | 25.0% | ₹-92,605 | ₹-11,576 |


---
## Run #10 — v2_tuned-r2: threshold=0.52, pctl=45, PCS=0.60, AUC_gate=0.54, feats=20
**Date**: 2026-04-08 22:47  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 8.64% |
| Total Return | 318.0% |
| Total P&L | ₹1,589,862 |
| Sharpe | 3.85 |
| Sortino | 4.02 |
| Calmar | 0.50 |
| Max Drawdown | 17.3% |
| Win Rate | 64.3% |
| Total Trades | 286 |
| Profit Factor | 1.86 |
| Avg P&L/Trade | ₹5,559 |
| Best Trade | ₹129,807 |
| Worst Trade | ₹-143,434 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1207 |
| ML Skips | 848 |
| Circuit Breaker Blocks | 94 |
| Smart Exits | 196 |
| Rule Exits | 90 |
| Multi-expiry Selections | 796 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 796 |
| Avg Final Lots | 10.7 |
| Avg Base Lots | 23.1 |
| Avg Confidence Scale | 0.892x |
| Avg Regime Scale | 0.756x |
| Avg DD Scale | 0.693x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 158 | 60.1% | ₹-181,405 | ₹-1,148 |
| adaptive:calendar_spread | 54 | 83.3% | ₹1,233,637 | ₹22,845 |
| adaptive:ratio_put_spread | 49 | 59.2% | ₹98,003 | ₹2,000 |
| adaptive:broken_wing_butterfly | 25 | 60.0% | ₹439,626 | ₹17,585 |


---
## Run #11 — v2_tuned-r3: fix confidence sizing (0.80/1.0/1.2), AUC gate=0.53
**Date**: 2026-04-08 23:04  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 16.26% |
| Total Return | 1247.9% |
| Total P&L | ₹6,239,494 |
| Sharpe | 4.14 |
| Sortino | 4.28 |
| Calmar | 0.93 |
| Max Drawdown | 17.4% |
| Win Rate | 65.2% |
| Total Trades | 293 |
| Profit Factor | 2.36 |
| Avg P&L/Trade | ₹21,295 |
| Best Trade | ₹469,878 |
| Worst Trade | ₹-409,812 |
| Max Consec Wins | 15 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1256 |
| ML Skips | 750 |
| Circuit Breaker Blocks | 98 |
| Smart Exits | 194 |
| Rule Exits | 99 |
| Multi-expiry Selections | 851 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 851 |
| Avg Final Lots | 30.1 |
| Avg Base Lots | 43.6 |
| Avg Confidence Scale | 1.033x |
| Avg Regime Scale | 0.756x |
| Avg DD Scale | 0.868x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 162 | 61.7% | ₹198,875 | ₹1,228 |
| adaptive:calendar_spread | 55 | 85.5% | ₹4,624,103 | ₹84,075 |
| adaptive:ratio_put_spread | 47 | 57.4% | ₹107,372 | ₹2,285 |
| adaptive:broken_wing_butterfly | 29 | 58.6% | ₹1,309,144 | ₹45,143 |


---
## Run #12 — v1: GBM+RF ensemble, binary labels, all features
**Date**: 2026-04-08 23:28  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 16.95% |
| Total Return | 1392.1% |
| Total P&L | ₹6,960,284 |
| Sharpe | 3.90 |
| Sortino | 4.31 |
| Calmar | 0.90 |
| Max Drawdown | 18.8% |
| Win Rate | 62.2% |
| Total Trades | 339 |
| Profit Factor | 2.15 |
| Avg P&L/Trade | ₹20,532 |
| Best Trade | ₹989,300 |
| Worst Trade | ₹-539,586 |
| Max Consec Wins | 11 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1604 |
| ML Skips | 15 |
| Circuit Breaker Blocks | 93 |
| Smart Exits | 224 |
| Rule Exits | 115 |
| Multi-expiry Selections | 1147 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 1147 |
| Avg Final Lots | 31.5 |
| Avg Base Lots | 42.1 |
| Avg Confidence Scale | 1.192x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.783x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 179 | 57.5% | ₹-415,709 | ₹-2,322 |
| adaptive:ratio_put_spread | 67 | 55.2% | ₹460,953 | ₹6,880 |
| adaptive:calendar_spread | 65 | 81.5% | ₹5,381,786 | ₹82,797 |
| adaptive:broken_wing_butterfly | 28 | 64.3% | ₹1,533,255 | ₹54,759 |


---
## Run #13 — v2-consolidated: regime thresholds, 3d cooldown, loss-streak throttle, PCS=0.45
**Date**: 2026-04-08 23:49  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 8.20% |
| Total Return | 290.1% |
| Total P&L | ₹1,450,472 |
| Sharpe | 3.61 |
| Sortino | 3.23 |
| Calmar | 0.56 |
| Max Drawdown | 14.7% |
| Win Rate | 65.6% |
| Total Trades | 180 |
| Profit Factor | 2.11 |
| Avg P&L/Trade | ₹8,058 |
| Best Trade | ₹131,489 |
| Worst Trade | ₹-119,528 |
| Max Consec Wins | 12 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 499 |
| ML Skips | 2225 |
| Circuit Breaker Blocks | 107 |
| Smart Exits | 114 |
| Rule Exits | 66 |
| Multi-expiry Selections | 361 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 361 |
| Avg Final Lots | 15.3 |
| Avg Base Lots | 24.0 |
| Avg Confidence Scale | 1.015x |
| Avg Regime Scale | 0.769x |
| Avg DD Scale | 0.801x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 89 | 57.3% | ₹15,023 | ₹169 |
| adaptive:calendar_spread | 47 | 85.1% | ₹1,296,538 | ₹27,586 |
| adaptive:ratio_put_spread | 30 | 66.7% | ₹71,560 | ₹2,385 |
| adaptive:broken_wing_butterfly | 14 | 50.0% | ₹67,350 | ₹4,811 |


---
## Run #14 — v2-r2: regime gates(0.53-0.56), cooldown=2d, streak=3L+0.03, AUC_min=0.52
**Date**: 2026-04-08 23:56  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #15 — v2-r3: block neg-PnL strategies, regime gates, cooldown=2d, AUC_min=0.52
**Date**: 2026-04-09 00:02  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-08 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #16 — v2-r4: PCS_penalty=0.25, regime gates, cooldown=2d, streak=3L
**Date**: 2026-04-09 00:07  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #17 — v2-r5: ranked fallback, PCS=0.25, regime gates, cooldown=2d
**Date**: 2026-04-09 00:14  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #18 — v2-r6: deprioritize PCS in recommendation, regime gates, cooldown=2d
**Date**: 2026-04-09 00:19  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #19 — v2-r7: PCS quality floor=0.60, regime gates, cooldown=2d, streak throttle
**Date**: 2026-04-09 00:25  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #20
**Date**: 2026-04-09 00:33  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.14% |
| Total Return | 430.1% |
| Total P&L | ₹2,150,354 |
| Sharpe | 3.82 |
| Sortino | 3.53 |
| Calmar | 0.56 |
| Max Drawdown | 18.3% |
| Win Rate | 64.4% |
| Total Trades | 250 |
| Profit Factor | 1.90 |
| Avg P&L/Trade | ₹8,601 |
| Best Trade | ₹209,175 |
| Worst Trade | ₹-174,170 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 789 |
| ML Skips | 1527 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 165 |
| Rule Exits | 85 |
| Multi-expiry Selections | 542 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 542 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 31.7 |
| Avg Confidence Scale | 0.966x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.77x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 61.2% | ₹-42,362 | ₹-316 |
| adaptive:calendar_spread | 50 | 84.0% | ₹1,609,226 | ₹32,185 |
| adaptive:ratio_put_spread | 41 | 61.0% | ₹103,339 | ₹2,520 |
| adaptive:broken_wing_butterfly | 25 | 48.0% | ₹480,150 | ₹19,206 |


---
## Run #21
**Date**: 2026-04-09 00:41  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 16.22% |
| Total Return | 1240.0% |
| Total P&L | ₹6,200,209 |
| Sharpe | 1.37 |
| Sortino | 1.13 |
| Calmar | 1.22 |
| Max Drawdown | 13.3% |
| Win Rate | 63.6% |
| Total Trades | 297 |
| Profit Factor | 2.94 |
| Avg P&L/Trade | ₹20,876 |
| Best Trade | ₹357,324 |
| Worst Trade | ₹-322,917 |
| Max Consec Wins | 22 |
| Max Consec Losses | 5 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 751 |
| ML Skips | 1284 |
| Circuit Breaker Blocks | 97 |
| Smart Exits | 182 |
| Rule Exits | 115 |
| Multi-expiry Selections | 545 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 545 |
| Avg Final Lots | 32.1 |
| Avg Base Lots | 45.6 |
| Avg Confidence Scale | 0.967x |
| Avg Regime Scale | 0.773x |
| Avg DD Scale | 0.835x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 164 | 61.6% | ₹669,334 | ₹4,081 |
| adaptive:calendar_spread | 59 | 88.1% | ₹4,522,017 | ₹76,644 |
| adaptive:ratio_put_spread | 46 | 39.1% | ₹18,522 | ₹403 |
| adaptive:broken_wing_butterfly | 28 | 64.3% | ₹990,336 | ₹35,369 |


---
## Run #22 — v3 baseline — cost-adjusted + iron condor + MTM
**Date**: 2026-04-09 00:42  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 21.57% |
| Total Return | 2810.6% |
| Total P&L | ₹14,053,130 |
| Sharpe | 1.48 |
| Sortino | 1.19 |
| Calmar | 1.35 |
| Max Drawdown | 16.0% |
| Win Rate | 60.6% |
| Total Trades | 353 |
| Profit Factor | 2.47 |
| Avg P&L/Trade | ₹39,811 |
| Best Trade | ₹1,019,303 |
| Worst Trade | ₹-696,802 |
| Max Consec Wins | 10 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1001 |
| ML Skips | 456 |
| Circuit Breaker Blocks | 91 |
| Smart Exits | 207 |
| Rule Exits | 146 |
| Multi-expiry Selections | 718 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 718 |
| Avg Final Lots | 52.8 |
| Avg Base Lots | 67.3 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.758x |
| Avg DD Scale | 0.879x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:iron_condor | 166 | 57.2% | ₹6,602,304 | ₹39,773 |
| adaptive:put_credit_spread | 77 | 77.9% | ₹3,589,417 | ₹46,616 |
| adaptive:ratio_put_spread | 57 | 47.4% | ₹380,915 | ₹6,683 |
| adaptive:broken_wing_butterfly | 28 | 42.9% | ₹880,974 | ₹31,463 |
| adaptive:calendar_spread | 25 | 80.0% | ₹2,599,519 | ₹103,981 |


---
## Run #23
**Date**: 2026-04-09 00:49  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 7.10% |
| Total Return | 226.6% |
| Total P&L | ₹1,133,117 |
| Sharpe | 0.94 |
| Sortino | 0.51 |
| Calmar | 0.33 |
| Max Drawdown | 21.5% |
| Win Rate | 66.1% |
| Total Trades | 127 |
| Profit Factor | 2.04 |
| Avg P&L/Trade | ₹8,922 |
| Best Trade | ₹140,424 |
| Worst Trade | ₹-139,436 |
| Max Consec Wins | 10 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 286 |
| ML Skips | 2627 |
| Circuit Breaker Blocks | 106 |
| Smart Exits | 67 |
| Rule Exits | 60 |
| Multi-expiry Selections | 218 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 218 |
| Avg Final Lots | 16.0 |
| Avg Base Lots | 24.1 |
| Avg Confidence Scale | 1.02x |
| Avg Regime Scale | 0.787x |
| Avg DD Scale | 0.834x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:iron_condor | 61 | 62.3% | ₹482,058 | ₹7,903 |
| adaptive:calendar_spread | 25 | 80.0% | ₹374,768 | ₹14,991 |
| adaptive:put_credit_spread | 15 | 80.0% | ₹60,024 | ₹4,002 |
| adaptive:broken_wing_butterfly | 14 | 57.1% | ₹213,851 | ₹15,275 |
| adaptive:ratio_put_spread | 12 | 50.0% | ₹2,415 | ₹201 |


---
## Run #24
**Date**: 2026-04-09 00:54  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 6.81% |
| Total Return | 211.8% |
| Total P&L | ₹1,059,209 |
| Sharpe | 0.90 |
| Sortino | 0.49 |
| Calmar | 0.32 |
| Max Drawdown | 21.5% |
| Win Rate | 65.9% |
| Total Trades | 129 |
| Profit Factor | 1.98 |
| Avg P&L/Trade | ₹8,211 |
| Best Trade | ₹133,023 |
| Worst Trade | ₹-132,469 |
| Max Consec Wins | 11 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 308 |
| ML Skips | 2556 |
| Circuit Breaker Blocks | 106 |
| Smart Exits | 69 |
| Rule Exits | 60 |
| Multi-expiry Selections | 229 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 229 |
| Avg Final Lots | 15.3 |
| Avg Base Lots | 22.9 |
| Avg Confidence Scale | 1.014x |
| Avg Regime Scale | 0.791x |
| Avg DD Scale | 0.837x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:iron_condor | 63 | 60.3% | ₹396,472 | ₹6,293 |
| adaptive:calendar_spread | 26 | 84.6% | ₹413,077 | ₹15,888 |
| adaptive:put_credit_spread | 14 | 78.6% | ₹38,114 | ₹2,722 |
| adaptive:broken_wing_butterfly | 14 | 57.1% | ₹208,663 | ₹14,905 |
| adaptive:ratio_put_spread | 12 | 50.0% | ₹2,883 | ₹240 |


---
## Run #25
**Date**: 2026-04-09 01:01  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 8.67% |
| Total Return | 320.1% |
| Total P&L | ₹1,600,409 |
| Sharpe | 1.15 |
| Sortino | 0.67 |
| Calmar | 0.60 |
| Max Drawdown | 14.6% |
| Win Rate | 65.1% |
| Total Trades | 106 |
| Profit Factor | 2.55 |
| Avg P&L/Trade | ₹15,098 |
| Best Trade | ₹189,026 |
| Worst Trade | ₹-162,599 |
| Max Consec Wins | 8 |
| Max Consec Losses | 5 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 239 |
| ML Skips | 2810 |
| Circuit Breaker Blocks | 105 |
| Smart Exits | 49 |
| Rule Exits | 57 |
| Multi-expiry Selections | 186 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 186 |
| Avg Final Lots | 19.9 |
| Avg Base Lots | 25.8 |
| Avg Confidence Scale | 1.016x |
| Avg Regime Scale | 0.813x |
| Avg DD Scale | 0.941x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:iron_condor | 43 | 55.8% | ₹261,836 | ₹6,089 |
| adaptive:calendar_spread | 28 | 82.1% | ₹647,559 | ₹23,127 |
| adaptive:broken_wing_butterfly | 13 | 69.2% | ₹585,192 | ₹45,015 |
| adaptive:put_credit_spread | 12 | 75.0% | ₹115,714 | ₹9,643 |
| adaptive:ratio_put_spread | 10 | 40.0% | ₹-9,892 | ₹-989 |


---
## Run #26 — v4 — walk-forward + Greeks caps + normalized exits + PCS tilt
**Date**: 2026-04-09 01:05  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.39% |
| Total Return | 543.6% |
| Total P&L | ₹2,718,251 |
| Sharpe | 0.99 |
| Sortino | 0.77 |
| Calmar | 1.34 |
| Max Drawdown | 8.5% |
| Win Rate | 59.5% |
| Total Trades | 279 |
| Profit Factor | 2.24 |
| Avg P&L/Trade | ₹9,743 |
| Best Trade | ₹213,155 |
| Worst Trade | ₹-157,802 |
| Max Consec Wins | 11 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1156 |
| ML Skips | 609 |
| Circuit Breaker Blocks | 87 |
| Smart Exits | 178 |
| Rule Exits | 101 |
| Multi-expiry Selections | 980 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 980 |
| Avg Final Lots | 31.4 |
| Avg Base Lots | 35.6 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.806x |
| Avg DD Scale | 0.717x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 122 | 61.5% | ₹1,197,370 | ₹9,815 |
| adaptive:iron_condor | 80 | 61.2% | ₹1,075,537 | ₹13,444 |
| adaptive:broken_wing_butterfly | 43 | 46.5% | ₹29,018 | ₹675 |
| adaptive:ratio_put_spread | 18 | 50.0% | ₹-71,850 | ₹-3,992 |
| adaptive:calendar_spread | 16 | 81.2% | ₹488,176 | ₹30,511 |


---
## Run #27
**Date**: 2026-04-09 01:05  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 6.02% |
| Total Return | 174.2% |
| Total P&L | ₹871,012 |
| Sharpe | 0.73 |
| Sortino | 0.39 |
| Calmar | 0.27 |
| Max Drawdown | 22.0% |
| Win Rate | 61.5% |
| Total Trades | 135 |
| Profit Factor | 1.86 |
| Avg P&L/Trade | ₹6,452 |
| Best Trade | ₹112,381 |
| Worst Trade | ₹-137,813 |
| Max Consec Wins | 6 |
| Max Consec Losses | 5 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 339 |
| ML Skips | 2559 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 80 |
| Rule Exits | 55 |
| Multi-expiry Selections | 299 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 299 |
| Avg Final Lots | 15.0 |
| Avg Base Lots | 23.9 |
| Avg Confidence Scale | 1.015x |
| Avg Regime Scale | 0.79x |
| Avg DD Scale | 0.797x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 51 | 56.9% | ₹4,739 | ₹93 |
| adaptive:iron_condor | 41 | 65.9% | ₹461,272 | ₹11,251 |
| adaptive:broken_wing_butterfly | 20 | 55.0% | ₹132,018 | ₹6,601 |
| adaptive:calendar_spread | 18 | 72.2% | ₹244,789 | ₹13,599 |
| adaptive:ratio_put_spread | 5 | 60.0% | ₹28,193 | ₹5,639 |


---
## Run #28
**Date**: 2026-04-09 01:10  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.79% |
| Total Return | 486.7% |
| Total P&L | ₹2,433,461 |
| Sharpe | 0.98 |
| Sortino | 0.71 |
| Calmar | 0.53 |
| Max Drawdown | 20.3% |
| Win Rate | 61.3% |
| Total Trades | 253 |
| Profit Factor | 1.88 |
| Avg P&L/Trade | ₹9,618 |
| Best Trade | ₹206,180 |
| Worst Trade | ₹-151,848 |
| Max Consec Wins | 11 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 778 |
| ML Skips | 1228 |
| Circuit Breaker Blocks | 92 |
| Smart Exits | 160 |
| Rule Exits | 93 |
| Multi-expiry Selections | 662 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 662 |
| Avg Final Lots | 18.5 |
| Avg Base Lots | 31.3 |
| Avg Confidence Scale | 0.961x |
| Avg Regime Scale | 0.778x |
| Avg DD Scale | 0.804x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 103 | 60.2% | ₹315,822 | ₹3,066 |
| adaptive:iron_condor | 85 | 65.9% | ₹1,225,555 | ₹14,418 |
| adaptive:broken_wing_butterfly | 33 | 45.5% | ₹47,034 | ₹1,425 |
| adaptive:calendar_spread | 20 | 85.0% | ₹850,831 | ₹42,542 |
| adaptive:ratio_put_spread | 12 | 41.7% | ₹-5,781 | ₹-482 |


---
## Run #29 — v4.1 — RPS removed, caps relaxed 62%/6K/60K, starvation guard, BWB<20
**Date**: 2026-04-09 01:13  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #30
**Date**: 2026-04-09 01:16  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 9.43% |
| Total Return | 373.4% |
| Total P&L | ₹1,867,045 |
| Sharpe | 0.89 |
| Sortino | 0.57 |
| Calmar | 0.80 |
| Max Drawdown | 11.8% |
| Win Rate | 63.5% |
| Total Trades | 255 |
| Profit Factor | 1.84 |
| Avg P&L/Trade | ₹7,322 |
| Best Trade | ₹174,711 |
| Worst Trade | ₹-179,765 |
| Max Consec Wins | 7 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 906 |
| ML Skips | 1421 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 189 |
| Rule Exits | 66 |
| Multi-expiry Selections | 603 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 603 |
| Avg Final Lots | 16.1 |
| Avg Base Lots | 25.5 |
| Avg Confidence Scale | 0.956x |
| Avg Regime Scale | 0.791x |
| Avg DD Scale | 0.834x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 60.4% | ₹124,482 | ₹929 |
| adaptive:iron_condor | 100 | 65.0% | ₹1,174,804 | ₹11,748 |
| adaptive:calendar_spread | 17 | 82.4% | ₹461,995 | ₹27,176 |
| adaptive:broken_wing_butterfly | 4 | 50.0% | ₹105,763 | ₹26,441 |


---
## Run #31 — v4.2 — conc 68%/15, calendar VIX<22, vol_exp 1.05
**Date**: 2026-04-09 01:18  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.96% |
| Total Return | 853.9% |
| Total P&L | ₹4,269,613 |
| Sharpe | 1.27 |
| Sortino | 0.98 |
| Calmar | 0.93 |
| Max Drawdown | 14.9% |
| Win Rate | 64.8% |
| Total Trades | 290 |
| Profit Factor | 2.62 |
| Avg P&L/Trade | ₹14,723 |
| Best Trade | ₹277,679 |
| Worst Trade | ₹-174,779 |
| Max Consec Wins | 13 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1324 |
| ML Skips | 717 |
| Circuit Breaker Blocks | 102 |
| Smart Exits | 205 |
| Rule Exits | 85 |
| Multi-expiry Selections | 875 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 875 |
| Avg Final Lots | 42.0 |
| Avg Base Lots | 46.1 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.809x |
| Avg DD Scale | 0.755x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 166 | 64.5% | ₹1,554,692 | ₹9,366 |
| adaptive:iron_condor | 83 | 65.1% | ₹2,018,640 | ₹24,321 |
| adaptive:calendar_spread | 32 | 75.0% | ₹604,519 | ₹18,891 |
| adaptive:broken_wing_butterfly | 9 | 33.3% | ₹91,761 | ₹10,196 |


---
## Run #32
**Date**: 2026-04-09 01:21  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 9.35% |
| Total Return | 367.9% |
| Total P&L | ₹1,839,349 |
| Sharpe | 0.92 |
| Sortino | 0.65 |
| Calmar | 0.45 |
| Max Drawdown | 21.0% |
| Win Rate | 62.8% |
| Total Trades | 266 |
| Profit Factor | 1.95 |
| Avg P&L/Trade | ₹6,915 |
| Best Trade | ₹178,779 |
| Worst Trade | ₹-108,926 |
| Max Consec Wins | 7 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 868 |
| ML Skips | 1314 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 191 |
| Rule Exits | 75 |
| Multi-expiry Selections | 566 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 566 |
| Avg Final Lots | 15.6 |
| Avg Base Lots | 27.6 |
| Avg Confidence Scale | 0.955x |
| Avg Regime Scale | 0.799x |
| Avg DD Scale | 0.772x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 138 | 59.4% | ₹66,565 | ₹482 |
| adaptive:iron_condor | 94 | 63.8% | ₹1,212,723 | ₹12,901 |
| adaptive:calendar_spread | 29 | 75.9% | ₹479,363 | ₹16,530 |
| adaptive:broken_wing_butterfly | 5 | 60.0% | ₹80,699 | ₹16,140 |


---
## Run #33 — v4.3 — conc 62%/18 (reverted), calendar VIX<22 kept
**Date**: 2026-04-09 01:23  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.74% |
| Total Return | 822.6% |
| Total P&L | ₹4,113,044 |
| Sharpe | 1.29 |
| Sortino | 1.01 |
| Calmar | 0.86 |
| Max Drawdown | 16.0% |
| Win Rate | 65.5% |
| Total Trades | 275 |
| Profit Factor | 2.58 |
| Avg P&L/Trade | ₹14,957 |
| Best Trade | ₹274,692 |
| Worst Trade | ₹-181,763 |
| Max Consec Wins | 14 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1362 |
| ML Skips | 753 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 192 |
| Rule Exits | 83 |
| Multi-expiry Selections | 912 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 912 |
| Avg Final Lots | 42.7 |
| Avg Base Lots | 47.4 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.809x |
| Avg DD Scale | 0.78x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 151 | 65.6% | ₹1,587,552 | ₹10,514 |
| adaptive:iron_condor | 83 | 65.1% | ₹1,856,593 | ₹22,369 |
| adaptive:calendar_spread | 32 | 75.0% | ₹613,382 | ₹19,168 |
| adaptive:broken_wing_butterfly | 9 | 33.3% | ₹55,518 | ₹6,169 |


---
## Run #34
**Date**: 2026-04-09 01:25  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 8.13% |
| Total Return | 285.2% |
| Total P&L | ₹1,426,122 |
| Sharpe | 0.84 |
| Sortino | 0.59 |
| Calmar | 0.38 |
| Max Drawdown | 21.2% |
| Win Rate | 62.2% |
| Total Trades | 254 |
| Profit Factor | 1.75 |
| Avg P&L/Trade | ₹5,615 |
| Best Trade | ₹146,239 |
| Worst Trade | ₹-144,725 |
| Max Consec Wins | 7 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 861 |
| ML Skips | 1327 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 180 |
| Rule Exits | 74 |
| Multi-expiry Selections | 562 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 562 |
| Avg Final Lots | 15.1 |
| Avg Base Lots | 26.2 |
| Avg Confidence Scale | 0.956x |
| Avg Regime Scale | 0.799x |
| Avg DD Scale | 0.784x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 127 | 59.1% | ₹33,262 | ₹262 |
| adaptive:iron_condor | 94 | 63.8% | ₹963,819 | ₹10,253 |
| adaptive:calendar_spread | 28 | 75.0% | ₹369,501 | ₹13,196 |
| adaptive:broken_wing_butterfly | 5 | 40.0% | ₹59,540 | ₹11,908 |


---
## Run #35 — v4.4 — v4.1 base + quality threshold 0.46 (was 0.48)
**Date**: 2026-04-09 01:28  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #36
**Date**: 2026-04-09 01:29  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 9.43% |
| Total Return | 373.4% |
| Total P&L | ₹1,867,045 |
| Sharpe | 0.89 |
| Sortino | 0.57 |
| Calmar | 0.80 |
| Max Drawdown | 11.8% |
| Win Rate | 63.5% |
| Total Trades | 255 |
| Profit Factor | 1.84 |
| Avg P&L/Trade | ₹7,322 |
| Best Trade | ₹174,711 |
| Worst Trade | ₹-179,765 |
| Max Consec Wins | 7 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 906 |
| ML Skips | 1421 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 189 |
| Rule Exits | 66 |
| Multi-expiry Selections | 603 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 603 |
| Avg Final Lots | 16.1 |
| Avg Base Lots | 25.5 |
| Avg Confidence Scale | 0.956x |
| Avg Regime Scale | 0.791x |
| Avg DD Scale | 0.834x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 60.4% | ₹124,482 | ₹929 |
| adaptive:iron_condor | 100 | 65.0% | ₹1,174,804 | ₹11,748 |
| adaptive:calendar_spread | 17 | 82.4% | ₹461,995 | ₹27,176 |
| adaptive:broken_wing_butterfly | 4 | 50.0% | ₹105,763 | ₹26,441 |


---
## Run #37
**Date**: 2026-04-09 01:33  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 9.43% |
| Total Return | 373.4% |
| Total P&L | ₹1,867,045 |
| Sharpe | 0.89 |
| Sortino | 0.57 |
| Calmar | 0.80 |
| Max Drawdown | 11.8% |
| Win Rate | 63.5% |
| Total Trades | 255 |
| Profit Factor | 1.84 |
| Avg P&L/Trade | ₹7,322 |
| Best Trade | ₹174,711 |
| Worst Trade | ₹-179,765 |
| Max Consec Wins | 7 |
| Max Consec Losses | 4 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 906 |
| ML Skips | 1421 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 189 |
| Rule Exits | 66 |
| Multi-expiry Selections | 603 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 603 |
| Avg Final Lots | 16.1 |
| Avg Base Lots | 25.5 |
| Avg Confidence Scale | 0.956x |
| Avg Regime Scale | 0.791x |
| Avg DD Scale | 0.834x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 134 | 60.4% | ₹124,482 | ₹929 |
| adaptive:iron_condor | 100 | 65.0% | ₹1,174,804 | ₹11,748 |
| adaptive:calendar_spread | 17 | 82.4% | ₹461,995 | ₹27,176 |
| adaptive:broken_wing_butterfly | 4 | 50.0% | ₹105,763 | ₹26,441 |


---
## Run #38 — v4.5 — threshold 0.46 (fixed in main.py + trade_learner)
**Date**: 2026-04-09 01:33  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #39
**Date**: 2026-04-09 01:37  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.39% |
| Total Return | 775.2% |
| Total P&L | ₹3,876,232 |
| Sharpe | 1.20 |
| Sortino | 0.78 |
| Calmar | 2.29 |
| Max Drawdown | 5.9% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.04 |
| Avg P&L/Trade | ₹14,199 |
| Best Trade | ₹223,598 |
| Worst Trade | ₹-132,514 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1428 |
| ML Skips | 816 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 969 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 969 |
| Avg Final Lots | 34.5 |
| Avg Base Lots | 39.4 |
| Avg Confidence Scale | 1.196x |
| Avg Regime Scale | 0.815x |
| Avg DD Scale | 0.633x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,768,059 | ₹11,407 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,583,897 | ₹16,673 |
| adaptive:calendar_spread | 16 | 81.2% | ₹445,064 | ₹27,816 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹79,212 | ₹11,316 |


---
## Run #40 — v4.6 — BWB removed, PCS takes over high-VIX band
**Date**: 2026-04-09 01:39  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.96% |
| Total Return | 719.7% |
| Total P&L | ₹3,598,358 |
| Sharpe | 1.08 |
| Sortino | 0.70 |
| Calmar | 1.01 |
| Max Drawdown | 12.8% |
| Win Rate | 65.3% |
| Total Trades | 300 |
| Profit Factor | 2.61 |
| Avg P&L/Trade | ₹11,995 |
| Best Trade | ₹226,776 |
| Worst Trade | ₹-207,724 |
| Max Consec Wins | 19 |
| Max Consec Losses | 9 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1408 |
| ML Skips | 752 |
| Circuit Breaker Blocks | 104 |
| Smart Exits | 229 |
| Rule Exits | 71 |
| Multi-expiry Selections | 1074 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 1074 |
| Avg Final Lots | 23.8 |
| Avg Base Lots | 32.1 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.771x |
| Avg DD Scale | 0.584x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 171 | 64.9% | ₹1,604,065 | ₹9,380 |
| adaptive:iron_condor | 112 | 63.4% | ₹1,555,037 | ₹13,884 |
| adaptive:calendar_spread | 17 | 82.4% | ₹439,256 | ₹25,839 |


---
## Run #41 — v4.1-FINAL — production version after 6 iteration attempts
**Date**: 2026-04-09 01:44  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #42
**Date**: 2026-04-09 07:28  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.83% |
| Total Return | 589.3% |
| Total P&L | ₹2,946,424 |
| Sharpe | 1.02 |
| Sortino | 0.69 |
| Calmar | 0.69 |
| Max Drawdown | 17.1% |
| Win Rate | 63.1% |
| Total Trades | 314 |
| Profit Factor | 2.27 |
| Avg P&L/Trade | ₹9,384 |
| Best Trade | ₹174,925 |
| Worst Trade | ₹-193,701 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1358 |
| ML Skips | 711 |
| Circuit Breaker Blocks | 102 |
| Smart Exits | 253 |
| Rule Exits | 61 |
| Multi-expiry Selections | 895 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 895 |
| Avg Final Lots | 17.7 |
| Avg Base Lots | 26.3 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.801x |
| Avg DD Scale | 0.546x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 164 | 63.4% | ₹768,182 | ₹4,684 |
| adaptive:iron_condor | 119 | 59.7% | ₹1,125,022 | ₹9,454 |
| adaptive:calendar_spread | 24 | 83.3% | ₹960,388 | ₹40,016 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹92,832 | ₹13,262 |


---
## Run #43
**Date**: 2026-04-09 07:31  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.57% |
| Total Return | 672.3% |
| Total P&L | ₹3,361,312 |
| Sharpe | 1.08 |
| Sortino | 0.70 |
| Calmar | 1.54 |
| Max Drawdown | 8.2% |
| Win Rate | 66.8% |
| Total Trades | 271 |
| Profit Factor | 2.71 |
| Avg P&L/Trade | ₹12,403 |
| Best Trade | ₹234,979 |
| Worst Trade | ₹-188,775 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1401 |
| ML Skips | 770 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 65 |
| Multi-expiry Selections | 940 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 940 |
| Avg Final Lots | 29.0 |
| Avg Base Lots | 33.7 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.815x |
| Avg DD Scale | 0.639x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 150 | 68.7% | ₹1,296,122 | ₹8,641 |
| adaptive:iron_condor | 97 | 63.9% | ₹1,508,565 | ₹15,552 |
| adaptive:calendar_spread | 16 | 81.2% | ₹470,925 | ₹29,433 |
| adaptive:broken_wing_butterfly | 8 | 37.5% | ₹85,700 | ₹10,713 |


---
## Run #44
**Date**: 2026-04-09 07:34  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 12.57% |
| Total Return | 672.3% |
| Total P&L | ₹3,361,312 |
| Sharpe | 1.08 |
| Sortino | 0.70 |
| Calmar | 1.54 |
| Max Drawdown | 8.2% |
| Win Rate | 66.8% |
| Total Trades | 271 |
| Profit Factor | 2.71 |
| Avg P&L/Trade | ₹12,403 |
| Best Trade | ₹234,979 |
| Worst Trade | ₹-188,775 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1401 |
| ML Skips | 770 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 65 |
| Multi-expiry Selections | 940 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 940 |
| Avg Final Lots | 29.0 |
| Avg Base Lots | 33.7 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.815x |
| Avg DD Scale | 0.639x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 150 | 68.7% | ₹1,296,122 | ₹8,641 |
| adaptive:iron_condor | 97 | 63.9% | ₹1,508,565 | ₹15,552 |
| adaptive:calendar_spread | 16 | 81.2% | ₹470,925 | ₹29,433 |
| adaptive:broken_wing_butterfly | 8 | 37.5% | ₹85,700 | ₹10,713 |


---
## Run #45
**Date**: 2026-04-09 07:39  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.76% |
| Total Return | 825.5% |
| Total P&L | ₹4,127,266 |
| Sharpe | 1.23 |
| Sortino | 0.79 |
| Calmar | 2.32 |
| Max Drawdown | 5.9% |
| Win Rate | 66.4% |
| Total Trades | 271 |
| Profit Factor | 3.21 |
| Avg P&L/Trade | ₹15,230 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-140,855 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1432 |
| ML Skips | 799 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 209 |
| Rule Exits | 62 |
| Multi-expiry Selections | 969 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 969 |
| Avg Final Lots | 36.5 |
| Avg Base Lots | 40.9 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.638x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 153 | 66.7% | ₹1,870,759 | ₹12,227 |
| adaptive:iron_condor | 94 | 66.0% | ₹1,707,505 | ₹18,165 |
| adaptive:calendar_spread | 16 | 81.2% | ₹478,203 | ₹29,888 |
| adaptive:broken_wing_butterfly | 8 | 37.5% | ₹70,799 | ₹8,850 |


---
## Run #46
**Date**: 2026-04-09 07:44  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.09% |
| Total Return | 514.8% |
| Total P&L | ₹2,573,827 |
| Sharpe | 0.95 |
| Sortino | 0.61 |
| Calmar | 0.67 |
| Max Drawdown | 16.6% |
| Win Rate | 64.0% |
| Total Trades | 297 |
| Profit Factor | 2.25 |
| Avg P&L/Trade | ₹8,666 |
| Best Trade | ₹244,084 |
| Worst Trade | ₹-170,344 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1340 |
| ML Skips | 713 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 223 |
| Rule Exits | 74 |
| Multi-expiry Selections | 876 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 876 |
| Avg Final Lots | 12.7 |
| Avg Base Lots | 21.7 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.796x |
| Avg DD Scale | 0.525x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 156 | 64.1% | ₹637,154 | ₹4,084 |
| adaptive:iron_condor | 110 | 61.8% | ₹969,871 | ₹8,817 |
| adaptive:calendar_spread | 23 | 82.6% | ₹889,521 | ₹38,675 |
| adaptive:broken_wing_butterfly | 8 | 37.5% | ₹77,282 | ₹9,660 |


---
## Run #47
**Date**: 2026-04-09 07:48  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.76% |
| Total Return | 825.5% |
| Total P&L | ₹4,127,266 |
| Sharpe | 1.23 |
| Sortino | 0.79 |
| Calmar | 2.32 |
| Max Drawdown | 5.9% |
| Win Rate | 66.4% |
| Total Trades | 271 |
| Profit Factor | 3.21 |
| Avg P&L/Trade | ₹15,230 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-140,855 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1432 |
| ML Skips | 799 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 209 |
| Rule Exits | 62 |
| Multi-expiry Selections | 969 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 969 |
| Avg Final Lots | 36.5 |
| Avg Base Lots | 40.9 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.638x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 153 | 66.7% | ₹1,870,759 | ₹12,227 |
| adaptive:iron_condor | 94 | 66.0% | ₹1,707,505 | ₹18,165 |
| adaptive:calendar_spread | 16 | 81.2% | ₹478,203 | ₹29,888 |
| adaptive:broken_wing_butterfly | 8 | 37.5% | ₹70,799 | ₹8,850 |


---
## Run #48
**Date**: 2026-04-09 07:53  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #49
**Date**: 2026-04-09 07:57  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.00% |
| Total Return | 724.8% |
| Total P&L | ₹3,624,040 |
| Sharpe | 1.08 |
| Sortino | 0.71 |
| Calmar | 1.10 |
| Max Drawdown | 11.8% |
| Win Rate | 64.9% |
| Total Trades | 288 |
| Profit Factor | 2.58 |
| Avg P&L/Trade | ₹12,583 |
| Best Trade | ₹269,053 |
| Worst Trade | ₹-217,572 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1368 |
| ML Skips | 736 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 203 |
| Rule Exits | 85 |
| Multi-expiry Selections | 909 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 909 |
| Avg Final Lots | 22.5 |
| Avg Base Lots | 29.2 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.805x |
| Avg DD Scale | 0.587x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 159 | 65.4% | ₹1,408,311 | ₹8,857 |
| adaptive:iron_condor | 103 | 63.1% | ₹1,658,631 | ₹16,103 |
| adaptive:calendar_spread | 19 | 78.9% | ₹494,111 | ₹26,006 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹62,987 | ₹8,998 |


---
## Run #50
**Date**: 2026-04-09 08:01  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #51 — v4-final-cleanup-verify
**Date**: 2026-04-09 08:38  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 13.78% |
| Total Return | 828.1% |
| Total P&L | ₹4,140,728 |
| Sharpe | 1.23 |
| Sortino | 0.80 |
| Calmar | 2.36 |
| Max Drawdown | 5.8% |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Profit Factor | 3.11 |
| Avg P&L/Trade | ₹15,168 |
| Best Trade | ₹236,887 |
| Worst Trade | ₹-139,813 |
| Max Consec Wins | 15 |
| Max Consec Losses | 7 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1438 |
| ML Skips | 806 |
| Circuit Breaker Blocks | 101 |
| Smart Exits | 206 |
| Rule Exits | 67 |
| Multi-expiry Selections | 979 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 979 |
| Avg Final Lots | 36.3 |
| Avg Base Lots | 40.8 |
| Avg Confidence Scale | 1.199x |
| Avg Regime Scale | 0.817x |
| Avg DD Scale | 0.64x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 155 | 66.5% | ₹1,893,235 | ₹12,214 |
| adaptive:iron_condor | 95 | 63.2% | ₹1,684,619 | ₹17,733 |
| adaptive:calendar_spread | 16 | 81.2% | ₹479,469 | ₹29,967 |
| adaptive:broken_wing_butterfly | 7 | 42.9% | ₹83,405 | ₹11,915 |


---
## Run #52
**Date**: 2026-04-09 21:19  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-09 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.51% |
| Total Return | 461.6% |
| Total P&L | ₹2,307,737 |
| Sharpe | 0.86 |
| Sortino | 0.58 |
| Calmar | 1.29 |
| Max Drawdown | 8.2% |
| Win Rate | 63.6% |
| Total Trades | 280 |
| Profit Factor | 2.29 |
| Avg P&L/Trade | ₹8,242 |
| Best Trade | ₹180,500 |
| Worst Trade | ₹-135,029 |
| Max Consec Wins | 14 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1083 |
| ML Skips | 533 |
| Circuit Breaker Blocks | 635 |
| Smart Exits | 208 |
| Rule Exits | 72 |
| Multi-expiry Selections | 771 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 771 |
| Avg Final Lots | 12.7 |
| Avg Base Lots | 20.0 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.799x |
| Avg DD Scale | 0.632x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 152 | 61.8% | ₹549,112 | ₹3,613 |
| adaptive:iron_condor | 101 | 62.4% | ₹1,041,263 | ₹10,310 |
| adaptive:calendar_spread | 23 | 82.6% | ₹773,854 | ₹33,646 |
| adaptive:broken_wing_butterfly | 4 | 50.0% | ₹-56,492 | ₹-14,123 |


---
## Run #53
**Date**: 2026-04-13 23:37  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-13 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 9.35% |
| Total Return | 367.9% |
| Total P&L | ₹1,839,454 |
| Sharpe | 0.83 |
| Sortino | 0.56 |
| Calmar | 0.60 |
| Max Drawdown | 15.5% |
| Win Rate | 62.9% |
| Total Trades | 272 |
| Profit Factor | 2.13 |
| Avg P&L/Trade | ₹6,763 |
| Best Trade | ₹192,959 |
| Worst Trade | ₹-118,271 |
| Max Consec Wins | 16 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1104 |
| ML Skips | 556 |
| Circuit Breaker Blocks | 628 |
| Smart Exits | 203 |
| Rule Exits | 69 |
| Multi-expiry Selections | 790 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 790 |
| Avg Final Lots | 12.5 |
| Avg Base Lots | 20.2 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.8x |
| Avg DD Scale | 0.624x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 149 | 60.4% | ₹274,265 | ₹1,841 |
| adaptive:iron_condor | 97 | 62.9% | ₹1,135,630 | ₹11,708 |
| adaptive:calendar_spread | 22 | 81.8% | ₹486,051 | ₹22,093 |
| adaptive:broken_wing_butterfly | 4 | 50.0% | ₹-56,492 | ₹-14,123 |


---
## Run #54 — with-85%-max-profit-rule
**Date**: 2026-04-16 21:43  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-16 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 11.91% |
| Total Return | 598.7% |
| Total P&L | ₹2,993,688 |
| Sharpe | 1.05 |
| Sortino | 0.62 |
| Calmar | 1.18 |
| Max Drawdown | 10.1% |
| Win Rate | 71.6% |
| Total Trades | 296 |
| Profit Factor | 2.33 |
| Avg P&L/Trade | ₹10,114 |
| Best Trade | ₹307,140 |
| Worst Trade | ₹-267,191 |
| Max Consec Wins | 11 |
| Max Consec Losses | 6 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1243 |
| ML Skips | 645 |
| Circuit Breaker Blocks | 674 |
| Smart Exits | 127 |
| Rule Exits | 169 |
| Multi-expiry Selections | 917 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 917 |
| Avg Final Lots | 30.0 |
| Avg Base Lots | 38.0 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.812x |
| Avg DD Scale | 0.764x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 167 | 66.5% | ₹810,233 | ₹4,852 |
| adaptive:iron_condor | 92 | 78.3% | ₹704,965 | ₹7,663 |
| adaptive:calendar_spread | 32 | 84.4% | ₹1,739,685 | ₹54,365 |
| adaptive:broken_wing_butterfly | 5 | 40.0% | ₹-261,196 | ₹-52,239 |


---
## Run #55
**Date**: 2026-04-16 23:41  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-16 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.19% |
| Total Return | 434.9% |
| Total P&L | ₹2,174,335 |
| Sharpe | 0.92 |
| Sortino | 0.54 |
| Calmar | 0.70 |
| Max Drawdown | 14.5% |
| Win Rate | 74.0% |
| Total Trades | 289 |
| Profit Factor | 2.07 |
| Avg P&L/Trade | ₹7,524 |
| Best Trade | ₹174,799 |
| Worst Trade | ₹-222,739 |
| Max Consec Wins | 14 |
| Max Consec Losses | 5 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1235 |
| ML Skips | 1324 |
| Circuit Breaker Blocks | 645 |
| Smart Exits | 116 |
| Rule Exits | 173 |
| Multi-expiry Selections | 913 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 913 |
| Avg Final Lots | 25.4 |
| Avg Base Lots | 32.9 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.814x |
| Avg DD Scale | 0.748x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 159 | 69.2% | ₹616,109 | ₹3,875 |
| adaptive:iron_condor | 96 | 81.2% | ₹980,410 | ₹10,213 |
| adaptive:calendar_spread | 29 | 82.8% | ₹781,708 | ₹26,955 |
| adaptive:broken_wing_butterfly | 5 | 40.0% | ₹-203,892 | ₹-40,778 |


---
## Run #56
**Date**: 2026-04-16 23:53  
**Git**: `unknown`  
**Params**: 2009-01-01 to 2026-04-16 | Capital ₹500,000 | Lots 15

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | 10.19% |
| Total Return | 434.9% |
| Total P&L | ₹2,174,335 |
| Sharpe | 0.92 |
| Sortino | 0.54 |
| Calmar | 0.70 |
| Max Drawdown | 14.5% |
| Win Rate | 74.0% |
| Total Trades | 289 |
| Profit Factor | 2.07 |
| Avg P&L/Trade | ₹7,524 |
| Best Trade | ₹174,799 |
| Worst Trade | ₹-222,739 |
| Max Consec Wins | 14 |
| Max Consec Losses | 5 |

### Engine Stats
| Stat | Count |
|------|------:|
| ML Entries | 1235 |
| ML Skips | 1324 |
| Circuit Breaker Blocks | 645 |
| Smart Exits | 116 |
| Rule Exits | 173 |
| Multi-expiry Selections | 913 |

### Position Sizing (3-layer)
| Metric | Value |
|--------|------:|
| Sizing Decisions | 913 |
| Avg Final Lots | 25.4 |
| Avg Base Lots | 32.9 |
| Avg Confidence Scale | 1.2x |
| Avg Regime Scale | 0.814x |
| Avg DD Scale | 0.748x |

### Strategy Breakdown
| Strategy | Trades | Win Rate | Total P&L | Avg P&L |
|----------|-------:|---------:|----------:|--------:|
| adaptive:put_credit_spread | 159 | 69.2% | ₹616,109 | ₹3,875 |
| adaptive:iron_condor | 96 | 81.2% | ₹980,410 | ₹10,213 |
| adaptive:calendar_spread | 29 | 82.8% | ₹781,708 | ₹26,955 |
| adaptive:broken_wing_butterfly | 5 | 40.0% | ₹-203,892 | ₹-40,778 |
