#!/usr/bin/env python3
"""
Read-only cross-check of Yahoo parquet cache index closes against NSE's MCP server.

Compares EOD closes for Nifty 50 (nifty_close), Nifty Bank (nifty_bank) and
India VIX (vix) from the repo's Yahoo cache with NSE's official EOD MCP server.

USAGE
    .venv/bin/python scripts/check_nse_mcp.py                 # live cross-check, last 90 days
    .venv/bin/python scripts/check_nse_mcp.py --days 30 --pct-threshold 0.3
    .venv/bin/python scripts/check_nse_mcp.py --selftest      # offline fixtures only

EXIT CODES
    0  clean (no discrepancies)
    1  discrepancies flagged (index pct or VIX abs threshold, implausible VIX)
    2  network or protocol error (HTTP, timeout, bad JSON-RPC/SSE, tool mismatch)

LICENSE / USE CAVEAT (NSE terms)
    NSE's MCP data is for informational use only. NSE's disclaimer forbids using
    this data to train or fine-tune AI models or algorithms, and forbids
    commercial deployment of it. This script is a read-only cross-check. It never
    writes into data/.cache, never feeds any training or model code, and must not
    be extended to do so. Output is printed to stdout only.

SCOPE
    Uses the EOD endpoint only (https://mcp.nseindia.in/bhavcopy/cm/mcp). The
    live endpoint (cmmkt/mcp) is not used. NSE's MCP has no option chain, F&O or
    intraday data.

PROTOCOL
    MCP streamable-HTTP (protocol 2025-03-26): POST initialize, capture the
    Mcp-Session-Id header, POST notifications/initialized, then tools/list
    (to verify tool and argument names at runtime) and tools/call. Responses may
    be application/json or text/event-stream.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_URL = "https://mcp.nseindia.in/bhavcopy/cm/mcp"
PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "check_nse_mcp", "version": "0.1"}

# Expected NSE tool/argument names (verified against tools/list at runtime).
EXPECTED_TOOL = "get_index_history"
EXPECTED_ARGS = ("indexName", "months", "endDate")

# comparison key -> (NSE index name, label, comparison mode)
SERIES = {
    "nifty_close": ("NIFTY 50", "Nifty 50 close", "pct"),
    "nifty_bank": ("NIFTY BANK", "Nifty Bank close", "pct"),
    "vix": ("India VIX", "India VIX", "abs"),
}

DEFAULT_PCT_THRESHOLD = 0.5
DEFAULT_VIX_THRESHOLD = 0.3
VIX_IMPLAUSIBLE_ABOVE = 60.0


class McpError(Exception):
    """Network, HTTP, JSON-RPC or protocol failure. Maps to exit code 2."""


# ---------------------------------------------------------------------------
# Offline parsing helpers (pure functions, unit-tested)
# ---------------------------------------------------------------------------

def parse_rpc_body(body: str, content_type: str, request_id: int | None) -> dict[str, Any] | None:
    """Parse a JSON-RPC response body delivered as JSON or as SSE.

    Returns the matching JSON-RPC message, or None for an empty body (202 for
    notifications). Raises McpError if the body cannot be parsed.
    """
    text = (body or "").strip()
    if not text:
        return None

    is_sse = "text/event-stream" in (content_type or "").lower() or text.startswith(("event:", "data:"))
    if not is_sse:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpError(f"Response is neither JSON nor SSE: {text[:200]!r}") from exc

    # SSE: events are separated by blank lines; a data field may span lines.
    messages: list[dict[str, Any]] = []
    for event in re.split(r"\r?\n\r?\n", text):
        data_lines = [line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise McpError(f"Invalid JSON in SSE data: {payload[:200]!r}") from exc
        if isinstance(msg, dict):
            messages.append(msg)

    if not messages:
        raise McpError("SSE body contained no data events")
    for msg in messages:
        if request_id is None or msg.get("id") == request_id:
            return msg
    return messages[-1]


def extract_tool_payload(result: dict[str, Any]) -> Any:
    """Turn a tools/call result into Python data (prefers structuredContent)."""
    if result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)]
        raise McpError(f"Tool returned isError: {' '.join(texts)[:300]}")
    if "structuredContent" in result and result["structuredContent"] is not None:
        return result["structuredContent"]
    texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
    if not texts:
        raise McpError("Tool result has no text content")
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError as exc:
        raise McpError(f"Tool text is not JSON (parser needs update): {joined[:200]!r}") from exc


def check_tools(tools: list[dict[str, Any]]) -> None:
    """Fail clearly if the advertised tool or its arguments differ from what this script expects."""
    by_name = {t.get("name"): t for t in tools if isinstance(t, dict)}
    if EXPECTED_TOOL not in by_name:
        raise McpError(f"Tool {EXPECTED_TOOL!r} not advertised. Available: {sorted(by_name)}")
    schema = by_name[EXPECTED_TOOL].get("inputSchema") or {}
    props = set((schema.get("properties") or {}).keys())
    missing = [a for a in EXPECTED_ARGS if a not in props]
    if missing:
        raise McpError(
            f"Tool {EXPECTED_TOOL!r} argument(s) {missing} not in inputSchema. Advertised: {sorted(props)}"
        )


_DATE_KEYS = ("date", "tradedate", "businessdate", "timestamp")
_CLOSE_KEYS = ("close", "closeprice", "indexclose", "closingvalue", "closevalue", "closingprice", "value", "last")


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z]", "", key.lower())


def _find_rows(payload: Any) -> list[dict[str, Any]]:
    """Depth-first search for the first list of dicts that carries a date and a close field."""
    if isinstance(payload, list):
        if payload and all(isinstance(r, dict) for r in payload):
            keys = {_norm_key(k) for r in payload[:3] for k in r}
            if any(k in keys for k in _DATE_KEYS) and any(k in keys for k in _CLOSE_KEYS):
                return payload
        for item in payload:
            found = _find_rows(item)
            if found:
                return found
    elif isinstance(payload, dict):
        for value in payload.values():
            found = _find_rows(value)
            if found:
                return found
    return []


def _pick_key(row: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    lookup = {_norm_key(k): k for k in row}
    for cand in candidates:
        if cand in lookup:
            return lookup[cand]
    return None


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DMY_RE = re.compile(r"^\d{2}[-/.]\d{2}[-/.]\d{4}$")


def parse_date_str(value: str) -> pd.Timestamp:
    """Parse one date string without day/month ambiguity.

    ISO (YYYY-MM-DD) is always year-first. DD-MM-YYYY / DD/MM/YYYY is always
    day-first. Anything else falls back to pandas with dayfirst=True. Note that
    pandas' dayfirst=True mis-reads ISO strings with day <= 12 (2026-08-06 became
    2026-06-08), so ISO must never reach that fallback.
    """
    text = str(value).strip()
    if _ISO_RE.match(text):
        return pd.Timestamp(text[:10])
    if _DMY_RE.match(text):
        return pd.to_datetime(text, format="%d-%m-%Y" if "-" in text else
                              ("%d/%m/%Y" if "/" in text else "%d.%m.%Y"))
    return pd.Timestamp(pd.to_datetime(text, dayfirst=True, errors="coerce"))


def parse_index_history(payload: Any) -> pd.Series:
    """Convert get_index_history output into a date-indexed Series of closes."""
    rows = _find_rows(payload)
    if not rows:
        raise McpError(f"No date+close rows found in tool output: {str(payload)[:200]!r}")
    date_key = _pick_key(rows[0], _DATE_KEYS)
    close_key = _pick_key(rows[0], _CLOSE_KEYS)
    dates = [parse_date_str(r.get(date_key)) for r in rows]
    raw = [str(r.get(close_key, "")).replace(",", "") for r in rows]
    closes = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy()
    series = pd.Series(closes, index=pd.DatetimeIndex(dates)).dropna()
    series = series[~series.index.isna()]
    series.index = series.index.normalize()
    return series.groupby(level=0).last().sort_index()


def to_day_index(series: pd.Series) -> pd.Series:
    """Normalise a Series index to tz-naive midnight timestamps (so NSE and Yahoo align)."""
    idx = pd.DatetimeIndex(pd.to_datetime(series.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = series.copy()
    out.index = idx.normalize()
    return out.groupby(level=0).last().sort_index()


def compare_series(
    nse: pd.Series,
    yahoo: pd.Series,
    *,
    mode: str,
    threshold: float,
) -> pd.DataFrame:
    """Per-day diff of NSE vs Yahoo on overlapping dates.

    mode="pct": flag when |pct diff| > threshold (percent units, e.g. 0.5 = 0.5%).
    mode="abs": flag when |abs diff| > threshold (index points, e.g. VIX 0.3).
    """
    if mode not in {"pct", "abs"}:
        raise ValueError(f"mode must be 'pct' or 'abs', got {mode!r}")
    nse = to_day_index(nse)
    yahoo = to_day_index(yahoo)
    joined = pd.DataFrame({"nse": nse, "yahoo": yahoo}).dropna()
    joined["abs_diff"] = joined["nse"] - joined["yahoo"]
    joined["pct_diff"] = joined["abs_diff"] / joined["yahoo"] * 100.0
    if mode == "pct":
        joined["flag"] = joined["pct_diff"].abs() > threshold
    else:
        joined["flag"] = joined["abs_diff"].abs() > threshold
    joined.index.name = "date"
    return joined


def vix_sanity(vix: pd.Series, others: dict[str, pd.Series], source: str) -> list[str]:
    """Flag implausible VIX values: above 60, or exactly equal to another index's close that day."""
    problems: list[str] = []
    vix = to_day_index(vix)
    for day, value in vix.items():
        if value > VIX_IMPLAUSIBLE_ABOVE:
            problems.append(f"{source} VIX {day.date()} = {value:.2f} (> {VIX_IMPLAUSIBLE_ABOVE:g})")
        for name, other in others.items():
            other = to_day_index(other)
            if day in other.index and other.loc[day] == value:
                problems.append(f"{source} VIX {day.date()} = {value:.2f} equals {name} on the same day")
    return problems


def unmatched_days(nse: pd.Series, yahoo: pd.Series) -> tuple[list[date], list[date]]:
    """Dates present on only one side (informational, not a discrepancy)."""
    n = set(to_day_index(nse).index.date)
    y = set(to_day_index(yahoo).index.date)
    return sorted(n - y), sorted(y - n)


@dataclass
class CheckReport:
    lines: list[str] = field(default_factory=list)
    discrepancies: int = 0

    def add(self, line: str = "") -> None:
        self.lines.append(line)

    def flag(self, line: str) -> None:
        self.discrepancies += 1
        self.lines.append(f"  FLAG: {line}")


def diff_report(
    report: CheckReport,
    label: str,
    comparison: pd.DataFrame,
    mode: str,
    threshold: float,
    only_nse: list[date],
    only_yahoo: list[date],
) -> None:
    report.add(f"{label}: {len(comparison)} overlapping days")
    for day, row in comparison.iterrows():
        unit = "%" if mode == "pct" else " pts"
        shown = f"{row['pct_diff']:+.3f}%" if mode == "pct" else f"{row['abs_diff']:+.2f} pts"
        msg = f"  {day.date()}  nse={row['nse']:.2f}  yahoo={row['yahoo']:.2f}  diff={shown}"
        if row["flag"]:
            report.flag(msg.strip() + f" (threshold {threshold:g}{unit})")
        else:
            report.add(msg)
    if only_nse or only_yahoo:
        report.add(f"  info: dates only in NSE: {[str(d) for d in only_nse]}")
        report.add(f"  info: dates only in Yahoo cache: {[str(d) for d in only_yahoo]}")


# ---------------------------------------------------------------------------
# Minimal MCP streamable-HTTP client (stdlib urllib)
# ---------------------------------------------------------------------------

class McpClient:
    def __init__(self, url: str, timeout: float = 20.0):
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 1

    def _post(self, payload: dict[str, Any], expect_response: bool) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                content_type = resp.headers.get("Content-Type", "")
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200] if exc.fp else ""
            raise McpError(f"HTTP {exc.code} for {payload.get('method')}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise McpError(f"Network error for {payload.get('method')}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise McpError(f"Timeout after {self.timeout:g}s for {payload.get('method')}") from exc

        if not expect_response:
            return None
        msg = parse_rpc_body(body, content_type, payload.get("id"))
        if msg is None:
            raise McpError(f"Empty response body for {payload.get('method')}")
        if "error" in msg:
            err = msg["error"] or {}
            raise McpError(f"JSON-RPC error for {payload.get('method')}: {err.get('code')} {err.get('message')}")
        if "result" not in msg:
            raise McpError(f"JSON-RPC response for {payload.get('method')} has no result")
        return msg["result"]

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._next_id += 1
        result = self._post(payload, expect_response=True)
        assert result is not None
        return result

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method}, expect_response=False)

    def initialize(self) -> None:
        self.request(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        if not self.session_id:
            raise McpError("Server did not return an Mcp-Session-Id header on initialize")
        self.notify("notifications/initialized")

    def list_tools(self) -> list[dict[str, Any]]:
        return self.request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        return extract_tool_payload(result)


def fetch_nse_closes(client: McpClient, index_name: str, start: date, end: date, max_pages: int = 40) -> pd.Series:
    """Fetch EOD closes for [start, end] via get_index_history, following pagination.

    Observed server behaviour: endDate must be ISO YYYY-MM-DD (other formats are
    silently ignored and it defaults to today), each call returns at most ~3
    months of rows, and the response carries next_end_date to continue backwards.
    """
    months = max(1, min(12, (end - start).days // 30 + 2))
    parts: list[pd.Series] = []
    cur_end = end
    for _ in range(max_pages):
        payload = client.call_tool(
            EXPECTED_TOOL,
            {"indexName": index_name, "months": months, "endDate": cur_end.isoformat()},
        )
        parts.append(parse_index_history(payload))
        from_date = payload.get("from_date") if isinstance(payload, dict) else None
        nxt = payload.get("next_end_date") if isinstance(payload, dict) else None
        if from_date and date.fromisoformat(str(from_date)[:10]) <= start:
            break
        if not nxt:
            break
        nxt_date = date.fromisoformat(str(nxt)[:10])
        if nxt_date >= cur_end:
            raise McpError(f"Pagination did not advance for {index_name} (next_end_date={nxt})")
        if nxt_date < start:
            break
        cur_end = nxt_date
    else:
        raise McpError(f"Pagination exceeded {max_pages} pages for {index_name}")
    series = pd.concat(parts).groupby(level=0).last().sort_index()
    return series[(series.index.date >= start) & (series.index.date <= end)]


# ---------------------------------------------------------------------------
# Yahoo cache side (read-only, cache-only)
# ---------------------------------------------------------------------------

def build_yahoo_dataset(start: date, end: date) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build the dataset the same safe way as the backtester, cache-only (no network).

    Returns the combined frame plus the raw per-ticker Yahoo frames, so the
    caller can detect silent fallbacks (build_combined_dataset fills VIX with
    15.0 and missing indices with 0.0 when a series is absent).
    """
    import os

    from data.market_data import MarketDataFetcher

    prev = os.environ.get("MARKET_DATA_CACHE_ONLY")
    os.environ["MARKET_DATA_CACHE_ONLY"] = "1"
    try:
        fetcher = MarketDataFetcher(start, end)
        raw = fetcher.fetch_all()
        frame = fetcher.build_combined_dataset()
    finally:
        if prev is None:
            os.environ.pop("MARKET_DATA_CACHE_ONLY", None)
        else:
            os.environ["MARKET_DATA_CACHE_ONLY"] = prev

    for key, label in (("nifty", "Nifty 50"), ("vix", "India VIX"), ("nifty_bank", "Nifty Bank")):
        if raw.get(key) is None or len(raw[key]) == 0:
            raise McpError(f"No Yahoo {label} rows in cache for this window; refresh cache with network first")
    return frame, raw


def window_series(series: pd.Series, start: date, end: date) -> pd.Series:
    """Restrict a series to [start, end] on normalised calendar days."""
    s = to_day_index(series)
    return s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]


# ---------------------------------------------------------------------------
# Selftest fixtures (offline)
# ---------------------------------------------------------------------------

_FIXTURE_JSON_RESULT = {
    "content": [
        {
            "type": "text",
            "text": json.dumps(
                {
                    "indexName": "NIFTY 50",
                    "data": [
                        {"Date": "05-09-2026", "CLOSE": "25,000.50"},
                        {"Date": "04-09-2026", "CLOSE": "24,900.00"},
                    ],
                }
            ),
        }
    ],
    "isError": False,
}
_FIXTURE_JSON_BODY = json.dumps({"jsonrpc": "2.0", "id": 3, "result": _FIXTURE_JSON_RESULT})
_FIXTURE_SSE_BODY = (
    "event: message\n"
    'data: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"}}\n\n'
    f"event: message\ndata: {_FIXTURE_JSON_BODY}\n\n"
)
_FIXTURE_TOOLS = {
    "tools": [
        {
            "name": "get_index_history",
            "inputSchema": {
                "type": "object",
                "properties": {"indexName": {}, "months": {}, "endDate": {}},
                "required": ["indexName"],
            },
        },
        {"name": "get_market_mood", "inputSchema": {"type": "object", "properties": {"date": {}}}},
    ]
}


def _selftest() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(f"{'PASS' if cond else 'FAIL'}  {name}")
        if not cond:
            failures.append(name)

    # 1. JSON body
    msg = parse_rpc_body(_FIXTURE_JSON_BODY, "application/json", 3)
    check("parse JSON-RPC body", msg is not None and msg["id"] == 3)

    # 2. SSE body with a notification event first
    msg = parse_rpc_body(_FIXTURE_SSE_BODY, "text/event-stream", 3)
    check("parse SSE body picks matching id", msg is not None and msg.get("id") == 3)

    # 3. Empty body (202 for notifications)
    check("empty body returns None", parse_rpc_body("", "", None) is None)

    # 4. Garbage body raises
    try:
        parse_rpc_body("<html>oops</html>", "text/html", 1)
        check("garbage body raises McpError", False)
    except McpError:
        check("garbage body raises McpError", True)

    # 5. Tool payload extraction and history parsing (comma-formatted closes, DD-MM-YYYY dates)
    payload = extract_tool_payload(msg["result"])
    nse = parse_index_history(payload)
    check(
        "parse index history values",
        list(nse.round(2)) == [24900.0, 25000.5] and nse.index[-1] == pd.Timestamp("2026-09-05"),
    )

    # 5b. ISO dates with day <= 12 must not be read day-first (regression: 2026-08-06 -> 2026-06-08)
    check(
        "ISO date 2026-08-06 parses as 6 Aug",
        parse_date_str("2026-08-06") == pd.Timestamp("2026-08-06")
        and parse_date_str("06-08-2026") == pd.Timestamp("2026-08-06"),
    )

    # 6. Tool error result raises
    try:
        extract_tool_payload({"isError": True, "content": [{"type": "text", "text": "bad date"}]})
        check("isError result raises", False)
    except McpError:
        check("isError result raises", True)

    # 7. Tool discovery: ok, then missing argument
    try:
        check_tools(_FIXTURE_TOOLS["tools"])
        check("tools/list has expected tool and args", True)
    except McpError as exc:
        check(f"tools/list has expected tool and args ({exc})", False)
    renamed = json.loads(json.dumps(_FIXTURE_TOOLS["tools"]))
    renamed[0]["inputSchema"]["properties"].pop("endDate")
    try:
        check_tools(renamed)
        check("missing endDate arg is detected", False)
    except McpError:
        check("missing endDate arg is detected", True)

    # 8. Diff logic: pct mode flags a 0.6% move, passes a 0.1% move
    yahoo = pd.Series([25000.0, 25000.0], index=pd.to_datetime(["2026-09-04", "2026-09-05"]))
    nse_fix = pd.Series([25150.0, 25025.0], index=pd.to_datetime(["2026-09-04", "2026-09-05"]))
    cmp_pct = compare_series(nse_fix, yahoo, mode="pct", threshold=0.5)
    check("pct diff flags >0.5% and not 0.1%", bool(cmp_pct.loc["2026-09-04", "flag"]) and not bool(cmp_pct.loc["2026-09-05", "flag"]))

    # 9. Diff logic: abs mode for VIX, 0.2 pts passes, 0.5 pts flags
    vix_y = pd.Series([14.0, 14.0], index=pd.to_datetime(["2026-09-04", "2026-09-05"]))
    vix_n = pd.Series([14.2, 14.5], index=pd.to_datetime(["2026-09-04", "2026-09-05"]))
    cmp_vix = compare_series(vix_n, vix_y, mode="abs", threshold=0.3)
    check("abs diff flags >0.3 pts only", (not cmp_vix.loc["2026-09-04", "flag"]) and bool(cmp_vix.loc["2026-09-05", "flag"]))

    # 10. Tz-aware and unsorted indices align after normalisation
    tz_y = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2026-09-05 15:30", "2026-09-04 15:30"]).tz_localize("Asia/Kolkata"))
    tz_n = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-09-04", "2026-09-05"]))
    check("tz-aware index aligns with naive", len(compare_series(tz_n, tz_y, mode="abs", threshold=0.3)) == 2)

    # 11. Unmatched dates are reported, not dropped silently
    only_n, only_y = unmatched_days(
        pd.Series([1.0], index=pd.to_datetime(["2026-09-03"])),
        pd.Series([1.0], index=pd.to_datetime(["2026-09-04"])),
    )
    check("unmatched days reported both ways", only_n == [date(2026, 9, 3)] and only_y == [date(2026, 9, 4)])

    # 12. VIX sanity: >60 and equal-to-another-series
    problems = vix_sanity(
        pd.Series([65.0, 14.0], index=pd.to_datetime(["2026-09-04", "2026-09-05"])),
        {"Nifty 50": pd.Series([14.0], index=pd.to_datetime(["2026-09-05"]))},
        source="test",
    )
    check("VIX >60 flagged", any("> 60" in p for p in problems))
    check("VIX equal to another series flagged", any("equals Nifty 50" in p for p in problems))

    print(f"\nselftest: {len(failures)} failure(s)")
    return 0 if not failures else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_live(args: argparse.Namespace) -> int:
    try:
        frame, raw = build_yahoo_dataset(date(2009, 1, 1), date.today())
    except McpError as exc:
        print(f"ERROR (cache): {exc}", file=sys.stderr)
        return 2
    latest = to_day_index(raw["nifty"]["Close"]).index.max().date()
    end = date.fromisoformat(args.end) if args.end else latest
    start = end - timedelta(days=args.days)
    print(f"Window: {start} .. {end} (latest cached Nifty row: {latest})")
    print("Source: Yahoo parquet cache (MARKET_DATA_CACHE_ONLY=1) vs NSE MCP EOD")

    report = CheckReport()
    try:
        client = McpClient(args.url, timeout=args.timeout)
        client.initialize()
        report.add(f"MCP session: {'ok' if client.session_id else 'none'} ({args.url})")
        check_tools(client.list_tools())
        report.add(f"Tool check: {EXPECTED_TOOL} with args {', '.join(EXPECTED_ARGS)} verified")

        nse_series: dict[str, pd.Series] = {}
        for key, (index_name, label, _mode) in SERIES.items():
            nse_series[key] = fetch_nse_closes(client, index_name, start, end)
    except McpError as exc:
        print(f"ERROR (NSE MCP): {exc}", file=sys.stderr)
        return 2

    # Use raw Yahoo closes (not the combined frame) so no fallback values leak in.
    yahoo_by_key = {
        "nifty_close": window_series(raw["nifty"]["Close"], start, end),
        "nifty_bank": window_series(raw["nifty_bank"]["Close"], start, end),
        "vix": window_series(raw["vix"]["Close"], start, end),
    }

    for key, (_idx, label, mode) in SERIES.items():
        threshold = args.pct_threshold if mode == "pct" else args.vix_threshold
        nse = nse_series[key]
        yah = yahoo_by_key[key]
        if nse.empty or yah.empty:
            report.add(f"{label}: no overlapping data (nse rows={len(nse)}, yahoo rows={len(yah)})")
            continue
        comparison = compare_series(nse, yah, mode=mode, threshold=threshold)
        only_nse, only_yahoo = unmatched_days(nse, yah)
        diff_report(report, label, comparison, mode, threshold, only_nse, only_yahoo)

    problems = vix_sanity(nse_series["vix"], {"NSE Nifty 50": nse_series["nifty_close"]}, "NSE")
    problems += vix_sanity(yahoo_by_key["vix"], {"Yahoo Nifty 50": yahoo_by_key["nifty_close"]}, "Yahoo")
    report.add("VIX sanity:")
    if problems:
        for p in problems:
            report.flag(p)
    else:
        report.add("  no implausible VIX values")

    print("\n".join(report.lines))
    print(f"\nDiscrepancies: {report.discrepancies}")
    return 1 if report.discrepancies else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only cross-check of Yahoo cache Nifty 50 / Nifty Bank / India VIX closes against "
            "NSE's MCP EOD server.\n\n"
            "NSE CAVEAT: informational use only. NSE's terms forbid using this data to train or "
            "fine-tune AI models or algorithms, and forbid commercial deployment. This script never "
            "writes to data/.cache and must never feed training code."
        ),
        epilog=(
            "Exit codes: 0 clean, 1 discrepancies, 2 network/protocol error. "
            "--selftest runs offline fixtures and needs no network."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--selftest", action="store_true", help="run offline parsing/diff fixtures and exit")
    parser.add_argument("--days", type=int, default=90, help="window length in calendar days (default 90)")
    parser.add_argument("--end", default=None, help="window end YYYY-MM-DD (default: latest cached Yahoo row)")
    parser.add_argument("--pct-threshold", type=float, default=DEFAULT_PCT_THRESHOLD,
                        help="flag index closes differing by more than this percent (default 0.5)")
    parser.add_argument("--vix-threshold", type=float, default=DEFAULT_VIX_THRESHOLD,
                        help="flag VIX differing by more than this many points (default 0.3)")
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint (default: NSE EOD bhavcopy server)")
    parser.add_argument("--timeout", type=float, default=20.0, help="per-request timeout in seconds (default 20)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    return run_live(args)


if __name__ == "__main__":
    sys.exit(main())
