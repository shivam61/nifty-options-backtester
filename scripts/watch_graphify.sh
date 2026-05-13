#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

find_graphify() {
  if [ -n "${GRAPHIFY_BIN:-}" ] && [ -x "${GRAPHIFY_BIN:-}" ]; then
    printf '%s\n' "$GRAPHIFY_BIN"
    return 0
  fi

  if command -v graphify >/dev/null 2>&1; then
    command -v graphify
    return 0
  fi

  for candidate in "$ROOT/.venv/bin/graphify" "$ROOT/../"*/.venv/bin/graphify "$HOME/github/"*/.venv/bin/graphify; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

GRAPHIFY="$(find_graphify || true)"

if [ -z "$GRAPHIFY" ]; then
  echo "graphify is not available. Install graphify, activate its environment, or set GRAPHIFY_BIN=/path/to/graphify." >&2
  exit 1
fi

exec "$GRAPHIFY" watch "$ROOT"
