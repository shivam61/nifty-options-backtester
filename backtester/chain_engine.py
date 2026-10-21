"""
Real-price (end-of-day option chain) backtest of the weekly strategy.

What is shared with the live/model system (imported, not copied):
  - strategy-selection rule      backtester.weekly_exit_policy.select_weekly_strategy_name
  - strike/wing targets          strategies.weekly_strategies.WeeklyPutCreditSpread / WeeklyIronCondor
                                 .generate_legs(spot, vix, dte)  (only the strikes are used; the
                                 Black-Scholes premiums it returns are discarded)
  - strategy entry gate          strategy.should_enter(...)
  - exit rules                   backtester.weekly_exit_policy.check_weekly_exit / build_tracker /
                                 update_tracker / trading_sessions_held, and strategy.should_exit
  - VIX gates, streak cooldown   WeeklyBacktestConfig.min_vix_entry / max_vix_entry (engine rules)
  - fee schedule                 config.CostModel (STT, exchange, SEBI, stamp, brokerage, GST)

What is different (real prices only):
  - every fill and every mark is the archive settle price for that listed strike/expiry/day
  - strikes are snapped to the nearest listed strike with a positive settle
  - Black-Scholes is used only for option greeks (portfolio delta for the IC trailing-delta rule),
    never for a price

Timing (one trade per weekly cycle):
  - signal on the listed expiry day E (VIX gate, streak cooldown, strategy gate on E's data)
  - fill on the next market session F at F's settle (underlying on F is the spot)
  - expiry for the trade is the next listed weekly expiry with calendar DTE in [min, max] AT FILL
  - marks and exit decisions on each later session at that day's settle; expiry-day exit uses
    that day's settle (should be intrinsic; the max deviation from intrinsic is recorded)

Costs:
  - fees: CostModel fee components, applied once per round trip on the entry credit (engine
    convention: notional on the entry credit, brokerage 2 orders per leg)
  - slippage: CostModel.slippage_per_unit(vix, moneyness) x slippage_multiplier, per leg per unit,
    charged adversely on entry (inside the fill price) and on exit (inside the exit fill). The
    multiplier is applied to the unscaled CostModel (the engine's close-side convention); the
    engine's entry fill used 0.75x of this, so 1.0x here is harsher than the engine's entry.

Lots: fixed cfg.lots (default 1). Results are reported per lot; no budget-based sizing.
"""

from __future__ import annotations

import copy
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config import WeeklyBacktestConfig
from strategies.base import Leg, Trade, TradeAction, ExitReason
from strategies.weekly_strategies import WeeklyExitArms, WeeklyPutCreditSpread, WeeklyIronCondor
from backtester.weekly_exit_policy import (
    WEEKLY_IC,
    build_tracker,
    check_weekly_exit,
    select_weekly_strategy_name,
    trading_sessions_held,
    update_tracker,
)

TICK = 0.05  # NSE option tick; settle floor and minimum executable price

SKIP_REASONS = (
    "vix_gate", "streak_cooldown", "strategy_gate", "fill_day_missing_archive",
    "no_expiry_in_dte_window", "expiry_not_listed_on_fill", "strike_not_listed",
    "illiquid_leg", "no_price", "no_spot_on_fill", "invalid_structure", "non_positive_credit",
    "vix_floor",
)


@dataclass
class ChainConfig:
    slippage_multiplier: float = 1.0
    weekly: WeeklyBacktestConfig = field(default_factory=WeeklyBacktestConfig)
    lots: int = 1
    initial_equity: float = 500_000.0       # only used by the capital-protection stop
    start: date = date(2019, 2, 11)         # first signal date considered
    end: date = date(2026, 8, 28)           # last signal date considered
    liquidity_min_contracts: int = 0        # illiquid = contracts <= this AND open_int == 0
    # Structural / exit arms (defaults = baseline). See strategies.weekly_strategies.WeeklyExitArms.
    pcs_put_sd: float = 0.9                 # arm A: PCS short-put distance in 1-SD units (baseline 0.9)
    exit_arms: WeeklyExitArms = field(default_factory=WeeklyExitArms)  # arms B and C
    # Capital-protection stop (WeeklyBacktestConfig.capital_protection_pct x equity, total Rs P&L).
    # True (default): equity = initial_equity x lots, i.e. 4% of Rs5L per lot-unit of sizing, so the
    # per-lot threshold is Rs20,000 at every lot count. False: legacy fixed Rs20,000 total (binds
    # only at large lot counts and makes per-lot results depend on lots). At lots=1 both are identical.
    capital_protection_per_lot: bool = True
    # Family F2 entry gate: skip signals with VIX below this value (None = no floor, baseline).
    min_vix_floor: Optional[float] = None


class ChainBacktest:
    """Sequential day-by-day simulation over the market calendar."""

    def __init__(self, archive, market: pd.DataFrame, cfg: ChainConfig):
        """
        archive: data.nse_fo_archive.NseFoArchive
        market:  DataFrame indexed by date with columns nifty_close, vix, nifty_return_5d,
                 vix_change_5d (all taken from the repo's own feature definitions)
        """
        self.arch = archive
        self.cfg = cfg
        self.w = cfg.weekly
        self.cm = cfg.weekly.cost_model
        self.rf = cfg.weekly.risk_free_rate
        self.lot_size = cfg.weekly.lot_size
        m = market.copy()
        m.index = pd.to_datetime(m.index).normalize()
        m = m.sort_index()
        m = m[~m.index.duplicated(keep="last")]
        self.market = m
        self.cal = [t.date() for t in m.index]
        self._cal_set = set(self.cal)
        self._cal_index = pd.DatetimeIndex(m.index)
        self.strategies = {
            "weekly_pcs": WeeklyPutCreditSpread(lots=cfg.lots, lot_size=self.lot_size),
            "weekly_ic": WeeklyIronCondor(lots=cfg.lots, lot_size=self.lot_size),
        }
        self.strategies["weekly_pcs"].put_sd = cfg.pcs_put_sd   # arm A (baseline 0.9 unchanged)
        self.skips: Counter = Counter()
        self.skip_log: list[dict] = []
        self.diag: Counter = Counter()
        self.trades: list[dict] = []
        self.expiry_intrinsic_dev: list[float] = []
        self.index_vs_nifty: list[float] = []
        self.signal_days = 0
        self.signals_while_open = 0

    # ------------------------------------------------------------ helpers
    def _mkt(self, d: date) -> Optional[pd.Series]:
        ts = pd.Timestamp(d)
        if ts not in self.market.index:
            return None
        return self.market.loc[ts]

    def _slip_unit(self, vix: float, strike: float, spot: float) -> float:
        moneyness = strike / spot if spot > 0 else 1.0
        return self.cm.slippage_per_unit(vix, moneyness) * self.cfg.slippage_multiplier

    def _fee_rs(self, credit_per_unit: float, n_legs: int, lots: int) -> float:
        """CostModel fee components, identical to total_cost_per_trade minus the slippage term."""
        qty = lots * self.lot_size
        notional = abs(credit_per_unit) * qty
        stt = notional * self.cm.stt_on_sell_pct / 100
        exchange = notional * self.cm.exchange_txn_pct / 100
        sebi = notional * self.cm.sebi_turnover_pct / 100
        stamp = notional * self.cm.stamp_duty_buy_pct / 100
        brokerage = self.cm.brokerage_per_order * n_legs * 2
        gst = brokerage * self.cm.gst_on_brokerage_pct / 100
        return stt + exchange + sebi + stamp + brokerage + gst

    def _capital_base(self) -> float:
        """Equity used by the capital-protection stop (see ChainConfig.capital_protection_per_lot)."""
        if self.cfg.capital_protection_per_lot:
            return self.cfg.initial_equity * self.cfg.lots
        return self.cfg.initial_equity

    def _skip(self, reason: str, d: date, **detail) -> None:
        self.skips[reason] += 1
        rec = {"date": str(d), "reason": reason}
        rec.update(detail)
        self.skip_log.append(rec)

    def _snap(self, day: date, expiry: date, target: float, opt: str) -> Optional[float]:
        strikes = self.arch.listed_strikes(day, expiry, opt)
        if strikes.size == 0:
            return None
        dist = np.abs(strikes - target)
        best = np.flatnonzero(dist == dist.min())
        return float(strikes[best[0]])  # ties: lower strike (deterministic)

    # ------------------------------------------------------------ entry
    def _try_fill(self, pend: dict, day: date) -> Optional[dict]:
        """Fill a pending signal on `day`. Returns an open-trade state dict or None (skip counted)."""
        if not self.arch.has_day(day):
            self._skip("fill_day_missing_archive", pend["signal_date"], fill_date=str(day))
            return None
        mk = self._mkt(day)
        if mk is None or not np.isfinite(mk["nifty_close"]):
            self._skip("no_spot_on_fill", pend["signal_date"], fill_date=str(day))
            return None
        spot = float(mk["nifty_close"])
        vix = pend["signal_vix"]
        cands = [e for e in self.arch.weekly_expiries(day)
                 if self.w.min_dte_entry <= (e - day).days <= self.w.max_dte_entry]
        if not cands:
            self._skip("no_expiry_in_dte_window", pend["signal_date"], fill_date=str(day))
            return None
        expiry = min(cands)
        dte = (expiry - day).days
        strat_name = pend["strategy"]
        strat = self.strategies[strat_name]
        if not self.arch.chain(day, expiry).shape[0]:
            self._skip("expiry_not_listed_on_fill", pend["signal_date"], fill_date=str(day), expiry=str(expiry))
            return None

        targets = strat.generate_legs(spot, vix, dte, self.rf)
        legs: list[Leg] = []
        entry_settle = []
        entry_fill = []
        pen_entry_rs = 0.0
        for tg in targets:
            opt = "CE" if tg.option_type in ("CE", "CALL") else "PE"
            k = self._snap(day, expiry, tg.strike, opt)
            if k is None:
                self._skip("strike_not_listed", pend["signal_date"], fill_date=str(day), expiry=str(expiry), opt=opt, target=tg.strike)
                return None
            r = self.arch.row(day, expiry, k, opt)
            if r is None:
                self._skip("strike_not_listed", pend["signal_date"], fill_date=str(day), expiry=str(expiry), opt=opt, target=tg.strike)
                return None
            if r["contracts"] <= self.cfg.liquidity_min_contracts and r["open_int"] == 0:
                self._skip("illiquid_leg", pend["signal_date"], fill_date=str(day), expiry=str(expiry), opt=opt, strike=k)
                return None
            if r["px_src"] < 0 or not np.isfinite(r["px"]):
                self._skip("no_price", pend["signal_date"], fill_date=str(day), expiry=str(expiry), opt=opt, strike=k)
                return None
            if r["px_src"] == 1:
                self.diag["close_fallback_entry"] += 1
            s = r["px"]
            if s < TICK:
                self.diag["settle_floored_entry"] += 1
                s = TICK
            slip = self._slip_unit(vix, k, spot)
            if tg.is_short:
                f = max(s - slip, TICK)
            else:
                f = s + slip
            pen_entry_rs += abs(f - s) * self.lot_size * self.cfg.lots
            legs.append(Leg(opt, k, tg.is_short, f, f, self.cfg.lots, self.lot_size))
            entry_settle.append(s)
            entry_fill.append(f)

        if not self._structure_ok(legs):
            self._skip("invalid_structure", pend["signal_date"], fill_date=str(day), expiry=str(expiry))
            return None

        trade = Trade(strategy_name=strat_name, entry_date=day, signal_date=pend["signal_date"], legs=legs,
                      entry_spot=spot, entry_vix=vix, lots=self.cfg.lots, lot_size=self.lot_size)
        # refresh BS greeks at the snapped strikes (used only by the IC trailing-delta rule)
        strat.update_premiums(trade, spot, vix, dte, self.rf)
        for leg, f in zip(trade.legs, entry_fill):
            leg.entry_premium = f
            leg.current_premium = f

        credit = trade.net_credit
        if credit <= 0:
            self._skip("non_positive_credit", pend["signal_date"], fill_date=str(day), expiry=str(expiry))
            return None

        credit_settle = sum((s if lg.is_short else -s) for lg, s in zip(legs, entry_settle))
        return {
            "trade": trade, "strat": strat, "strat_name": strat_name, "expiry": expiry,
            "signal_date": pend["signal_date"], "signal_vix": vix, "fill_date": day,
            "entry_settle": entry_settle, "entry_pen_rs": pen_entry_rs,
            "credit_settle": credit_settle, "tracker": build_tracker(trade),
            "stale_marks": 0, "last_marks": [s for s in entry_settle], "expiry_dev_max": None,
            "last_spot": spot,
            "dte_at_signal": (expiry - pend["signal_date"]).days,
        }

    @staticmethod
    def _structure_ok(legs: list[Leg]) -> bool:
        if len({(l.option_type, l.strike, l.is_short) for l in legs}) != len(legs):
            return False
        for side in ("CE", "PE"):
            sh = [l.strike for l in legs if l.option_type == side and l.is_short]
            lo = [l.strike for l in legs if l.option_type == side and not l.is_short]
            if sh or lo:
                if len(sh) != len(lo) or len(sh) > 1:
                    return False
                s, lg_ = sh[0], lo[0]
                if side == "CE" and not lg_ > s:
                    return False
                if side == "PE" and not lg_ < s:
                    return False
        return True

    # ------------------------------------------------------------ exit
    def _mark_and_check(self, st: dict, d: date) -> Optional[tuple]:
        """Mark open trade on session d. Returns (exit_info) if the trade closes on d, else None."""
        trade, strat, expiry = st["trade"], st["strat"], st["expiry"]
        mk = self._mkt(d)
        spot = float(mk["nifty_close"]) if mk is not None and np.isfinite(mk["nifty_close"]) else st["last_spot"]
        st["last_spot"] = spot
        vix = float(mk["vix"]) if mk is not None and np.isfinite(mk["vix"]) else st.get("last_vix", st["signal_vix"])
        st["last_vix"] = vix
        dte = (expiry - d).days
        marks = []
        for i, leg in enumerate(trade.legs):
            r = self.arch.row(d, expiry, leg.strike, leg.option_type)
            if r is None or r["px_src"] < 0 or not np.isfinite(r["px"]):
                st["stale_marks"] += 1
                s = st["last_marks"][i]
            else:
                s = r["px"]
                if r["px_src"] == 1:
                    self.diag["close_fallback_mark"] += 1
                if r["px_src"] in (2, 3):
                    self.diag["expiry_intrinsic_mark"] += 1
                if s < TICK:
                    self.diag["settle_floored_mark"] += 1
                    s = TICK
            marks.append(s)
        st["last_marks"] = marks
        # greeks (model) refreshed, then prices overwritten with real settle marks
        if dte >= 0:
            strat.update_premiums(trade, spot, vix, max(dte, 0), self.rf)
        for leg, s in zip(trade.legs, marks):
            leg.current_premium = s
        if dte == 0:
            # Expiry-day marks are intrinsic vs the archive index settle. Diagnostics:
            #  (a) archive index settle vs repo Nifty close (should be ~0 where both exist)
            #  (b) raw option close on expiry day vs the intrinsic mark (how far the last
            #      traded close sits from the final settlement)
            idx = self.arch.expiry_index_value(d)
            if np.isfinite(idx):
                self.index_vs_nifty.append(abs(idx - spot))
            dev = 0.0
            for i, leg in enumerate(trade.legs):
                r = self.arch.row(d, expiry, leg.strike, leg.option_type)
                if r is not None and np.isfinite(r["close"]):
                    dev = max(dev, abs(r["close"] - marks[i]))
            st["expiry_dev_max"] = dev
            self.expiry_intrinsic_dev.append(dev)

        holding = trading_sessions_held(self._cal_index, trade.entry_date, d)
        prior = copy.copy(st["tracker"])
        should_exit, reason = check_weekly_exit(
            config=self.w, trade=trade, tracker=prior, spot=spot, vix=vix, dte=dte,
            entry_vix=st["signal_vix"], current_equity=self._capital_base(), holding_days=holding,
            arms=self.cfg.exit_arms,
        )
        if not should_exit:
            action, r2 = strat.should_exit(trade, spot, vix, dte, arms=self.cfg.exit_arms)
            if action == TradeAction.EXIT or dte <= 0:
                should_exit, reason = True, (r2 if r2 else ExitReason.EXPIRY)
        if should_exit:
            return {"date": d, "spot": spot, "vix": vix, "reason": reason, "dte": dte,
                    "marks": marks, "holding_sessions": holding}
        update_tracker(st["tracker"], trade, spot)
        return None

    def _close(self, st: dict, ex: dict) -> dict:
        trade = st["trade"]
        d, spot, vix = ex["date"], ex["spot"], ex["vix"]
        gross_fill = 0.0
        gross_settle = 0.0
        pen_exit_rs = 0.0
        legs_out = []
        for i, (leg, s_exit) in enumerate(zip(trade.legs, ex["marks"])):
            slip = self._slip_unit(vix, leg.strike, spot)
            if leg.is_short:
                f_exit = s_exit + slip
                gross_fill += (leg.entry_premium - f_exit) * leg.quantity
                gross_settle += (st["entry_settle"][i] - s_exit) * leg.quantity
            else:
                f_exit = max(s_exit - slip, TICK)
                gross_fill += (f_exit - leg.entry_premium) * leg.quantity
                gross_settle += (s_exit - st["entry_settle"][i]) * leg.quantity
            pen_exit_rs += abs(f_exit - s_exit) * leg.quantity
            legs_out.append({"type": leg.option_type, "strike": leg.strike, "short": bool(leg.is_short),
                             "entry_settle": st["entry_settle"][i], "entry_fill": leg.entry_premium,
                             "exit_settle": s_exit, "exit_fill": f_exit})
        credit = trade.net_credit
        fee = self._fee_rs(credit, len(trade.legs), self.cfg.lots)
        pnl = gross_fill - fee
        lots = self.cfg.lots
        rec = {
            "track": "weekly", "strategy": st["strat_name"],
            "signal_date": str(st["signal_date"]), "fill_date": str(st["fill_date"]),
            "entry_date": str(st["fill_date"]), "exit_date": str(d), "expiry": str(st["expiry"]),
            "lots": lots, "pnl": pnl, "total_pnl": pnl, "pnl_per_lot": pnl / lots,
            "exit_reason": ex["reason"].value if ex["reason"] else "unknown",
            "entry_spot": trade.entry_spot, "exit_spot": spot,
            "entry_vix": st["signal_vix"], "exit_vix": vix,
            "dte_at_signal": st["dte_at_signal"], "dte_at_fill_raw": (st["expiry"] - st["fill_date"]).days,
            "dte_at_exit": ex["dte"], "holding_days": (d - st["fill_date"]).days,
            "holding_sessions": ex["holding_sessions"],
            "entry_credit_fill": credit, "entry_credit_settle": st["credit_settle"],
            "entry_pen_rs": st["entry_pen_rs"], "close_slip_rs": pen_exit_rs,
            "fee_rs": fee, "gross_settle_rs": gross_settle, "gross_fill_rs": gross_fill,
            "stale_marks": st["stale_marks"], "expiry_intrinsic_dev": st["expiry_dev_max"],
            "legs": legs_out, "slip_multiplier": self.cfg.slippage_multiplier,
        }
        return rec

    # ------------------------------------------------------------ main loop
    def run(self) -> list[dict]:
        pending = None
        open_st = None
        losses = 0
        cooldown_until = None
        for d in self.cal:
            if d < self.cfg.start:
                continue
            if open_st is not None and d > open_st["fill_date"]:
                ex = self._mark_and_check(open_st, d)
                if ex is not None:
                    rec = self._close(open_st, ex)
                    self.trades.append(rec)
                    losses = 0 if rec["pnl"] > 0 else losses + 1
                    open_st = None
            if pending is not None and pending["fill_day"] == d:
                st = self._try_fill(pending, d)
                pending = None
                if st is not None:
                    open_st = st
            if d > self.cfg.end:
                continue
            if not self.arch.has_day(d):
                continue
            if not self.arch.expires_on(d):  # signal only on a listed expiry day
                continue
            self.signal_days += 1
            if open_st is not None:
                self.signals_while_open += 1
                continue
            if pending is not None:
                continue
            mk = self._mkt(d)
            if mk is None or not np.isfinite(mk["vix"]):
                self._skip("vix_gate", d, note="no_market_data")
                continue
            vix = float(mk["vix"])
            if vix < self.w.min_vix_entry or vix > self.w.max_vix_entry:
                self._skip("vix_gate", d, vix=vix)
                continue
            if self.cfg.min_vix_floor is not None and vix < self.cfg.min_vix_floor:
                self._skip("vix_floor", d, vix=vix)
                continue
            if cooldown_until is not None and d < cooldown_until:
                self._skip("streak_cooldown", d)
                continue
            if cooldown_until is not None and d >= cooldown_until:
                cooldown_until = None
                losses = 0
            if losses >= 4:
                cooldown_until = d + timedelta(days=3)
                losses = 0
                self._skip("streak_cooldown", d)
                continue
            ret5 = float(mk["nifty_return_5d"]) if np.isfinite(mk["nifty_return_5d"]) else float("nan")
            vchg = float(mk["vix_change_5d"]) if np.isfinite(mk["vix_change_5d"]) else float("nan")
            name = select_weekly_strategy_name(vix, ret5)
            strat = self.strategies[name]
            spot_sig = float(mk["nifty_close"])
            market_data = {"nifty_return_5d": ret5, "vix_change_5d": vchg}
            if strat.should_enter(spot_sig, vix, market_data) != TradeAction.ENTER:
                self._skip("strategy_gate", d, strategy=name)
                continue
            fill_day = self._next_session(d)
            if fill_day is None:
                self._skip("fill_day_missing_archive", d, note="no_next_session")
                continue
            pending = {"signal_date": d, "fill_day": fill_day, "signal_vix": vix, "strategy": name}
        # force-close anything still open at the end of the window (diagnostic only)
        if open_st is not None:
            self.diag["open_at_end"] += 1
        return self.trades

    def _next_session(self, d: date) -> Optional[date]:
        i = self._cal_index.searchsorted(pd.Timestamp(d), side="right")
        return self.cal[i] if i < len(self.cal) else None
