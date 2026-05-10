"""
Helpers for period-aware model caches and strict out-of-sample guards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return value


def stable_config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(_normalize_value(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ModelPeriodMetadata:
    model_type: str
    train_start: str
    train_end: str
    feature_version: str
    config_hash: str
    config: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        model_type: str,
        train_start: date,
        train_end: date,
        feature_version: str,
        config: dict[str, Any],
    ) -> "ModelPeriodMetadata":
        normalized = _normalize_value(config)
        return cls(
            model_type=model_type,
            train_start=train_start.isoformat(),
            train_end=train_end.isoformat(),
            feature_version=feature_version,
            config_hash=stable_config_hash(normalized),
            config=normalized,
        )

    @property
    def cache_key(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def train_end_date(self) -> date:
        return date.fromisoformat(self.train_end)

    def assert_usable_for(self, signal_date: date) -> None:
        if self.train_end_date >= signal_date:
            raise ValueError(
                f"{self.model_type} trained through {self.train_end} cannot be used for "
                f"signal date {signal_date.isoformat()}."
            )

    def assert_matches(self, other: "ModelPeriodMetadata") -> None:
        if asdict(self) != asdict(other):
            raise ValueError(
                f"Model cache metadata mismatch for {self.model_type}: "
                f"expected {asdict(other)}, got {asdict(self)}"
            )


def metadata_from_state(state: dict[str, Any]) -> ModelPeriodMetadata | None:
    raw = state.get("period_metadata")
    if not raw:
        return None
    return ModelPeriodMetadata(**raw)

