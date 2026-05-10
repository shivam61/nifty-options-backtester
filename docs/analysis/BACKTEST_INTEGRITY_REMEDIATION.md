# Backtest Integrity Remediation

## What Changed

- Monthly entry and exit models now support period-aware metadata and strict
  out-of-sample guards.
- Weekly entry and weekly risk models now support the same period-aware cache
  identity checks.
- New walk-forward orchestration builds expanding-window model bundles keyed by:
  `model_type`, `train_start`, `train_end`, `feature_version`, and `config_hash`.
- Monthly and weekly training simulators no longer enter on the signal bar.
  They record `signal_date` and fill on the next executable bar.
- A new fill abstraction separates theoretical marking from executable fills.
  Black-Scholes remains the theoretical mark; executable fills now worsen
  entry/exit prices via spread/slippage and gap-sensitive widening.

## Bias Removed

- Future-trained model reuse: earlier backtests could load a cache that had no
  train-window identity and therefore could be reused outside its valid period.
- Same-bar EOD entry bias: signal-day close features were previously paired with
  same-bar fills in training data and backtest entry paths.
- Optimistic executable pricing: theoretical repricing and actual fills are now
  distinct concepts, which makes the backtest less optimistic under gaps and
  wider spreads.

## Expected Metric Drift

- Win rate may fall because entries are no longer allowed at the same close
  that generated the signal.
- Average credit collected may fall because next-bar execution and spread-aware
  fills are worse than theoretical marks.
- Drawdown and tail-loss metrics may worsen because adverse gaps now widen
  executable fills instead of assuming frictionless repricing.

These changes are expected and should be treated as realism corrections, not as
strategy regressions.

## Remaining Realism Gaps

- Option-chain-based executable fills are still not available in the historical
  dataset, so executable prices remain modelled rather than broker-observed.
- Intraday stop logic is still constrained by daily OHLCV granularity.
- The new fill model is conservative, but it is still a proxy until chain-level
  bid/ask, OI, and size are wired into the engine.
