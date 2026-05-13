#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

if [ "${SKIP_GRAPHIFY_UPDATE:-}" = "1" ]; then
  echo "graphify update skipped because SKIP_GRAPHIFY_UPDATE=1"
  exit 0
fi

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
  echo "warning: graphify is not on PATH; graphify-out was not updated" >&2
  echo "hint: install graphify, activate its environment, or set GRAPHIFY_BIN=/path/to/graphify" >&2
  exit 0
fi

mode="${1:-}"

has_relevant_change() {
  if [ "$mode" = "--staged" ]; then
    git diff --cached --name-only --diff-filter=ACMR
  else
    git status --short --untracked-files=all | awk '{print $NF}'
  fi | awk '
    /^graphify-out\// { next }
    /^data\/raw\// { next }
    /^data\/processed\// { next }
    /^data\/\.cache\// { next }
    /^\.git\// { next }
    /^\.venv\// { next }
    /\.(py|md|sh|yml|yaml|toml|json|txt)$/ { found=1 }
    END { exit found ? 0 : 1 }
  '
}

if [ "$mode" = "--staged" ] && ! has_relevant_change; then
  exit 0
fi

if [ "$mode" != "--staged" ] && [ "${GRAPHIFY_FORCE_UPDATE:-}" != "1" ] && ! has_relevant_change; then
  exit 0
fi

echo "Updating graphify-out from repository files..."
"$GRAPHIFY" update "$ROOT"

if [ "$mode" = "--staged" ]; then
  git add graphify-out
fi
