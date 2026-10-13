"""
Offline tests for scripts/check_nse_mcp.py (parsing and diff logic only).

No network: the MCP client and Yahoo cache are never touched here.
"""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts import check_nse_mcp as m  # noqa: E402


def _rpc_json(result, request_id=2):
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def _tool_result(payload):
    return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


class TestRpcParsing:
    def test_json_body(self):
        msg = m.parse_rpc_body(_rpc_json({"ok": 1}), "application/json", 2)
        assert msg["result"] == {"ok": 1}

    def test_sse_body_skips_notifications_and_matches_id(self):
        body = (
            "event: message\n"
            'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n\n'
            f"event: message\ndata: {_rpc_json({'ok': 2}, request_id=7)}\n\n"
        )
        msg = m.parse_rpc_body(body, "text/event-stream", 7)
        assert msg["result"] == {"ok": 2}

    def test_multiline_sse_data_is_joined(self):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"a": 1}})
        half = len(payload) // 2
        body = f"data: {payload[:half]}\ndata: {payload[half:]}\n\n"
        assert m.parse_rpc_body(body, "text/event-stream", 1)["result"] == {"a": 1}

    def test_empty_body_is_none(self):
        assert m.parse_rpc_body("", "", None) is None

    def test_garbage_body_raises(self):
        with pytest.raises(m.McpError):
            m.parse_rpc_body("<html>nope</html>", "text/html", 1)

    def test_sse_without_data_raises(self):
        with pytest.raises(m.McpError):
            m.parse_rpc_body("event: ping\n\n", "text/event-stream", 1)


class TestToolPayload:
    def test_text_json_is_decoded(self):
        assert m.extract_tool_payload(_tool_result({"a": 1})) == {"a": 1}

    def test_structured_content_preferred(self):
        result = {"structuredContent": {"b": 2}, "content": [{"type": "text", "text": "ignored"}]}
        assert m.extract_tool_payload(result) == {"b": 2}

    def test_is_error_raises(self):
        with pytest.raises(m.McpError):
            m.extract_tool_payload({"isError": True, "content": [{"type": "text", "text": "bad"}]})

    def test_non_json_text_raises(self):
        with pytest.raises(m.McpError):
            m.extract_tool_payload({"content": [{"type": "text", "text": "| a | b |"}]})


class TestToolDiscovery:
    TOOLS = [
        {
            "name": "get_index_history",
            "inputSchema": {"properties": {"indexName": {}, "months": {}, "endDate": {}}},
        }
    ]

    def test_expected_tool_passes(self):
        m.check_tools(self.TOOLS)

    def test_missing_tool_raises(self):
        with pytest.raises(m.McpError, match="not advertised"):
            m.check_tools([{"name": "something_else", "inputSchema": {}}])

    def test_renamed_argument_raises(self):
        tools = json.loads(json.dumps(self.TOOLS))
        tools[0]["inputSchema"]["properties"].pop("endDate")
        with pytest.raises(m.McpError, match="endDate"):
            m.check_tools(tools)


class TestHistoryParsing:
    def test_iso_date_with_day_le_12_is_not_swapped(self):
        # Regression: pandas dayfirst=True read 2026-08-06 as 2026-06-08.
        s = m.parse_index_history({"data": [{"date": "2026-08-06", "close": 24636.0}]})
        assert s.index[0] == pd.Timestamp("2026-08-06")

    def test_dmy_date_is_day_first(self):
        assert m.parse_date_str("06-08-2026") == pd.Timestamp("2026-08-06")
        assert m.parse_date_str("06/08/2026") == pd.Timestamp("2026-08-06")

    def test_comma_formatted_closes_and_dayfirst_dates(self):
        payload = {
            "data": [
                {"Date": "05-09-2026", "CLOSE": "25,000.50"},
                {"Date": "04-09-2026", "CLOSE": "24,900.00"},
            ]
        }
        s = m.parse_index_history(payload)
        assert list(s.index) == [pd.Timestamp("2026-09-04"), pd.Timestamp("2026-09-05")]
        assert s.iloc[-1] == pytest.approx(25000.5)

    def test_iso_dates_and_nested_rows(self):
        payload = {"result": {"rows": [{"date": "2026-09-05", "closeValue": 14.2}]}}
        s = m.parse_index_history(payload)
        assert s.iloc[0] == pytest.approx(14.2)

    def test_no_rows_raises(self):
        with pytest.raises(m.McpError):
            m.parse_index_history({"nothing": "here"})


class TestDiffLogic:
    IDX = pd.to_datetime(["2026-09-04", "2026-09-05"])

    def test_pct_mode_flags_only_large_moves(self):
        yahoo = pd.Series([25000.0, 25000.0], index=self.IDX)
        nse = pd.Series([25150.0, 25025.0], index=self.IDX)  # +0.6% and +0.1%
        cmp = m.compare_series(nse, yahoo, mode="pct", threshold=0.5)
        assert bool(cmp.loc["2026-09-04", "flag"]) is True
        assert bool(cmp.loc["2026-09-05", "flag"]) is False

    def test_abs_mode_flags_vix_points(self):
        yahoo = pd.Series([14.0, 14.0], index=self.IDX)
        nse = pd.Series([14.2, 14.5], index=self.IDX)
        cmp = m.compare_series(nse, yahoo, mode="abs", threshold=0.3)
        assert bool(cmp.loc["2026-09-04", "flag"]) is False
        assert bool(cmp.loc["2026-09-05", "flag"]) is True

    def test_tz_aware_index_aligns_with_naive(self):
        yahoo = pd.Series(
            [1.0, 2.0],
            index=pd.DatetimeIndex(["2026-09-05 15:30", "2026-09-04 15:30"]).tz_localize("Asia/Kolkata"),
        )
        nse = pd.Series([1.0, 2.0], index=self.IDX)
        assert len(m.compare_series(nse, yahoo, mode="abs", threshold=0.3)) == 2

    def test_no_overlap_gives_empty_comparison(self):
        nse = pd.Series([1.0], index=pd.to_datetime(["2026-01-01"]))
        yahoo = pd.Series([1.0], index=pd.to_datetime(["2026-02-01"]))
        assert m.compare_series(nse, yahoo, mode="pct", threshold=0.5).empty

    def test_unmatched_days_reported_both_ways(self):
        only_n, only_y = m.unmatched_days(
            pd.Series([1.0], index=pd.to_datetime(["2026-09-03"])),
            pd.Series([1.0], index=pd.to_datetime(["2026-09-04"])),
        )
        assert only_n == [date(2026, 9, 3)]
        assert only_y == [date(2026, 9, 4)]

    def test_bad_mode_raises(self):
        with pytest.raises(ValueError):
            m.compare_series(pd.Series(dtype=float), pd.Series(dtype=float), mode="bps", threshold=1)


class TestVixSanity:
    def test_above_60_flagged(self):
        problems = m.vix_sanity(
            pd.Series([65.0], index=pd.to_datetime(["2026-09-04"])), {}, source="test"
        )
        assert any("> 60" in p for p in problems)

    def test_equal_to_other_series_flagged(self):
        vix = pd.Series([22000.0], index=pd.to_datetime(["2026-09-05"]))
        nifty = pd.Series([22000.0], index=pd.to_datetime(["2026-09-05"]))
        problems = m.vix_sanity(vix, {"Nifty 50": nifty}, source="test")
        assert any("equals Nifty 50" in p for p in problems)

    def test_plausible_vix_is_clean(self):
        vix = pd.Series([14.2], index=pd.to_datetime(["2026-09-05"]))
        nifty = pd.Series([25000.0], index=pd.to_datetime(["2026-09-05"]))
        assert m.vix_sanity(vix, {"Nifty 50": nifty}, source="test") == []
