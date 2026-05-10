# Weekly Exit Redesign Log

Decision record for the weekly exit overhaul. This exists to prevent re-running
the same failed path later without new evidence.

## Status

- Default: adopted
- Applies to: `backtest-combined`, `signal-combined`, `evolve` training inputs,
  and the shared weekly exit policy used by weekly engines
- Decision date: 2026-04-17

## Final Default

### Engine A — Income Core (`weekly_pcs`)

- Profit target: `75%` of credit
- Minimum hold: `2` trading days
- Keep distance / strike-breach risk exits

### Engine B — Convex Booster (`weekly_ic`)

- No profit-target exits
- Exit on:
  - `trailing_delta`
  - `trend_reversal`
  - `max_hold_time`
- Keep hard risk exits

## What Was Removed

The old weekly experiment path based on max-profit booking is retired.

- `backtester/weekly_engine_max_profit.py`
- `strategies/weekly_strategies_max_profit.py`
- `tools/validation/find_optimal_threshold.py`

Those files tested a weekly `70%–95%` max-profit / trailing booking idea.
That branch is not the default and should not be revived casually.

## Why We Changed It

Observed issue in weekly strategies:

- profit-target exits dominated
- winners were cut too early
- convex payoff capture was weak

Additional implementation issue discovered during combined-backtest testing:

- the weekly risk engine was still firing legacy weekly `profit_target` exits
  before the redesigned weekly logic could act

The important production fix was routing in `CombinedBacktestEngine`:

- `weekly_pcs`: keep weekly risk-engine breach exits, but do not allow its
  `profit_target` shortcut
- `weekly_ic`: bypass the old risk-engine profit-target behavior and let the
  redesigned exit policy control the trade

## Measured Impact

### Full-Range Combined Backtest

Command:

```bash
PYTHONPATH=. ./.venv/bin/python main.py --mode backtest-combined
```

Period: `2009-01-01` to `2026-04-17`

#### Legacy Combined Path

- Total P&L: `₹4,421,439`
- CAGR: `14.56%`
- Max DD: `11.1%`
- Sharpe: `1.73`
- Weekly P&L: `₹2,641,540`
- Weekly trades: `451`
- Weekly dynamic exits:
  - `profit_target: 321`
  - `distance_breach_50pct: 102`
  - `dte_losing_exit: 3`

#### Current Default

- Total P&L: `₹4,672,871`
- CAGR: `14.90%`
- Max DD: `10.8%`
- Sharpe: `1.78`
- Weekly P&L: `₹2,892,780`
- Weekly trades: `448`
- Weekly dynamic exits:
  - `distance_breach_50pct: 46`

#### Delta

- Total P&L: `+₹251,432`
- CAGR: `+0.34pp`
- Max DD: `-0.3pp`
- Sharpe: `+0.05`
- Weekly P&L: `+₹251,240`

Interpretation:

- the lift came almost entirely from the weekly leg
- removing weekly dynamic `profit_target` exits materially improved the combined path
- risk did not worsen at portfolio level; drawdown improved slightly

## Robustness Check

### Year-by-year lift

Positive yearly contribution occurred in most active weekly years, not just one.
Largest positive years:

- `2025`: `+₹85,521`
- `2021`: `+₹32,865`
- `2018`: `+₹29,123`
- `2024`: `+₹27,898`
- `2016`: `+₹25,516`

Negative years:

- `2017`: `-₹13,944`
- `2023`: `-₹9,027`

Interpretation:

- improvement is broad, not a single-regime artifact
- `2025` is the largest contributor but does not explain the whole lift

### Weekly Tail Audit

Legacy weekly tail:

- Worst loss: `-₹22,947`
- `P1`: `-₹12,429`
- `P5`: `-₹4,356`
- `P10`: `-₹2,788`
- Loss rate: `24.2%`

Current weekly tail:

- Worst loss: `-₹18,315`
- `P1`: `-₹12,814`
- `P5`: `-₹4,052`
- `P10`: `-₹2,076`
- Loss rate: `21.0%`

Interpretation:

- worst loss improved
- `P5` and `P10` improved
- loss frequency improved
- `P1` got slightly worse, so the extreme left tail still needs monitoring

### Gap / Event Week Audit

Stress proxy: high VIX, large overnight gap, or strong 5-day VIX acceleration.

Legacy:

- Count: `59`
- Total P&L: `₹87,639`
- Worst: `-₹18,315`
- `P5`: `-₹3,163`
- Loss rate: `28.8%`

Current:

- Count: `59`
- Total P&L: `₹121,123`
- Worst: `-₹18,315`
- `P5`: `-₹3,163`
- Loss rate: `27.1%`

Interpretation:

- stressed weeks remained controlled
- no evidence that removing profit targets silently worsened gap/event behavior

## Tried And Rejected

### 1. Weekly 80% max-profit booking branch

Outcome: rejected.

- The repo had a dedicated experiment branch for weekly max-profit booking.
- It underperformed and is now retired.
- Do not re-run this path unless there is a genuinely new hypothesis.

### 2. Post-routing threshold tweak

Tried:

- PCS target from `75%` to `70%`
- more sensitive IC trend-reversal thresholds

Outcome: no change on the real combined backtest.

Decision:

- reverted
- keep only the routing fix plus redesigned default policy

## Do Not Circle Back Without New Evidence

Avoid repeating these without a new reason:

- weekly `80%` max-profit booking experiments
- weekly threshold sweeps on the deleted max-profit engine
- reintroducing weekly risk-engine `profit_target` exits ahead of the redesigned policy

Future work should target:

- extreme-left-tail improvement (`P1`) without reintroducing profit-target dominance
- better IC trend-reversal sensitivity if it improves full combined results
- explicit weekly exit-reason reporting in combined CLI output
