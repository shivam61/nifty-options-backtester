"""Append-only, hash-chained ledger of holdout looks (logs/holdout_ledger.json by default).

Every evaluation that uses allow_holdout=True (CLI --allow-holdout, or the library flag) appends one
row before any holdout trade is scored:
  {index, timestamp (UTC ISO), candidate, window, prev_hash, hash}
The file is a JSON array with one row per line. Appending never rewrites earlier bytes: the writer
checks the existing chain, then replaces only the closing bracket with the new row and a new closing
bracket. Each row's hash covers its content and the previous row's hash, so an edited or deleted row
makes read_ledger() raise LedgerError. This is tamper-evident, not tamper-proof: a person with write
access could rebuild the whole chain. Keep the file in version control or a backup if that matters.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Read at call time so tests can redirect it.
DEFAULT_LEDGER_PATH = REPO_ROOT / "logs" / "holdout_ledger.json"
GENESIS_HASH = "0" * 64


class LedgerError(RuntimeError):
    """The ledger file is not a valid chain (edited, truncated or not a ledger)."""


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def read_ledger(path: str | Path | None = None) -> list[dict]:
    """All ledger rows in order. Verifies indices and the hash chain; raises LedgerError on any break."""
    p = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    if not p.exists() or p.stat().st_size == 0:
        return []
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerError(f"{p} is not valid JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise LedgerError(f"{p} must hold a JSON array")
    prev = GENESIS_HASH
    for i, rec in enumerate(rows):
        if rec.get("index") != i:
            raise LedgerError(f"row {i} has index {rec.get('index')!r}")
        if rec.get("prev_hash") != prev:
            raise LedgerError(f"row {i} prev_hash does not match row {i - 1}")
        if rec.get("hash") != _digest(rec):
            raise LedgerError(f"row {i} content does not match its hash")
        prev = rec["hash"]
    return rows


def append_holdout_look(candidate: str, window: dict, path: str | Path | None = None) -> dict:
    """Append one holdout look and return the stored row. Verifies the existing chain first."""
    p = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    rows = read_ledger(p)
    prev = rows[-1]["hash"] if rows else GENESIS_HASH
    rec = {
        "index": len(rows),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidate": str(candidate),
        "window": dict(window),
        "prev_hash": prev,
    }
    rec["hash"] = _digest(rec)
    line = json.dumps(rec, sort_keys=True, default=str)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists() or p.stat().st_size == 0:
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("[\n" + line + "\n]\n")
            fh.flush()
            os.fsync(fh.fileno())
        return rec
    with open(p, "r+b") as fh:
        raw = fh.read()
        end = len(raw.rstrip())
        if raw[:end][-1:] != b"]":
            raise LedgerError(f"{p} does not end with a closing bracket")
        fh.seek(end - 1)                       # keep every byte before the closing bracket
        fh.truncate()
        sep = b",\n" if rows else b"\n"
        fh.write(sep + line.encode("utf-8") + b"\n]\n")
        fh.flush()
        os.fsync(fh.fileno())
    return rec
