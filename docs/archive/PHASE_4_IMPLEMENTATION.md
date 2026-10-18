# Phase 4 Implementation Guide: Dynamic VIX Allocation

**Status**: Ready to implement and test  
**Baseline Models**: Backed up to `data/.cache/baseline_v10_backup/` (2.6M, verified)  
**Target**: Runs #60-#62 (dynamic capital allocation experiments)  
**Expected Runtime**: ~30 minutes total (3 backtests × ~10 min each)

---

## Step 1: Add Dynamic Allocation Function

**File**: `main.py`

Find the `run_backtest_combined()` function and add this code block:

```python
def get_dynamic_allocation(current_vix):
    """
    Allocate capital between monthly and weekly tracks based on VIX regime.
    
    Logic:
    - VIX < 18 (low vol): 80% weekly, 20% monthly (aggressive, trend-following)
    - VIX 18-22 (normal): 50% weekly, 50% monthly (balanced, baseline)
    - VIX > 22 (high vol): 30% weekly, 70% monthly (defensive, hedging)
    
    Args:
        current_vix (float): Current India VIX value
        
    Returns:
        tuple: (monthly_pct, weekly_pct) where both are floats summing to 1.0
    """
    if current_vix < 18:
        # Low volatility: aggressive weekly dominance
        return 0.20, 0.80
    elif current_vix > 22:
        # High volatility: defensive monthly dominance
        return 0.70, 0.30
    else:
        # Normal: balanced baseline
        return 0.50, 0.50
```

**Where to add**: Right before `run_backtest_combined()` function definition (around line 150-200)

---

## Step 2: Integrate into Backtest Loop

**Inside `run_backtest_combined()`**, replace the static allocation with dynamic:

### Before (Baseline v10):
```python
_monthly_pct = 0.50
_weekly_pct = 0.50

# ... later in the loop ...
monthly_capital = total_capital * _monthly_pct
weekly_capital = total_capital * _weekly_pct
```

### After (Phase 4):
```python
# Remove the static allocation lines above

# ... in the backtest day loop ...
for day in backtest_dates:
    current_vix = market_data.loc[day, 'india_vix']
    _monthly_pct, _weekly_pct = get_dynamic_allocation(current_vix)
    
    monthly_capital = total_capital * _monthly_pct
    weekly_capital = total_capital * _weekly_pct
    
    # Rest of backtest logic continues unchanged
```

**Key Point**: The VIX value is read from market data daily; allocation automatically adjusts.

---

## Step 3: Test Code Before Running

```bash
# Quick syntax check
python3 -c "
from main import get_dynamic_allocation

# Test all three regimes
print('VIX=15 (low):', get_dynamic_allocation(15))    # Should be (0.2, 0.8)
print('VIX=20 (normal):', get_dynamic_allocation(20)) # Should be (0.5, 0.5)
print('VIX=25 (high):', get_dynamic_allocation(25))   # Should be (0.7, 0.3)
"

# Expected output:
# VIX=15 (low): (0.2, 0.8)
# VIX=20 (normal): (0.5, 0.5)
# VIX=25 (high): (0.7, 0.3)
```

If output matches, code is correct. ✓

---

## Step 4: Create Feature Branch

```bash
git checkout -b feat/phase4_exp2_vix_regimes

git add main.py config.py  # (if config changes too)

git commit -m "feat(phase4): implement dynamic VIX-regime capital allocation

Add get_dynamic_allocation() function:
  - VIX < 18: 80% weekly / 20% monthly (aggressive)
  - VIX 18-22: 50% weekly / 50% monthly (baseline)
  - VIX > 22: 30% weekly / 70% monthly (defensive)

Allocations computed daily from India VIX level during backtest.
No ML model changes. No retrain needed.

Ready for runs #60-#62."

git push origin feat/phase4_exp2_vix_regimes
```

---

## Step 5: Run Experiment #60 (Aggressive)

```bash
# Launch backtest in background
nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_aggressive_80_20" \
  > logs/backtest_exp2_$(date +%Y%m%d_%H%M).log 2>&1 &

# Capture the PID
echo "Run #60 PID: $!"

# Immediately start monitoring in another terminal/tab
tail -f logs/backtest_exp2_*.log
```

**Typical Output** (watch for these messages):
```
[INFO] Starting backtest: exp2_dynamic_vix_aggressive_80_20
[INFO] Date range: 2009-01-01 to 2026-08-29
[INFO] Initial capital: ₹500000
[DEBUG] 2009-01-01: VIX=15 → Monthly=20%, Weekly=80% (aggressive)
[DEBUG] 2020-03-15: VIX=85 → Monthly=70%, Weekly=30% (defensive)
[DEBUG] Daily loop: 4500+ days processed...
[INFO] Backtest complete in 10m 23s
[INFO] Run #60 Results appended to BACKTEST_CHANGELOG.md
```

**Checkpoint**: Check results after ~10 minutes

```bash
# Quick check
grep "CAGR\|Sharpe\|Win Rate" logs/backtest_exp2_*.log

# Full results
tail -50 BACKTEST_CHANGELOG.md
```

---

## Step 6: Analyze Run #60 Results

```python
# Python snippet to load and analyze
import pandas as pd
import json

# Read from BACKTEST_CHANGELOG.md or backtest_runs.jsonl
results = json.load(open('backtest_runs.jsonl'))
run_60 = results[-1]  # Latest run

print(f"Run #60 Results:")
print(f"  CAGR: {run_60['metrics']['cagr_pct']:.2f}%")
print(f"  Baseline: 11.16%")
print(f"  Improvement: {run_60['metrics']['cagr_pct'] - 11.16:+.2f}%")
print(f"  Sharpe: {run_60['metrics']['sharpe']:.2f}")
print(f"  Win Rate: {run_60['metrics']['win_rate_pct']:.1f}%")

# Decision
if run_60['metrics']['cagr_pct'] > 11.16:
    print("\n✓ Run #60 OUTPERFORMS baseline → Proceed to Run #61")
else:
    print("\n✗ Run #60 underperforms → Check diagnostics")
```

---

## Step 7: Run Experiment #61 (Defensive) — If #60 Promising

```bash
# No code changes needed! Same dynamic allocation function.
# The function automatically selects 30/70 split when VIX > 22.

nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_defensive_30_70" \
  > logs/backtest_exp2_def_$(date +%Y%m%d_%H%M).log 2>&1 &

echo "Run #61 PID: $!"

# Monitor
tail -f logs/backtest_exp2_def_*.log

# Check after ~10 min
grep "CAGR\|Sharpe" logs/backtest_exp2_def_*.log
```

---

## Step 8: Run Experiment #62 (Full Blend) — If #61 Promising

```bash
# Same code, same dynamic allocation function.
# This tests the complete algorithm across all 17 years with smooth transitions.

nohup python3 main.py --mode backtest-combined \
  --run-label "exp2_dynamic_vix_full_blend" \
  > logs/backtest_exp2_blend_$(date +%Y%m%d_%H%M).log 2>&1 &

echo "Run #62 (Full Blend) PID: $!"

# Monitor
tail -f logs/backtest_exp2_blend_*.log

# Check results
grep "CAGR\|Sharpe\|Max Drawdown\|Profit Factor" logs/backtest_exp2_blend_*.log
```

---

## Step 9: Compare All Runs

After all 3 complete, create comparison:

```bash
# Extract metrics from changelog
grep -A 20 "## Run #5[0-9] —" BACKTEST_CHANGELOG.md | grep "CAGR\|Sharpe\|Win Rate\|Profit Factor"

# Or create manual table:
cat > PHASE_4_RESULTS.txt << 'EOF'
| Run | Label | CAGR | Sharpe | Win Rate | Status |
|-----|-------|------|--------|----------|--------|
| #59 | v10_baseline_50_50 | 11.16% | 1.05 | 59.2% | ✓ |
| #60 | exp2_aggressive_80_20 | ?.??% | ?.?? | ??.?% | |
| #61 | exp2_defensive_30_70 | ?.??% | ?.?? | ??.?% | |
| #62 | exp2_full_blend | ?.??% | ?.?? | ??.?% | |
EOF

cat PHASE_4_RESULTS.txt
```

---

## Step 10: Commit Final Results

```bash
# After all 3 runs complete
git add BACKTEST_CHANGELOG.md docs/EXPERIMENT_INDEX.md PHASE_4_RESULTS.txt

git commit -m "results(phase4): runs #60-#62 dynamic VIX allocation complete

**Experiment Summary**:
  Run #60 (exp2_aggressive): CAGR X.XX% | Sharpe X.XX | [PASS/FAIL]
  Run #61 (exp2_defensive): CAGR X.XX% | Sharpe X.XX | [PASS/FAIL]
  Run #62 (exp2_full_blend): CAGR X.XX% | Sharpe X.XX | [PASS/FAIL]

**Baseline Comparison**:
  Baseline v10: 11.16% CAGR (50/50 static)
  Best Run: Run #[X] with X.XX% CAGR (+X.XX%)

**Conclusion**: [Dynamic allocation improves / confirms 50/50 is optimal]

**Next Phase**: [Phase 5 direction / production deployment]

Baseline models preserved in data/.cache/baseline_v10_backup/
All code changes reversible by reverting feature branch."

git push origin feat/phase4_exp2_vix_regimes
```

---

## Step 11: Merge to Main & Tag

```bash
# Switch to main and merge
git checkout main
git pull origin main
git merge feat/phase4_exp2_vix_regimes --no-ff -m "Merge Phase 4 dynamic VIX allocation experiments"

# Create release tag
git tag phase4_experiments_complete -m "Phase 4 complete: Dynamic VIX allocation (runs #60-#62)"

# Push everything
git push origin main --tags

# Optional: Delete feature branch locally and remote
git branch -d feat/phase4_exp2_vix_regimes
git push origin --delete feat/phase4_exp2_vix_regimes
```

---

## Troubleshooting

### If Backtest Hangs
```bash
# Check process
ps aux | grep "python3 main.py"

# Kill if needed
kill -9 <PID>

# Check for errors
tail -100 logs/backtest_exp2_*.log
```

### If Models Corrupt
```bash
# Restore from backup
cp data/.cache/baseline_v10_backup/*.pkl data/.cache/

# Verify
python3 -c "import pickle; print(type(pickle.load(open('data/.cache/entry_model_v4.pkl', 'rb'))))"

# Restart backtest
nohup python3 main.py --mode backtest-combined --run-label "retry" > logs/backtest_retry.log 2>&1 &
```

### If Results Unexpected
```bash
# Run diagnostic with verbose logging
python main.py --mode backtest-combined --run-label "diagnostic" --verbose 2>&1 | tee diagnostic.log

# Check VIX regime distribution
python3 << 'PYEOF'
import pandas as pd
data = pd.read_parquet('data/backtest_results.parquet')
print(data[['vix', 'monthly_pct', 'weekly_pct']].describe())
PYEOF
```

---

## Success Metrics

| Metric | Target | Pass/Fail |
|--------|--------|-----------|
| Run #60 CAGR | > 11.16% | ? |
| Run #61 CAGR | > 11.16% | ? |
| Run #62 CAGR | > 11.16% | ? |
| Sharpe (any) | > 1.05 | ? |
| Win Rate (any) | > 59% | ? |
| Max DD (any) | < 7% | ? |

---

## Timeline

| Step | Time | Status |
|------|------|--------|
| 1-3: Code prep | 5 min | ✓ Ready |
| 4: Feature branch | 2 min | Pending |
| 5: Run #60 | 10 min | Pending |
| 6: Analyze | 5 min | Pending |
| 7: Run #61 | 10 min | Pending (conditional) |
| 8: Run #62 | 10 min | Pending (conditional) |
| 9-10: Results | 10 min | Pending |
| 11: Merge & tag | 5 min | Pending |
| **Total** | **~57 min** | **Estimated** |

---

## Quick Checklist

- [ ] Code added to main.py (get_dynamic_allocation function)
- [ ] Test with Python: `get_dynamic_allocation(15)` → `(0.2, 0.8)` ✓
- [ ] Feature branch created: `feat/phase4_exp2_vix_regimes`
- [ ] Run #60 executed with nohup
- [ ] Run #60 results analyzed (CAGR > 11.16%?)
- [ ] Run #61 executed (if #60 promising)
- [ ] Run #62 executed (if #61 promising)
- [ ] Results table created
- [ ] BACKTEST_CHANGELOG.md updated
- [ ] Final commit & push
- [ ] Merged to main & tagged
- [ ] Baseline backup verified still in place

---

**Ready?** → Start with Step 1: Add dynamic allocation function to main.py

**Questions?** → See docs/PHASE_4_PLAN.md for detailed context
