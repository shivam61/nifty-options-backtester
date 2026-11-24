# Data-driven half-spread model (opt-in)

Status: **not usable for pass/fail verdicts.** The table is built from two in-window trading days.
It is an opt-in input for exploration only. The default chain engine still uses the flat CostModel
slippage.

## What it does

`backtester/spread_model.py` replaces the flat per-leg slippage base with the observed half-spread
for the leg's bucket, when that bucket is calibrated. Set `ChainConfig(spread_model=...)` to enable
it. The slippage multiplier (1.0 / 1.5 / 2.0x) still applies on top of the modelled half-spread.

- Source: the NSE option-chain quotes logged by `scripts/log_option_quotes.py` into
  `paper_trading/tracker/QUOTE_LOG*.csv`. These are the owner's own logs, not licensed archive data.
  Both files are git-tracked, so `data/spread_table.json` derived from them is not restricted and is
  not gitignored.
- Quotes used: NSE source, `in_window=1`, `forced=0`, `quote_status=ok`, bid > 0, ask >= bid.
  Duplicates are removed on (snapshot, expiry, strike, type). The same quote appears once per
  structure that uses it (IC, PCS, straddle, neighbours), so it is counted once.
- Measure: `half = (ask - bid) / 2`, and `frac = half / mid`.
- Calibrated base value: median `frac` in the bucket x the engine's settle price for the leg.
- Buckets: moneyness `|K/S-1|` in `lt1pct | 1to2pct | 2to4pct | gt4pct` (same bands as the logger);
  calendar DTE in `dte_le5 | dte_6to8 | dte_ge9`; VIX in `vix_lt13 | vix_ge13`.
- A bucket is calibrated only with at least **30 quote rows** AND at least **3 distinct snapshots**.
  The snapshot gate is an addition to the spec. Quotes inside one snapshot are highly correlated.
- Anything else falls back to the flat CostModel value, and the fallback is counted and reported.
  Lookup is exact-bucket only. Nothing is interpolated or borrowed from a neighbouring bucket.

## Build and report

```bash
.venv/Scripts/python.exe -m backtester.spread_model --out data/spread_table.json   # build + coverage
.venv/Scripts/python.exe -m backtester.spread_model --table data/spread_table.json  # coverage only
.venv/Scripts/python.exe scripts/run_chain_backtest.py --spread-table data/spread_table.json \
    --slippage 1.0 1.5 2.0 --out <dir>
```

The driver prints, per multiplier, how many entry and exit legs used a calibrated bucket versus the
fallback, with the fallback reasons (`below_min_samples`, `no_bucket`, `bad_price`). Counts are
per leg charge, not per trade.

## Data sufficiency (table as built 2026-11-17)

Source snapshots: 776 unique in-window quotes, 16 snapshots, **2 trading dates** (2026-10-28 and
2026-10-29). The 2026-10-26 snapshots were off-window and forced, so they are excluded.

| Bucket (moneyness \| DTE \| VIX) | rows | snapshots | dates | status | frac of mid (median) |
|---|---:|---:|---:|---|---:|
| lt1pct \| dte_6to8 \| vix_ge13 | 24 | 12 | 1 | FALLBACK (rows < 30) | 0.00106 |
| lt1pct \| dte_le5 \| vix_ge13 | 8 | 4 | 1 | FALLBACK | 0.00110 |
| lt1pct \| dte_ge9 \| vix_ge13 | 32 | 16 | 2 | calibrated | 0.00151 |
| 1to2pct \| dte_6to8 \| vix_ge13 | 53 | 12 | 1 | calibrated (1 date) | 0.00143 |
| 1to2pct \| dte_le5 \| vix_ge13 | 32 | 4 | 1 | calibrated (1 date) | 0.00174 |
| 1to2pct \| dte_ge9 \| vix_ge13 | 8 | 6 | 2 | FALLBACK | 0.00198 |
| 2to4pct \| dte_6to8 \| vix_ge13 | 188 | 12 | 1 | calibrated (1 date) | 0.00190 |
| 2to4pct \| dte_le5 \| vix_ge13 | 52 | 4 | 1 | calibrated (1 date) | 0.00292 |
| 2to4pct \| dte_ge9 \| vix_ge13 | 200 | 16 | 2 | calibrated | 0.00242 |
| gt4pct \| dte_6to8 \| vix_ge13 | 11 | 11 | 1 | FALLBACK | 0.00413 |
| gt4pct \| dte_ge9 \| vix_ge13 | 168 | 16 | 2 | calibrated | 0.00324 |

Not observed at all (always fall back): every `vix_lt13` bucket (logged VIX was 15.7 to 17.4), every
`gt4pct | dte_le5` bucket, and any bucket with moneyness beyond the observed strikes.

## Why it cannot yet support a verdict

1. **Two dates.** Four of the seven calibrated buckets come from a single trading date, so
   day-to-day regime effects are not averaged out. The 30-row gate counts rows, not days.
2. **No low-VIX data.** Every bucket is VIX >= 13. Any backtest trade entered at VIX < 13 falls back
   to the flat model, whatever the table says.
3. **Coarse ticks.** Median half-spreads are 0.025 to 0.4 Rs, close to the 0.05 Rs tick. Fractions
   of mid for cheap options are dominated by tick rounding.
4. **Mid-session only.** All quotes are 11:00 to 13:00 IST. The engine fills at settle-based prices,
   so the calibrated base is a proxy for entry quality, not a measured fill.
5. **Settle proxy.** The base is `frac x settle`. The logged mid was not used as the reference.
6. **Expiry-day legs.** The table has no expiry-day quotes. Exit legs on expiry use cash settlement
   (no slippage) under the default config.

For reference, the flat model gives 0.54 Rs per unit at VIX 16.5 and ATM (0.45 at VIX 12). A
median calibrated half-spread of roughly 0.10 Rs on a Rs40 leg is about 0.2x of the flat value.
This is indicative only. It rests on two days.

## Rules for using it

- Do not quote an expectancy or pass/fail verdict from a run with `--spread-table` until the
  buckets it uses are better covered. A 30-row gate is the spec; a multi-date gate (proposed here,
  at least 5 distinct dates per bucket) is not yet in the code. Fallback counts
  from the report must be read alongside the result, and a run that falls back on most fills is the
  flat model with a label.
- Regenerate the table as the logs grow: `python -m backtester.spread_model --out data/spread_table.json`.
  Check the coverage printout before any run.
- The flat model stays the default. `spread_model=None` gives output byte-identical to the
  pre-change engine (checked on the synthetic fixtures in `tests/test_spread_model.py`).
