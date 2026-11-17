"""
Read-only DuckDB query helper over the local NSE F&O archive (NIFTY index options, EOD).

Why: aggregate in SQL and return SMALL tables. Do not load or print raw archive rows
(millions of them). The helper caps every result (default 200 rows, hard max 5000).

Archive: env NSE_FO_ARCHIVE_DIR, default ~/nse_fo_archive. The queried data is the parquet
cache built by data/nse_fo_archive.py (build_cache). Nothing here writes to the archive dir.
Internal, licence-restricted data: never commit or copy derived files into the repo.

API
    con = connect(archive_dir=None)          -> duckdb connection with views fo, fo_with_dte
    df  = query(sql, params=None, limit=200, archive_dir=None) -> pandas.DataFrame
    EXAMPLES                                 -> dict of ready-made queries (name -> Example)
    run_example(name, limit=200, archive_dir=None) -> DataFrame
    coverage(archive_dir=None)               -> (per-year DataFrame, summary dict)

CLI
    python -m data.archive_query "SELECT ..."
    python -m data.archive_query --examples
    python -m data.archive_query --example <name>
    python -m data.archive_query --coverage

Views
    fo          raw cache: date, expiry (TIMESTAMP), strike, opt (CE/PE), open, high, low, close,
                settle, contracts, open_int, underlying
    fo_with_dte fo + dte (expiry - date, days), moneyness_pct (strike/underlying - 1, in percent),
                moneyness_band (strike-relative band, NULL when underlying is missing)

Caveat: underlying is empty before 2024-07-08, so moneyness_* is NULL for earlier dates.
There is no spot view; see docs/ARCHIVE_QUERY.md.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import warnings
from dataclasses import dataclass
from typing import Optional

import duckdb
import pandas as pd

from data.nse_fo_archive import default_archive_dir

DEFAULT_LIMIT = 200
MAX_LIMIT = 5000
CACHE_SUBPATH = ("_cache", "nifty_fo_all.parquet")
MANIFEST_SUBPATH = ("_cache", "nifty_fo_all.manifest.json")
REBUILD_CMD = '.venv/Scripts/python.exe -c "from data.nse_fo_archive import build_cache; build_cache()"'
FETCH_CMD = "python scripts/fetch_nse_fo_archive.py"

_DAILY_RE = re.compile(r"^(\d{8})\.csv\.gz$")


class ArchiveCacheError(RuntimeError):
    """Parquet cache missing or older than the daily files. Rebuild it; this module never does."""


def _resolve_dir(archive_dir: Optional[str]) -> str:
    return archive_dir or default_archive_dir()


def _cache_path(archive_dir: str) -> str:
    return os.path.join(archive_dir, *CACHE_SUBPATH)


def _manifest_path(archive_dir: str) -> str:
    return os.path.join(archive_dir, *MANIFEST_SUBPATH)


def _daily_files(archive_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(archive_dir, "daily", "*.csv.gz")))


def _check_cache(archive_dir: str) -> str:
    """Return the cache path, or raise ArchiveCacheError with the rebuild command."""
    files = _daily_files(archive_dir)
    if not files:
        raise ArchiveCacheError(f"no daily files under {archive_dir}/daily. Download with: {FETCH_CMD}")
    pq = _cache_path(archive_dir)
    if not os.path.exists(pq):
        raise ArchiveCacheError(f"archive cache missing: {pq}. Rebuild it with: {REBUILD_CMD}")
    man = _manifest_path(archive_dir)
    expected = {"n_files": len(files), "total_bytes": sum(os.path.getsize(f) for f in files)}
    current = None
    if os.path.exists(man):
        with open(man) as fh:
            current = json.load(fh)
    newest_daily = max(os.path.getmtime(f) for f in files)
    if current != expected or os.path.getmtime(pq) < newest_daily:
        raise ArchiveCacheError(
            f"archive cache is stale ({len(files)} daily files on disk, cache manifest {current}). "
            f"Rebuild it with: {REBUILD_CMD}"
        )
    return pq


def _sql_str(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# Strike-relative moneyness bands (strike / underlying - 1). Prefixes keep the sort order.
_BAND_SQL = """
CASE
  WHEN underlying IS NULL OR underlying <= 0 THEN NULL
  WHEN strike / underlying - 1 < -0.05  THEN '1 < -5%'
  WHEN strike / underlying - 1 < -0.02  THEN '2 -5..-2%'
  WHEN strike / underlying - 1 < -0.005 THEN '3 -2..-0.5%'
  WHEN strike / underlying - 1 <= 0.005 THEN '4 ATM +-0.5%'
  WHEN strike / underlying - 1 <= 0.02  THEN '5 +0.5..+2%'
  WHEN strike / underlying - 1 <= 0.05  THEN '6 +2..+5%'
  ELSE '7 > +5%'
END
"""


def connect(archive_dir: Optional[str] = None) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection with views `fo` and `fo_with_dte` over the parquet cache.

    Raises ArchiveCacheError if the cache is missing or stale. Never writes to the archive dir.
    """
    ad = _resolve_dir(archive_dir)
    pq = _check_cache(ad)
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW fo AS SELECT * FROM read_parquet({_sql_str(pq.replace(os.sep, '/'))})")
    con.execute(
        f"""
        CREATE VIEW fo_with_dte AS
        SELECT
            *,
            CAST(CAST(expiry AS DATE) - CAST(date AS DATE) AS INTEGER) AS dte,
            CASE WHEN underlying > 0 THEN (strike / underlying - 1) * 100 END AS moneyness_pct,
            {_BAND_SQL} AS moneyness_band
        FROM fo
        """
    )
    return con


_FORBIDDEN_START = ("SELECT", "WITH")


def query(sql: str, params=None, limit: int = DEFAULT_LIMIT, archive_dir: Optional[str] = None) -> pd.DataFrame:
    """Run one read-only SELECT/WITH against `fo` / `fo_with_dte`; return at most `limit` rows.

    limit must be 1..5000 (ValueError otherwise). If more rows exist, the result is truncated,
    a warning is issued and df.attrs["truncated"] is True. Only a single SELECT or WITH statement
    is accepted; anything else (COPY, CREATE, INSERT, multiple statements) is rejected.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit > MAX_LIMIT:
        raise ValueError(f"limit {limit} exceeds the hard maximum of {MAX_LIMIT}; aggregate further instead")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    text = sql.strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    if ";" in text:
        raise ValueError("only one statement is allowed")
    if not text.upper().startswith(_FORBIDDEN_START):
        raise ValueError("only SELECT or WITH queries are allowed (read-only helper)")
    con = connect(archive_dir)
    try:
        wrapped = f"SELECT * FROM ({text}) AS q LIMIT {limit + 1}"
        df = con.execute(wrapped, params).df()
    finally:
        con.close()
    truncated = len(df) > limit
    if truncated:
        df = df.iloc[:limit].reset_index(drop=True)
        warnings.warn(f"result truncated to {limit} rows (row cap); aggregate further or raise limit (max {MAX_LIMIT})")
    df.attrs["truncated"] = truncated
    return df


# ---- ready-made queries -----------------------------------------------------------------

@dataclass(frozen=True)
class Example:
    description: str
    sql: str
    limit: int = DEFAULT_LIMIT


EXAMPLES: dict[str, Example] = {
    "coverage_per_year": Example(
        "Days, rows, first and last date per calendar year",
        """
        SELECT year(date) AS year, count(DISTINCT date) AS days, count(*) AS rows,
               CAST(min(date) AS DATE) AS first_date, CAST(max(date) AS DATE) AS last_date
        FROM fo GROUP BY 1 ORDER BY 1
        """,
    ),
    "put_settle_by_moneyness_dte": Example(
        "Average put settle by strike-relative moneyness band and DTE, weekly horizon 1..14 days (2024-07-08+, needs underlying; excludes expiry days)",
        """
        SELECT moneyness_band, dte, count(*) AS n, round(avg(settle), 2) AS avg_settle
        FROM fo_with_dte
        WHERE opt = 'PE' AND dte BETWEEN 1 AND 14 AND settle > 0 AND moneyness_band IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
    ),
    "oi_by_expiry_latest_day": Example(
        "Total open interest and contracts by expiry for the latest archive date (replace the subquery with a literal date to pick another day)",
        """
        SELECT CAST(expiry AS DATE) AS expiry, sum(open_int) AS total_open_int,
               sum(contracts) AS total_contracts, count(*) AS n_rows
        FROM fo WHERE date = (SELECT max(date) FROM fo)
        GROUP BY 1 ORDER BY 1
        """,
    ),
    "weekly_atm_straddle_by_year": Example(
        "Average ATM straddle settle by year and DTE (1..14 days). ATM = strike minimising |CE - PE| per day and expiry (works without underlying)",
        """
        WITH px AS (
            SELECT date, expiry, strike,
                   CAST(CAST(expiry AS DATE) - CAST(date AS DATE) AS INTEGER) AS dte,
                   max(CASE WHEN opt = 'CE' THEN settle END) AS ce,
                   max(CASE WHEN opt = 'PE' THEN settle END) AS pe
            FROM fo
            WHERE expiry > date AND settle > 0
            GROUP BY 1, 2, 3, 4
        ),
        pairs AS (
            SELECT *, row_number() OVER (PARTITION BY date, expiry ORDER BY abs(ce - pe), strike) AS rn
            FROM px
            WHERE ce IS NOT NULL AND pe IS NOT NULL AND dte BETWEEN 1 AND 14
        )
        SELECT year(date) AS year, dte, count(*) AS n, round(avg(ce + pe), 2) AS avg_straddle
        FROM pairs WHERE rn = 1
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
    ),
    "zero_volume_share_by_moneyness": Example(
        "Share of contract-days with zero volume (contracts = 0) by moneyness band and option type (2024-07-08+, needs underlying)",
        """
        SELECT moneyness_band, opt, count(*) AS n,
               round(avg(CASE WHEN contracts = 0 THEN 1.0 ELSE 0.0 END), 4) AS share_zero_volume
        FROM fo_with_dte
        WHERE moneyness_band IS NOT NULL AND dte > 0
        GROUP BY 1, 2 ORDER BY 1, 2
        """,
    ),
    "expiry_day_index_settle": Example(
        "Expiry days per year and average index settlement carried on expiry-day rows (0 in 2019 files, so those rows are excluded)",
        """
        WITH e AS (
            SELECT CAST(date AS DATE) AS expiry_day, max(settle) AS index_settle
            FROM fo WHERE CAST(expiry AS DATE) = CAST(date AS DATE)
            GROUP BY 1
        )
        SELECT year(expiry_day) AS year, count(*) AS expiry_days,
               round(avg(index_settle), 2) AS avg_index_settle
        FROM e WHERE index_settle > 0
        GROUP BY 1 ORDER BY 1
        """,
    ),
}


def run_example(name: str, limit: int = DEFAULT_LIMIT, archive_dir: Optional[str] = None) -> pd.DataFrame:
    if name not in EXAMPLES:
        raise KeyError(f"unknown example {name!r}; known: {', '.join(EXAMPLES)}")
    ex = EXAMPLES[name]
    return query(ex.sql, limit=max(limit, ex.limit), archive_dir=archive_dir)


# ---- coverage ---------------------------------------------------------------------------

def coverage(archive_dir: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """Per-year coverage from the cache, plus first/last date, total rows and weekdays with no file.

    'Weekdays without a file' counts Mon-Fri days between the first and last daily file that have
    no daily file. Exchange holidays appear here too, so this is not a count of missing data.
    """
    ad = _resolve_dir(archive_dir)
    per_year = query(
        """
        SELECT year(date) AS year, count(DISTINCT date) AS days, count(*) AS rows
        FROM fo GROUP BY 1 ORDER BY 1
        """,
        limit=100,
        archive_dir=ad,
    )
    names = {}
    for f in _daily_files(ad):
        m = _DAILY_RE.match(os.path.basename(f))
        if m:
            names[pd.Timestamp(m.group(1))] = True
    days = sorted(names)
    weekdays_missing = 0
    if days:
        span = pd.bdate_range(days[0], days[-1])
        weekdays_missing = int(sum(1 for d in span if d not in names))
    total = query("SELECT count(*) AS rows, CAST(min(date) AS DATE) AS first_date, "
                  "CAST(max(date) AS DATE) AS last_date, count(DISTINCT date) AS days FROM fo",
                  limit=1, archive_dir=ad)
    row = total.iloc[0]
    summary = {
        "first_date": pd.Timestamp(row["first_date"]).date().isoformat(),
        "last_date": pd.Timestamp(row["last_date"]).date().isoformat(),
        "total_rows": int(row["rows"]),
        "days_in_cache": int(row["days"]),
        "daily_files": len(days),
        "weekdays_without_file": weekdays_missing,
    }
    return per_year, summary


# ---- CLI --------------------------------------------------------------------------------

def _print_examples() -> None:
    for name, ex in EXAMPLES.items():
        print(f"{name}: {ex.description}")
        print(ex.sql.strip())
        print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SQL over the NSE F&O archive (returns small tables).")
    parser.add_argument("sql", nargs="?", help="SELECT/WITH query over views fo and fo_with_dte")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"row cap (default {DEFAULT_LIMIT}, max {MAX_LIMIT})")
    parser.add_argument("--archive-dir", default=None, help="archive dir (default NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive)")
    parser.add_argument("--examples", action="store_true", help="list ready-made queries")
    parser.add_argument("--example", metavar="NAME", help="run one ready-made query")
    parser.add_argument("--coverage", action="store_true", help="days/rows per year and first/last date")
    args = parser.parse_args(argv)

    try:
        if args.examples:
            _print_examples()
            return 0
        if args.coverage:
            per_year, summary = coverage(args.archive_dir)
            print(per_year.to_string(index=False))
            print()
            for k, v in summary.items():
                print(f"{k}: {v}")
            return 0
        if args.example:
            df = run_example(args.example, limit=args.limit, archive_dir=args.archive_dir)
        elif args.sql:
            df = query(args.sql, limit=args.limit, archive_dir=args.archive_dir)
        else:
            parser.print_help()
            return 0
        print(df.to_string(index=False))
        print(f"({len(df)} rows{', truncated' if df.attrs.get('truncated') else ''})")
        return 0
    except (ArchiveCacheError, ValueError, KeyError, duckdb.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
