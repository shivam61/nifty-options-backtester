# Phase 4 Plan: Dynamic VIX-Regime Capital Allocation Experiments

**Start Date**: 2026-08-29  
**Baseline**: Run #59 (v10: 11.16% CAGR, rule-based weekly)  
**Goal**: Improve CAGR from 11.16% → 14–16% via dynamic capital rebalancing  
**Status**: Ready to launch experiments

---

## Executive Summary

**Hypothesis**: Optimal capital allocation between monthly (50%) and weekly (50%) tracks changes with market volatility regime. During low-VIX periods, weekly strategies generate more alpha; during high-VIX, monthly strategies hedge better.

**Experimental Design**: 3 backtests (runs #60–#62) testing regime-based capital shifts:
- **Run #60**: VIX < 18 → 80% weekly / 20% monthly (aggressive)
- **Run #61**: VIX > 22 → 30% weekly / 70% monthly (defensive)
- **Run #62**: Full dynamic blend (all regimes) with smooth transitions

**Success Criteria**: Any run > 11.16% CAGR = improvement

**Expected Timeline**: 2–3 backtests (each ~10 min on current hardware)

---

## Phase 4A: Baseline Model Preservation

### Step 1: Backup Current Models

**Location**: `data/.cache/`

```bash
# Create backup directory
mkdir -p data/.cache/baseline_v10_backup

# Copy all v10 baseline models
cp data/.cache/entry_model_v4.pkl data/.cache/baseline_v10_backup/
cp data/.cache/exit_model.pkl data/.cache/baseline_v10_backup/

# Verify backup
ls -lh data/.cache/baseline_v10_backup/
```

**Why**: If experiments show degradation, we can instantly revert to v10 by restoring these files.

### Step 2: Document Model Metadata

**Create**: `data/.cache/baseline_v10_backup/README.md`

```markdown
# Baseline v10 Model Backup

**Date**: 2026-08-29  
**Baseline Run**: #59 (v10-no-etl-gate-ruledbased)  
**Git Commit**: 4458400  
**CAGR**: 11.16%  
**Sharpe**: 1.05  

## Files
- `entry_model_v4.pkl` (1.9M) — LightGBM entry classifier (AUC 0.696)
- `exit_model.pkl` (668K) — LightGBM exit classifier

## Revert Instructions
```bash
cp data/.cache/baseline_v10_backup/entry_model_v4.pkl data/.cache/
cp data/.cache/baseline_v10_backup/exit_model.pkl data/.cache/
```

## Notes
- No retraining needed after restore
- Tested 17-year backtest (2009-2026)
- Rule-based weekly entries (no ML ETL gate)
```

### Step 3: Tag in Git

```bash
# Commit baseline backup
git add data/.cache/baseline_v10_backup/
git commit -m "chore(baseline): backup v10 models before Phase 4 experiments

Preserve entry_model_v4.pkl (AUC 0.696) and exit_model.pkl
before running dynamic VIX allocation experiments (runs #60-#62).

If experiments degrade performance, restore with:
  cp data/.cache/baseline_v10_backup/*.pkl data/.cache/

Baseline: Run #59 (11.16% CAGR)
Git: 4458400"

# Tag for easy reference
git tag baseline_v10_locked -m "v10: 11.16% CAGR, rule-based weekly, LightGBM ML models"
git push origin main --tags
```

---

## Phase 4B: Experiment Configuration

### Experiment A: VIX < 18 (Low-Volatility Aggressive)

**File to Modify**: `main.py` in `run_backtest_combined()` function

```python
# BEFORE (baseline v10)
_monthly_pct = 0.50
_weekly_pct = 0.50

# AFTER (exp A)
def get_dynamic_allocation(current_vix):
    """Allocate capital based on VIX regime."""
    if current_vix < 18:
        return 0.20, 0.80  # 20% monthly, 80% weekly (aggressive)
    elif current_vix > 22:
        return 0.70, 0.30  # 70% monthly, 30% weekly (defensive)
    else:
        return 0.50, 0.50  # 50/50 (balanced, baseline)

# In backtest loop:
monthly_pct, weekly_pct = get_dynamic_allocation(current_vix)
```

**Rationale**: 
- Low VIX = high confidence in trend-following (weekly premium decay)
- High VIX = tail-risk hedging (monthly protective spreads)
- Smooth transitions between regimes

### Experiment B: VIX > 22 (High-Volatility Defensive)

**Same code as Experiment A** — the function handles all regimes automatically.

### Experiment C: Full Dynamic Blend (All Regimes)

**Same code as Experiment A** — tests all three VIX bands simultaneously across 17-year backtest.

---

## Phase 4C: Experiment Launch Sequence

### Run #60: VIX < 18 Allocation (Aggressive)

```bash
# 1. Update main.py with dynamic allocation function
#    (copy code from Phase 4B section above)

# 2. Run backtest with nohup (long-running job)
nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_aggressive_80_20" \
  > logs/backtest_exp2_$(date +%Y%m%d_%H%M).log 2>&1 &

# Capture PID for reference
echo "Run #60 started with PID $!"

# 3. Monitor progress
tail -f logs/backtest_exp2_*.log

# 4. Check results when complete
grep "CAGR\|Sharpe\|Max Drawdown\|Win Rate" logs/backtest_exp2_*.log
tail -50 BACKTEST_CHANGELOG.md
```

**Expected Run Time**: ~10 minutes (17-year backtest on current hardware)

**Checkpoint**: 
- CAGR > 11.16% → Move to Run #61
- CAGR < 11.16% → Investigate (check Phase 4D diagnostics)

### Run #61: VIX > 22 Allocation (Defensive)

**No code changes** — same dynamic allocation function, but will naturally select 30/70 split when VIX > 22.

```bash
# 1. Code already in place (from Run #60)

# 2. Run backtest
nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_defensive_30_70" \
  > logs/backtest_exp2_def_$(date +%Y%m%d_%H%M).log 2>&1 &

echo "Run #61 started"

# 3. Monitor
tail -f logs/backtest_exp2_def_*.log

# 4. Check results
grep "CAGR\|Sharpe\|Max Drawdown" logs/backtest_exp2_def_*.log
```

**Checkpoint**:
- CAGR > 11.16% → Move to Run #62 (full blend test)
- CAGR < 11.16% for both #60 and #61 → 50/50 static is optimal, document learnings

### Run #62: Full Dynamic Blend (All Regimes Combined)

**Same code** — tests the complete dynamic allocation function across entire 17-year history.

```bash
# 1. Code already in place

# 2. Run backtest (full dynamic with smooth transitions)
nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_full_blend" \
  > logs/backtest_exp2_blend_$(date +%Y%m%d_%H%M).log 2>&1 &

echo "Run #62 (full dynamic blend) started"

# 3. Monitor
tail -f logs/backtest_exp2_blend_*.log

# 4. Check final results
grep "CAGR\|Sharpe\|Max Drawdown\|Win Rate\|Profit Factor" logs/backtest_exp2_blend_*.log
tail -100 BACKTEST_CHANGELOG.md | head -50
```

---

## Phase 4D: Decision Framework

### After Run #60 Results

```
IF Run #60 CAGR > 11.16%:
  ├─ Analysis: VIX < 18 aggressive allocation improves performance
  └─ Decision: Continue to Run #61 to test defensive regime

ELSE IF Run #60 CAGR < 11.16%:
  ├─ Analysis: Aggressive allocation underperforms baseline
  ├─ Diagnostics: Check weekly trade volume, monthly risk events
  └─ Decision: May skip to Run #62 if deficit is small (-0.5% acceptable)
```

### After Run #61 Results

```
IF Run #61 CAGR > 11.16%:
  ├─ Analysis: Defensive allocation improves performance
  ├─ Interpretation: At least one regime-based shift works
  └─ Decision: Proceed to Run #62 (full blend) to validate combined strategy

ELSE IF both Run #60 and Run #61 < 11.16%:
  ├─ Analysis: Static 50/50 is better than any dynamic split
  ├─ Conclusion: Capital allocation is not the limiting factor
  ├─ Next Direction: Try Experiment B (Entry Threshold Sweep)
  └─ Decision: Document findings and archive Phase 4

ELSE (mixed results):
  ├─ Analysis: Some regimes work, others don't
  └─ Decision: Proceed to Run #62 to see blended effect
```

### After Run #62 Results

```
IF Run #62 CAGR > 11.16% AND > Run #59, #60, #61:
  ├─ Analysis: Full dynamic blend outperforms all static splits
  ├─ Outcome: SUCCESS — Document new allocation weights
  ├─ Next: Test stability (Run #63: add transaction costs)
  └─ Decision: Consider for production

ELSE IF Run #62 CAGR > 11.16% but < max(#60, #61):
  ├─ Analysis: Best single-regime > blended dynamic
  ├─ Interpretation: Smooth transitions may be suboptimal
  └─ Next: Try step-based transitions instead of smooth

ELSE (Run #62 < 11.16%):
  ├─ Conclusion: Dynamic allocation doesn't improve baseline
  ├─ Recommendation: 50/50 static is production-ready optimal
  └─ Phase 4 Complete: Archive and plan Phase 5
```

---

## Phase 4E: Results Tracking

### Update BACKTEST_CHANGELOG.md

After each run completes:

```markdown
## Run #60 — exp2_dynamic_vix_aggressive_80_20 — [COMBINED]
**Date**: YYYY-MM-DD HH:MM  
**Git**: [commit hash]  
**Params**: 2009-01-01 to 2026-08-29 | Capital ₹500,000 | Lots 15 | **Dynamic VIX < 18**

### Key Metrics
| Metric | Value |
|--------|------:|
| CAGR | X.XX% |
| Total P&L | ₹X,XXX,XXX |
| Sharpe | X.XX |
| Max Drawdown | X.X% |
| Win Rate | XX.X% |

### Experiment Notes
- Allocation: 80% weekly / 20% monthly (VIX < 18 regime)
- Days in VIX < 18: X% of backtest period
- Avg weekly allocation: XX% | Avg monthly allocation: XX%
- Comparison to baseline: +X.XX% (+183% baseline vs v9)
```

### Create Comparison Table

After all 3 runs, add to docs/EXPERIMENT_INDEX.md:

```markdown
## Phase 4 Experiment Results (Runs #60–#62)

| Run | Label | Strategy | CAGR | Sharpe | Win Rate | Change vs Baseline |
|-----|-------|----------|------|--------|----------|-------------------|
| #59 | v10 | Static 50/50 | 11.16% | 1.05 | 59.2% | Baseline ✓ |
| #60 | exp2_aggressive | Dynamic 80/20 (VIX<18) | ?.??% | ?.?? | ??.?% | +X.XX% |
| #61 | exp2_defensive | Dynamic 30/70 (VIX>22) | ?.??% | ?.?? | ??.?% | +X.XX% |
| #62 | exp2_blend | Full dynamic | ?.??% | ?.?? | ??.?% | +X.XX% |
```

---

## Phase 4F: Key Metrics to Track

For each run, monitor:

1. **CAGR** — Primary success metric (target: > 11.16%)
2. **Sharpe Ratio** — Risk-adjusted returns (target: > 1.05)
3. **Win Rate** — Profitability consistency (target: > 59%)
4. **Profit Factor** — Win/loss ratio (target: > 4.47)
5. **Capital Utilization** — % of capital deployed (baseline: 43.1%)
6. **Monthly Trades** — Should remain stable (~315)
7. **Weekly Trades** — Should remain stable (~102)
8. **Max Drawdown** — Risk control (target: < 7%)
9. **Trade Distribution** — Winners vs losers (baseline: 24.5% large wins)
10. **VIX Regime Days** — % of backtest in each regime

---

## Phase 4G: Contingency Plans

### If Hardware/Runtime Issues Occur

```bash
# Kill a stuck backtest
kill -9 <PID>

# Check nohup output for errors
cat logs/backtest_exp2_*.log | tail -100

# Restart from checkpoint (if implemented)
python main.py --mode backtest-combined --resume-run 60

# If no resume support, restart fresh:
rm -f data/backtest_results.parquet  # Clear partial results
nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_aggressive_80_20_retry" \
  > logs/backtest_exp2_retry_$(date +%Y%m%d_%H%M).log 2>&1 &
```

### If Baseline Models Corrupt

```bash
# Restore from backup
cp data/.cache/baseline_v10_backup/entry_model_v4.pkl data/.cache/
cp data/.cache/baseline_v10_backup/exit_model.pkl data/.cache/

# Verify restoration
python3 -c "import pickle; pickle.load(open('data/.cache/entry_model_v4.pkl', 'rb')); print('✓ Model restored')"

# Re-run backtest
nohup python3 main.py --mode backtest-combined ...
```

### If Results Unexpected

```bash
# Run diagnostic backtest with verbose logging
python main.py --mode backtest-combined --run-label "diagnostic" --verbose > diagnostic.log 2>&1

# Check VIX regime distribution
python3 -c "
import pandas as pd
data = pd.read_parquet('data/backtest_results.parquet')
print('VIX Regimes:')
print(data['vix'].describe())
print('Allocation distribution:')
print(data[['monthly_alloc_pct', 'weekly_alloc_pct']].describe())
"
```

---

## Phase 4H: Git Workflow

### Before Each Experiment

```bash
# Create feature branch
git checkout -b feat/phase4_exp2_vix_regimes

# Commit code changes
git add main.py config.py
git commit -m "feat(phase4): add dynamic VIX-regime capital allocation

Implement get_dynamic_allocation() function:
- VIX < 18: 80% weekly / 20% monthly (aggressive)
- VIX 18-22: 50% weekly / 50% monthly (baseline)
- VIX > 22: 30% weekly / 70% monthly (defensive)

Ready for Run #60-#62 experiments.
Baseline models backed up to data/.cache/baseline_v10_backup/"

git push origin feat/phase4_exp2_vix_regimes
```

### After Experiments Complete

```bash
# Merge feature branch
git checkout main
git pull origin main
git merge feat/phase4_exp2_vix_regimes --no-ff

# Create experiment results commit
git add BACKTEST_CHANGELOG.md docs/EXPERIMENT_INDEX.md
git commit -m "results(phase4): runs #60-#62 dynamic VIX allocation experiments

Exp Summary:
- Run #60 (exp2_aggressive): CAGR X.XX% | Sharpe X.XX
- Run #61 (exp2_defensive): CAGR X.XX% | Sharpe X.XX
- Run #62 (exp2_blend): CAGR X.XX% | Sharpe X.XX

Winner: Run #X (X.XX% CAGR, +X.XX% vs baseline 11.16%)

Analysis: [key findings]

Next Phase: [Phase 5 plan or confirmation that 50/50 is optimal]"

git push origin main
git tag phase4_experiments_complete -m "Phase 4: Dynamic VIX allocation experiments (runs #60-#62)"
git push origin main --tags
```

---

## Phase 4I: Success Criteria & Next Phase Decision

### If Phase 4 Succeeds (Any Run > 11.16%)

**Action**: Document new optimal allocation weights

```markdown
## Phase 4 Outcome: SUCCESS ✓

**Winning Configuration**: Run #X (exp2_dynamic_[regime])
- CAGR: X.XX% (+X.XX% vs baseline 11.16%)
- Allocation Strategy: [Dynamic VIX < 18 / > 22 / Full Blend]
- Stability: Tested 17-year history, consistent improvements

**New Recommended Config**:
```python
def get_dynamic_allocation(current_vix):
    if current_vix < 18:
        return 0.20, 0.80   # [or new optimal split]
    elif current_vix > 22:
        return 0.70, 0.30   # [or new optimal split]
    else:
        return 0.50, 0.50
```

**Next Phase (Phase 5)**: Stress test new allocation
- Add transaction costs (slippage impact)
- Test on new 2026 data (out-of-sample validation)
- Consider production deployment
```

### If Phase 4 Fails (All Runs ≤ 11.16%)

**Action**: Confirm 50/50 is optimal, plan Phase 5

```markdown
## Phase 4 Outcome: STATIC 50/50 IS OPTIMAL ✓

**Conclusion**: Dynamic VIX-regime allocation does not improve baseline.

**Tested**:
- Run #60: VIX < 18 (80% weekly / 20% monthly) → X.XX% CAGR
- Run #61: VIX > 22 (30% weekly / 70% monthly) → X.XX% CAGR
- Run #62: Full dynamic blend → X.XX% CAGR

**Result**: All ≤ 11.16% baseline

**Interpretation**: 
- Capital allocation is not the performance limiting factor
- Rule-based weekly + LightGBM monthly works well at 50/50 split
- Improvements must come from other levers (entry timing, exit logic, strategy selection)

**Next Phase (Phase 5)**: Entry Threshold Sweep
- Vary `monthly_entry_threshold` (0.40 → 0.60)
- Test if tighter/looser ML gates improve CAGR
- 50/50 capital allocation locked in
```

---

## Timeline & Checkpoints

| Date | Checkpoint | Status |
|------|-----------|--------|
| 2026-08-29 | Phase 4 plan created | ✓ Ready |
| 2026-08-29 | Baseline models backed up | Pending |
| 2026-08-29 | Dynamic allocation code written | Pending |
| **2026-08-29** | **Run #60 executed** | **⏳ In Progress** |
| 2026-08-29 | Run #60 results analyzed | Pending |
| 2026-08-29 | Run #61 executed (if #60 promising) | Pending |
| 2026-08-30 | Run #62 executed (if #61 promising) | Pending |
| 2026-08-30 | Phase 4 complete, results documented | Pending |
| 2026-08-30 | Decision: Phase 5 or production | Pending |

---

## Quick Reference: Command Checklist

```bash
# Backup models
mkdir -p data/.cache/baseline_v10_backup
cp data/.cache/*.pkl data/.cache/baseline_v10_backup/
git add data/.cache/baseline_v10_backup/
git commit -m "chore(baseline): backup v10 models"

# Create feature branch
git checkout -b feat/phase4_exp2_vix_regimes

# Update code (main.py), then test
python3 -c "from main import get_dynamic_allocation; print(get_dynamic_allocation(15))"

# Run experiments
nohup python3 main.py --mode backtest-combined --run-label "exp2_dynamic_vix_aggressive_80_20" > logs/backtest_exp2_$(date +%Y%m%d_%H%M).log 2>&1 &

# Monitor
tail -f logs/backtest_exp2_*.log

# Check results
grep "CAGR\|Sharpe" logs/backtest_exp2_*.log
tail -100 BACKTEST_CHANGELOG.md

# Commit results
git add BACKTEST_CHANGELOG.md
git commit -m "results(phase4): run #60 dynamic VIX aggressive allocation"
git push origin feat/phase4_exp2_vix_regimes

# Merge & tag
git checkout main && git pull
git merge feat/phase4_exp2_vix_regimes
git tag phase4_experiments_complete
git push origin main --tags
```

---

## Notes

- **No retrain needed**: ML models (entry_model_v4.pkl, exit_model.pkl) remain unchanged
- **Only config changes**: Dynamic allocation happens at runtime in `run_backtest_combined()`
- **Reversible**: If results degrade, restore from baseline_v10_backup/
- **Fast iterations**: Each run ~10 min, so 3 runs in ~30 min total
- **Clear decision**: After #62, we'll know if dynamic beats static 50/50

---

**Status**: ✅ Plan Ready | 🔄 Awaiting Model Backup & Experiment Launch
