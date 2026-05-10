# Institutional Flow Pipeline

This pipeline is designed to build an auditable research dataset for Indian institutional flows with explicit provenance.

What is currently supported:

- Official current-day DII and FII/FPI pull from NSE JSON endpoints.
- Official latest final FPI/FII validation from NSDL HTML.
- Official latest and archive-oriented FPI/FII flows from CDSL.
- Official SEBI FPI statistics archive discovery, including trade-wise equity links and transaction-code documentation.
- Official CDSL fortnightly sector-wise FPI investment pages.
- Daily sector proxy generation from the official fortnightly sector series.
- Raw payload retention, parquet/csv outputs, checkpointing, and QA reports.

Current limitations:

- A 10-year official DII history source was not confirmed during discovery.
- FYERS historical institutional-flow access was not confirmed from documented endpoints.
- CDSL/SEBI monthly trade-wise equity ZIPs are official, and SEBI documents transaction codes, but reconstruction still needs correct handling of amendments/deletions/reporting semantics before it can be treated as final daily buy/sell history.
- Sector-wise data is direct only for FPI and only at fortnightly cadence; daily output is a proxy.

Key scripts:

- `python scripts/discover_sources.py`
- `python scripts/update_daily_institutional_flows.py`
- `python scripts/backfill_institutional_flows.py --start-year 2016`
- `python scripts/build_sector_proxy.py`
- `python scripts/run_data_quality_checks.py`
- `python scripts/analyze_cdsl_zip_reconstruction.py --zip-path /tmp/Jan_2025.zip --daily-dir /tmp/cdsl_jan_2025`
- `python scripts/reconstruct_fpi_from_tradewise_zips.py --zip /tmp/Dec_2024.zip --zip /tmp/Jan_2025.zip --zip /tmp/Feb_2025.zip --start-date 2025-01-01 --end-date 2025-01-31`

Key current research result:

- SEBI’s official trade-wise FPI archive explicitly defines transaction codes:
  - `01` purchase in secondary market
  - `02` purchase in primary market
  - `03` preferential allotment
  - `04` sale in secondary market
  - `05` purchase through rights issue
- This materially improves the official reconstruction path for FPI/FII.
- FYERS still does not document a public institutional-flow API.
- Best current practical reconstruction rule:
  - `report_date` aggregation
  - instrument scope `REG_DL_INSTR_EQ` + `REG_DL_INSTR_EU`
  - adjacent-month ZIP window for month-boundary spillovers
