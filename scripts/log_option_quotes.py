#!/usr/bin/env python3
"""
Log-only collector of real NIFTY option bid/ask quotes on the legs the weekly strategy would trade.

NO ORDERS. NO TRADES. This script only reads public option-chain data and appends rows to
paper_trading/tracker/QUOTE_LOG.csv. Its purpose is to measure real half-spreads on the exact
structures (IC / PCS legs, ATM straddle, +-2 strike neighbours) and compare them with the
backtest's own per-unit slippage model (backtester.chain_engine.ChainBacktest._slip_unit), so the
slippage assumption can be calibrated. See paper_trading/QUOTE_LOGGING.md.

USAGE
    python scripts/log_option_quotes.py                       # NSE source, 11:00-13:00 IST gate
    python scripts/log_option_quotes.py --source groww        # fallback (no bid/ask; LTP/OI only)
    python scripts/log_option_quotes.py --from-json FIX.json  # offline replay / tests
    python scripts/log_option_quotes.py --force --vix 14.2    # bypass market/window gate (testing)

EXIT CODES
    0  rows appended
    2  source unavailable (blocked, HTTP error, bad JSON) or required input missing (no VIX/spot)
    3  nothing written: market closed, outside the entry window, or duplicate snapshot

No credentials are read or stored. Requests: NSE homepage (cookies), option-chain-indices and
allIndices, with ~1 s between calls. One run = at most 3 HTTP requests. Do not loop it faster
than every few minutes.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from backtester.weekly_exit_policy import WEEKLY_IC, select_weekly_strategy_name  # noqa: E402
from config import BacktestConfig, WeeklyBacktestConfig  # noqa: E402
from data.expiry_calendar import get_next_weekly_expiry, get_weekly_expiry_in_range  # noqa: E402
from data.option_chain import GROWW_OC_URL, HEADERS, NSE_BASE, OPTION_CHAIN_URL, GrowwOptionChainFetcher  # noqa: E402
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread  # noqa: E402
from utils.market_clock import IST, market_day_gate, now_ist  # noqa: E402

DEFAULT_LOG = REPO_ROOT / "paper_trading" / "tracker" / "QUOTE_LOG.csv"
NSE_INDICES_URL = f"{NSE_BASE}/api/allIndices"
STRIKE_STEP = 50
NEIGHBOUR_OFFSETS = (-2, -1, 1, 2)
EXPIRY_FMT = "%d-%b-%Y"

COLUMNS = [
    "timestamp_ist", "fetched_at_ist", "source", "in_window", "forced",
    "spot", "vix", "ret_5d", "expiry", "expiry_role", "dte", "dte_in_window",
    "structure", "rule_selected", "role", "offset_strikes",
    "strike", "option_type", "moneyness", "moneyness_bucket", "vix_bucket",
    "bid", "ask", "bid_qty", "ask_qty", "last", "volume", "oi",
    "mid", "spread", "half_spread", "quote_status",
    "model_slip_unit", "half_spread_to_model", "model_multiplier",
]

STRUCTURE_LEG_ROLES = ("short", "long", "atm")


class SourceUnavailable(RuntimeError):
    """Endpoint blocked, HTTP error, or unparseable response. Reported, never retried in a loop."""


# ─────────────────────────────────────────────────────────────── model slippage

def model_slip_unit(vix: float, strike: float, spot: float) -> float:
    """Per-unit slippage the backtest charges for one leg, with the chain engine's own function.

    ChainBacktest._slip_unit only reads self.cm and self.cfg, so a stub with those two attributes
    gives exactly the engine's value. Multiplier is the ChainConfig default (1.0).
    """
    cfg = ChainConfig()
    stub = SimpleNamespace(cm=cfg.weekly.cost_model, cfg=cfg)
    return float(ChainBacktest._slip_unit(stub, float(vix), float(strike), float(spot)))


# ─────────────────────────────────────────────────────────────── parsing

@dataclass
class Snapshot:
    source: str
    exchange_ts: str                      # IST "DD-Mon-YYYY HH:MM:SS" as published, or ""
    spot: float
    vix: Optional[float]
    expiries: list                        # "DD-Mon-YYYY" strings, as the source lists them
    quotes: dict = field(default_factory=dict)   # (expiry_str, strike:int, "CE"|"PE") -> dict


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse_nse_chain(payload: dict) -> Snapshot:
    """Parse NSE /api/option-chain-indices?symbol=NIFTY.

    Field names (as read by data/option_chain.py NSEOptionChainFetcher._parse_response):
      records.underlyingValue, records.timestamp, records.expiryDates,
      records.data[i].expiryDate, .strikePrice, .CE / .PE with
      bidprice, askPrice, bidQty, askQty, lastPrice, totalTradedVolume, openInterest.
    """
    rec = payload.get("records", {})
    spot = _num(rec.get("underlyingValue")) or 0.0
    quotes: dict = {}
    for row in rec.get("data", []):
        exp = row.get("expiryDate")
        strike = row.get("strikePrice")
        if not exp or strike is None:
            continue
        for opt in ("CE", "PE"):
            leg = row.get(opt)
            if not leg:
                continue
            quotes[(exp, int(strike), opt)] = {
                "bid": _num(leg.get("bidprice")),
                "ask": _num(leg.get("askPrice")),
                "bid_qty": _num(leg.get("bidQty")),
                "ask_qty": _num(leg.get("askQty")),
                "last": _num(leg.get("lastPrice")),
                "volume": _num(leg.get("totalTradedVolume")),
                "oi": _num(leg.get("openInterest")),
            }
    return Snapshot(
        source="nse",
        exchange_ts=str(rec.get("timestamp", "") or ""),
        spot=spot,
        vix=None,
        expiries=list(rec.get("expiryDates", []) or []),
        quotes=quotes,
    )


def parse_nse_indices(payload: dict) -> dict:
    """Return {'vix': float|None, 'nifty': float|None} from NSE /api/allIndices."""
    out = {"vix": None, "nifty": None}
    for idx in payload.get("data", []) or []:
        sym = idx.get("indexSymbol", "")
        if sym == "INDIA VIX":
            out["vix"] = _num(idx.get("last", idx.get("lastPrice")))
        elif sym == "NIFTY 50":
            out["nifty"] = _num(idx.get("last", idx.get("lastPrice")))
    return out


def parse_groww(payload: dict) -> Snapshot:
    """Groww fallback. Reuses the repo's own parser; Groww has no bid/ask, so quotes stay blank."""
    snap = GrowwOptionChainFetcher()._parse_groww(payload, None)
    exp = snap.selected_expiry
    quotes = {}
    for s in list(snap.calls) + list(snap.puts):
        quotes[(exp, int(s.strike), s.option_type)] = {
            "bid": None, "ask": None, "bid_qty": None, "ask_qty": None,
            "last": _num(s.ltp), "volume": _num(s.volume), "oi": _num(s.oi),
        }
    return Snapshot(source="groww", exchange_ts="", spot=float(snap.spot_price or 0.0), vix=None,
                    expiries=[exp] if exp else [], quotes=quotes)


def parse_exchange_ts(raw: str, fallback: datetime) -> str:
    try:
        return datetime.strptime(raw, "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S+05:30")
    except (TypeError, ValueError):
        return fallback.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0530", "+05:30")


# ─────────────────────────────────────────────────────────────── spread math

def spread_fields(bid: Optional[float], ask: Optional[float]) -> dict:
    """mid, spread, half_spread and quote_status from the best bid and ask."""
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        status = "no_quote" if (bid or 0) <= 0 and (ask or 0) <= 0 else "one_sided"
        return {"mid": "", "spread": "", "half_spread": "", "quote_status": status}
    if ask < bid:
        return {"mid": "", "spread": "", "half_spread": "", "quote_status": "crossed"}
    spread = ask - bid
    return {"mid": round((ask + bid) / 2, 4), "spread": round(spread, 4),
            "half_spread": round(spread / 2, 4), "quote_status": "ok"}


def moneyness_bucket(m: float) -> str:
    d = abs(m - 1.0)
    if d < 0.01:
        return "lt1pct"
    if d < 0.02:
        return "1to2pct"
    if d < 0.04:
        return "2to4pct"
    return "gt4pct"


def vix_bucket(vix: float) -> str:
    return "vix_lt13" if vix < 13 else "vix_ge13"


# ─────────────────────────────────────────────────────────────── leg construction

def build_structures(spot: float, vix: float, dte: int, rf: float, ret_5d: Optional[float]) -> list[dict]:
    """Legs the strategy would trade (IC and PCS, from the repo's own generate_legs) plus the ATM
    straddle and +-2 strike neighbours. Premiums returned by generate_legs are discarded; only
    strikes are used (same convention as backtester/chain_engine.py)."""
    wc = WeeklyBacktestConfig()
    ic = WeeklyIronCondor(lots=1, lot_size=wc.lot_size).generate_legs(spot, vix, dte, rf)
    pcs = WeeklyPutCreditSpread(lots=1, lot_size=wc.lot_size).generate_legs(spot, vix, dte, rf)
    rule = select_weekly_strategy_name(vix, ret_5d if ret_5d is not None else float("nan"))
    rule_code = "IC" if rule == WEEKLY_IC else "PCS"

    rows: list[dict] = []
    seen: set = set()

    def add(structure, role, strike, opt, offset=0):
        key = (structure, int(strike), opt)
        if key in seen:
            return
        seen.add(key)
        rows.append({"structure": structure, "role": role, "offset_strikes": offset,
                     "strike": int(strike), "option_type": opt,
                     "rule_selected": "1" if structure == rule_code else "0"})

    for name, legs in (("IC", ic), ("PCS", pcs)):
        for leg in legs:
            add(name, "short" if leg.is_short else "long", leg.strike, leg.option_type)
    atm = int(round(spot / STRIKE_STEP) * STRIKE_STEP)
    add("ATM_STRADDLE", "atm", atm, "CE")
    add("ATM_STRADDLE", "atm", atm, "PE")
    for name in ("IC", "PCS"):
        anchors = [r for r in rows if r["structure"] == name]
        for r in anchors:
            for off in NEIGHBOUR_OFFSETS:
                add(name, "neighbour", r["strike"] + off * STRIKE_STEP, r["option_type"], off)
    return rows


# ─────────────────────────────────────────────────────────────── row building

def build_rows(snap: Snapshot, *, vix: float, today: date, ts_ist: str, fetched_ist: str,
               in_window: bool, forced: bool, ret_5d: Optional[float], rf: float,
               window_expiry: Optional[date]) -> list[dict]:
    """One row per (expiry role, structure, role, strike, option_type) for the window expiry and
    the next expiry. Missing strikes or expiries are recorded with quote_status not_listed."""
    wc = WeeklyBacktestConfig()
    spot = snap.spot
    if window_expiry is None:
        next_exp, _ = get_next_weekly_expiry(today)
        window_dte_ok = False
        exp_targets = [("window_fallback", next_exp)]
    else:
        window_dte_ok = True
        exp_targets = [("window", window_expiry)]
    base = window_expiry if window_expiry is not None else exp_targets[0][1]
    exp_targets.append(("next", get_next_weekly_expiry(base)[0]))

    rows: list[dict] = []
    for role_name, exp_date in exp_targets:
        exp_str = exp_date.strftime(EXPIRY_FMT)
        dte = (exp_date - today).days
        dte_ok = window_dte_ok and role_name == "window" and wc.min_dte_entry <= dte <= wc.max_dte_entry
        listed = exp_str in snap.expiries
        for leg in build_structures(spot, vix, dte, rf, ret_5d):
            key = (exp_str, leg["strike"], leg["option_type"])
            q = snap.quotes.get(key) if listed else None
            m = leg["strike"] / spot if spot > 0 else 1.0
            slip = model_slip_unit(vix, leg["strike"], spot)
            if q is None:
                sp = {"mid": "", "spread": "", "half_spread": "",
                      "quote_status": "not_listed" if not listed else "strike_not_listed"}
                q = {}
            else:
                sp = spread_fields(q.get("bid"), q.get("ask"))
            half = sp["half_spread"]
            rows.append({
                "timestamp_ist": ts_ist, "fetched_at_ist": fetched_ist, "source": snap.source,
                "in_window": int(in_window), "forced": int(forced),
                "spot": round(spot, 2), "vix": round(vix, 2),
                "ret_5d": "" if ret_5d is None else round(ret_5d, 5),
                "expiry": exp_str, "expiry_role": role_name,
                "dte": dte, "dte_in_window": int(dte_ok),
                "structure": leg["structure"], "rule_selected": leg["rule_selected"],
                "role": leg["role"], "offset_strikes": leg["offset_strikes"],
                "strike": leg["strike"], "option_type": leg["option_type"],
                "moneyness": round(m, 5), "moneyness_bucket": moneyness_bucket(m),
                "vix_bucket": vix_bucket(vix),
                "bid": _fmt(q.get("bid")), "ask": _fmt(q.get("ask")),
                "bid_qty": _fmt(q.get("bid_qty")), "ask_qty": _fmt(q.get("ask_qty")),
                "last": _fmt(q.get("last")), "volume": _fmt(q.get("volume")), "oi": _fmt(q.get("oi")),
                "mid": sp["mid"], "spread": sp["spread"], "half_spread": half,
                "quote_status": sp["quote_status"],
                "model_slip_unit": round(slip, 4),
                "half_spread_to_model": round(half / slip, 4) if half != "" and slip > 0 else "",
                "model_multiplier": 1.0,
            })
    return rows


def _fmt(v) -> str:
    if v is None:
        return ""
    return round(v, 4) if isinstance(v, float) else v


# ─────────────────────────────────────────────────────────────── log file

def read_existing_keys(path: Path) -> set:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="") as fh:
        return {(r["timestamp_ist"], r["source"]) for r in csv.DictReader(fh)}


def append_rows(path: Path, rows: list[dict]) -> None:
    """Append only. Creates parent dirs and the header if the file is new or empty."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


# ─────────────────────────────────────────────────────────────── fetch

def _get(session: requests.Session, url: str, timeout: int = 15) -> dict:
    try:
        resp = session.get(url, timeout=timeout)
    except requests.RequestException as e:
        raise SourceUnavailable(f"{url.split('?')[0]} request failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise SourceUnavailable(f"{url.split('?')[0]} returned HTTP {resp.status_code} (blocked or unavailable)")
    try:
        return resp.json()
    except ValueError as e:
        raise SourceUnavailable(f"{url.split('?')[0]} returned non-JSON") from e


def fetch_nse() -> dict:
    """Three polite requests: homepage (cookies), option chain, allIndices (VIX)."""
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        s.get(NSE_BASE, timeout=10)
    except requests.RequestException as e:
        raise SourceUnavailable(f"NSE homepage request failed: {type(e).__name__}") from e
    time.sleep(1.0)
    chain = _get(s, OPTION_CHAIN_URL)
    if not chain.get("records", {}).get("data"):
        raise SourceUnavailable("NSE option chain response has no records (market closed or endpoint changed)")
    time.sleep(1.0)
    indices = _get(s, NSE_INDICES_URL)
    return {"option_chain": chain, "all_indices": indices}


def fetch_groww() -> dict:
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept": "application/json"})
    return {"groww": _get(s, GROWW_OC_URL, timeout=10)}


# ─────────────────────────────────────────────────────────────── run

@dataclass
class RunResult:
    status: str          # appended | skipped_closed | skipped_outside_window | duplicate | source_unavailable | no_input
    message: str
    exit_code: int
    rows: list = field(default_factory=list)
    snapshot_ts: str = ""


def _in_window(now: datetime) -> bool:
    bt = BacktestConfig()
    start = dtime(bt.entry_window_start_hour, bt.entry_window_start_minute)
    end = dtime(bt.entry_window_end_hour, bt.entry_window_end_minute)
    return now.weekday() < 5 and start <= now.time().replace(tzinfo=None) <= end


def _window_expiry(today: date) -> Optional[date]:
    wc = WeeklyBacktestConfig()
    exp, _ = get_weekly_expiry_in_range(today, wc.min_dte_entry, wc.max_dte_entry)
    return exp


def run_once(*, source: str = "nse", from_json: Optional[Path] = None, log_path: Path = DEFAULT_LOG,
             force: bool = False, vix_override: Optional[float] = None, ret_5d: Optional[float] = None,
             now: Optional[datetime] = None, write: bool = True) -> RunResult:
    now = now or now_ist()
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    today = now.date()
    fetched_ist = now.strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0530", "+05:30")

    if not force:
        reason = market_day_gate(today)
        if reason:
            return RunResult("skipped_closed", f"{reason}: no quotes logged ({today}).", 3)
        if not _in_window(now):
            bt = BacktestConfig()
            return RunResult("skipped_outside_window",
                             f"Outside the {bt.entry_window_start_hour:02d}:00-{bt.entry_window_end_hour:02d}:00 "
                             f"IST entry window (now {now:%H:%M}). Nothing logged.", 3)

    in_window = _in_window(now) and market_day_gate(today) is None

    try:
        if from_json is not None:
            raw = json.loads(Path(from_json).read_text())
        elif source == "groww":
            raw = fetch_groww()
        else:
            raw = fetch_nse()
    except SourceUnavailable as e:
        return RunResult("source_unavailable", f"Source '{source}' unavailable: {e}. "
                         "Try --source groww (no bid/ask) or re-run later.", 2)
    except (OSError, ValueError) as e:
        return RunResult("source_unavailable", f"Could not read input: {e}", 2)

    if "groww" in raw:
        snap = parse_groww(raw["groww"])
        indices = {}
    else:
        snap = parse_nse_chain(raw["option_chain"])
        indices = parse_nse_indices(raw.get("all_indices", {}) or {})
    if snap.source == "nse" and not snap.spot and indices.get("nifty"):
        snap.spot = indices["nifty"]
    snap.vix = vix_override if vix_override is not None else indices.get("vix")
    if not snap.spot or snap.spot <= 0:
        return RunResult("no_input", "No spot price in the response; nothing logged.", 2)
    if snap.vix is None or snap.vix <= 0:
        return RunResult("no_input", "No India VIX in the response (pass --vix to override); nothing logged.", 2)
    if not snap.quotes:
        return RunResult("no_input", "Option chain has no strikes; nothing logged.", 2)

    ts_ist = parse_exchange_ts(snap.exchange_ts, now) if snap.exchange_ts else fetched_ist
    if write and (ts_ist, snap.source) in read_existing_keys(log_path):
        return RunResult("duplicate", f"Snapshot {ts_ist} ({snap.source}) already logged; not appended.", 3,
                         snapshot_ts=ts_ist)

    rows = build_rows(snap, vix=snap.vix, today=today, ts_ist=ts_ist, fetched_ist=fetched_ist,
                      in_window=in_window, forced=force, ret_5d=ret_5d, rf=WeeklyBacktestConfig().risk_free_rate,
                      window_expiry=_window_expiry(today))
    if write:
        append_rows(log_path, rows)
    return RunResult("appended", f"Appended {len(rows)} rows to {log_path}" if write else "dry run",
                     0, rows=rows, snapshot_ts=ts_ist)


def one_screen_summary(res: RunResult) -> str:
    lines = [f"[{res.status}] {res.message}"]
    if not res.rows:
        return "\n".join(lines)
    spot = res.rows[0]["spot"]
    vix = res.rows[0]["vix"]
    lines.append(f"snapshot {res.snapshot_ts}  spot {spot}  VIX {vix}  source {res.rows[0]['source']}")
    lines.append(f"{'exp':<12}{'struct':<13}{'role':<10}{'K':>7}{'T':>3}{'bid':>9}{'ask':>9}"
                 f"{'half':>8}{'model':>8}{'ratio':>7}  status")
    for r in res.rows:
        if r["expiry_role"] != "window" or r["role"] == "neighbour":
            continue
        lines.append(f"{r['expiry']:<12}{r['structure']:<13}{r['role']:<10}{r['strike']:>7}{r['option_type']:>3}"
                     f"{str(r['bid']):>9}{str(r['ask']):>9}{str(r['half_spread']):>8}"
                     f"{r['model_slip_unit']:>8}{str(r['half_spread_to_model']):>7}  {r['quote_status']}")
    ratios = [float(r["half_spread_to_model"]) for r in res.rows
              if r["half_spread_to_model"] != "" and r["role"] in STRUCTURE_LEG_ROLES]
    if ratios:
        ratios.sort()
        med = ratios[len(ratios) // 2]
        lines.append(f"structure legs with a quote: {len(ratios)}  median half_spread/model: {med:.2f}x")
    else:
        lines.append("no two-sided quotes on structure legs in this snapshot")
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Log-only NIFTY option quote collector (no orders).")
    p.add_argument("--source", choices=["nse", "groww"], default="nse")
    p.add_argument("--from-json", type=Path, default=None,
                   help='Offline replay: JSON {"option_chain": <NSE payload>, "all_indices": <allIndices>} '
                        'or {"groww": <Groww payload>}.')
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--vix", type=float, default=None, help="Override India VIX (needed for --source groww).")
    p.add_argument("--ret-5d", type=float, default=None,
                   help="5-day Nifty return as a fraction (e.g. -0.012). Only sets the rule_selected label.")
    p.add_argument("--force", action="store_true", help="Bypass the market-day and 11-13 IST window gate.")
    p.add_argument("--dry-run", action="store_true", help="Fetch and summarise, do not append.")
    a = p.parse_args(argv)
    res = run_once(source=a.source, from_json=a.from_json, log_path=a.log, force=a.force,
                   vix_override=a.vix, ret_5d=a.ret_5d, write=not a.dry_run)
    print(one_screen_summary(res))
    return res.exit_code


if __name__ == "__main__":
    sys.exit(main())
