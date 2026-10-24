# Pre-registration: edge search on NIFTY weekly option selling

Written 2026-10-24, before any run listed here. Development window: 2019-02-11..2023-12-31. Holdout (2024-01-01 onward) is not touched; `scripts/run_chain_backtest.py` and `scripts/audit_vrp.py` refuse `--end` after 2023-12-31 without `--allow-holdout`.

## Regression anchor (corrected cost model, dev window, lots=10)
| Variant | 1.0x | 1.5x |
|---|---:|---:|
| baseline | -133.5 | -253.2 |
| F1 `--no-early-exits` | +48.6 | -9.8 |

Reproduced 2026-10-24 with default flags. Every change must keep these numbers when its new flags are off.

## Hypotheses
- H1: the weekly index-option premium sits in OTM puts (put skew), not symmetrically across calls and puts.
- H2: premium varies with VIX level; VIX 25+ is a loss bucket and VIX 13-25 carries the gain.
- H3: the dev-window sample is too small to resolve an effect of ~8 pts/unit (power statement, not a test).
- H4: fewer legs and hold-to-expiry lower cost enough to turn expectancy positive at measured spreads.
- H5: a forecast-based VRP gate (implied minus forecast realised vol, signal-day data only) beats the VIX floor.
- H6 (exploratory): IV crush after scheduled events is tradeable. Reported only, never a candidate by itself.

## Pass rule for a candidate (all four)
1. Beats the baseline at the cost level used (1.5x, or measured spreads once the quote log supports them).
2. Per-lot expectancy > 0.
3. Year-cluster bootstrap 95% CI lower bound > 0.
4. At least 4 of 5 dev years positive.

## Multiple-testing budget
Each agent records every cut it examines (bucket, structure, filter threshold). Holm correction is applied over all cuts in the report. Thresholds come from a pre-stated grid; no post-hoc thresholds. Walk-forward splits inside the dev window: train 2019-2021, test 2022-2023.

## Decision table
| Outcome | Action |
|---|---|
| A candidate passes the rule at measured costs | Ask the user for a single holdout look on that one candidate; if it holds, paper-trade that variant only |
| Nothing passes | Record "no demonstrable edge at realistic costs"; paper logging stays data collection only |
| Quote log too thin (<20 snapshots per bucket) | Report with the sample-size caveat; costs stay as model multipliers; no candidate is promoted on thin costs |

## Agent acceptance
Accept only after the lead re-runs tests and the anchor, reads the diff, re-runs the headline command, and confirms: no dates after 2023-12-31, defaults unchanged, cuts counted, units stated (pts/unit vs Rs/lot).
