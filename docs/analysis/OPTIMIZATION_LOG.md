# Nifty Options Backtester — Optimization Log

> **Purpose**: Machine-readable decision log for AI agents. Before making any
> change to entry/exit models, strategy selection, position sizing, or risk
> parameters, consult this file to understand what was tried and why it
> succeeded or failed.

## Finalized Production Configuration

| Component | Version | Key Parameters |
|-----------|---------|----------------|
| Entry Model | v4 | Walk-forward CV (5 folds, 21-day purge), nested feature selection, calibrated GBM, cost-adjusted binary labels, quality threshold 0.48 |
| Exit Model | v4.1 | GBM danger detector (62.6% F1, 80 features), ML backstop at 0.75 probability / -15% P&L |
| Exit Heuristics | v4.1 | VIX-adaptive step targets (60/50/40/30), trailing stops (25/35 and 40/20), 6% capital cap, circuit breaker |
| Strategies | v4.1 | PCS + IC + Calendar + BWB (4 strategies, regime-adaptive) |
| Position Sizing | v4.1 | 3-layer: margin-based → regime scale → DD protection |
| Risk Controls | v4.1 | Greeks caps (delta 6000, vega 60000), concentration 62%/20, starvation guard (min 4/quarter) |

### Production Metrics (17.3 years, 2009-2026)

| Metric | Value |
|--------|-------|
| CAGR | 13.78% |
| Max Drawdown | 5.8% |
| Calmar Ratio | 2.36 |
| Sharpe Ratio | 1.23 |
| Profit Factor | 3.11 |
| Win Rate | 65.6% |
| Total Trades | 273 |
| Payoff Ratio | 1.62x |

---

## Entry Model Evolution

### v1 → v2: Calibration + Quality Scoring

**What changed**: Added calibrated GBM (Platt scaling), per-regime models,
quality score (not just win/loss), per-strategy return regressors.

**Result**: Improved entry timing, reduced false positives.

**Why it worked**: Win/loss labels are trivially solvable for option selling
(~70% structural win rate). Quality scoring asks "is it a *good* trade?" which
is the harder, more valuable question.

### v2 → v3: Cost-Adjusted Labels + Iron Condor + Realistic Costs

**What changed**:
- Cost-adjusted binary label (P&L > cost hurdle, not percentile ranking)
- Single unified model with regime as a feature (not separate per-regime models)
- Added Iron Condor strategy
- Comprehensive Indian transaction cost model (STT, exchange, GST, stamp, SEBI, brokerage)
- Enhanced skew-aware B-S pricing (steeper put skew 0.35, 5% IV floor)
- Daily MTM P&L instead of entry-to-exit only
- Expanded to 30 features (from 20)

**Result**: CAGR 21.57% → but likely still overstated due to no walk-forward.

**Why it worked**: Cost-adjusted labels prevent the model from recommending
trades where costs eat the edge. Single model avoids data fragmentation
across 4 regimes (each having too few samples).

### v3 → v4: Walk-Forward + Portfolio Risk Controls

**What changed**:
- Rolling walk-forward CV (5 folds, 21-day purge) with nested feature selection
- Portfolio Greeks caps (delta, vega)
- Strategy concentration caps (62% max per strategy in last 20 trades)
- Normalized exit rules (% of max_risk, not fixed rupees)
- Volatility-scaled slippage (base + VIX-scaled + moneyness-scaled)
- Rebalanced strategy allocation
- Ablation and stress test modes

**Result**: CAGR dropped from 21.57% to 11.39% due to aggressive blocking.

**Why it worked for risk**: Max DD halved (16% → 8.5%), worst trade reduced.
Walk-forward eliminated look-ahead bias that inflated v3 metrics.

**Why CAGR dropped**: Greeks caps and concentration limits were too tight,
blocking too many valid trades.

### v4 → v4.1: Parameter Tuning (BEST VERSION)

**What changed**:
- Removed underperforming Ratio Put Spread strategy
- Relaxed Greeks caps by +20% (delta 5000→6000, vega 50000→60000)
- Added starvation guard (auto-loosen concentration if < 4 trades/quarter)
- Froze BWB to VIX > 18 only (conditional eligibility)

**Result**: CAGR 13.78%, DD 5.8%, Calmar 2.36 — optimal balance.

**Why it worked**: RPS removal eliminated a net-negative strategy. Relaxed
caps allowed more trades through without degrading risk. Starvation guard
prevented dead periods.

### v4.2-v4.6: Attempted Improvements (ALL REJECTED)

| Version | Change | CAGR | DD | Verdict |
|---------|--------|------|-----|---------|
| v4.2 | Relaxed concentration 68%/15, calendar VIX 12-20 | 13.96% | 14.9% | REJECT — DD tripled |
| v4.3 | Reverted concentration, kept calendar expansion | 12.98% | 16.0% | REJECT — calendar in high VIX hurt |
| v4.4 | Lowered ML threshold 0.48→0.46 | 13.78% | 5.8% | NO EFFECT — ML decisions far from threshold |
| v4.5 | Fixed hardcoded threshold in main.py | 13.78% | 5.8% | NO EFFECT — same root cause |
| v4.6 | Removed BWB entirely | 12.96% | 12.8% | REJECT — lost diversification |

**Key lessons**:
1. Loosening concentration allows bad trades through → DD explodes
2. Calendar spreads above VIX 18 are unprofitable
3. ML quality threshold is not the bottleneck (decisions cluster far from it)
4. Even marginal strategies (BWB, 8 trades) contribute to diversification

---

## Exit Model Evolution

### Original (v4.1 Baseline)

**Architecture**: GBM danger detector trained on simulated trade paths.
- Labels: observable danger signals (strike proximity, VIX spike, hard stop, theta stall) + 3-day forward P&L
- Features: 80 (market features from FeatureExtractor + 16 trade-state features)
- Engine use: ML backstop fires only at 0.75 probability AND -15% P&L loss
- Heuristic exits carry the load: capital cap → hard rules → VIX-adaptive targets → trailing stops → ML

### Exit v1: Aggressive ML Expansion (REJECTED)

**What changed**:
- Lowered ML stop threshold: 0.75→0.65, P&L gate: -15%→-10%
- Added ML profit-taking: 0.65 probability + 30%+ profit → exit
- Feature pruning: 80→25 features
- Walk-forward CV for exit model

**Result**: CAGR 11.83%, DD 17.1%, Calmar 0.69

**Why it failed**: The ML model's 62.6% F1 generates too many false exits.
Lowering thresholds caused premature stops on recovering trades AND
premature profit-taking that cut big winners short. Feature pruning
degraded model quality (62.6% → 62.0%).

### Exit v2: Conservative ML Profit-Taking (REJECTED)

**What changed**: ML profit-taking at 0.72/45%, stop reverted to 0.75/-15%, kept pruning.

**Result**: CAGR 12.57%, DD 8.2%, Calmar 1.54

**Why it failed**: Feature pruning (80→25) changed model behavior, reducing
quality. The pruned model lost nuance in danger detection.

### Exit v3: Removed Profit Labels from Training (REJECTED)

**What changed**: Reverted profit-taking labels (Signal C), kept everything else.

**Result**: Identical to v2 (12.57%, 8.2%) — profit-taking labels never fired
in training because simulated trades rarely reach 35%+ profit.

**Lesson**: Training data structure limits what labels can capture.

### Exit v4: Original Model + ML Profit-Taking (NEAR-BASELINE)

**What changed**: Reverted ALL training changes (no pruning, no walk-forward),
kept only ML profit-taking at 0.72/45% in engine.

**Result**: CAGR 13.76%, DD 5.9%, Calmar 2.32, Sharpe 1.23, PF 3.21

**Why it was close**: Original model (all 80 features, original training)
preserved model quality. ML profit-taking at 0.72/45% barely fires
(too restrictive to trigger often).

### Exit v5: Tight Trailing Stops + Velocity Exit (REJECTED)

**What changed**: Added 3rd trailing tier (50/12%), P&L velocity exit (-8%/day).

**Result**: CAGR 11.09%, DD 16.6%, Calmar 0.67

**Why it failed**: Tight trailing stops cut the fat right tail. A few big
winners that survive existing trailing stops account for disproportionate
P&L. Cutting them destroys returns.

### Exit v6: Regime-Aware Trailing (NO EFFECT)

**What changed**: Loosened trailing stops by 1.25x when VIX collapsing (vix_vs_sma < 0.85).

**Result**: Identical to v4 — condition fires too rarely to impact.

### Exit v7: Pure Baseline Confirmation

**What changed**: Removed ALL exit changes to confirm baseline.

**Result**: CAGR 13.78%, DD 5.8%, Calmar 2.36 — exact v4.1 baseline.

### Exit v8: Continuous VIX Targets + Stale Trade Exit (REJECTED)

**What changed**: Replaced step-function VIX targets with continuous formula,
added stale trade exit (DTE≤3, 0-15% P&L, 5+ days held).

**Result**: CAGR 13.00%, DD 11.8%, Calmar 1.10

**Why it failed**: The step-function VIX targets (60/50/40/30 at VIX
15/20/30) align with actual market regime boundaries better than any
smooth function. Stale trade exits close positions that would have
captured remaining theta acceleration near expiry.

---

## Rules for Future Changes

### DO NOT change these parameters (proven optimal via exhaustive testing):

1. **VIX-adaptive profit targets**: 60 (VIX<15), 50 (15-20), 40 (20-30), 30 (30+)
2. **VIX-adaptive stop losses**: 80 (VIX<15), 65 (15-20), 55 (20-30), 45 (30+)
3. **Trailing stops**: peak≥25 + drop>35%, peak≥40 + drop>20%
4. **ML exit threshold**: 0.75 probability + P&L < -15%
5. **Strategy concentration**: 62% max in last 20 trades
6. **Greeks caps**: delta 6000, vega 60000
7. **Entry quality threshold**: 0.48
8. **Exit model features**: keep all 80 (pruning hurts)
9. **Capital protection cap**: 6% of equity per trade

### IF you want to improve returns, focus on:

1. **New uncorrelated strategies** (e.g., Bank Nifty options, weekly expiry plays)
2. **Better entry timing** (more features, alternative ML architectures)
3. **Weekly expiry optimization** (different theta decay dynamics)
4. **Live paper trading validation** (B-S pricing likely overstates edge by 1-3%)

### IF you want to reduce risk further, focus on:

1. **Correlation-based exposure reduction** during global stress
2. **Intraday gap risk modeling**
3. **Margin-call simulation**
4. **Maximum absolute notional cap** (not just percentage-based)

---

## Architecture Summary (for AI agents)

```
main.py
  └─ run_backtest()
       ├─ [1] MarketDataFetcher → 4233 days, 80+ features
       ├─ [2] ExitStrategyEngine.train_from_simulations() → GBM danger detector
       ├─ [3] RegimeAwareLearner.train() → single GBM with regime features
       ├─ [4] SmartBacktestEngine.run()
       │     ├─ _ml_entry_check() → quality filter (threshold 0.48)
       │     ├─ PositionSizer.compute_lots() → 3-layer sizing
       │     ├─ Greeks/concentration caps → portfolio risk limits
       │     └─ _smart_exit_check()
       │           ├─ Capital protection (6%)
       │           ├─ Hard rules (strike proximity, VIX spike, crash)
       │           ├─ VIX-adaptive profit/stop targets
       │           ├─ Trailing stops (25/35, 40/20)
       │           └─ ML backstop (0.75 / -15%)
       └─ [5] BacktestReporter → HTML dashboard + metrics
```
