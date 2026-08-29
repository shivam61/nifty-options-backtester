# Backtest Experiment Index

**Purpose**: Quick reference for all backtest runs, phases, and experiments  
**Current Date**: 2026-08-29 | **Last Updated**: 2026-08-24  
**Baseline**: Run #59 | **Status**: Ready for next experiment

---

## Current Baseline Summary

| Metric | Value |
|--------|-------|
| **Run #** | 59 |
| **Label** | v10-no-etl-gate-ruledbased |
| **CAGR** | 11.16% |
| **Total P&L** | ₹2,574,922 |
| **Sharpe** | 1.05 |
| **Max Drawdown** | 6.9% |
| **Win Rate** | 59.2% (Monthly 53.3%, Weekly 77.5%) |
| **Total Trades** | 417 (315 monthly + 102 weekly) |
| **Capital Util** | 43.1% |
| **Date** | 2026-08-24 03:37 |
| **Git** | `4458400` |

**Key Feature**: Rule-based weekly entries (no ML ETL gate) — 183% improvement over v9 ML baseline

---

## Phase Timeline

```
Aug 23 — Phase 1: LightGBM Migration
         ├─ Migrate 6 models from sklearn → LightGBM
         ├─ Add 18 trade-structure features
         └─ Result: AUC 0.554 → 0.696

Aug 23-24 — Phase 2: ETL Gate Tuning
         ├─ Identify ML gate blocking 78% weekly entries
         ├─ Test dynamic allocation experiments (75/25)
         ├─ Delete ML risk model, use rule-based fallback
         └─ Result: CAGR 6.22% → 11.16%

Aug 24 — Phase 3: Baseline Stabilization
         ├─ Commit all changes to main
         ├─ Standardize documentation format
         ├─ Archive old runs (#3-#55)
         └─ Ready for experiments

Aug 29 — Phase 4: Dynamic VIX Allocation (READY)
         └─ Test regime-based capital rebalancing
```

---

## Baseline Runs Comparison (#56–#59)

| Run | Date | Label | Strategy | CAGR | Notes |
|-----|------|-------|----------|------|-------|
| #56 | 8/23 | v8 | 50/50 split, LightGBM + Gate8 | 11.17% | ML gate active, good baseline |
| #57 | 8/23 | exp1_75w_25m | 75% weekly / 25% monthly | 7.95% | ❌ Worse than 50/50 |
| #58 | 8/24 | v9 | ML ETL tuned baseline | 6.22% | ⚠️ ML gate blocking trades |
| #59 | 8/24 | v10 | **Rule-based, no ML** | **11.16%** | ✅ **Current Baseline** |

---

## Archived Experiments (#3–#55)

**Total**: 53 historical runs (Apr–Aug 2026)  
**Status**: Archived to `docs/archive/ARCHIVED_RUNS.md`  
**Key phases**:
- **Runs #3–#11**: Early baseline development
- **Runs #12–#25**: Weekly exit strategy optimization
- **Runs #26–#35**: Cache and fallback validation
- **Runs #36–#50**: Gate tuning and feature engineering
- **Runs #51–#55**: LightGBM migration and AUC optimization

**Access**: See `docs/archive/ARCHIVED_RUNS.md` for complete history

---

## Planned Experiments (Phase 4 & Beyond)

### Experiment A: Dynamic VIX Allocation (Runs #60–#62)

**Hypothesis**: Optimal capital allocation changes with market regime

**Test Parameters**:
| VIX Range | Weekly | Monthly | Rationale |
|-----------|--------|---------|-----------|
| < 18 | 80% | 20% | Low vol → aggressive |
| 18–22 | 50% | 50% | Normal → balanced (current) |
| > 22 | 30% | 70% | High vol → defensive |

**Expected Outcome**:
- Run #60: VIX < 18 allocation
- Run #61: VIX > 22 allocation
- Run #62: Full dynamic (blend all regimes)

**Success Criteria**: Any run > 11.16% CAGR indicates improvement

**Next Decision**:
- If #60 or #61 > 11.16% → Investigate which regime drives gains
- If all < 11.16% → Confirm 50/50 static is optimal

---

### Experiment B: Weekly Entry Threshold Sweep (Planned)

If dynamic allocation doesn't improve baseline:

**Test**: Vary `weekly_entry_confidence_threshold` (e.g., 0.40 → 0.60)

**Rationale**: v10 uses 43.1% capital; maybe threshold is too restrictive

---

### Experiment C: Stop-Loss Tuning (Planned)

If allocation experiments plateau:

**Test**: Vary weekly stop-loss % (currently 100%)

**Rationale**: Larger losses suggest stop-loss may be too loose

---

## Running a Backtest

### Quick Start

```bash
# 1. Ensure ML models are cached
ls data/.cache/*.pkl

# 2. Launch backtest with nohup
nohup python3 main.py --mode backtest-combined --run-label "exp_name" \
  > logs/backtest_$(date +%Y%m%d_%H%M).log 2>&1 &
echo $!

# 3. Monitor progress
tail -f logs/backtest_*.log

# 4. Check results
grep "CAGR\|Total P&L\|Max Drawdown" logs/backtest_*.log
tail -20 BACKTEST_CHANGELOG.md
```

### If ML Models Missing

```bash
# Retrain all models (15–20 min)
nohup python3 main.py --mode evolve > logs/evolve_$(date +%Y%m%d_%H%M).log 2>&1 &
echo $!

# Wait for completion, then backtest
```

### Committing Results

```bash
# After backtest completes
git add BACKTEST_CHANGELOG.md backtest_runs.jsonl
git commit -m "feat(exp): test dynamic VIX allocation with 80/20 split"
git push origin main
```

---

## Documentation Map

| File | Purpose | Audience |
|------|---------|----------|
| `BACKTEST_CHANGELOG.md` | Current baseline runs #56-#59 | Everyone |
| `docs/BASELINE_LEARNINGS.md` | Phase transitions, learnings, standards | Decision makers |
| `docs/EXPERIMENT_INDEX.md` | This file — quick reference | Experiment runners |
| `docs/BACKTEST_COMBINED_MODE.md` | Technical details of backtest engine | Developers |
| `docs/archive/ARCHIVED_RUNS.md` | Historical runs #3-#55 | Reference only |
| `docs/CLAUDE.md` | Configuration constants and gotchas | Developers |

---

## Key Constants (Baseline v10)

```python
# Capital allocation (main.py)
_monthly_pct = 0.50      # 50%
_weekly_pct = 0.50       # 50%

# Entry gates (config.py)
entry_threshold = 0.50   # ML gate threshold
monthly_entry_threshold = 0.50
vix_simultaneous_cap = 25.0

# Risk controls (run_backtest_combined)
dd_kill_pct = 0.20       # Kill-switch at -20% DD
dd_recovery_pct = 0.16   # Recovery at -16% DD

# Weekly config
etl_skip_multiplier = 1.5  # ETL threshold (configurable)
min_dte_entry = 3
max_dte_entry = 8

# Fill proxy (11 AM mid-session)
mid_session_intraday_alpha = 0.40
nifty_mid_session = open + 0.40 * (close - open)
```

**To modify for experiments**: Edit `main.py` or `config.py`, then backtest

---

## Status Dashboard

### Green (✅ Ready)
- ML models cached and validated
- Test suite passing (489/489)
- Git main branch clean
- Baseline v10 documented
- Logs infrastructure in place

### Yellow (🟡 Planning)
- Dynamic VIX allocation experiment (design phase)
- Experimental branches (not yet created)

### Tracking
- BACKTEST_CHANGELOG.md: 4 baseline runs (#56-#59)
- backtest_runs.jsonl: 59+ entries with full metadata
- docs/archive/: 53 historical runs

---

## Decision Framework for Next Experiment

**Question**: Should we test dynamic VIX allocation?

**Answer Flowchart**:
```
Start with Run #60: VIX < 18 allocation (80/20)
    ↓
CAGR > 11.16%?
    ├─ YES → Run #61-62 (test other regimes)
    │        Identify winning allocation profile
    │        Document new weights
    │
    └─ NO → Run #61: VIX > 22 allocation (30/70)
            CAGR > 11.16%?
                ├─ YES → Document defensive regime works
                │        Blend into strategy
                │
                └─ NO → 50/50 static is optimal
                        Move to Experiment B (threshold sweep)
```

---

## Quick Links

- **Baseline**: [Run #59 in BACKTEST_CHANGELOG.md](BACKTEST_CHANGELOG.md)
- **Learnings**: [Phase transitions and insights](BASELINE_LEARNINGS.md)
- **History**: [Archived runs #3-#55](archive/ARCHIVED_RUNS.md)
- **Configuration**: [CLAUDE.md](CLAUDE.md) (constants & gotchas)
- **Technical**: [BACKTEST_COMBINED_MODE.md](BACKTEST_COMBINED_MODE.md)

---

## Maintenance

**Weekly**:
- Review new backtest results
- Update this index with run numbers

**Before Experiment**:
- Verify ML models exist (`ls data/.cache/*.pkl`)
- Confirm test suite passes (`pytest tests/ -q`)
- Ensure git is clean (`git status`)

**After Experiment**:
- Commit results to main
- Update BACKTEST_CHANGELOG.md with new run
- Add learnings to BASELINE_LEARNINGS.md
