#!/usr/bin/env bash
# Manual runner for the log-only NIFTY option quote logger.
# Start it any time on a weekday; it waits for 11:00 IST, snapshots every 10 min, stops after 13:00 IST.
# With any argument (e.g. --dry-run, --force) it runs one snapshot with those args and exits.
# Usage: scripts/run_quote_logger.sh [log_option_quotes.py args]
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p logs

ist_hhmm() { TZ=Asia/Kolkata date +%H%M; }
ist_dow() { TZ=Asia/Kolkata date +%u; }

if [ "$#" -gt 0 ]; then
  exec "$PY" scripts/log_option_quotes.py "$@"
fi

if [ "$(ist_dow)" -ge 6 ]; then
  echo "Weekend in IST, nothing to log."
  exit 0
fi

while [ "$(ist_hhmm)" -lt 1100 ]; do
  sleep 30
done

while [ "$(ist_hhmm)" -le 1300 ]; do
  "$PY" scripts/log_option_quotes.py "$@" 2>&1 | tee -a logs/quote_logger.log
  rc=${PIPESTATUS[0]}
  # 0 = rows appended, 3 = nothing to write (holiday / duplicate); 2 = source unavailable, retry next tick
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ] && [ "$rc" -ne 2 ]; then
    echo "logger failed with exit code $rc" >&2
    exit "$rc"
  fi
  sleep 600
done

echo "Window closed. Rows so far: $(($(wc -l < paper_trading/tracker/QUOTE_LOG.csv) - 1))"
