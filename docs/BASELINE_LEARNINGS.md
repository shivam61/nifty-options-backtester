# Baseline Learnings & Phase Transitions

**Document**: Standard format for recording findings and phase changes  
**Last Updated**: 2026-08-24  
**Baseline**: Run #59 (11.16% CAGR, rule-based)

---

## Phase History

### ✅ Phase 1: LightGBM Migration (Aug 23, 2026)

**Objective**: Replace sklearn GBM with LightGBM 4.6 for performance and parallel training

**Changes**:
- Migrated 6 model files (entry, exit, regime, position sizing)
- Added 18 trade-structure features (11 strategy flags + 7 metrics)
- Regularization: `num_leaves`, `colsample_bytree=0.8`, `n_jobs=-1`
- Parameter rename: `min_samples_leaf` → `min_child_samples`

**Results**:
| Stage | Framework | AUC |
|-------|-----------|-----|
| Before features | sklearn GBM | 0.554 |
| +18 features | sklearn GBM | 0.693 |
| +LightGBM | LightGBM 4.6 | **0.696** |

**Commits**: 
- `35f23aa` perf(ml): migrate all models from sklearn GBM → LightGBM 4.6
- `3743787` perf(ml): add num_leaves + colsample_bytree regularisation for LightGBM
- `1ccf44a` feat(ml): add 18 trade-structure features to break AUC ceiling

**Key Learnings**:
1. **Feature discovery**: ML models had no signal to distinguish strategies until trade-structure features added
   - Before: `(date, iron_butterfly)` and `(date, put_credit_spread)` identical feature vectors
   - After: 11 one-hot strategy flags + 7 continuous metrics enabled differentiation
2. **Regularization critical**: LightGBM leaf-wise growth needs explicit `num_leaves` constraint
3. **Parallel training**: LightGBM `n_jobs=-1` ~3x faster than sklearn GBM

**Status**: ✅ Complete | All tests passing (489/489)

---

### ✅ Phase 2: ETL Gate Tuning (Aug 23-24, 2026)

**Objective**: Fix aggressive ML-based weekly entry filtering

**Problem Identified**:
- `WeeklyRiskEngine` had hardcoded `1.0×` ETL threshold
- Blocked 78% of weekly entries (363/465) uniformly across all market regimes
- Collapsed trade volume without improving risk-adjusted returns
- Scikit-learn serialization version mismatch (1.8.0 → 1.5.0)

**Runs Tested**:
| Run | Label | CAGR | Strategy | Finding |
|-----|-------|------|----------|---------|
| #56 | v8 | 11.17% | 50/50 split, ML gate active | Good baseline |
| #57 | exp1 | 7.95% | 75% weekly / 25% monthly | Worse than 50/50 |
| #58 | v9 | 6.22% | ML ETL baseline | Gate blocking trades |
| #59 | v10 | **11.16%** | **Rule-based, no ML** | ✅ **Best** |

**Solution Implemented**:
- Deleted `weekly_risk_engine_v2.pkl` to force rule-based fallback
- Configured `WeeklyBacktestConfig.etl_skip_multiplier` (now 1.5× by default)
- Confirmed DTE validator [3,8] is independent rule-based mechanism

**Trade Distribution Shift** (v9 → v10):
| Metric | v9 | v10 | Change |
|--------|-----|------|--------|
| Large Winners (≥25k) | 12.7% | 24.5% | +93% |
| Median P&L | ₹193 | ₹9,772 | +4,965% |
| P90 | ₹12,065 | ₹110,320 | +814% |
| Large Losses (<-10k) | 40.7% | 19.6% | -52% |

**Commits**:
- `4458400` fix(weekly): disable ML ETL gate, return to rule-based weekly mode
- `4f8f3ba` feat(etl): configurable ETL skip multiplier + revert 50/50 split

**Key Learnings**:
1. **ML gating is double-edged**: Aggressive filtering (1.0×) blocks profitable trades uniformly
2. **Rule-based wins**: Simple circuit breakers (VIX zones, DTE windows, % stops) outperform complex ML scoring
3. **Capital utilization paradox**: v10 uses 43.1% capital but achieves best CAGR; v9 tried 64.9% and suffered
4. **Serialization risk**: Cross-version scikit-learn compatibility is real; consider version pinning in requirements
5. **Weekly strategy is sound**: 102 trades at 77.5% win rate shows core IC/PCS logic works

**Status**: ✅ Complete | Baseline v10 stable and documented

---

### ✅ Phase 3: Baseline Stabilization (Aug 24, 2026)

**Objective**: Consolidate findings, document standards, prepare for experiments

**Actions**:
- Committed all changes to main branch
- Created standardized backtest changelog format
- Verified ML model cache integrity
- Set up logs directory infrastructure
- Documented nohup workflow for long-running jobs
- Archived historical runs #3–#55

**Configuration Locked** (v10 baseline):
```python
# main.py run_backtest_combined()
_monthly_pct = 0.50      # 50% capital
_weekly_pct = 0.50       # 50% capital
etl_skip_multiplier = 1.5  # Weekly ETL gate

# config.py
entry_threshold = 0.50
monthly_entry_threshold = 0.50
vix_simultaneous_cap = 25.0
dd_kill_pct = 0.20
dd_recovery_pct = 0.16
```

**ML Models Cached**:
- `entry_model_v4.pkl` (1.9M) — LightGBM entry classifier
- `exit_model.pkl` (668K) — LightGBM exit classifier

**Documentation Created**:
- `BACKTEST_CHANGELOG.md` — Baseline runs #56-#59
- `docs/archive/ARCHIVED_RUNS.md` — Historical runs #3-#55
- `docs/BASELINE_LEARNINGS.md` — This file
- `docs/BACKTEST_COMBINED_MODE.md` — Technical reference

**Status**: ✅ Complete | Ready for experiments

---

## Key Metrics Summary (Baseline v10)

| Category | Metric | Value |
|----------|--------|-------|
| **Returns** | CAGR | 11.16% |
| | Total P&L | ₹2.57M |
| | Best Trade | ₹200,787 |
| | Worst Trade | ₹-53,255 |
| **Risk** | Max Drawdown | 6.9% |
| | Sharpe Ratio | 1.05 |
| | Sortino Ratio | 2.23 |
| | Calmar Ratio | 1.62 |
| **Quality** | Win Rate | 59.2% |
| | Profit Factor | 4.47 |
| | Monthly Trades | 315 (53.3% WR) |
| | Weekly Trades | 102 (77.5% WR) |
| **Utilization** | Capital Used | 43.1% |
| | VIX Gate Blocks | 11 |

---

## Next Phase: Dynamic VIX Allocation Experiments

**Objective**: Improve from 11.16% → 14–16% CAGR via dynamic capital rebalancing

**Hypothesis**: Market regimes affect optimal capital allocation
- VIX < 18 (low vol) → 80% weekly / 20% monthly (aggressive)
- VIX 18–22 (normal) → 50% weekly / 50% monthly (balanced, current)
- VIX > 22 (high vol) → 30% weekly / 70% monthly (defensive)

**Experimental Design**:
1. Test dynamic allocation without changing ML models or risk rules
2. Measure if regime-driven rebalancing exceeds 11.16% baseline
3. If successful: document new allocation weights
4. If not: confirm 50/50 static split is production-ready optimum

**Expected Runs**: #60–#65 (parametric sweep)

---

## Standardized Backtest Run Format

Every new backtest run should include:

### Header
```markdown
## Run #X — <label> — [COMBINED|MONTHLY|WEEKLY]
**Date**: YYYY-MM-DD HH:MM  
**Git**: <commit hash>  
**Params**: <start> to <end> | Capital ₹<amount> | Lots <n>
```

### Key Metrics (table)
- CAGR, Total P&L, Win Rate, Max Drawdown, Sharpe, Sortino, Calmar
- Monthly/Weekly P&L, Win Rates
- Profit Factor, Best/Worst Trade

### Engine Stats (table)
- Monthly Trades, Weekly Trades
- Gate blocks (VIX, cap, DD)
- Capital Utilization %

### Trade Distribution (weekly only)
- Bucket analysis: Large Loss → Small Win → Large Win
- Median, P10/P90
- Top 5 winners and losers

### Phase Notes (when applicable)
- What changed from prior run
- Key findings or surprises
- Recommendation for next phase

---

## File Organization

```
nifty-options-backtester/
├── BACKTEST_CHANGELOG.md           ← Current baseline runs #56-#59
├── backtest_runs.jsonl              ← Machine-readable run metadata
├── docs/
│   ├── BASELINE_LEARNINGS.md       ← This file
│   ├── BACKTEST_COMBINED_MODE.md   ← Technical reference
│   ├── archive/
│   │   ├── ARCHIVED_RUNS.md        ← Historical runs #3-#55
│   │   └── README.md
│   ├── analysis/                    ← Experimental analyses
│   └── architecture/
├── logs/                            ← Long-running job logs (gitignored)
└── data/
    ├── .cache/
    │   ├── entry_model_v4.pkl
    │   ├── exit_model.pkl
    │   └── ...
    └── backtest_results.parquet     ← Trade-level data from last backtest
```

---

## Git Workflow Policy

**After every logical unit of work**:
1. `git add <changed files>`
2. `git commit -m "type(scope): description"` with conventional commits
3. `git push origin main` immediately

**For long-running jobs** (> 5 min):
```bash
nohup python3 main.py --mode backtest-combined --run-label "exp_name" \
  > logs/backtest_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "PID=$!"
```

**Never leave uncommitted edits at session end.**

---

## Quick Reference: Configuration Constants

| Parameter | Value | Location | Role |
|-----------|-------|----------|------|
| `lot_size` | 65 | `config.BacktestConfig` | Nifty lot standard |
| `initial_capital` | ₹500k | `config.BacktestConfig` | Base capital |
| `entry_threshold` | 0.50 | `config.BacktestConfig` | ML gate (monthly) |
| `monthly_max_lots_cap` | 30 | `CombinedBacktestEngine` | Safety limit |
| `monthly_budget_pct` | 50% | `main.py` | Capital allocation |
| `weekly_budget_pct` | 50% | `main.py` | Capital allocation |
| `mid_session_intraday_alpha` | 0.40 | `config.BacktestConfig` | 11 AM fill proxy |
| `vix_simultaneous_cap` | 25.0 | `run_backtest_combined()` | Weekly VIX gate |
| `dd_kill_pct` | 20% | `ProductionRulesConfig` | Drawdown kill-switch |
| `dd_recovery_pct` | 16% | `ProductionRulesConfig` | Drawdown recovery |
| `etl_skip_multiplier` | 1.5 | `WeeklyBacktestConfig` | Weekly ETL gate (configurable) |

---

## Appendix: Previous Phase Mistakes (Avoid)

1. **❌ Hardcoded ML thresholds** → Use configurable parameters instead
2. **❌ Ignoring capital utilization** → Low util + high CAGR often better than vice versa
3. **❌ Aggressive filtering without validation** → Test gate impact separately
4. **❌ Skipping feature engineering** → Trade-structure features were critical breakthrough
5. **❌ Mixing sklearn versions** → Pin versions in requirements.txt
6. **❌ Not pushing to git immediately** → Session crashes lose work; always push

---

## Contact / Questions

For experimental updates or phase transitions, update this file with:
- Run number and baseline comparison
- Changes made (with git commits)
- Key metrics and learnings
- Next phase recommendation
