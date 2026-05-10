from __future__ import annotations

from datetime import date

import pandas as pd

from src.normalize.tradewise_reconstruction import (
    DEFAULT_PROFILES,
    _coerce_transaction_code,
    aggregate_reconstruction,
    build_archive_month_index,
    expand_month_window,
    iter_month_starts,
    reconstruct_streaming_for_date_range,
)


def test_aggregate_reconstruction_strict_profile() -> None:
    trade_df = pd.DataFrame(
        [
            {
                "trade_date": date(2025, 1, 1),
                "transaction_action": "buy",
                "report_type": "DL_RPT_TYPE_N",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 10.0,
            },
            {
                "trade_date": date(2025, 1, 1),
                "transaction_action": "sell",
                "report_type": "DL_RPT_TYPE_N",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 4.0,
            },
            {
                "trade_date": date(2025, 1, 1),
                "transaction_action": "buy",
                "report_type": "DL_RPT_TYPE_D",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 100.0,
            },
        ]
    )
    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == "strict_cash_new_only")
    result = aggregate_reconstruction(trade_df, profile)
    row = result.iloc[0]
    assert row["buy"] == 10.0
    assert row["sell"] == 4.0
    assert row["net"] == 6.0


def test_aggregate_reconstruction_signed_delete_profile() -> None:
    trade_df = pd.DataFrame(
        [
            {
                "trade_date": date(2025, 1, 1),
                "transaction_action": "buy",
                "report_type": "DL_RPT_TYPE_N",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 10.0,
            },
            {
                "trade_date": date(2025, 1, 1),
                "transaction_action": "buy",
                "report_type": "DL_RPT_TYPE_D",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 3.0,
            },
        ]
    )
    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == "cash_signed_with_delete")
    result = aggregate_reconstruction(trade_df, profile)
    row = result.iloc[0]
    assert row["buy"] == 7.0


def test_aggregate_reconstruction_uses_report_date_by_default() -> None:
    trade_df = pd.DataFrame(
        [
            {
                "trade_date": date(2025, 1, 1),
                "report_date": date(2025, 1, 2),
                "transaction_action": "buy",
                "report_type": "DL_RPT_TYPE_N",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 10.0,
            },
            {
                "trade_date": date(2025, 1, 1),
                "report_date": date(2025, 1, 2),
                "transaction_action": "sell",
                "report_type": "DL_RPT_TYPE_N",
                "instrument_type": "REG_DL_INSTR_EQ",
                "value_crore": 4.0,
            },
        ]
    )
    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == "strict_cash_new_only")
    result = aggregate_reconstruction(trade_df, profile)
    row = result.iloc[0]
    assert row["date"] == date(2025, 1, 2)
    assert row["net"] == 6.0


def test_iter_month_starts_and_window_expansion() -> None:
    months = iter_month_starts(date(2025, 1, 15), date(2025, 3, 2))
    assert months == [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)]
    expanded = expand_month_window([date(2025, 2, 1)], window_months=1)
    assert expanded == [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)]


def test_build_archive_month_index_parses_href_and_label() -> None:
    records = [
        {"year": 2025, "month_label": "January", "href": "Monthly_Trade_Files/Jan_2025.zip"},
        {"year": 2025, "month_label": "February", "href": "Monthly_Trade_Files/Feb_2025.zip"},
    ]
    month_index = build_archive_month_index(records)
    assert month_index[date(2025, 1, 1)]["href"].endswith("Jan_2025.zip")
    assert month_index[date(2025, 2, 1)]["href"].endswith("Feb_2025.zip")


def test_transaction_code_is_zero_padded() -> None:
    assert _coerce_transaction_code(1) == "01"
    assert _coerce_transaction_code("4") == "04"
    assert _coerce_transaction_code("12") == "12"


def test_reconstruct_streaming_for_date_range_sums_by_date(monkeypatch) -> None:
    frames = {
        "a.zip": pd.DataFrame(
            [
                {
                    "trade_date": date(2025, 1, 1),
                    "report_date": date(2025, 1, 2),
                    "transaction_action": "buy",
                    "report_type": "DL_RPT_TYPE_N",
                    "instrument_type": "REG_DL_INSTR_EQ",
                    "value_crore": 10.0,
                }
            ]
        ),
        "b.zip": pd.DataFrame(
            [
                {
                    "trade_date": date(2025, 1, 1),
                    "report_date": date(2025, 1, 2),
                    "transaction_action": "sell",
                    "report_type": "DL_RPT_TYPE_N",
                    "instrument_type": "REG_DL_INSTR_EQ",
                    "value_crore": 4.0,
                }
            ]
        ),
    }

    def fake_parse(path: str) -> pd.DataFrame:
        return frames[path]

    monkeypatch.setattr("src.normalize.tradewise_reconstruction.parse_tradewise_zip", fake_parse)
    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == "strict_cash_new_only")
    result = reconstruct_streaming_for_date_range(["a.zip", "b.zip"], profile)
    row = result.iloc[0]
    assert row["date"] == date(2025, 1, 2)
    assert row["buy"] == 10.0
    assert row["sell"] == 4.0
    assert row["net"] == 6.0
