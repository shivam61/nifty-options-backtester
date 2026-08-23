# Archive — Historical Decision Records

These documents capture analyses and experiments that were completed and whose
conclusions are now built into the live system. They are **not current configuration
references** — the canonical state of the system lives in `CLAUDE.md`, `config.py`,
and the running code.

They are preserved here because the "why we didn't do X" reasoning is useful
when the same question resurfaces.

## Contents

| File | Decision recorded |
|------|------------------|
| `EXIT_STRATEGY_ANALYSIS.md` | Rejected the flat 80% profit-lock exit rule in favour of VIX-adaptive thresholds |
| `HYBRID_BACKTEST_RESULTS.md` | Concluded fixed 85% profit target outperforms hybrid/adaptive approach for weekly exits |
| `EXIT_PRIORITY_COMPARISON_FINDINGS.md` | Both exit ordering variants (profit-first vs stop-first) produced identical P&L — stopped pursuing |
| `OPTIMAL_THRESHOLDS_ANALYSIS.md` | Selected 85% as optimal weekly profit target (now superseded by 100% stop-loss widening) |
| `BACKTEST_COMPARISON_WITH_85_RULE.md` | Side-by-side confirming 85% rule wins; decision finalised |
| `MONTHLY_EXIT_STRATEGY_ANALYSIS.md` | Monthly exit strategy comparison; superseded by `WEEKLY_EXIT_REDESIGN_LOG.md` |
