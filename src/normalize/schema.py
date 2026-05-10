from __future__ import annotations

from typing import Any

import pandas as pd


CANONICAL_COLUMNS = [
    "date",
    "participant_type",
    "buy_value",
    "sell_value",
    "net_value",
    "market_segment",
    "sector",
    "instrument",
    "series_kind",
    "source_name",
    "source_url",
    "source_type",
    "extraction_method",
    "is_official",
    "is_provisional",
    "is_final",
    "confidence_score",
    "currency",
    "notes",
]


def canonicalize(df: pd.DataFrame, defaults: dict[str, Any] | None = None) -> pd.DataFrame:
    defaults = defaults or {}
    frame = df.copy()
    for column in CANONICAL_COLUMNS:
        if column not in frame.columns:
            frame[column] = defaults.get(column)

    numeric_columns = ["buy_value", "sell_value", "net_value", "confidence_score"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    bool_columns = ["is_official", "is_provisional", "is_final"]
    for column in bool_columns:
        frame[column] = frame[column].astype("boolean")

    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date

    return frame[CANONICAL_COLUMNS]
