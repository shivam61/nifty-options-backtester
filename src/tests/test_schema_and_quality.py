from __future__ import annotations

from datetime import date

import pandas as pd

from src.normalize.schema import CANONICAL_COLUMNS, canonicalize
from src.validate.qa import build_quality_report, validate_net_consistency


def test_canonicalize_adds_required_columns() -> None:
    frame = canonicalize(pd.DataFrame([{"date": "2026-04-17", "participant_type": "FII/FPI"}]))
    assert list(frame.columns) == CANONICAL_COLUMNS


def test_net_consistency_flags_mismatch() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": date(2026, 4, 17),
                "participant_type": "FII/FPI",
                "buy_value": 100.0,
                "sell_value": 80.0,
                "net_value": 5.0,
                "market_segment": "capital_market",
                "sector": pd.NA,
                "series_kind": "direct",
                "source_name": "test",
            }
        ]
    )
    mismatches = validate_net_consistency(frame, tolerance=0.1)
    assert len(mismatches) == 1


def test_quality_report_detects_duplicate() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": date(2026, 4, 17),
                "participant_type": "FII/FPI",
                "buy_value": 100.0,
                "sell_value": 80.0,
                "net_value": 20.0,
                "market_segment": "capital_market",
                "sector": pd.NA,
                "series_kind": "direct",
                "source_name": "test",
            },
            {
                "date": date(2026, 4, 17),
                "participant_type": "FII/FPI",
                "buy_value": 100.0,
                "sell_value": 80.0,
                "net_value": 20.0,
                "market_segment": "capital_market",
                "sector": pd.NA,
                "series_kind": "direct",
                "source_name": "test",
            },
        ]
    )
    report = build_quality_report(frame)
    assert len(report.duplicates) == 2
