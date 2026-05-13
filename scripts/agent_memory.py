#!/usr/bin/env python3
"""Maintain a small, decaying memory of agent pitfalls for this repository."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "docs" / "agent_memory.jsonl"
ARCHIVE_PATH = ROOT / "docs" / "agent_memory.archive.jsonl"
REPORT_PATH = ROOT / "docs" / "AGENT_MEMORY.md"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:72] or "memory"


def load_records(path: Path = MEMORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def write_records(records: list[dict[str, Any]], path: Path = MEMORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
    path.write_text(body, encoding="utf-8")


def append_records(records: list[dict[str, Any]], path: Path) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def score(record: dict[str, Any], now: datetime | None = None) -> float:
    now = now or utc_now()
    created_at = parse_time(record["created_at"])
    age_days = max((now - created_at).total_seconds() / 86400.0, 0.0)
    half_life_days = max(float(record.get("half_life_days", 90)), 1.0)
    confidence = float(record.get("confidence", 0.7))
    helpful = int(record.get("helpful_count", 0))
    stale = int(record.get("stale_count", 0))
    base = confidence * math.pow(0.5, age_days / half_life_days)
    return round(base + (0.12 * helpful) - (0.25 * stale), 4)


def render(records: list[dict[str, Any]]) -> str:
    now = utc_now()
    active = sorted(
        [record for record in records if record.get("status", "active") == "active"],
        key=lambda item: score(item, now),
        reverse=True,
    )
    lines = [
        "# Agent Memory",
        "",
        "Short-lived, evidence-backed lessons for Claude, Codex, and other agents working in this repo.",
        "Entries decay automatically so stale or one-off advice does not become permanent guidance.",
        "",
        "## Current Active Memories",
        "",
    ]
    if not active:
        lines.append("_No active memories._")
    for record in active:
        tags = ", ".join(record.get("tags", [])) or "untagged"
        lines.extend(
            [
                f"### {record['id']}",
                f"- Score: {score(record, now)}",
                f"- Status: {record.get('status', 'active')}",
                f"- Tags: {tags}",
                f"- Summary: {record['summary']}",
                f"- Pitfall: {record['pitfall']}",
                f"- Prevention: {record['prevention']}",
                f"- Evidence: {record.get('evidence', 'not recorded')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Workflow",
            "",
            "- Before a non-trivial change, read this file and `docs/architecture/AGENTS.md`.",
            "- When an agent hits a repeatable repo-specific pitfall, add it with `python3 scripts/agent_memory.py add ...`.",
            "- When a memory helps, run `python3 scripts/agent_memory.py mark <id> --helpful`.",
            "- When a memory is stale or misleading, run `python3 scripts/agent_memory.py mark <id> --stale`.",
            "- Periodically run `python3 scripts/agent_memory.py decay` to archive low-score records.",
            "",
            "The machine-readable source of truth is `docs/agent_memory.jsonl`; this markdown file is rendered from it.",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_add(args: argparse.Namespace) -> None:
    records = load_records()
    now = iso(utc_now())
    base_id = slugify(args.summary)
    existing = {record["id"] for record in records}
    record_id = base_id
    counter = 2
    while record_id in existing:
        record_id = f"{base_id}-{counter}"
        counter += 1
    records.append(
        {
            "id": record_id,
            "created_at": now,
            "updated_at": now,
            "agent": args.agent,
            "status": "active",
            "severity": args.severity,
            "confidence": args.confidence,
            "half_life_days": args.half_life_days,
            "helpful_count": 0,
            "stale_count": 0,
            "tags": args.tags,
            "summary": args.summary,
            "pitfall": args.pitfall,
            "prevention": args.prevention,
            "evidence": args.evidence,
        }
    )
    write_records(records)
    REPORT_PATH.write_text(render(records), encoding="utf-8")
    print(record_id)


def cmd_mark(args: argparse.Namespace) -> None:
    records = load_records()
    for record in records:
        if record["id"] == args.id:
            if args.helpful:
                record["helpful_count"] = int(record.get("helpful_count", 0)) + 1
            if args.stale:
                record["stale_count"] = int(record.get("stale_count", 0)) + 1
            record["updated_at"] = iso(utc_now())
            break
    else:
        raise SystemExit(f"unknown memory id: {args.id}")
    write_records(records)
    REPORT_PATH.write_text(render(records), encoding="utf-8")


def cmd_decay(args: argparse.Namespace) -> None:
    records = load_records()
    now = utc_now()
    keep: list[dict[str, Any]] = []
    archive: list[dict[str, Any]] = []
    for record in records:
        current_score = score(record, now)
        if current_score < args.min_score or int(record.get("stale_count", 0)) >= args.max_stale:
            record["status"] = "archived"
            record["archived_at"] = iso(now)
            record["archive_score"] = current_score
            archive.append(record)
        else:
            keep.append(record)
    write_records(keep)
    append_records(archive, ARCHIVE_PATH)
    REPORT_PATH.write_text(render(keep), encoding="utf-8")
    print(f"active={len(keep)} archived={len(archive)}")


def cmd_render(_: argparse.Namespace) -> None:
    records = load_records()
    REPORT_PATH.write_text(render(records), encoding="utf-8")
    print(REPORT_PATH)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(required=True)

    add = sub.add_parser("add", help="add a new repo-specific pitfall memory")
    add.add_argument("--agent", default="unknown")
    add.add_argument("--severity", choices=["low", "medium", "high"], default="medium")
    add.add_argument("--confidence", type=float, default=0.7)
    add.add_argument("--half-life-days", type=int, default=90)
    add.add_argument("--tags", nargs="*", default=[])
    add.add_argument("--summary", required=True)
    add.add_argument("--pitfall", required=True)
    add.add_argument("--prevention", required=True)
    add.add_argument("--evidence", default="")
    add.set_defaults(func=cmd_add)

    mark = sub.add_parser("mark", help="mark a memory as helpful or stale")
    mark.add_argument("id")
    mark.add_argument("--helpful", action="store_true")
    mark.add_argument("--stale", action="store_true")
    mark.set_defaults(func=cmd_mark)

    decay = sub.add_parser("decay", help="archive weak or stale memories")
    decay.add_argument("--min-score", type=float, default=0.25)
    decay.add_argument("--max-stale", type=int, default=2)
    decay.set_defaults(func=cmd_decay)

    render_cmd = sub.add_parser("render", help="render markdown from JSONL")
    render_cmd.set_defaults(func=cmd_render)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
