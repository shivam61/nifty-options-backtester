#!/usr/bin/env bash
# Cache-integrity guardrail: fails loudly if the market-data cache could feed wrong-ticker data.
#
# Thin wrapper around scripts/validate_market_cache.py, run in its strongest mode:
#   1. --selftest   the validator itself (synthetic clean vs corrupted frames).
#   2. --dataset    file-level scan of CACHE_DIR (readability, ticker coverage, byte-identical
#                   Close series) PLUS a cache-only build of the combined dataset through
#                   MarketDataFetcher. The build raises on identical or default-filled macro
#                   columns; the validator then runs identity, range and freshness checks.
#
# Usage:  scripts/check_cache_health.sh
# Env:    CACHE_DIR       default <repo>/data/.cache
#         START           dataset start, default 2009-01-01
#         MAX_STALE_DAYS  business days the last date may lag ASOF, default 5
#         ASOF            reference date, default today (freshness is wall-clock based)
#         PYTHON          interpreter; default <repo>/.venv/bin/python if present, else python3
# Exit:   0 PASS | 1 a check FAILed | 2 runtime error (e.g. the build refused the cache)
#         Any non-zero exit should fail CI. The last line is a one-line summary for CI logs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="${CACHE_DIR:-$ROOT/data/.cache}"
START="${START:-2009-01-01}"
MAX_STALE_DAYS="${MAX_STALE_DAYS:-5}"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then PYTHON="$ROOT/.venv/bin/python"; else PYTHON="python3"; fi
fi
VALIDATOR="$ROOT/scripts/validate_market_cache.py"

asof_args=()
if [[ -n "${ASOF:-}" ]]; then asof_args=(--asof "$ASOF"); fi

echo "== validator self-test =="
if ! "$PYTHON" "$VALIDATOR" --selftest; then
  echo "cache-health: FAIL rc=1 validator selftest failed (validator is not trustworthy)"
  exit 1
fi

echo "== cache health: $CACHE_DIR (start=$START, max_stale_days=$MAX_STALE_DAYS) =="
set +e
OUT="$(MARKET_DATA_CACHE_ONLY=1 "$PYTHON" "$VALIDATOR" --cache-dir "$CACHE_DIR" --dataset \
        --start "$START" --max-stale-days "$MAX_STALE_DAYS" ${asof_args[@]+"${asof_args[@]}"} 2>&1)"
RC=$?
set -e
printf '%s\n' "$OUT"

FILES="$(printf '%s\n' "$OUT" | sed -n 's/^cache dir: .*  files: \([0-9]*\)  asof:.*/\1/p' | head -n1)"
CHECKS_SECTION="$(printf '%s\n' "$OUT" | sed -n '/^== CHECKS ==/,$p')"
CHECKS="$(printf '%s\n' "$CHECKS_SECTION" | grep -cE '^.{52}(PASS|FAIL) ' || true)"
FAILED="$(printf '%s\n' "$CHECKS_SECTION" | grep -cE '^.{52}FAIL ' || true)"
case "$RC" in
  0) STATUS=PASS ;;
  1) STATUS=FAIL ;;
  *) STATUS=ERROR ;;
esac
echo "cache-health: $STATUS rc=$RC files=${FILES:-0} checks=$CHECKS failed=$FAILED cache=$CACHE_DIR start=$START"
exit "$RC"
