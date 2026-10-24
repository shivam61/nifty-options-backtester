"""Tests for scripts/log_option_quotes.py and scripts/summarize_quote_log.py.

Offline only: no test calls a live endpoint. The NSE payload is the synthetic fixture
tests/fixtures/nse_option_chain_sample.json (field names as read by data/option_chain.py).
Every test writes to tmp_path, never to the committed paper_trading/tracker/QUOTE_LOG.csv.
"""

import csv
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from config import WeeklyBacktestConfig
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread
from utils.market_clock import IST

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "nse_option_chain_sample.json"
COMMITTED_LOG = REPO / "paper_trading" / "tracker" / "QUOTE_LOG.csv"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod          # dataclasses look the module up by name while executing
    spec.loader.exec_module(mod)
    return mod


LQ = _load("log_option_quotes", "scripts/log_option_quotes.py")
SQ = _load("summarize_quote_log", "scripts/summarize_quote_log.py")

TUE_1130 = datetime(2026, 10, 21, 11, 30, tzinfo=IST)   # Wednesday, inside the window
WED_OUT = datetime(2026, 10, 21, 10, 15, tzinfo=IST)     # Wednesday, before 11:00
SAT_1130 = datetime(2026, 10, 24, 11, 30, tzinfo=IST)    # Saturday


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


# ───────────────────────────────────────────────────────── parsing

def test_parse_nse_chain_fields(payload):
    snap = LQ.parse_nse_chain(payload["option_chain"])
    assert snap.spot == 23000.0
    assert snap.exchange_ts == "21-Oct-2026 11:30:05"
    assert snap.expiries == ["27-Oct-2026", "03-Nov-2026"]
    q = snap.quotes[("27-Oct-2026", 23350, "CE")]
    assert q["bid"] == 23.1 and q["ask"] == 24.3
    assert q["bid_qty"] == 1300 and q["ask_qty"] == 975
    assert q["oi"] > 0 and q["volume"] > 0 and q["last"] > 0


def test_parse_nse_chain_zero_bid_is_kept_as_zero_not_dropped(payload):
    snap = LQ.parse_nse_chain(payload["option_chain"])
    assert snap.quotes[("27-Oct-2026", 22900, "PE")]["bid"] == 0


def test_parse_indices_vix(payload):
    ix = LQ.parse_nse_indices(payload["all_indices"])
    assert ix == {"vix": 14.5, "nifty": 23000.0, "nifty_week_ago": None}


def _to_v3(payload):
    """The legacy fixture rewritten into option-chain-v3 field names (live 2026-10-24 shape)."""
    out = json.loads(json.dumps(payload))
    for row in out["option_chain"]["records"]["data"]:
        row["expiryDates"] = row.pop("expiryDate")
        for opt in ("CE", "PE"):
            leg = row.get(opt)
            if not leg:
                continue
            for old, new in (("bidprice", "buyPrice1"), ("askPrice", "sellPrice1"),
                             ("bidQty", "buyQuantity1"), ("askQty", "sellQuantity1")):
                leg[new] = leg.pop(old, None)
    return out


def test_parse_v3_shape_matches_legacy_shape(payload):
    legacy = LQ.parse_nse_chain(payload["option_chain"])
    v3 = LQ.parse_nse_chain(_to_v3(payload)["option_chain"])
    assert v3.quotes == legacy.quotes
    assert v3.spot == legacy.spot and v3.expiries == legacy.expiries


def test_nse_session_never_requests_brotli():
    # requests cannot decode br without the brotli package; NSE then returns undecodable bytes
    tokens = [t.strip() for t in LQ._nse_session().headers["Accept-Encoding"].split(",")]
    assert "br" not in tokens and "gzip" in tokens


def test_fetch_nse_one_v3_request_per_expiry(payload, monkeypatch):
    v3 = _to_v3(payload)
    all_rows = v3["option_chain"]["records"]["data"]
    urls = []

    class _NoopSession:
        def get(self, url, timeout=None):
            return None

    def fake_get(session, url, timeout=15):
        urls.append(url)
        if "option-chain-v3" in url:
            exp = url.split("expiry=")[1]
            rows = [r for r in all_rows if r["expiryDates"] == exp]
            return {"records": {"data": rows, "timestamp": v3["option_chain"]["records"]["timestamp"],
                                "underlyingValue": 23000.0,
                                "expiryDates": v3["option_chain"]["records"]["expiryDates"]}}
        return payload["all_indices"]

    monkeypatch.setattr(LQ, "_nse_session", lambda: _NoopSession())
    monkeypatch.setattr(LQ, "_get", fake_get)
    monkeypatch.setattr(LQ.time, "sleep", lambda _s: None)
    out = LQ.fetch_nse(["27-Oct-2026", "03-Nov-2026"])

    chain_urls = [u for u in urls if "option-chain-v3" in u]
    assert [u.split("expiry=")[1] for u in chain_urls] == ["27-Oct-2026", "03-Nov-2026"]
    assert all("symbol=NIFTY" in u for u in chain_urls)
    snap = LQ.parse_nse_chain(out["option_chain"])
    assert ("27-Oct-2026", 23350, "CE") in snap.quotes
    assert snap.expiries == v3["option_chain"]["records"]["expiryDates"]
    assert snap.exchange_ts == "21-Oct-2026 11:30:05"


def test_fetch_nse_no_rows_is_source_unavailable(monkeypatch):
    class _NoopSession:
        def get(self, url, timeout=None):
            return None

    empty = {"records": {"data": [], "timestamp": "", "underlyingValue": 0, "expiryDates": ["27-Oct-2026"]}}
    monkeypatch.setattr(LQ, "_nse_session", lambda: _NoopSession())
    monkeypatch.setattr(LQ, "_get", lambda session, url, timeout=15: empty)
    monkeypatch.setattr(LQ.time, "sleep", lambda _s: None)
    with pytest.raises(LQ.SourceUnavailable, match="no rows"):
        LQ.fetch_nse(["27-Oct-2026"])


def test_unattended_ret_5d_from_one_week_close_and_override(tmp_path, payload):
    p = json.loads(json.dumps(payload))
    for d in p["all_indices"]["data"]:
        if d.get("indexSymbol") == "NIFTY 50":
            d["oneWeekAgoVal"] = 23230.0            # close five trading days back
    f = tmp_path / "week.json"
    f.write_text(json.dumps(p))
    res = LQ.run_once(from_json=f, log_path=tmp_path / "Q.csv", now=TUE_1130, write=False)
    assert res.status == "appended"
    assert res.rows[0]["ret_5d"] == round(23000 / 23230 - 1, 5)          # -0.0099: inside the 2% band
    assert {r["rule_selected"] for r in res.rows if r["structure"] == "IC"} == {"1"}

    # an explicit --ret-5d still wins over the derived value
    res = LQ.run_once(from_json=f, log_path=tmp_path / "Q.csv", now=TUE_1130, ret_5d=-0.03, write=False)
    assert res.rows[0]["ret_5d"] == -0.03
    assert {r["rule_selected"] for r in res.rows if r["structure"] == "IC"} == {"0"}


def test_parse_groww_has_no_bid_ask():
    groww = {"optionChain": {
        "expiryDetailsDto": {"currentExpiry": "2026-10-27", "expiryDates": ["2026-10-27"], "expiryLotSize": 65},
        "optionChains": [{"strikePrice": 2300000,
                          "callOption": {"ltp": 65.0, "openInterest": 1000, "prevOpenInterest": 900, "volume": 50},
                          "putOption": {"ltp": 63.0, "openInterest": 800, "prevOpenInterest": 800, "volume": 40}}],
    }}
    snap = LQ.parse_groww(groww)
    assert snap.source == "groww" and snap.expiries == ["27-Oct-2026"]
    q = snap.quotes[("27-Oct-2026", 23000, "CE")]
    assert q["bid"] is None and q["ask"] is None and q["last"] == 65.0
    row = LQ.spread_fields(q["bid"], q["ask"])
    assert row["quote_status"] == "no_quote" and row["half_spread"] == ""


# ───────────────────────────────────────────────────────── spread math

@pytest.mark.parametrize("bid,ask,status,half", [
    (23.1, 24.3, "ok", 0.6),
    (10.0, 10.0, "ok", 0.0),
    (24.3, 23.1, "crossed", ""),
    (0, 24.3, "one_sided", ""),
    (23.1, 0, "one_sided", ""),
    (0, 0, "no_quote", ""),
    (None, None, "no_quote", ""),
])
def test_spread_math(bid, ask, status, half):
    f = LQ.spread_fields(bid, ask)
    assert f["quote_status"] == status
    assert f["half_spread"] == half
    if status == "ok":
        assert f["mid"] == round((bid + ask) / 2, 4)
        assert f["spread"] == round(ask - bid, 4)


# ───────────────────────────────────────────────────────── model slippage

def test_model_slip_matches_engine_function():
    cfg = ChainConfig()
    cm = cfg.weekly.cost_model
    # base 0.45 at VIX <= 15 and ATM; the engine's own _slip_unit is the reference
    assert LQ.model_slip_unit(14.5, 23000, 23000) == pytest.approx(0.45)
    assert LQ.model_slip_unit(20.0, 23000, 23000) == pytest.approx(
        cm.slippage_per_unit(20.0, 1.0) * cfg.slippage_multiplier)
    # OTM strike adds the moneyness term (strike 23600 is 2.6% OTM; term applies only beyond 5%)
    assert LQ.model_slip_unit(14.5, 24500, 23000) == pytest.approx(
        cm.slippage_per_unit(14.5, 24500 / 23000) * cfg.slippage_multiplier)
    assert LQ.model_slip_unit(20.0, 23000, 23000) == pytest.approx(0.45 + 5 * cm.slippage_vix_scale)


# ───────────────────────────────────────────────────────── leg construction

def test_build_structures_legs_and_roles():
    spot, vix, dte = 23000.0, 14.5, 6
    rows = LQ.build_structures(spot, vix, dte, 0.065, ret_5d=None)
    by = lambda s: [r for r in rows if r["structure"] == s]  # noqa: E731

    ic = WeeklyIronCondor(lots=1, lot_size=65).generate_legs(spot, vix, dte)
    pcs = WeeklyPutCreditSpread(lots=1, lot_size=65).generate_legs(spot, vix, dte)
    ic_keys = {(int(l.strike), l.option_type) for l in ic}
    pcs_keys = {(int(l.strike), l.option_type) for l in pcs}

    ic_leg_rows = [r for r in by("IC") if r["role"] in ("short", "long")]
    pcs_leg_rows = [r for r in by("PCS") if r["role"] in ("short", "long")]
    assert {(r["strike"], r["option_type"]) for r in ic_leg_rows} == ic_keys
    assert {(r["strike"], r["option_type"]) for r in pcs_leg_rows} == pcs_keys
    assert len(ic_leg_rows) == 4 and len(pcs_leg_rows) == 2
    # short legs are the sold strikes
    shorts = {(int(l.strike), l.option_type) for l in ic if l.is_short}
    assert {(r["strike"], r["option_type"]) for r in ic_leg_rows if r["role"] == "short"} == shorts

    straddle = by("ATM_STRADDLE")
    assert {(r["strike"], r["option_type"], r["role"]) for r in straddle} == {
        (23000, "CE", "atm"), (23000, "PE", "atm")}

    nb = [r for r in by("IC") if r["role"] == "neighbour"]
    assert nb and {r["offset_strikes"] for r in nb} <= {-2, -1, 1, 2}
    assert all(r["strike"] % 50 == 0 for r in rows)


def test_build_structures_no_duplicate_keys():
    rows = LQ.build_structures(23000.0, 14.5, 6, 0.065, ret_5d=0.001)
    keys = [(r["structure"], r["strike"], r["option_type"]) for r in rows]
    assert len(keys) == len(set(keys))


def test_rule_selected_follows_weekly_rule():
    # VIX 14.5 with |5d return| < 2% -> IC (weekly_exit_policy rule); no return -> PCS fallback
    ic_rows = LQ.build_structures(23000.0, 14.5, 6, 0.065, ret_5d=0.001)
    pcs_rows = LQ.build_structures(23000.0, 14.5, 6, 0.065, ret_5d=None)
    assert {r["rule_selected"] for r in ic_rows if r["structure"] == "IC"} == {"1"}
    assert {r["rule_selected"] for r in ic_rows if r["structure"] == "PCS"} == {"0"}
    assert {r["rule_selected"] for r in pcs_rows if r["structure"] == "PCS"} == {"1"}


# ───────────────────────────────────────────────────────── row building

def test_build_rows_window_and_next_expiry(payload):
    snap = LQ.parse_nse_chain(payload["option_chain"])
    rows = LQ.build_rows(snap, vix=14.5, today=date(2026, 10, 21), ts_ist="2026-10-21T11:30:05+05:30",
                         fetched_ist="2026-10-21T11:30:09+05:30", in_window=True, forced=False,
                         ret_5d=None, rf=0.065, window_expiry=date(2026, 10, 27))
    win = [r for r in rows if r["expiry_role"] == "window"]
    nxt = [r for r in rows if r["expiry_role"] == "next"]
    assert win and nxt
    assert all(r["expiry"] == "27-Oct-2026" and r["dte"] == 6 and r["dte_in_window"] == 1 for r in win)
    assert all(r["expiry"] == "03-Nov-2026" and r["dte_in_window"] == 0 for r in nxt)
    leg = next(r for r in win if r["structure"] == "IC" and r["strike"] == 23350 and r["option_type"] == "CE")
    assert leg["quote_status"] == "ok"
    assert leg["half_spread"] == 0.6
    assert leg["model_slip_unit"] == pytest.approx(0.45)
    assert leg["half_spread_to_model"] == pytest.approx(0.6 / 0.45, rel=1e-3)
    assert leg["in_window"] == 1 and leg["forced"] == 0


def test_build_rows_one_sided_and_not_listed(payload):
    snap = LQ.parse_nse_chain(payload["option_chain"])
    snap.quotes[("27-Oct-2026", 22550, "PE")]["bid"] = 0      # one-sided quote on a PCS short leg
    rows = LQ.build_rows(snap, vix=14.5, today=date(2026, 10, 21), ts_ist="t", fetched_ist="t",
                         in_window=True, forced=False, ret_5d=None, rf=0.065, window_expiry=date(2026, 10, 27))
    one = [r for r in rows if r["structure"] == "PCS" and r["strike"] == 22550 and r["option_type"] == "PE"
           and r["expiry_role"] == "window"]
    assert one and one[0]["quote_status"] == "one_sided" and one[0]["half_spread"] == ""

    snap.expiries = ["27-Oct-2026"]     # next expiry not listed by the source
    rows = LQ.build_rows(snap, vix=14.5, today=date(2026, 10, 21), ts_ist="t", fetched_ist="t",
                         in_window=True, forced=False, ret_5d=None, rf=0.065, window_expiry=date(2026, 10, 27))
    nxt = [r for r in rows if r["expiry_role"] == "next"]
    assert nxt and {r["quote_status"] for r in nxt} == {"not_listed"}


def test_moneyness_and_vix_buckets():
    assert LQ.moneyness_bucket(1.0) == "lt1pct"
    assert LQ.moneyness_bucket(1.015) == "1to2pct"
    assert LQ.moneyness_bucket(0.97) == "2to4pct"
    assert LQ.moneyness_bucket(1.05) == "gt4pct"
    assert LQ.vix_bucket(12.9) == "vix_lt13" and LQ.vix_bucket(13.0) == "vix_ge13"


# ───────────────────────────────────────────────────────── run, dedupe, gates, failures

def test_fixture_run_appends_then_dedupes(tmp_path, payload):
    log = tmp_path / "sub" / "QUOTE_LOG.csv"          # parent dir must be created
    res = LQ.run_once(from_json=FIXTURE, log_path=log, now=TUE_1130)
    assert res.status == "appended" and res.exit_code == 0
    with log.open() as fh:
        n1 = len(list(csv.reader(fh)))
    assert n1 == len(res.rows) + 1                  # header + rows
    header = log.read_text().splitlines()[0].split(",")
    assert header == LQ.COLUMNS

    again = LQ.run_once(from_json=FIXTURE, log_path=log, now=TUE_1130)
    assert again.status == "duplicate" and again.exit_code == 3
    with log.open() as fh:
        assert len(list(csv.reader(fh))) == n1      # nothing appended, header not repeated


def test_append_never_overwrites_existing_rows(tmp_path):
    log = tmp_path / "QUOTE_LOG.csv"
    log.write_text(",".join(LQ.COLUMNS) + "\n")
    existing = {c: "" for c in LQ.COLUMNS}
    existing.update(timestamp_ist="2026-10-20T11:00:00+05:30", source="nse")
    LQ.append_rows(log, [existing])
    LQ.append_rows(log, [dict(existing, timestamp_ist="2026-10-21T11:00:00+05:30")])
    rows = list(csv.DictReader(log.open()))
    assert [r["timestamp_ist"] for r in rows] == ["2026-10-20T11:00:00+05:30", "2026-10-21T11:00:00+05:30"]
    assert log.read_text().count(",".join(LQ.COLUMNS)) == 1


def test_closed_market_weekend_writes_nothing(tmp_path, payload):
    log = tmp_path / "QUOTE_LOG.csv"
    res = LQ.run_once(from_json=FIXTURE, log_path=log, now=SAT_1130)
    assert res.status == "skipped_closed" and res.exit_code == 3
    assert "weekend" in res.message
    assert not log.exists()


def test_window_edges_are_minute_level(tmp_path, payload):
    # cron fires on the minute; Python starts 1-2 s later, so 13:00:02 and 11:00:03 must count
    assert LQ._in_window(datetime(2026, 10, 21, 13, 0, 2, tzinfo=IST))
    assert LQ._in_window(datetime(2026, 10, 21, 11, 0, 3, tzinfo=IST))
    assert not LQ._in_window(datetime(2026, 10, 21, 13, 1, 0, tzinfo=IST))
    assert not LQ._in_window(datetime(2026, 10, 21, 10, 59, 59, tzinfo=IST))
    late = datetime(2026, 10, 21, 13, 0, 2, tzinfo=IST)
    res = LQ.run_once(from_json=FIXTURE, log_path=tmp_path / "QUOTE_LOG.csv", now=late, write=False)
    assert res.status == "appended" and res.rows[0]["in_window"] == 1


def test_outside_window_writes_nothing_and_force_bypasses(tmp_path):
    log = tmp_path / "QUOTE_LOG.csv"
    res = LQ.run_once(from_json=FIXTURE, log_path=log, now=WED_OUT)
    assert res.status == "skipped_outside_window" and res.exit_code == 3
    assert not log.exists()
    forced = LQ.run_once(from_json=FIXTURE, log_path=log, now=WED_OUT, force=True)
    assert forced.status == "appended"
    assert all(r["forced"] == 1 and r["in_window"] == 0 for r in forced.rows)


def test_source_unavailable_fails_soft(tmp_path, monkeypatch):
    def blocked(*_args):
        raise LQ.SourceUnavailable("https://www.nseindia.com/api/option-chain-v3 returned HTTP 403")
    monkeypatch.setattr(LQ, "fetch_nse", blocked)
    log = tmp_path / "QUOTE_LOG.csv"
    res = LQ.run_once(source="nse", log_path=log, now=TUE_1130)
    assert res.status == "source_unavailable" and res.exit_code == 2
    assert "HTTP 403" in res.message and "groww" in res.message
    assert not log.exists()


def test_missing_vix_is_reported_not_guessed(tmp_path, payload):
    no_vix = dict(payload)
    no_vix["all_indices"] = {"data": [{"indexSymbol": "NIFTY 50", "last": 23000.0}]}
    p = tmp_path / "novix.json"
    p.write_text(json.dumps(no_vix))
    log = tmp_path / "QUOTE_LOG.csv"
    res = LQ.run_once(from_json=p, log_path=log, now=TUE_1130)
    assert res.status == "no_input" and res.exit_code == 2 and "VIX" in res.message
    assert not log.exists()
    ok = LQ.run_once(from_json=p, log_path=log, now=TUE_1130, vix_override=15.0)
    assert ok.status == "appended"


def test_cli_dry_run_and_summary_line(tmp_path, capsys):
    log = tmp_path / "QUOTE_LOG.csv"
    code = LQ.main(["--from-json", str(FIXTURE), "--log", str(log), "--force", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "snapshot 2026-10-21T11:30:05+05:30" in out and "median half_spread/model" in out
    assert not log.exists()


def test_committed_log_is_header_only_and_matches_columns():
    text = COMMITTED_LOG.read_text().splitlines()
    assert len(text) == 1
    assert text[0].split(",") == LQ.COLUMNS


# ───────────────────────────────────────────────────────── summary script

def _snapshot_rows(payload, scale, ts, vix=14.5):
    snap = LQ.parse_nse_chain(payload["option_chain"])
    for q in snap.quotes.values():
        if q.get("bid") and q.get("ask"):
            mid = (q["bid"] + q["ask"]) / 2
            hs = (q["ask"] - q["bid"]) / 2 * scale
            q["bid"], q["ask"] = round(mid - hs, 2), round(mid + hs, 2)
    return LQ.build_rows(snap, vix=vix, today=date(2026, 10, 21), ts_ist=ts, fetched_ist=ts,
                         in_window=True, forced=False, ret_5d=None, rf=0.065, window_expiry=date(2026, 10, 27))


def test_summary_multiplier_matches_known_scale(tmp_path, payload):
    log = tmp_path / "QUOTE_LOG.csv"
    LQ.append_rows(log, _snapshot_rows(payload, 1.0, "2026-10-21T11:30:05+05:30"))
    LQ.append_rows(log, _snapshot_rows(payload, 1.0, "2026-10-21T11:45:05+05:30"))
    df = SQ.load(log)
    s = SQ.summarize(df)
    assert s["snapshots"] == 2 and s["dates"] == 1
    # scale=1.0 reproduces the fixture spreads, so structure-leg multipliers equal the fixture ratios
    assert s["structure_all"]["n"] > 0
    assert s["structure_all"]["median"] > 0
    assert s["by_role"]["neighbour"]["n"] > 0


def test_summary_halving_spread_halves_multiplier(tmp_path, payload):
    full = tmp_path / "full.csv"
    half = tmp_path / "half.csv"
    LQ.append_rows(full, _snapshot_rows(payload, 1.0, "2026-10-21T11:30:05+05:30"))
    LQ.append_rows(half, _snapshot_rows(payload, 0.5, "2026-10-21T11:30:05+05:30"))
    m_full = SQ.summarize(SQ.load(full))["structure_all"]["median"]
    m_half = SQ.summarize(SQ.load(half))["structure_all"]["median"]
    assert m_half == pytest.approx(m_full * 0.5, rel=0.05)


def test_summary_report_reads_break_even_axis(tmp_path, payload):
    log = tmp_path / "QUOTE_LOG.csv"
    LQ.append_rows(log, _snapshot_rows(payload, 0.2, "2026-10-21T11:30:05+05:30"))
    report = SQ.format_report(SQ.load(log), min_snapshots=1)
    assert "break-even axis" in report
    assert "baseline (expiry-day exits)" in report and "0.44x" in report
    assert "BELOW" in report                       # 0.2x of the observed spread is well under 0.44x
    assert "WARNING: only 1 distinct dates" in report


def test_summary_empty_and_missing(tmp_path, capsys):
    empty = tmp_path / "QUOTE_LOG.csv"
    empty.write_text(",".join(LQ.COLUMNS) + "\n")
    assert "empty" in SQ.format_report(SQ.load(empty))
    assert SQ.main(["--log", str(tmp_path / "nope.csv")]) == 2
    assert SQ.main(["--log", str(empty)]) == 0
