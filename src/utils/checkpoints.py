from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PATHS


@dataclass
class CheckpointRecord:
    source_name: str
    item_key: str
    status: str
    updated_at: str
    metadata_json: str | None


class CheckpointStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or PATHS.checkpoint_db
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    source_name TEXT NOT NULL,
                    item_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT,
                    PRIMARY KEY (source_name, item_key)
                )
                """
            )
            conn.commit()

    def get_status(self, source_name: str, item_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM checkpoints WHERE source_name = ? AND item_key = ?",
                (source_name, item_key),
            ).fetchone()
        return row[0] if row else None

    def upsert(
        self,
        source_name: str,
        item_key: str,
        status: str,
        metadata_json: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (source_name, item_key, status, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_name, item_key)
                DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    source_name,
                    item_key,
                    status,
                    datetime.utcnow().isoformat(timespec="seconds"),
                    metadata_json,
                ),
            )
            conn.commit()
