# Querying the NSE F&O archive (`data/archive_query.py`)

Read-only DuckDB helper over the local NIFTY options archive. Use it for every question about archive contents.

## What data we have

- **Source.** NSE public F&O bhavcopy archive, downloaded by `scripts/fetch_nse_fo_archive.py`. Before 2024-07-08 the
  legacy URL is used (`archives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip`). From
  2024-07-08 the UDiFF URL is used (`nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip`).
  The other format is tried on a 404.
- **Coverage (measured 2026-11-17).** 1,913 daily files, first trading day 2019-02-11, last 2026-11-16. Total 4,020,963
  rows in the cache. 113 Mon-Fri days in that span have no file (17, 12, 14, 12, 15, 16, 13, 14 for 2019 to 2026).
  These are exchange holidays. `data/nse_holidays.json` lists only forward holidays (from 2026-10-20), so the
  historical gaps cannot be cross-checked against it.
- **Contents.** NIFTY index options only: OPTIDX rows before 2024-07-08, IDO rows after (the fetch script filters on
  `INSTRUMENT`/`FinInstrmTp` and `SYMBOL`/`TckrSymb` = NIFTY). Calls and puts. Columns: `date, expiry, strike, opt,
  open, high, low, close, settle, contracts, open_int, underlying`.
- **Not in the archive.** End-of-day only. No bid/ask, no intraday data, no futures, no Bank Nifty or stock options,
  nothing before 2019-02-11. `underlying` is empty before 2024-07-08.
- **Layout.** `~/nse_fo_archive/daily/YYYYMMDD.csv.gz` plus `_cache/nifty_fo_all.parquet` (rebuilt by
  `build_cache()`). The env var `NSE_FO_ARCHIVE_DIR` overrides the location.
- **Licence.** Internal, licence-restricted data. Never commit or redistribute it, or any file derived from it.
- **Refresh.** `python scripts/fetch_nse_fo_archive.py` is resumable and only downloads missing days. For a
  from-scratch download use `nohup` (about 1 to 1.5 hours). Then rebuild the cache as described in
  "Refreshing the archive" below.
- **Known caveats.**
  - On expiry day `settle` is the index settlement value, not an option price. The chain engine prices expiry-day
    legs at intrinsic.
  - 19 historical expiry days were shifted for exchange holidays. They are listed in
    `data/nse_holidays.json` under `historical_expiry_closures`.
  - Entry-basis bias: EOD settle versus intraday mid is about +1.3 points per unit for condors. This rests on n=2
    days and has not been re-measured here.
- **Verified use.** The chain backtest on this archive reproduces the pre-registered anchors: baseline -133.5 and
  -253.2 per lot at lots=10, at 1.0x and 1.5x slippage. This was reported by the study owner and not re-run for this
  document.

## How to search it

Start with the smallest command. Each recipe was run against the real archive on 2026-11-17 and returned a small table.

### 1. Health check and catalogue

```bash
python -m data.archive_query --coverage     # days and rows per year, first/last date, weekdays without a file
python -m data.archive_query --examples     # the ready-made queries listed below
```

### 2. Ad-hoc SQL (aggregates, GROUP BY, LIMIT; cap enforced)

```bash
python -m data.archive_query "SELECT opt, count(*) AS n FROM fo WHERE date = (SELECT max(date) FROM fo) GROUP BY 1"
python -m data.archive_query "SELECT ..." --limit 50
```

### 3. From Python: `query` for exploration, `NseFoArchive` for engines

```python
from data.archive_query import query          # exploration: capped SQL, returns a small DataFrame
df = query("SELECT year(date) AS y, count(*) AS n FROM fo GROUP BY 1 ORDER BY 1")

from data.nse_fo_archive import NseFoArchive  # engines: full chains per (day, expiry), used by backtests
arch = NseFoArchive(); arch.weekly_expiries(day); arch.chain(day, expiry)
```

Use `query` when you are asking a question. Use `NseFoArchive` when a backtest needs full option chains for each
trading day, which is how `scripts/run_chain_backtest.py` works.

### 4. Shell checks that print no rows

```bash
ls ~/nse_fo_archive/daily | wc -l        # number of daily files (1913 at 2026-11-17)
ls ~/nse_fo_archive/daily | tail -1      # newest file (20261116.csv.gz at 2026-11-17)
```

### 5. Recipes for common questions

```sql
-- a) Chain summary for one date: strikes, open interest, volume, strike range, per option type
SELECT opt, count(*) AS strikes, sum(open_int) AS oi, sum(contracts) AS vol, min(strike) AS lo, max(strike) AS hi
FROM fo WHERE date = DATE '2026-11-13' GROUP BY 1;

-- b) Expiries listed on one date with DTE (one row per expiry; n counts its CE and PE rows)
SELECT CAST(expiry AS DATE) AS expiry, dte, count(*) AS n
FROM fo_with_dte WHERE date = DATE '2026-11-13' GROUP BY 1, 2 ORDER BY 1;

-- c) ATM strike and straddle settle for one date (nearest expiry; ATM = smallest |CE - PE|, so it needs no spot)
WITH d AS (
  SELECT * FROM fo WHERE date = DATE '2026-11-13'
    AND expiry = (SELECT min(expiry) FROM fo WHERE date = DATE '2026-11-13' AND expiry > date)
), p AS (
  SELECT strike, max(CASE WHEN opt = 'CE' THEN settle END) AS ce, max(CASE WHEN opt = 'PE' THEN settle END) AS pe
  FROM d GROUP BY strike
)
SELECT strike, ce, pe, ce + pe AS straddle, abs(ce - pe) AS parity_gap
FROM p WHERE ce IS NOT NULL AND pe IS NOT NULL ORDER BY parity_gap LIMIT 3;

-- d) How many strikes had zero volume on one date, per option type
SELECT opt, count(*) AS strikes, sum(CASE WHEN contracts = 0 THEN 1 ELSE 0 END) AS zero_volume_strikes
FROM fo WHERE date = DATE '2026-11-13' GROUP BY 1;

-- e) Compare two dates side by side (spot is only present from 2024-07-08)
SELECT CAST(date AS DATE) AS day, count(*) AS rows, sum(open_int) AS oi, max(underlying) AS spot
FROM fo WHERE date IN (DATE '2026-11-13', DATE '2026-11-16') GROUP BY 1 ORDER BY 1;

-- f) Missing Mon-Fri days per year (exchange holidays included; 113 in total)
WITH span AS (
  SELECT CAST(g AS DATE) AS d FROM generate_series(TIMESTAMP '2019-02-11', TIMESTAMP '2026-11-16', INTERVAL 1 DAY) t(g)
  WHERE dayofweek(g) BETWEEN 1 AND 5
), have AS (SELECT DISTINCT CAST(date AS DATE) AS d FROM fo)
SELECT year(d) AS year, count(*) AS missing_weekdays FROM span WHERE d NOT IN (SELECT d FROM have)
GROUP BY 1 ORDER BY 1;
```

Recipe (c) uses the nearest listed expiry with `expiry > date`, which can be 0 to 14 days ahead. Filter `dte` if you
need a specific horizon.

### 6. Rules

- Aggregate in SQL. Never print raw rows into a conversation or a log.
- Exploring 2024+ data counts as peeking for pre-registered studies. Record each such look as described in
  [preregistration_candidates.md](preregistration_candidates.md) Section 7 and in [STRATEGY_EVAL.md](STRATEGY_EVAL.md)
  (holdout rules). The recipes above touch 2024+ data, so running them is a logged look.

## Why

The archive holds about 4 million end-of-day option rows (2019-02-11 onward). Loading it into a DataFrame or printing rows
floods the conversation and wastes tokens and time. Write the aggregation in SQL instead. The helper returns small,
capped tables (default 200 rows, hard maximum 5000), so an answer to "what was the average put settle by moneyness
band?" is a 20-row table, not a dump of raw rows. Never print or load raw archive rows.

## Connect and query

```bash
# CLI (from the repo root, venv active or via .venv/Scripts/python.exe)
python -m data.archive_query --coverage
python -m data.archive_query --examples
python -m data.archive_query --example put_settle_by_moneyness_dte
python -m data.archive_query "SELECT opt, count(*) AS n FROM fo WHERE date = DATE '2025-06-02' GROUP BY 1"
python -m data.archive_query "SELECT ..." --limit 50          # tighter cap
```

```python
from data.archive_query import query, connect, run_example, coverage

df = query("SELECT year(date) AS y, count(*) AS n FROM fo GROUP BY 1 ORDER BY 1")   # <= 200 rows
df = query("SELECT * FROM fo", limit=5000)                 # hard max 5000; larger raises ValueError
if df.attrs["truncated"]: ...                              # True when the cap cut the result
con = connect()                                            # raw duckdb connection, views fo / fo_with_dte
```

`query` accepts exactly one `SELECT` or `WITH` statement. Anything else (`COPY`, `CREATE`, `INSERT`, multiple
statements) raises `ValueError`. The connection is in memory and reads the parquet cache only.

## Views

| View | Contents |
|---|---|
| `fo` | Raw cache, one row per (date, expiry, strike, opt). |
| `fo_with_dte` | `fo` plus `dte`, `moneyness_pct`, `moneyness_band` (see caveats). |

Schema of `fo`:

| Column | Type | Meaning |
|---|---|---|
| `date` | TIMESTAMP | Trading day of the file (midnight). Cast with `CAST(date AS DATE)` for display. |
| `expiry` | TIMESTAMP | Contract expiry date. |
| `strike` | DOUBLE | Strike price (NIFTY points). |
| `opt` | VARCHAR | `CE` or `PE`. |
| `open`, `high`, `low`, `close` | DOUBLE | Day prices. |
| `settle` | DOUBLE | Settlement price. On expiry-day rows it is the index settlement value, not an option price. |
| `contracts` | BIGINT | Contracts traded that day (volume). 0 means no volume. |
| `open_int` | BIGINT | Open interest at end of day. |
| `underlying` | DOUBLE | NIFTY spot from the bhavcopy. Empty before 2024-07-08. |

`fo_with_dte` adds:

| Column | Meaning |
|---|---|
| `dte` | Days to expiry: `expiry - date` in calendar days. 0 on expiry day. |
| `moneyness_pct` | `(strike / underlying - 1) * 100`. Positive means the strike is above spot. NULL when underlying is missing. |
| `moneyness_band` | Strike-relative band: `1 < -5%`, `2 -5..-2%`, `3 -2..-0.5%`, `4 ATM +-0.5%`, `5 +0.5..+2%`, `6 +2..+5%`, `7 > +5%`. NULL when underlying is missing. |

Band definitions use the strike relative to spot for both CE and PE. Read "ITM" or "OTM" from the option type
yourself (for a put, a strike below spot is OTM).

## Caveats

- **Underlying gap.** `underlying` is empty before 2024-07-08 (the legacy bhavcopy format has no underlying column).
  `moneyness_pct` and `moneyness_band` are therefore NULL for earlier dates. Queries that use them only see 2024-07-08
  onward. Queries that avoid them (ATM straddle, coverage, OI) cover the whole archive.
- **No spot view.** There is no `spot` view. The repo's NIFTY close lives in the market-data cache, and loading it
  means importing `data.market_data` and its network-free cache path, which is heavier than this helper should be. Use
  `underlying` from the archive where it exists. For earlier dates, expiry-day `settle` is the index settlement value
  (zero in 2019 files), which covers only expiry days.
- **ATM proxy.** Without spot, the ATM strike in the straddle example is the strike minimising `|CE - PE|` for each
  (date, expiry). This works on the whole archive.
- **Expiry-day rows.** On expiry day `settle` is the index value, not an option price. Filter with `dte > 0` when you
  mean option prices.
- **Weekdays without a file.** `--coverage` counts Mon-Fri days with no daily file. Exchange holidays are included, so
  this is not a count of missing data.
- **Long-dated contracts.** The archive lists monthly and longer expiries (out to 2031). Restrict `dte` (for example
  `BETWEEN 1 AND 14` for the weekly horizon) when you need weekly behaviour.
- **Prices are EOD settles.** No bid/ask, no intraday data. Zero volume (`contracts = 0`) is common in deep OTM strikes.

## Ready-made queries

`python -m data.archive_query --examples` prints these. Run one with `--example NAME`.

| Name | Answers |
|---|---|
| `coverage_per_year` | Days, rows, first and last date per year. |
| `put_settle_by_moneyness_dte` | Average put settle by moneyness band and DTE, weekly horizon 1..14 (2024-07-08+). |
| `oi_by_expiry_latest_day` | Total open interest and contracts by expiry on the latest date. |
| `weekly_atm_straddle_by_year` | Average ATM straddle settle by year and DTE 1..14 (whole archive). |
| `zero_volume_share_by_moneyness` | Share of contract-days with zero volume, by band and option type (2024-07-08+). |
| `expiry_day_index_settle` | Expiry days per year and average index settle (2019 excluded, settle is 0). |

## Copy-paste queries (with expected shape)

Rows and columns are shown as shape only. Values depend on the data.

1. **Coverage (quick check).**
   `python -m data.archive_query --coverage`
   Shape: one row per year (year, days, rows), then first_date, last_date, total_rows, days_in_cache,
   daily_files, weekdays_without_file.

2. **Puts by moneyness band and DTE (weekly horizon).**
   `python -m data.archive_query --example put_settle_by_moneyness_dte`
   Shape: up to 98 rows (7 bands x 14 DTE). Columns: moneyness_band, dte, n, avg_settle.

3. **Open interest by expiry on one day.**
   ```sql
   SELECT CAST(expiry AS DATE) AS expiry, sum(open_int) AS total_open_int,
          sum(contracts) AS total_contracts, count(*) AS n_rows
   FROM fo WHERE date = DATE '2026-11-13'
   GROUP BY 1 ORDER BY 1
   ```
   Shape: one row per listed expiry (roughly 10 to 20 rows).

4. **Top open-interest strikes on one day (calls and puts).**
   ```sql
   SELECT CAST(expiry AS DATE) AS expiry, opt, strike, open_int, contracts, settle
   FROM fo_with_dte
   WHERE date = DATE '2026-11-13' AND dte BETWEEN 1 AND 14
   ORDER BY open_int DESC
   LIMIT 10
   ```
   Shape: 10 rows. One row per expiry, strike and option type.

5. **Weekly ATM straddle by year and DTE.**
   `python -m data.archive_query --example weekly_atm_straddle_by_year`
   Shape: up to 98 rows (years x 14 DTE). Columns: year, dte, n, avg_straddle.

6. **Liquidity: zero-volume share by moneyness band.**
   `python -m data.archive_query --example zero_volume_share_by_moneyness`
   Shape: up to 14 rows (7 bands x CE/PE). Columns: moneyness_band, opt, n, share_zero_volume.

7. **Count of expiry-day rows per year (sanity check on the settle convention).**
   ```sql
   SELECT year(date) AS y, count(*) AS n_rows
   FROM fo WHERE CAST(expiry AS DATE) = CAST(date AS DATE)
   GROUP BY 1 ORDER BY 1
   ```
   Shape: one row per year.

8. **Average settle for CE vs PE by DTE, ordinary days only.**
   ```sql
   SELECT opt, dte, count(*) AS n, round(avg(settle), 2) AS avg_settle
   FROM fo_with_dte
   WHERE dte BETWEEN 1 AND 7 AND settle > 0 AND date >= DATE '2024-07-08'
   GROUP BY 1, 2 ORDER BY 1, 2
   ```
   Shape: 14 rows (2 option types x 7 DTE).

## Licence rule

The archive is NSE F&O bhavcopy data, licence-restricted and internal. Rules:

- Never copy archive data into the repo, a commit, a log, a pull request or a shared artifact.
- Never commit any derived file: parquet caches, DuckDB database files, CSV exports or query results.
- The parquet cache and manifest live inside the archive directory (`<archive>/_cache/`), outside the repo. Keep it there.
- Share answers as aggregated numbers only, not row dumps.

## Refreshing the archive

The archive is downloaded by `scripts/fetch_nse_fo_archive.py`. It is resumable: existing non-empty daily files are
skipped. A from-scratch run takes about 1 to 1.5 hours. Use `nohup` for long runs:

```bash
python scripts/fetch_nse_fo_archive.py --dry-run          # plan only
nohup python scripts/fetch_nse_fo_archive.py > logs/fetch_fo_nohup.out 2>&1 &
```

Then rebuild the parquet cache. `connect()` never rebuilds it for you:

```bash
.venv/Scripts/python.exe -c "from data.nse_fo_archive import build_cache; build_cache()"
python -m data.archive_query --coverage                   # confirms the rebuilt cache
```

`build_cache()` skips the rebuild when the manifest (file count and total bytes) already matches. Pass
`force=True` to rebuild regardless.

The archive directory is `NSE_FO_ARCHIVE_DIR` if set, otherwise `~/nse_fo_archive`. Pass `--archive-dir` on the CLI or
`archive_dir=` in Python to point elsewhere.

## Troubleshooting

- **`archive cache is stale`.** New daily files arrived after the cache was built. Rebuild it (command above).
- **`archive cache missing`.** The `_cache` folder is absent. Rebuild it. If `daily/` is also empty, download first.
- **`no daily files under ... /daily`.** The archive dir is wrong or the download has not run. Check
  `NSE_FO_ARCHIVE_DIR` and `--archive-dir`.
- **`ModuleNotFoundError: No module named 'duckdb'`.** Install it into the venv:
  `.venv/Scripts/python.exe -m pip install -r requirements.txt`.
- **`result truncated to N rows`.** The row cap applied. Aggregate further (group by, filter) or raise `--limit` up to
  5000. Anything above 5000 is refused on purpose.
- **`only SELECT or WITH queries are allowed`.** The helper is read-only. Write SQL as a single `SELECT`.
- **Moneyness columns are NULL.** Those dates are before 2024-07-08, when the archive has no underlying.
