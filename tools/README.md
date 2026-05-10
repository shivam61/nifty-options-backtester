# Tools Directory

Utility scripts for analysis, comparison, debugging, and validation.

## Structure

### comparison/
Scripts for comparing different strategies and configurations.

- `backtest_hybrid_exit.py` - Compare hybrid exit strategies
- `compare_exit_strategies.py` - Compare different exit strategy configurations
- `compare_exit_priority.py` - Compare exit priority rules
- `compare_monthly_exit_strategies.py` - Compare monthly exit strategy variants

**Usage:**
```bash
python -m tools.comparison.compare_exit_strategies
```

### debug/
Debugging and diagnostic tools.

- `debug_exit_logic.py` - Debug exit logic behavior
- `test_circuit_breaker_detailed.py` - Detailed circuit breaker tests
- `test_circuit_breaker_scenarios.py` - Circuit breaker scenario tests

**Usage:**
```bash
python -m tools.debug.debug_exit_logic
```

### validation/
Model and strategy validation tools.

- `main_validate.py` - Walk-forward validation
- `verify_max_profit_implementation.py` - Verify max profit booking logic

**Usage:**
```bash
python -m tools.validation.main_validate
```

## Running Tools

All tools can be run as modules from the project root:

```bash
# From project root
cd /path/to/nifty-options-backtester

# Run comparison tools
python -m tools.comparison.compare_exit_strategies

# Run debug tools
python -m tools.debug.debug_exit_logic

# Run validation tools
python -m tools.validation.main_validate
```

## Adding New Tools

When adding new utility scripts:

1. Place in appropriate subdirectory (comparison/debug/validation)
2. Add module docstring explaining purpose
3. Update this README
4. Ensure imports work as module (use relative imports within package)
