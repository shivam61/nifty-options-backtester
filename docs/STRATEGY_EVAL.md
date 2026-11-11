# Strategy evaluation (`strategy_eval/`)

Judges an option-selling strategy, hedged or not, by the pre-registered rule in
`docs/preregistration_edge_search.md`. Win rate is printed for context and never enters the verdict.

## Use

```
python scripts/eval_strategy.py --trades path/trades.csv
python scripts/eval_strategy.py --trades hedged.csv --baseline unhedged.csv \
    --capital 2500000 --risk-cap 50000 --out logs/eval_hedged.md --registry logs/eval_registry.json
python scripts/eval_strategy.py --trades run.json            # chain-engine / run69-style dumps auto-detected
python scripts/eval_strategy.py --trades h9.csv --adapter h9 --input-haircut-pct 30   # regime-A H9 CSV
python scripts/eval_strategy.py ... --allow-holdout          # 2024+ holdout: one pre-registered candidate only
```

Writes a markdown report (default `logs/eval_<name>.md`, gitignored) and a JSON summary (same path, `.json`).
`--registry` keeps every cut examined across runs, so Holm correction counts all of them.

## Trade schema

One row per closed trade. Rs columns are totals at `lots` lots; per-lot = value / lots.

| column | meaning |
|---|---|
| strategy, entry_date, exit_date, expiry, lots | identity and size |
| credit_rs, max_loss_rs | premium received; defined worst loss (NaN if undefined risk) |
| pnl_gross_rs, cost_rs, pnl_net_rs | `pnl_net = pnl_gross - cost` (checked to 1 Rs) |
| exit_reason, entry_vix | context |
| hedge_cost_rs | part of cost_rs that belongs to a hedge (default 0) |
| slippage_rs, base_haircut_pct | optional: slippage share of costs; haircut already in the file's pricing |
| pricing_source | `bs`, `chain` or `live` |

Adapters: `from_chain_trades` (chain-engine `trades_x<m>.json`), `from_run69_trades` (combined-engine
dumps), `from_h9_frame` (H9 CSVs). `load_trades()` auto-detects. Pickle and CSV of the normalised schema
load directly.

## Pass rule (as implemented)

Verdict cost: 1.5x slippage, no extra haircut. Development window 2019-02-11..2023-12-31.

1. Beats the baseline at that cost (paired on common entry dates, mean difference > 0).
2. Per-lot expectancy > 0.
3. Year-cluster bootstrap 95% CI lower bound > 0 (10,000 draws, seed 20261111).
4. At least 4 of 5 dev years positive.
5. Holm-adjusted one-sided t-test p < 0.05 over every cut in the registry.

Assumption: the pre-registration names Holm as the multiple-testing rule but does not list it as a numbered
pass item. Criterion 5 turns it into one. The t-test uses a non-overlapping subsample and a t distribution.

Verdicts: `PASS`, `FAIL`, `INSUFFICIENT_DATA` (no baseline, fewer than 30 trades, or a missing year),
`INDICATIVE_ONLY`.

## Guards

- **Model-priced cap.** Any trade with `pricing_source='bs'` (candidate or baseline) caps the verdict at
  `INDICATIVE_ONLY`. The criteria are still printed, with their own result.
- **Holdout.** Entries after 2023-12-31 are excluded unless `--allow-holdout`. Entries before 2019-02-11 are
  always excluded. Counts appear in the report.

## Stress conventions

- Haircut h removes h of the credit (P&L falls by h x credit), as in `scratchpad/structure_search.py`
  regime A. Limitations: fees are not re-derived on the lower notional, and exit triggers are not re-run.
- Slippage m adds (m-1) x `slippage_rs`. Where slippage is unknown the whole `cost_rs` is scaled, which
  overstates the stress.
- A file priced under a base haircut only takes the incremental haircut.

## Other outputs

- Metrics: expectancy, payoff, breakeven and actual win rate (context), P5, worst, tail ratio, cumulative max
  drawdown, Sharpe-like, per-year table, exit-reason mix.
- Sizing: lots capped so the worst loss is at most the risk cap (default Rs 50,000 = 2% of Rs 25L). Implied
  CAGR and return on the risk cap (a margin proxy). Risk is taken from `max_loss_rs` where defined, otherwise
  from realised per-lot losses. Sizing uses the verdict window only.
- Hedge scorecard (with `--baseline`): paired difference with bootstrap CI, hedge cost as % of credit, P5 and
  worst change, and a decision: drop the hedge when its cost exceeds the tail loss it removes.

## Tests

`tests/test_strategy_eval.py` (synthetic data, no network, about 10 s). It covers the schema, hand-computed
metrics, bootstrap determinism, Holm against a worked example, each pass-rule criterion failing in turn, the
BS cap, the holdout guard, the hedge scorecard, adapters, and the CLI. Smoke tests run on the scratch research
files when present and skip otherwise.
