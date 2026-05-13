# Agent Memory

Short-lived, evidence-backed lessons for Claude, Codex, and other agents working in this repo.
Entries decay automatically so stale or one-off advice does not become permanent guidance.

## Current Active Memories

### graphify-output-can-drift-without-committed-hooks
- Score: 0.8984
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
