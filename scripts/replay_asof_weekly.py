#!/usr/bin/env python3
"""As-of replay of the Phase-1 weekly track (SIMULATED, Black-Scholes estimates).

Carries the paper-trading journal forward day by day from its last stored state, using the
method in paper_trading/analysis/REPLAY_2026-05-15_to_2026-10-16.md:

  * Decision for trading day D (11:30 IST) uses only the previous trading day's data:
    Nifty close, India VIX close, 5-day Nifty return and 5-day VIX change.
  * Strategy: select_weekly_strategy_name (the rule signal-combined prints). Gate:
    WeeklyPutCreditSpread / WeeklyIronCondor.should_enter.
  * Expiry: get_weekly_expiry_in_range(D, 3, 8). Strikes: generate_legs at the previous close.
  * Entry fill on D: Nifty mid-session spot, previous VIX, ConservativeFillModel.
  * Exits, checked on each later session close, in this order: expiry, short-strike breach,
    stop (mark loss >= 100% of credit), PCS profit target (75% captured), IC max hold (4 sessions).
  * 15 lots x 65 units. Rs500 brokerage per trade.

Dry run by default. --write appends the new rows to the three tracker CSVs. Writes refuse to run
unless the tracker's last DAILY_LOG date is the day before --start, so a rerun cannot duplicate rows.

Usage:
  python scripts/replay_asof_weekly.py --validate-journal
  python scripts/replay_asof_weekly.py --start 2026-10-17 --end 2026-11-24
  python scripts/replay_asof_weekly.py --start 2026-10-17 --end 2026-11-24 --write
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from backtester.fills import ConservativeFillModel  # noqa: E402
from backtester.weekly_exit_policy import WEEKLY_IC, WEEKLY_PCS, select_weekly_strategy_name  # noqa: E402
from config import CostModel  # noqa: E402
from data.expiry_calendar import get_holiday, get_weekly_expiry_in_range, is_trading_day  # noqa: E402
from data.market_data import MarketDataFetcher  # noqa: E402
from pricing.black_scholes import OptionType, iv_from_vix, price_option  # noqa: E402
from strategies.base import TradeAction  # noqa: E402
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread  # noqa: E402

LOTS = 15
LOT_SIZE = 65
MULT = LOTS * LOT_SIZE  # 975 units
BROKERAGE = 500.0
RF = 0.065
INITIAL_CAPITAL = 2_500_000.0
WEEKLY_ALLOC = 1_250_000
MONTHLY_ALLOC = 1_250_000
BACKTEST_EXPECTED = 29528
TAG = "[SIMULATED REPLAY (as-of, BS-est)]"
STRATEGY_NAME = {WEEKLY_IC: "iron_condor", WEEKLY_PCS: "put_credit_spread"}
TRACKER = REPO / "paper_trading" / "tracker"
TRADES_CSV = TRACKER / "TRADES.csv"
DAILY_CSV = TRACKER / "DAILY_LOG.csv"
ACCOUNT_CSV = TRACKER / "ACCOUNT_STATE.csv"


def _is_call(code: str) -> bool:
    return code in ("CE", "CALL")


def _theo(spot: float, leg, dte: int, vix: float) -> float:
    ot = OptionType.CALL if _is_call(leg.option_type) else OptionType.PUT
    iv = iv_from_vix(vix, leg.strike, spot, ot)
    return price_option(spot, leg.strike, max(dte, 0), iv, RF, ot).premium


@dataclass
class OpenTrade:
    trade_id: str
    entry_date: date
    expiry: date
    strategy: str
    legs: list
    credit: float            # filled net credit per unit
    cli_credit: float        # BS credit at the previous close (the "CLI-style" credit)
    entry_vix: float
    entry_spot_prev: float
    entry_spot_fill: float
    gap_pct: float
    entry_dte: int
    max_loss_unit: float     # widest wing minus credit
    fill_legs: list = field(default_factory=list)  # (side, option_type, strike, fill price)
    sessions: int = 0


def _short_label(legs) -> str:
    shorts = sorted((l.strike, l.option_type) for l in legs if l.is_short)
    return "/".join(f"{int(k)}{t}" for k, t in shorts)


# Penalty scales calibrated so the replay reproduces the journal's own fills on its 19 trades
# (see --validate-journal). Entry and exit need different scales: a single factor cannot match both.
ENTRY_SLIP_SCALE = 1.125
EXIT_SLIP_SCALE = 1.5


class _ScaledCost:
    """CostModel wrapper that multiplies the per-unit slippage by a constant."""

    def __init__(self, base, scale: float):
        self._base = base
        self._scale = scale

    def slippage_per_unit(self, vix: float = 15.0, moneyness: float = 1.0) -> float:
        return self._scale * self._base.slippage_per_unit(vix=vix, moneyness=moneyness)

    def __getattr__(self, name):
        return getattr(self._base, name)


class Replay:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.fill_entry = ConservativeFillModel(_ScaledCost(CostModel(), ENTRY_SLIP_SCALE))
        self.fill_exit = ConservativeFillModel(_ScaledCost(CostModel(), EXIT_SLIP_SCALE))

    # ---- data -------------------------------------------------------------------
    def row(self, d: date):
        ts = pd.Timestamp(d)
        return self.df.loc[ts] if ts in self.df.index else None

    def prev_row(self, d: date):
        ts = pd.Timestamp(d)
        before = self.df.index[self.df.index < ts]
        if len(before) == 0:
            return None
        return self.df.loc[before[-1]]

    # ---- pricing ----------------------------------------------------------------
    def _side_totals(self, legs, price_of):
        short_total, long_total = 0.0, 0.0
        for leg in legs:
            v = price_of(leg)
            if leg.is_short:
                short_total += v
            else:
                long_total += v
        return short_total - long_total

    def entry_fill(self, legs, spot_fill, vix_prev, dte, gap_pct):
        """Net credit per unit after the mid-session fill model, plus per-leg fill prices."""
        fills = []

        def price(leg):
            theo = _theo(spot_fill, leg, dte, vix_prev)
            f = self.fill_entry.executable_leg_premium(
                leg, theoretical_premium=theo, trade_spot=spot_fill, vix=vix_prev,
                is_entry=True, gap_pct=gap_pct,
            )
            fills.append((leg, f))
            return f

        credit = self._side_totals(legs, price)
        return credit, fills

    def cli_credit(self, legs, spot_prev, vix_prev, dte) -> float:
        return self._side_totals(legs, lambda leg: _theo(spot_prev, leg, dte, vix_prev))

    def close_cost(self, legs, spot, vix, dte, executable: bool, gap_pct: float = 0.0) -> float:
        def price(leg):
            theo = _theo(spot, leg, dte, vix)
            if not executable:
                return theo
            return self.fill_exit.executable_leg_premium(
                leg, theoretical_premium=theo, trade_spot=spot, vix=vix,
                is_entry=False, gap_pct=gap_pct,
            )

        return self._side_totals(legs, price)

    @staticmethod
    def intrinsic_cost(legs, spot: float) -> float:
        def price(leg):
            if _is_call(leg.option_type):
                return max(spot - leg.strike, 0.0)
            return max(leg.strike - spot, 0.0)

        return Replay._side_totals_static(legs, price)

    @staticmethod
    def _side_totals_static(legs, price_of):
        short_total, long_total = 0.0, 0.0
        for leg in legs:
            v = price_of(leg)
            if leg.is_short:
                short_total += v
            else:
                long_total += v
        return short_total - long_total

    # ---- entry decision for one trading day -------------------------------------
    def evaluate_entry(self, d: date, forced_strategy: str | None = None):
        """Return (action, info). action is ENTER, or a skip code."""
        prev = self.prev_row(d)
        cur = self.row(d)
        if prev is None or cur is None:
            return "NO_DATA", {}
        spot_p = float(prev["nifty_close"])
        vix_p = float(prev["vix"])
        ret5 = float(prev["nifty_return_5d"]) if pd.notna(prev["nifty_return_5d"]) else float("nan")
        vchg = float(prev["vix_change_5d"]) if pd.notna(prev["vix_change_5d"]) else float("nan")

        expiry, dte = get_weekly_expiry_in_range(d, 3, 8)
        if expiry is None:
            return "DTE_OUT_OF_RANGE", {}

        strat_name = forced_strategy or select_weekly_strategy_name(vix_p, ret5)
        info_base = {"vix": vix_p, "ret5": ret5, "vchg": vchg, "strategy": strat_name, "expiry": expiry, "dte": dte}
        if strat_name == WEEKLY_IC:
            strat = WeeklyIronCondor(lots=LOTS, lot_size=LOT_SIZE)
        else:
            strat = WeeklyPutCreditSpread(lots=LOTS, lot_size=LOT_SIZE)
        md = {"nifty_return_5d": ret5, "vix_change_5d": vchg}
        if strat.should_enter(spot_p, vix_p, md) != TradeAction.ENTER:
            code = "IC_DECLINED" if strat_name == WEEKLY_IC else "PCS_DECLINED"
            return code, info_base

        legs = strat.generate_legs(spot_p, vix_p, dte)
        spot_fill = float(cur["nifty_mid_session"]) if pd.notna(cur["nifty_mid_session"]) else float(cur["nifty_open"])
        gap_pct = (spot_fill / spot_p - 1.0) * 100.0  # mid-session spot vs previous close (journal convention)
        credit, fills = self.entry_fill(legs, spot_fill, vix_p, dte, gap_pct)
        cli = self.cli_credit(legs, spot_p, vix_p, dte)
        put_w = [abs(a.strike - b.strike) for a in legs if a.is_short and a.option_type == "PE"
                 for b in legs if not b.is_short and b.option_type == "PE"]
        call_w = [abs(a.strike - b.strike) for a in legs if a.is_short and _is_call(a.option_type)
                  for b in legs if not b.is_short and _is_call(b.option_type)]
        width = max(put_w + call_w)
        info = dict(info_base, legs=legs, credit=credit, cli_credit=cli, spot_prev=spot_p,
                    spot_fill=spot_fill, gap_pct=gap_pct, fills=fills, width=width)
        return "ENTER", info

    # ---- exits --------------------------------------------------------------------
    def check_exit(self, t: OpenTrade, d: date):
        """Evaluate one session after entry. Returns (reason, exit_cost_per_unit, spot, vix) or None."""
        cur = self.row(d)
        if cur is None:
            return None
        spot = float(cur["nifty_close"])
        vix = float(cur["vix"])
        prev = self.prev_row(d)
        gap = (spot / float(prev["nifty_close"]) - 1.0) * 100.0  # close-to-close move on the exit session
        dte = (t.expiry - d).days
        if dte <= 0:
            return "expiry", self.close_cost(t.legs, spot, vix, 0, True, gap), spot, vix
        mark = self.close_cost(t.legs, spot, vix, dte, executable=False)
        breached = any(
            (l.option_type == "PE" and spot < l.strike) or (_is_call(l.option_type) and spot > l.strike)
            for l in t.legs if l.is_short
        )
        if breached:
            return "short_strike_breach", self.close_cost(t.legs, spot, vix, dte, True, gap), spot, vix
        if mark - t.credit >= t.credit:
            return "stop_loss_100pct", self.close_cost(t.legs, spot, vix, dte, True, gap), spot, vix
        if t.strategy == WEEKLY_PCS and mark <= 0.25 * t.credit:
            return "profit_target", self.close_cost(t.legs, spot, vix, dte, True, gap), spot, vix
        if t.strategy == WEEKLY_IC and t.sessions >= 4:
            return "max_hold", self.close_cost(t.legs, spot, vix, dte, True, gap), spot, vix
        return None

    def mtm(self, t: OpenTrade, d: date):
        cur = self.row(d)
        spot = float(cur["nifty_close"])
        vix = float(cur["vix"])
        dte = (t.expiry - d).days
        return (t.credit - self.close_cost(t.legs, spot, vix, dte, executable=False)) * MULT, dte


def load_market() -> pd.DataFrame:
    return MarketDataFetcher(date(2009, 1, 1), date(2026, 11, 24)).build_combined_dataset()


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def starting_state() -> dict:
    """Read the journal's last stored state. Nothing is recomputed from earlier history."""
    daily = read_rows(DAILY_CSV)
    last = daily[-1]
    trades = [r for r in read_rows(TRADES_CSV) if r["Trade_ID"].startswith("RP-")]
    equity_peak = max(float(r["Account_Equity_₹"]) for r in daily)
    ids = [int(r["Trade_ID"].split("-")[1]) for r in trades]
    if last["Open_Trades_Count"] != "0":
        raise SystemExit("journal ends with an open position; replay needs that trade's details first")
    return {
        "last_date": date.fromisoformat(last["Date"]),
        "cum": float(last["Cumulative_P&L_₹"]),
        "equity": INITIAL_CAPITAL + float(last["Cumulative_P&L_₹"]),
        "peak": equity_peak,
        "trades": len(trades),
        "wins": sum(1 for r in trades if r["Win_Loss"] == "W"),
        "next_id": max(ids) + 1,
        "open": None,
    }


def run(rep: Replay, start: date, end: date, state: dict):
    """Day loop. Within a trading day: entry decision at 11:30 (position as it stood at 11:30),
    then exits on the 15:15 close. A trade opened today is not exit-checked until the next session."""
    daily, trade_rows, account_rows = [], [], []
    open_t: OpenTrade | None = state["open"]
    d = start
    while d <= end:
        dow = d.strftime("%A")
        head: list[str] = []
        tail: list[str] = []
        eligible = executed = 0
        vix_str, regime = "—", "—"
        if d.weekday() >= 5:
            head.append("Market closed (Weekend) [SIMULATED REPLAY]")
        elif not is_trading_day(d) or (get_holiday(d) or {}).get("segment_closed"):
            name = (get_holiday(d) or {}).get("name", "NSE closed")
            head.append(f"Market closed (holiday: {name}) [SIMULATED REPLAY]")
        else:
            cur = rep.row(d)
            vix_str = f"{float(cur['vix']):.2f}"
            regime = "rule-based"
            opened_today = None
            # 1. 11:30 entry decision, Mon/Tue only, against the position as it stands at 11:30
            if d.weekday() in (0, 1):
                action, info = rep.evaluate_entry(d)
                if open_t is not None:
                    eligible = 1 if action == "ENTER" else 0
                    head.append(f"SKIP OPEN_POSITION: weekly position {open_t.trade_id} still open "
                                f"(exp {open_t.expiry}); engine allows one weekly trade at a time")
                elif action == "ENTER":
                    tid = f"RP-{state['next_id']:03d}"
                    state["next_id"] += 1
                    eligible = executed = 1
                    fill_legs = [(("short" if l.is_short else "long"), l.option_type, l.strike, f)
                                 for l, f in info["fills"]]
                    opened_today = OpenTrade(
                        trade_id=tid, entry_date=d, expiry=info["expiry"], strategy=info["strategy"],
                        legs=info["legs"], credit=info["credit"], cli_credit=info["cli_credit"],
                        entry_vix=info["vix"], entry_spot_prev=info["spot_prev"],
                        entry_spot_fill=info["spot_fill"], gap_pct=info["gap_pct"],
                        entry_dte=info["dte"], max_loss_unit=info["width"] - info["credit"],
                        fill_legs=fill_legs,
                    )
                    head.append(f"TRADE {tid} entered {TAG}")
                    account_rows.append(_account_row(d, f"SIM_TRADE_{tid[3:]}_ENTERED", state))
                else:
                    eligible = 0
                    head.append(_skip_text(action, info))
            else:
                head.append(f"SKIP WEEKDAY_NOT_ENTRY_DAY: Weekly entries Mon/Tue only (today {dow[:3]})")
            # 2. 15:15 exits for trades opened on an earlier session
            if open_t is not None:
                open_t.sessions += 1
                hit = rep.check_exit(open_t, d)
                if hit:
                    reason, exit_cost, spot_x, vix_x = hit
                    gross = (open_t.credit - exit_cost) * MULT
                    net = gross - BROKERAGE
                    state["cum"] += net
                    state["equity"] = INITIAL_CAPITAL + state["cum"]
                    state["peak"] = max(state["peak"], state["equity"])
                    state["trades"] += 1
                    state["wins"] += 1 if net > 0 else 0
                    trade_rows.append(_trade_row(open_t, d, reason, exit_cost, gross, net, spot_x, vix_x))
                    account_rows.append(_account_row(d, f"SIM_TRADE_{open_t.trade_id[3:]}_EXITED", state))
                    tail.append(f"CLOSED {open_t.trade_id} {reason} net {net:+,.0f} {TAG}")
                    open_t = None
                else:
                    mtm, dte = rep.mtm(open_t, d)
                    tail.append(f"{open_t.trade_id} open MTM {mtm:+,.0f} (dte {dte}) {TAG}")
            if opened_today is not None:
                open_t = opened_today
        n = state["trades"]
        equity = state["equity"]
        dd = (state["peak"] - equity) / state["peak"] * 100
        daily.append({
            "Date": d.isoformat(), "Day_of_Week": dow, "Account_Equity_₹": f"{equity:.0f}",
            "Cumulative_P&L_₹": f"{state['cum']:.2f}", "Open_Trades_Count": 1 if open_t else 0,
            "VIX_Close": vix_str, "Market_Regime": regime, "Weekly_Opportunities_Eligible": eligible,
            "Weekly_Trades_Executed": executed, "Monthly_Eligible_Signals": 0,
            "Monthly_Trades_Paused_Count": 0, "Account_DD_%": f"{dd:.2f}",
            "Win_Rate_%_YTD": round(state["wins"] / n * 100) if n else "",
            "Avg_Trade_P&L_₹_YTD": round(state["cum"] / n) if n else "",
            "Notes": " | ".join(head + tail),
        })
        d += timedelta(days=1)
    state["open"] = open_t
    return daily, trade_rows, account_rows


def _skip_text(action: str, info: dict) -> str:
    if action == "DTE_OUT_OF_RANGE":
        return "SKIP DTE_OUT_OF_RANGE: No weekly expiry fits entry window [3–8] DTE"
    if action in ("PCS_DECLINED", "IC_DECLINED"):
        return (f"SKIP {action}: strategy {info['strategy']} declined entry "
                f"(VIX={info['vix']:.2f}, 5d={info['ret5'] * 100:+.2f}%, vix_chg_5d={info['vchg'] * 100:+.2f}%)")
    return f"SKIP {action}"


def _account_row(d: date, event: str, state: dict) -> dict:
    dd = (state["peak"] - state["equity"]) / state["peak"] * 100
    return {
        "Date": d.isoformat(), "Event": event, "Initial_Capital": int(INITIAL_CAPITAL),
        "Weekly_Allocation": WEEKLY_ALLOC, "Monthly_Allocation": MONTHLY_ALLOC,
        "Account_Equity": f"{state['equity']:.0f}", "Cumulative_P&L": f"{state['cum']:.2f}",
        "Account_DD_%": f"{dd:.2f}",
    }


def _trade_row(t: OpenTrade, d: date, reason: str, exit_cost: float, gross: float, net: float,
               spot_x: float, vix_x: float) -> dict:
    legs_txt = []
    for side, ot, k, f in t.fill_legs:
        legs_txt.append(f"{'SELL' if side == 'short' else 'BUY'} {int(k)}{ot}={f:.2f}")
    slip_bp = (t.credit - t.cli_credit) / t.cli_credit * 10_000 if t.cli_credit else 0.0
    notes = (
        f"SIMULATED REPLAY (as-of, BS-est). Strategy {STRATEGY_NAME[t.strategy]} VIX_prev {t.entry_vix:.2f} "
        f"strikes/gates on prev close {t.entry_spot_prev:.2f}; filled at mid-session proxy "
        f"{t.entry_spot_fill:.2f} (gap {t.gap_pct:+.2f}%); CLI-style credit {t.cli_credit:.2f}/unit; "
        f"exit {reason} at close {spot_x:.2f} VIX {vix_x:.2f}; brokerage Rs500 assumed; not a live trade"
    )
    return {
        "Trade_ID": t.trade_id, "Date_Entry": t.entry_date.isoformat(), "Entry_Time_IST": "11:30",
        "Strike_Entry": _short_label(t.legs),
        "Bid_Ask_Entry": "BS-est no quotes; exec legs " + "; ".join(legs_txt),
        "Entry_Price_Fill": f"{t.credit:.2f}", "Lots_Size": LOTS,
        "Capital_Deployed_₹": round(t.max_loss_unit * MULT), "Strategy": STRATEGY_NAME[t.strategy],
        "Signal_VIX": f"{t.entry_vix:.2f}", "Signal_Regime": "rule-based", "ML_Score": "NA",
        "Expiry_DTE": t.entry_dte, "Date_Exit": d.isoformat(), "Exit_Time_IST": "15:15",
        "Exit_Price_Fill": f"{exit_cost:.2f}", "Exit_Reason": reason, "Days_Held": t.sessions,
        "Gross_P&L_₹": f"{gross:.2f}", "Brokerage_₹": int(BROKERAGE),
        "Slippage_vs_Backtest_bp": round(slip_bp), "Net_P&L_₹": f"{net:.2f}",
        "Win_Loss": "W" if net > 0 else "L",
        "P&L_vs_Max_Profit_%": f"{net / (t.credit * MULT) * 100:.2f}",
        "Notes": notes, "Backtest_Expected_P&L_₹": BACKTEST_EXPECTED,
        "Backtest_Deviation_%": f"{(net - BACKTEST_EXPECTED) / BACKTEST_EXPECTED * 100:.2f}",
    }


def validate_against_journal(rep: Replay) -> None:
    """Re-run each journalled trade with its journalled strategy; compare entry, exit and net."""
    print(f"{'trade':7} {'entry':10} {'credit j':>8} {'credit r':>8} {'exit j':>7} {'exit r':>7} "
          f"{'net j':>8} {'net r':>8}  {'reason j':<20} {'reason r':<20} exit_date j/r")
    for r in read_rows(TRADES_CSV):
        tid, entry = r["Trade_ID"], r["Date_Entry"]
        if not tid.startswith("RP-") or entry < "2026-05-01":
            continue
        d = date.fromisoformat(entry)
        forced = WEEKLY_IC if r["Strategy"] == "iron_condor" else WEEKLY_PCS
        action, info = rep.evaluate_entry(d, forced_strategy=forced)
        if action != "ENTER":
            print(f"{tid:7} {entry} not entered by rule: {action}")
            continue
        t = OpenTrade(
            trade_id=tid, entry_date=d, expiry=info["expiry"], strategy=info["strategy"],
            legs=info["legs"], credit=info["credit"], cli_credit=info["cli_credit"],
            entry_vix=info["vix"], entry_spot_prev=info["spot_prev"], entry_spot_fill=info["spot_fill"],
            gap_pct=info["gap_pct"], entry_dte=info["dte"], max_loss_unit=info["width"] - info["credit"],
        )
        hit, exit_d = None, None
        nd = d
        while nd < info["expiry"] + timedelta(days=1):
            nd += timedelta(days=1)
            if rep.row(nd) is None:
                continue
            t.sessions += 1
            hit = rep.check_exit(t, nd)
            if hit:
                exit_d = nd
                break
        reason, exit_cost = (hit[0], hit[1]) if hit else (None, float("nan"))
        net = (t.credit - exit_cost) * MULT - BROKERAGE
        print(f"{tid:7} {entry} {t.credit:8.2f} {float(r['Entry_Price_Fill']):8.2f} "
              f"{float(r['Exit_Price_Fill']):7.2f} {exit_cost:7.2f} {float(r['Net_P&L_₹']):8.0f} {net:8.0f}  "
              f"{r['Exit_Reason']:<20} {str(reason):<20} {r['Date_Exit']}/{exit_d}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, default=date(2026, 10, 17))
    ap.add_argument("--end", type=date.fromisoformat, default=date(2026, 11, 24))
    ap.add_argument("--write", action="store_true", help="append rows to the tracker CSVs")
    ap.add_argument("--validate-journal", action="store_true", help="re-run journalled trades and compare")
    args = ap.parse_args()

    rep = Replay(load_market())
    if args.validate_journal:
        validate_against_journal(rep)
        return 0

    state = starting_state()
    if args.start != state["last_date"] + timedelta(days=1):
        print(f"start must be {state['last_date'] + timedelta(days=1)} (day after the stored state)")
        return 2
    daily, trade_rows, account_rows = run(rep, args.start, args.end, state)
    for r in daily:
        print(f"{r['Date']} {r['Day_of_Week'][:3]} eq={r['Account_Equity_₹']} dd={r['Account_DD_%']} | {r['Notes']}")
    print(f"\ntrades closed: {len(trade_rows)}  final equity: {state['equity']:.0f}  "
          f"cum P&L: {state['cum']:.2f}  DD: {(state['peak'] - state['equity']) / state['peak'] * 100:.2f}%")
    if state["open"]:
        print(f"open at end: {state['open'].trade_id} expiry {state['open'].expiry}")

    if args.write:
        if args.end < state["last_date"]:
            return 2
        _append(DAILY_CSV, daily)
        _append(TRADES_CSV, trade_rows)
        _append(ACCOUNT_CSV, account_rows)
        print(f"wrote {len(daily)} daily, {len(trade_rows)} trade, {len(account_rows)} account rows")
    return 0


def _append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_header(path)))
        for r in rows:
            writer.writerow(r)


def _header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


if __name__ == "__main__":
    raise SystemExit(main())
