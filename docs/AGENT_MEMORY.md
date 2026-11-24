# Agent Memory

Short-lived, evidence-backed lessons for Claude, Codex, and other agents working in this repo.
Entries decay automatically so stale or one-off advice does not become permanent guidance.

## Current Active Memories

### candidatespec-cadence-monthly-already-means-family-b-weekly-signals-mont
- Score: 0.7
- Status: active
- Tags: candidates, chain-engine, cadence
- Summary: CandidateSpec cadence='monthly' already means family B: weekly signals, monthly target
- Pitfall: Family B LS_B_*_mo signals on every weekly expiry and targets the monthly expiry. Setting cadence='monthly' on a new cell therefore does NOT give a monthly-expiry signal, and changing the meaning would silently change pre-registered B results.
- Prevention: Use CandidateSpec(monthly_signal=True) (requires cadence='monthly') for signal-on-monthly-expiry. Default False keeps B. Tests: tests/test_round3_engine.py (test_round1_monthly_b_cells_still_signal_every_weekly_expiry).
- Evidence: tests/test_candidates.py::test_one_position_at_a_time_and_skip_counters failed when monthly signal was keyed on cadence alone

### weekly-fixed-weekday-signals-only-overlap-when-a-position-is-held-8-days
- Score: 0.6975
- Status: active
- Tags: candidates, chain-engine, cadence
- Summary: Weekly fixed-weekday signals only overlap when a position is held 8 days
- Pitfall: With 7-day signal spacing and target expiry = earliest listed expiry with DTE in [3,8], the next position fills exactly when the previous one expires, unless the hold is 8 days. max_concurrent>1 with expiry_day cadence never overlaps.
- Prevention: Use signal_cadence=weekly_fixed_weekday with signal_weekday=1 (Tuesday) on Thursday-expiry data, or signal_cadence=daily for real overlap. Tests: tests/test_candidate_engine_ext.py (cadence section).
- Evidence: tests/test_candidate_engine_ext.py::test_weekly_fixed_weekday_opens_second_position_while_first_is_open

### use-data-archive-query-for-nse-archive-questions
- Score: 0.6955
- Status: active
- Tags: archive, duckdb, tokens
- Summary: Use data.archive_query for NSE archive questions
- Pitfall: Loading or printing raw rows from the NSE option archive (4M rows) wastes tokens and time, and exploring 2024+ data is a peek at the holdout.
- Prevention: Query with python -m data.archive_query 'SELECT ...' or data.archive_query.query(sql), aggregate in SQL, keep results small, and record any 2024+ exploration as a look (docs/ARCHIVE_QUERY.md, docs/STRATEGY_EVAL.md).
- Evidence: docs/ARCHIVE_QUERY.md

### nse-mcp-data-is-cross-check-only-never-for-training
- Score: 0.6827
- Status: active
- Tags: nse-mcp, licensing
- Summary: NSE MCP data is cross-check only, never for training
- Pitfall: NSE MCP output is informational only. NSE's disclaimer forbids training or fine-tuning AI models or algorithms on it, and forbids commercial deployment.
- Prevention: Keep scripts/check_nse_mcp.py read-only: never write to data/.cache, never feed model or training code, print output to stdout only.
- Evidence: NSE MCP terms as stated in the 2026-10-13 task brief.

### pd-to-datetime-dayfirst-true-misreads-iso-dates-with-day-12
- Score: 0.6069
- Status: active
- Tags: nse-mcp, date-parsing, cross-check
- Summary: pd.to_datetime(dayfirst=True) misreads ISO dates with day<=12
- Pitfall: pandas dayfirst=True parses YYYY-MM-DD strings day-first when day<=12 (2026-08-06 became 2026-06-08), which produced false day/month-swap mismatches against Yahoo. NSE MCP get_index_history also silently ignores endDate unless it is ISO YYYY-MM-DD (DD-MM-YYYY defaults to today) and returns ~3 months per call with next_end_date for pagination.
- Prevention: Parse ISO dates explicitly (scripts/check_nse_mcp.py parse_date_str). Always pass endDate as YYYY-MM-DD and follow next_end_date when calling NSE MCP. Verify a date-parse change against a known row before trusting a diff.
- Evidence: scripts/check_nse_mcp.py live run: Nifty 50 and India VIX matched NSE exactly on 63 overlapping days after the parse and endDate fixes.

### yahoo-parquet-cache-nsebank-series-is-not-bank-nifty
- Score: 0.6069
- Status: active
- Tags: cache, data-quality, nifty-bank
- Summary: Yahoo parquet cache ^NSEBANK series is not Bank Nifty
- Pitfall: Cached nifty_bank closes are ~4,000-4,600 (last 4624.10 on 2026-08-21) while NSE Bank Nifty is ~53,000-58,500 over the same window. _ticker_hint_score has no ^NSEBANK branch, so the cache picks an arbitrary highest-scoring parquet.
- Prevention: Do not trust nifty_bank from the Yahoo cache until the parquet is re-fetched or the ticker lookup is fixed. Re-run scripts/check_nse_mcp.py after cache refresh; expect 0 Bank Nifty flags.
- Evidence: scripts/check_nse_mcp.py live run 2026-10-13: 60 Bank Nifty days flagged at +1100% to +1360%; Nifty 50 and India VIX matched NSE exactly.

### graphify-output-can-drift-without-committed-hooks
- Score: 0.4332
- Status: active
- Tags: graphify, hooks, agent-workflow
- Summary: Graphify output can drift without committed hooks
- Pitfall: Assuming graphify-out is current just because it exists. Git hooks are local and were not installed, so graphify-out can drift after source edits or branch changes.
- Prevention: Use scripts/update_graphify.sh for one-shot refreshes, scripts/watch_graphify.sh while editing, and enable repo hooks with git config core.hooksPath .githooks.
- Evidence: graphify hook status reported no hooks installed while graphify-out existed as untracked output.

## Workflow

- Before a non-trivial change, read this file and `docs/architecture/AGENTS.md`.
- When an agent hits a repeatable repo-specific pitfall, add it with `python3 scripts/agent_memory.py add ...`.
- When a memory helps, run `python3 scripts/agent_memory.py mark <id> --helpful`.
- When a memory is stale or misleading, run `python3 scripts/agent_memory.py mark <id> --stale`.
- Periodically run `python3 scripts/agent_memory.py decay` to archive low-score records.

The machine-readable source of truth is `docs/agent_memory.jsonl`; this markdown file is rendered from it.
