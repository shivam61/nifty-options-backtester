#!/usr/bin/env bash
# Bootstrap data/.cache from the committed seed so a fresh clone (CI, a new session, a new
# machine) can run backtest/signal modes immediately, without a 17yr network refresh or a
# full `--mode evolve` retrain.
#
# Seed contents (data/.cache_seed/, committed, ~5MB):
#   - 16 parquet files, one per ticker in data.market_data.TICKERS, each the newest
#     ticker-safe cache file as of the date in SEED_ASOF below.
#   - manifest.json naming those 16 files (data/market_data.py trusts ONLY manifest-listed
#     files; see the "Cache Integrity Guardrails" gotcha in CLAUDE.md).
#   - entry_model_v4.pkl, exit_model.pkl, evolved_strategies.json (trained on the seed data;
#     no weekly_risk_engine_v2.pkl — the system falls back to the rule-based weekly gate,
#     which is the documented default; see CLAUDE.md).
#
# This script COPIES (never moves/deletes) the seed into data/.cache/. It will not overwrite
# a newer file already there, so it is safe to re-run.
#
# Usage:   scripts/bootstrap_cache.sh
# After:   scripts/check_cache_health.sh   (expect PASS; it will report the cache as stale
#          if today is more than 5 business days past SEED_ASOF below — that's expected,
#          not a bug: run `python main.py --mode refresh-data` to extend it with real data)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="$ROOT/data/.cache_seed"
DEST="$ROOT/data/.cache"
SEED_ASOF="2026-10-12"  # last_date of every parquet in the seed

if [[ ! -d "$SEED" ]]; then
  echo "bootstrap-cache: FAIL no seed at $SEED (did the clone fetch LFS/full history?)" >&2
  exit 2
fi

mkdir -p "$DEST"
copied=0
for f in "$SEED"/*; do
  name="$(basename "$f")"
  if [[ -e "$DEST/$name" ]]; then
    continue
  fi
  cp "$f" "$DEST/$name"
  copied=$((copied + 1))
done

echo "bootstrap-cache: copied $copied file(s) from $SEED to $DEST (seed as-of $SEED_ASOF)"
echo "bootstrap-cache: next -> scripts/check_cache_health.sh    (then: python main.py --mode refresh-data   to extend to today)"
