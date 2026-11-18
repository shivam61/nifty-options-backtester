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
  - opt-in spread model (ChainConfig.spread_model, default None): the base per-leg slippage is the
    calibrated observed half-spread for the leg's moneyness/DTE/VIX bucket (backtester.spread_model),
    falling back to the flat CostModel value when the bucket is not calibrated; the multiplier still
    applies on top. None leaves every output unchanged. See docs/SPREAD_MODEL.md.

Lots: fixed cfg.lots (default 1). Results are reported per lot; no budget-based sizing.

Candidate families (opt-in, ChainConfig.candidate set; default None leaves every output unchanged): see
backtester/candidates.py and docs/preregistration_candidates.md. Fixed sigma_T strikes, fill at F settle.
Defaults: hold to expiry (no stop, no adjustment), one position at a time. Family B debit max loss is set
explicitly (never Trade.max_loss, which is 5x |credit| with no short leg). Opt-in extensions (step 0 of the
edge-search plan, all off by default): CandidateSpec.profit_target_pct / stop_loss_x (exits at EOD settle marks,
paid with exit slippage and fees as on the non-candidate path); ChainConfig.max_concurrent (overlapping
positions); ChainConfig.equity_based_sizing (capital mode: sizing from current equity); ChainConfig.
candidate_entry_filter (callable on the market row, for the forecast-VRP gate); CALL_CREDIT_SPREAD and
IRON_CONDOR structures (defined max loss, W minus net credit).

Capital mode (opt-in, ChainConfig.capital_mode=True; default False leaves every output unchanged):
  - the engine still simulates one lot per trade, so every per-lot field (pnl, pnl_per_lot, fees,
    legs, marks) is identical to the default path and the trade table is the same
  - at fill, the trade is sized: max_loss_per_lot = (widest wing - net credit) x lot_size, and
    margin_per_lot = margin_proxy(...) (default: max_loss_per_lot, a SPAN-like proxy for defined-risk
    spreads, NOT exchange SPAN). sized_lots = floor(min(risk_cap_pct x capital / max_loss_per_lot,
    margin_cap_pct x capital / margin_per_lot, max_lots)); 0 is a 'sizing_zero' skip
  - sized P&L = pnl_per_lot x sized_lots (fees scale with lots too; brokerage is per order, so this
    slightly overstates it); equity = capital_rs + realised + open mark-to-market
  - kill switch: equity at or below peak x (1 - kill_dd_pct) halts new entries ('kill_switch' skip)
    and force-closes an open trade on that session ('capital_kill'). Absorbing: no re-arm.
  - ChainBacktest.capital_summary() reports the portfolio metrics (see that method)
"""

from __future__ import annotations

import copy
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

import numpy as np
import pandas as pd

from config import WeeklyBacktestConfig
from backtester.nse_option_rates import (
    BROKERAGE_PER_ORDER,
    EXCHANGE_TXN_PCT,
    GST_PCT,
    SEBI_PCT,
    STAMP_BUY_PCT,
    STT_EXERCISE_PCT,
    STT_SELL_PCT,
    rate_on,
)
from backtester.spread_model import SpreadModel
from backtester.candidates import (
    CALL_CREDIT_SPREAD, CREDIT_STRUCTURES, IRON_CONDOR, CandidateSpec, PCS, listed_expiries,
    pcs_max_loss_per_unit, ls_debit_per_unit, pick_expiry, target_strikes,
)
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
    "vix_floor", "ml_gate",
)

# Exit reason of a trade closed by ChainConfig.exit_gate (a plain string, not strategies.base.ExitReason).
ML_EXIT_REASON = "ml_exit"
# Exit reason of an open trade force-closed by the capital-mode kill switch.
KILL_EXIT_REASON = "capital_kill"
# Skip reasons that only occur in capital mode (the default mode never produces them).
CAPITAL_SKIP_REASONS = ("sizing_zero", "invalid_max_loss", "kill_switch")
SIGNAL_CADENCES = ("expiry_day", "weekly_fixed_weekday", "daily")
TRADING_DAYS_PER_YEAR = 252


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
    # Expiry settlement. True (default): a leg still open at expiry is cash-settled at intrinsic
    # value vs the archive index settle: no exit order, so no exit slippage and no exit brokerage;
    # long in-the-money legs pay STT on exercise. False (legacy): expiry is an exit order priced at
    # the intrinsic mark with exit slippage and exit fees.
    cash_settlement: bool = True
    # Fee model. False (default): per-order schedule from backtester.nse_option_rates (date-aware
    # STT / exchange rates; GST on brokerage + exchange + SEBI; entry and exit turnover charged
    # separately). True: legacy CostModel round-trip formula on the net credit (GST on brokerage only).
    legacy_costs: bool = False
    # ML gate hooks (None = no-op; output identical to a run without them). Injected by the caller;
    # this module loads no model. entry_gate(date, strategy_name, vix, market_row) -> (allow, score),
    # called on the signal date after the strategy gate; market_row = {nifty_return_5d, vix_change_5d}.
    # exit_gate(ctx) -> (exit_now, score), called on each open session with dte > 0 (ctx keys are
    # built in ChainBacktest._gate_ctx). Scores are recorded on the trade as entry/exit_gate_score.
    entry_gate: Optional[Callable] = None
    exit_gate: Optional[Callable] = None
    # Capital-aware mode (opt-in). False = per-lot results only, identical to the default path.
    # Requires lots == 1. capital_rs is the sizing and equity base (no compounding of sizing).
    # margin_proxy(max_loss_per_lot_rs, trade) -> margin per lot Rs; None = margin equals max loss per
    # lot (SPAN-like proxy for defined-risk spreads; not exchange SPAN).
    capital_mode: bool = False
    capital_rs: float = 500_000.0
    risk_cap_pct: float = 0.10
    margin_cap_pct: float = 0.20
    margin_proxy: Optional[Callable] = None
    max_lots: int = 30
    kill_dd_pct: float = 0.20
    # Data-driven half-spread (opt-in; None = flat CostModel slippage, output byte-identical to the
    # default). When set, each leg's base slippage is the calibrated half-spread for its bucket
    # (backtester.spread_model), falling back to the flat CostModel value per leg when the bucket is
    # not calibrated. slippage_multiplier still applies on top of the base value.
    spread_model: Optional[SpreadModel] = None
    # Candidate family (opt-in; None = the weekly baseline path, output unchanged). When set, the run uses
    # backtester.candidates: fixed strikes from sigma_T, hold to expiry, no stops, one position at a time.
    # Requires cash_settlement=True, legacy_costs=False and no entry/exit gate or VIX floor.
    candidate: Optional[CandidateSpec] = None
    # Candidate-mode options (opt-in; the defaults reproduce the one-position, hold-to-expiry path).
    # max_concurrent: positions open at once. A signal below the cap opens a new position; at 1 it is skipped
    # as 'position_open' exactly as before.
    max_concurrent: int = 1
    # equity_based_sizing (capital mode only): each candidate entry is sized from current equity
    # (capital_rs + realised + open mark-to-market) instead of the fixed capital_rs. The margin of other open
    # positions is not netted off, so with max_concurrent > 1 the margin cap applies per position.
    equity_based_sizing: bool = False
    # candidate_entry_filter(market_row) -> bool, called on a signal day that passed the VIX band and the
    # position cap. The row is the market frame row for the signal date. False skips it ('entry_filter').
    candidate_entry_filter: Optional[Callable] = None
    # signal_cadence (candidate families only): when a signal is considered.
    #   "expiry_day"          (default) signal on each listed weekly expiry day (the pre-registered cadence).
    #   "weekly_fixed_weekday" signal once a week, on the first session at or after weekday signal_weekday
    #                          (0 = Monday .. 4 = Friday) in that ISO week; the fill is the next session.
    #   "daily"               signal on every session.
    # Target expiry is still picked by pick_expiry from the fill day (DTE window). With 7-day signal spacing a
    # position overlaps the next one only when it is held 8 days, so overlap needs weekly_fixed_weekday/daily.
    signal_cadence: str = "expiry_day"
    signal_weekday: int = 0
    # skip_zero_contract_legs (candidate mode, opt-in; round 2 Section 11.1): if ANY entry leg has 0 contracts
    # traded on the fill day, the whole trade is skipped with reason 'zero_contract_leg'. Default False keeps
    # the settle-priced fill of every leg.
    skip_zero_contract_legs: bool = False

    @property
    def fully_legacy(self) -> bool:
        """Both legacy switches on: output schema and values are the pre-settlement-fix ones."""
        return (not self.cash_settlement) and self.legacy_costs


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
        # spread model usage, leg-level: "<entry|exit>:<calibrated|reason>" (empty unless spread_model set)
        self.spread_stats: Counter = Counter()
        self.trades: list[dict] = []
        self.expiry_intrinsic_dev: list[float] = []
        self.index_vs_nifty: list[float] = []
        self.signal_days = 0
        self.signals_while_open = 0
        # capital mode state (inert when cfg.capital_mode is False)
        self._capital_on = bool(cfg.capital_mode)
        if self._capital_on and cfg.lots != 1:
            raise ValueError("capital_mode requires ChainConfig.lots == 1 (sizing is applied per trade)")
        self.kill_active = False
        self.kill_date: Optional[date] = None
        self._realized_rs = 0.0                  # sum of sized P&L of closed trades
        self._peak_equity = float(cfg.capital_rs)
        self.capital_curve: list[tuple] = []     # (date, equity, margin_used) per session in [start, end]
        if cfg.candidate is not None:
            if not cfg.cash_settlement or cfg.legacy_costs:
                raise ValueError("candidate families require cash_settlement=True and legacy_costs=False")
            if cfg.entry_gate is not None or cfg.exit_gate is not None or cfg.min_vix_floor is not None:
                raise ValueError("candidate families take no entry/exit gate and no VIX floor")
        if cfg.max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if cfg.candidate is None and (cfg.max_concurrent != 1 or cfg.candidate_entry_filter is not None):
            raise ValueError("max_concurrent and candidate_entry_filter apply to candidate families only")
        if cfg.equity_based_sizing and not cfg.capital_mode:
            raise ValueError("equity_based_sizing requires capital_mode")
        if cfg.signal_cadence not in SIGNAL_CADENCES:
            raise ValueError(f"signal_cadence must be one of {SIGNAL_CADENCES}")
        if cfg.candidate is None and cfg.signal_cadence != "expiry_day":
            raise ValueError("signal_cadence applies to candidate families only")
        if cfg.candidate is None and cfg.skip_zero_contract_legs:
            raise ValueError("skip_zero_contract_legs applies to candidate families only")
        if not 0 <= cfg.signal_weekday <= 4:
            raise ValueError("signal_weekday must be 0 (Monday) to 4 (Friday)")

    # ------------------------------------------------------------ capital mode helpers
    def _capital_sizing(self, trade: Trade, credit_unit: float, debit_unit: Optional[float] = None,
                        capital: Optional[float] = None, committed_ml_rs: float = 0.0,
                        committed_margin_rs: float = 0.0) -> tuple:
        """(sized_lots, max_loss_per_lot_rs, margin_per_lot_rs, skip_reason or None).

        max loss per unit = widest short/long wing - net credit (the expiry loss of a defined-risk
        PCS or IC); per lot = x lot_size. lots = floor(min(risk_cap_pct x capital / max_loss_per_lot,
        margin_cap_pct x capital / margin_per_lot, max_lots)).

        debit_unit (candidate family B, no short leg): max loss per unit = debit paid, per lot = x lot_size,
        and margin per lot = max loss per lot. The width term and the Trade.max_loss 5x fallback are not used.
        capital: sizing base in Rs. None uses ChainConfig.capital_rs (the fixed base); the candidate path passes
        current equity when ChainConfig.equity_based_sizing is set.
        """
        if debit_unit is not None:
            ml_lot = float(debit_unit) * self.lot_size
            margin_lot = ml_lot
        else:
            widths = []
            for side in ("CE", "PE"):
                sh = [l.strike for l in trade.legs if l.option_type == side and l.is_short]
                lo = [l.strike for l in trade.legs if l.option_type == side and not l.is_short]
                if sh and lo:
                    widths.append(abs(sh[0] - lo[0]))
            ml_lot = (max(widths) - credit_unit) * self.lot_size if widths else float("nan")
            margin_lot = None
        if not ml_lot > 0:
            return 0, ml_lot, 0.0, "invalid_max_loss"
        if margin_lot is None:
            margin_lot = float(self.cfg.margin_proxy(ml_lot, trade)) if self.cfg.margin_proxy else ml_lot
        cap = float(self.cfg.capital_rs) if capital is None else float(capital)
        # committed_*: max loss and margin already held by open positions (netted off the caps; 0 = standalone)
        risk_lots = math.floor((self.cfg.risk_cap_pct * cap - committed_ml_rs) / ml_lot)
        margin_lots = (math.floor((self.cfg.margin_cap_pct * cap - committed_margin_rs) / margin_lot)
                       if margin_lot > 0 else 0)
        lots = max(0, min(risk_lots, margin_lots, self.cfg.max_lots))
        return int(lots), ml_lot, margin_lot, None

    def _update_equity(self, d: date, st: Optional[dict] = None) -> tuple:
        """Equity = capital + realised + open mark-to-market. Updates the peak and the kill switch.

        Returns (equity, margin_used). Breach: equity <= peak x (1 - kill_dd_pct).
        """
        eq = float(self.cfg.capital_rs) + self._realized_rs
        mg = 0.0
        if st is not None:
            eq += st["sized_lots"] * st.get("mtm_per_lot", 0.0)
            mg = st["sized_lots"] * st["margin_per_lot"]
        self._peak_equity = max(self._peak_equity, eq)
        if not self.kill_active and eq <= self._peak_equity * (1.0 - self.cfg.kill_dd_pct):
            self.kill_active = True
            self.kill_date = d
        return eq, mg

    def _record_day(self, d: date, st: Optional[dict]) -> None:
        eq, mg = self._update_equity(d, st)
        self.capital_curve.append((d, eq, mg))

    def _equity_now(self, opens: list) -> float:
        """Capital + realised + open mark-to-market over a list of open-position states (pure, no side effects)."""
        eq = float(self.cfg.capital_rs) + self._realized_rs
        for st in opens:
            eq += st["sized_lots"] * st.get("mtm_per_lot", 0.0)
        return eq

    def _update_equity_open(self, d: date, opens: list) -> tuple:
        """_update_equity for several open positions (candidate path). Returns (equity, margin_used)."""
        eq = self._equity_now(opens)
        mg = sum(st["sized_lots"] * st["margin_per_lot"] for st in opens)
        self._peak_equity = max(self._peak_equity, eq)
        if not self.kill_active and eq <= self._peak_equity * (1.0 - self.cfg.kill_dd_pct):
            self.kill_active = True
            self.kill_date = d
        return eq, mg

    def capital_summary(self, echo: bool = True) -> dict:
        """Portfolio metrics of a capital-mode run. Call after run().

        Equity is the daily session curve (capital + realised + open mark-to-market) from cfg.start to
        cfg.end. MaxDD is peak-to-trough on that curve. CAGR = (final / capital_rs)^(365.25 / calendar
        days) - 1 over the curve span. Sharpe = mean / sample-std of daily session returns of the
        curve x sqrt(252), risk-free rate 0 (daily basis; no per-trade Sharpe). Utilisation = margin used
        (sized lots x margin per lot) / capital_rs, averaged over all curve sessions (idle days count 0).
        """
        cap = float(self.cfg.capital_rs)
        curve = self.capital_curve
        eqs = [e for _, e, _ in curve]
        final = eqs[-1] if eqs else cap
        years = (curve[-1][0] - curve[0][0]).days / 365.25 if len(curve) > 1 else 0.0
        cagr = ((final / cap) ** (1.0 / years) - 1.0) * 100.0 if years > 0 and final > 0 else None
        peak, max_dd = -math.inf, 0.0
        for e in eqs:
            peak = max(peak, e)
            if peak > 0:
                max_dd = max(max_dd, 1.0 - e / peak)
        rets = [b / a - 1.0 for a, b in zip(eqs, eqs[1:]) if a > 0]
        sharpe = None
        if len(rets) > 1:
            mu = sum(rets) / len(rets)
            sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
            sharpe = mu / sd * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None
        utils = [mg / cap for _, _, mg in curve]
        sized = [int(t["sized_lots"]) for t in self.trades if "sized_lots" in t]
        pnl_lot = [float(t["pnl_per_lot"]) for t in self.trades]
        out = {
            "capital_rs": cap, "risk_cap_pct": self.cfg.risk_cap_pct, "margin_cap_pct": self.cfg.margin_cap_pct,
            "max_lots": self.cfg.max_lots, "kill_dd_pct": self.cfg.kill_dd_pct,
            "slippage_multiplier": self.cfg.slippage_multiplier,
            "start": str(self.cfg.start), "end": str(self.cfg.end),
            "trades": len(self.trades),
            "skips": dict(self.skips),
            "sizing_skips": int(self.skips.get("sizing_zero", 0) + self.skips.get("invalid_max_loss", 0)),
            "kill_switch_skips": int(self.skips.get("kill_switch", 0)),
            "kill_switch_active": bool(self.kill_active),
            "kill_switch_date": str(self.kill_date) if self.kill_date else None,
            "capital_kill_exits": sum(1 for t in self.trades if t.get("exit_reason") == KILL_EXIT_REASON),
            "avg_lots": round(sum(sized) / len(sized), 3) if sized else None,
            "min_lots": min(sized) if sized else None,
            "max_lots_used": max(sized) if sized else None,
            "exp_pnl_per_lot": round(sum(pnl_lot) / len(pnl_lot), 2) if pnl_lot else None,
            "final_equity": round(final, 2),
            "total_return_pct": round((final / cap - 1.0) * 100.0, 3),
            "cagr_pct": round(cagr, 3) if cagr is not None else None,
            "max_dd_pct": round(max_dd * 100.0, 3),
            "sharpe_daily_ann": round(sharpe, 3) if sharpe is not None else None,
            "capital_utilisation_avg_pct": round(sum(utils) / len(utils) * 100.0, 3) if utils else 0.0,
            "capital_utilisation_max_pct": round(max(utils) * 100.0, 3) if utils else 0.0,
            "curve_sessions": len(curve), "curve_years": round(years, 4),
        }
        if echo:
            print(f"capital mode: trades={out['trades']} final_equity={out['final_equity']:.0f} "
                  f"CAGR={out['cagr_pct']}% MaxDD={out['max_dd_pct']}% Sharpe(daily)={out['sharpe_daily_ann']}")
            print(f"  avg_lots={out['avg_lots']} utilisation avg={out['capital_utilisation_avg_pct']}% "
                  f"max={out['capital_utilisation_max_pct']}%  sizing_skips={out['sizing_skips']} "
                  f"kill_skips={out['kill_switch_skips']} kill={out['kill_switch_active']} {out['kill_switch_date']}")
            print(f"  skips={out['skips']}")
        return out

    # ------------------------------------------------------------ helpers
    def _mkt(self, d: date) -> Optional[pd.Series]:
        ts = pd.Timestamp(d)
        if ts not in self.market.index:
            return None
        return self.market.loc[ts]

    def _slip_unit(self, vix: float, strike: float, spot: float, dte: Optional[float] = None,
                   price: Optional[float] = None, phase: str = "entry") -> float:
        moneyness = strike / spot if spot > 0 else 1.0
        flat = self.cm.slippage_per_unit(vix, moneyness)
        if self.cfg.spread_model is None:
            return flat * self.cfg.slippage_multiplier
        est = self.cfg.spread_model.half_spread(strike, spot, dte, vix, price, flat=flat)
        self.spread_stats[f"{phase}:{est.reason}"] += 1
        return est.value * self.cfg.slippage_multiplier

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

    def _order_fees(self, day: date, sold_rs: float, bought_rs: float, n_orders: int) -> dict:
        """Charges on one set of orders (entry or exit) dated `day`, date-aware rates.

        sold_rs / bought_rs: premium turnover (price x quantity) of the option legs sold / bought.
        STT is on the sell side only; stamp duty on the buy side only; exchange and SEBI on both.
        GST 18% on brokerage + exchange + SEBI (not on STT or stamp). Sources: nse_option_rates.
        """
        turnover = sold_rs + bought_rs
        stt = sold_rs * rate_on(STT_SELL_PCT, day) / 100
        exchange = turnover * rate_on(EXCHANGE_TXN_PCT, day) / 100
        sebi = turnover * rate_on(SEBI_PCT, day) / 100
        stamp = bought_rs * rate_on(STAMP_BUY_PCT, day) / 100
        brokerage = BROKERAGE_PER_ORDER * n_orders
        gst = (brokerage + exchange + sebi) * GST_PCT / 100
        total = stt + exchange + sebi + stamp + brokerage + gst
        return {"stt": stt, "exchange": exchange, "sebi": sebi, "stamp": stamp,
                "brokerage": brokerage, "gst": gst, "total": total}

    @staticmethod
    def _exercise_stt(day: date, itm_long_intrinsic_rs: float) -> float:
        """STT on exercise: 0.125% of intrinsic value of bought options that finish in the money."""
        return itm_long_intrinsic_rs * rate_on(STT_EXERCISE_PCT, day) / 100

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
        if self._capital_on and self.kill_active:
            self._skip("kill_switch", pend["signal_date"], fill_date=str(day))
            return None
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
            slip = self._slip_unit(vix, k, spot, dte=dte, price=s, phase="entry")
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

        sized_lots, ml_lot, margin_lot = self.cfg.lots, float("nan"), float("nan")
        if self._capital_on:
            sized_lots, ml_lot, margin_lot, why = self._capital_sizing(trade, credit)
            if why is not None:
                self._skip(why, pend["signal_date"], fill_date=str(day), expiry=str(expiry))
                return None
            if sized_lots == 0:
                self._skip("sizing_zero", pend["signal_date"], fill_date=str(day), expiry=str(expiry),
                           max_loss_per_lot_rs=round(ml_lot, 2), margin_per_lot_rs=round(margin_lot, 2))
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
            "entry_gate_score": pend.get("entry_gate_score"),
            "sized_lots": sized_lots, "max_loss_per_lot_rs": ml_lot, "margin_per_lot": margin_lot,
            "mtm_per_lot": 0.0,
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
        raw_marks = []  # unfloored price: cash settlement uses this (intrinsic can be 0)
        for i, leg in enumerate(trade.legs):
            r = self.arch.row(d, expiry, leg.strike, leg.option_type)
            if r is None or r["px_src"] < 0 or not np.isfinite(r["px"]):
                st["stale_marks"] += 1
                s = st["last_marks"][i]
                raw = s
            else:
                s = r["px"]
                raw = s
                if r["px_src"] == 1:
                    self.diag["close_fallback_mark"] += 1
                if r["px_src"] in (2, 3):
                    self.diag["expiry_intrinsic_mark"] += 1
                if s < TICK:
                    self.diag["settle_floored_mark"] += 1
                    s = TICK
            marks.append(s)
            raw_marks.append(raw)
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
        if self._capital_on:
            st["mtm_per_lot"] = sum(leg.pnl for leg in trade.legs)   # lots == 1: per-lot Rs
            self._update_equity(d, st)
            if self.kill_active and not should_exit:
                should_exit, reason = True, KILL_EXIT_REASON
        if self.cfg.exit_gate is not None and dte > 0:
            # ML exit is an OR on top of the rules (rules untouched; gate sees rule_exit).
            ml_exit, ml_score = self.cfg.exit_gate(
                self._gate_ctx(st, d, spot, vix, dte, holding, rule_exit=should_exit))
            st["exit_gate_score"] = float(ml_score)
            if bool(ml_exit) and not should_exit:
                should_exit, reason = True, ML_EXIT_REASON
        if should_exit:
            return {"date": d, "spot": spot, "vix": vix, "reason": reason, "dte": dte,
                    "marks": marks, "raw_marks": raw_marks, "holding_sessions": holding}
        update_tracker(st["tracker"], trade, spot)
        return None

    def _gate_ctx(self, st: dict, d: date, spot: float, vix: float, dte: int, holding: int,
                  rule_exit: bool) -> dict:
        # All values are as of session d's close. P&L uses the entry fills and today's settle
        # marks, before exit slippage and fees. mark_pnl_pct_credit = mark_pnl_rs / entry credit Rs.
        # peak_pnl_rs = running max of mark P&L (tracker, floored at 0 at fill) including today.
        # short_dist_pct = min |spot - short strike| / spot. holding_sessions = trading sessions since
        # fill (rule convention); holding_days = calendar days since fill. rule_exit = rules fired today.
        trade = st["trade"]
        qty = trade.lots * trade.lot_size
        mark_pnl_rs = sum(leg.pnl for leg in trade.legs)
        credit_rs = trade.net_credit * qty
        shorts = [(leg.option_type, leg.strike) for leg in trade.legs if leg.is_short]
        short_dist = min(abs(spot - k) for _, k in shorts) / spot if shorts and spot > 0 else float("nan")
        return {
            "date": d, "trade": trade, "strategy": st["strat_name"], "fill_date": st["fill_date"],
            "dte": dte, "holding_sessions": holding, "holding_days": (d - st["fill_date"]).days,
            "entry_spot": trade.entry_spot, "spot": spot,
            "entry_vix": st["signal_vix"], "vix": vix,
            "entry_credit_rs": credit_rs, "mark_pnl_rs": mark_pnl_rs,
            "mark_pnl_pct_credit": mark_pnl_rs / credit_rs if credit_rs > 0 else float("nan"),
            "peak_pnl_rs": max(st["tracker"].peak_pnl_per_unit, trade.pnl_per_unit) * qty,
            "short_strikes": shorts, "short_dist_pct": short_dist,
            "rule_exit": bool(rule_exit),
        }

    def _close(self, st: dict, ex: dict) -> dict:
        trade = st["trade"]
        d, spot, vix = ex["date"], ex["spot"], ex["vix"]
        gross_fill = 0.0
        gross_settle = 0.0
        pen_exit_rs = 0.0
        legs_out = []
        # A leg open on its expiry day (dte == 0) is cash-settled, not traded out (new model).
        cash = bool(self.cfg.cash_settlement and ex["dte"] == 0)
        exit_marks = ex["raw_marks"] if cash else ex["marks"]
        n_legs = len(trade.legs)
        entry_sold_rs = entry_bought_rs = 0.0   # entry premium turnover, short / long legs
        exit_sold_rs = exit_bought_rs = 0.0     # exit-order turnover (not used when cash-settled)
        itm_long_intrinsic_rs = 0.0             # long legs that finish in the money (exercised)
        for i, (leg, s_exit) in enumerate(zip(trade.legs, exit_marks)):
            q = leg.quantity
            if leg.is_short:
                entry_sold_rs += leg.entry_premium * q
            else:
                entry_bought_rs += leg.entry_premium * q
            if cash:
                f_exit = s_exit  # settlement value, no order: no slippage
                if not leg.is_short and s_exit > 0:
                    itm_long_intrinsic_rs += s_exit * q
            else:
                slip = self._slip_unit(vix, leg.strike, spot, dte=ex["dte"], price=s_exit, phase="exit")
                if leg.is_short:
                    f_exit = s_exit + slip
                    exit_bought_rs += f_exit * q
                else:
                    f_exit = max(s_exit - slip, TICK)
                    exit_sold_rs += f_exit * q
            if leg.is_short:
                gross_fill += (leg.entry_premium - f_exit) * q
                gross_settle += (st["entry_settle"][i] - s_exit) * q
            else:
                gross_fill += (f_exit - leg.entry_premium) * q
                gross_settle += (s_exit - st["entry_settle"][i]) * q
            pen_exit_rs += abs(f_exit - s_exit) * q
            legs_out.append({"type": leg.option_type, "strike": leg.strike, "short": bool(leg.is_short),
                             "entry_settle": st["entry_settle"][i], "entry_fill": leg.entry_premium,
                             "exit_settle": s_exit, "exit_fill": f_exit})
        credit = trade.net_credit
        extra: dict = {}
        if self.cfg.legacy_costs:
            fee = self._fee_rs(credit, n_legs, self.cfg.lots)
            ent_fee = ex_fee = ex_stt = None
        else:
            ent = self._order_fees(st["fill_date"], entry_sold_rs, entry_bought_rs, n_legs)
            if cash:
                ex_stt = self._exercise_stt(d, itm_long_intrinsic_rs)
                ex_fee = ex_stt  # no exit order: no exit brokerage, exchange, SEBI, GST or stamp
            else:
                ex_fee = self._order_fees(d, exit_sold_rs, exit_bought_rs, n_legs)["total"]
                ex_stt = None
            ent_fee = ent["total"]
            fee = ent_fee + ex_fee
            extra = {"entry_fee_rs": ent_fee, "exit_fee_rs": ex_fee,
                     "exercise_stt_rs": ex_stt if cash else 0.0}
        if not self.cfg.fully_legacy:
            extra["settled_at_expiry"] = cash
        pnl = gross_fill - fee
        lots = self.cfg.lots
        rec = {
            "track": "weekly", "strategy": st["strat_name"],
            "signal_date": str(st["signal_date"]), "fill_date": str(st["fill_date"]),
            "entry_date": str(st["fill_date"]), "exit_date": str(d), "expiry": str(st["expiry"]),
            "lots": lots, "pnl": pnl, "total_pnl": pnl, "pnl_per_lot": pnl / lots,
            "exit_reason": (ex["reason"] if isinstance(ex["reason"], str) else
                            ex["reason"].value if ex["reason"] else "unknown"),
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
        rec.update(extra)  # new-model fields; absent in fully-legacy mode (schema unchanged)
        if self.cfg.entry_gate is not None:
            rec["entry_gate_score"] = st["entry_gate_score"]
        if self.cfg.exit_gate is not None:
            rec["exit_gate_score"] = st.get("exit_gate_score")  # last evaluated score (None if never)
        if self._capital_on:  # sizing fields; pnl / pnl_per_lot above are the unchanged per-lot values
            n = int(st["sized_lots"])
            rec.update({"sized_lots": n, "pnl_sized_rs": pnl * n,
                        "max_loss_per_lot_rs": st["max_loss_per_lot_rs"],
                        "margin_per_lot_rs": st["margin_per_lot"],
                        "margin_used_rs": st["margin_per_lot"] * n})
        return rec

    # ------------------------------------------------------------ candidate families (opt-in)
    def _candidate_fill(self, pend: dict, day: date, equity_cap: Optional[float] = None,
                        open_states: Optional[list] = None) -> Optional[dict]:
        """Open a candidate trade on fill day `day` at its EOD settle. Returns the open-trade state or None.

        equity_cap: sizing base for capital mode (current equity under ChainConfig.equity_based_sizing);
        None sizes from ChainConfig.capital_rs.
        open_states: positions already open on `day`. Their max loss and margin are netted off the risk and
        margin caps (capital mode), so the caps bind on total committed risk, not per position. Empty for
        max_concurrent=1, where it changes nothing.
        """
        spec = self.cfg.candidate
        sig = pend["signal_date"]
        if self._capital_on and self.kill_active:
            self._skip("kill_switch", sig, fill_date=str(day))
            return None
        if not self.arch.has_day(day):
            self._skip("missing_data", sig, fill_date=str(day))
            return None
        mk = self._mkt(day)
        if mk is None or not np.isfinite(mk["nifty_close"]):
            self._skip("missing_data", sig, fill_date=str(day))
            return None
        spot = float(mk["nifty_close"])
        vix = pend["signal_vix"]
        expiry, dte = pick_expiry(spec, listed_expiries(self.arch, day), day)
        if expiry is None:
            self._skip("no_expiry_in_window", sig, fill_date=str(day), cadence=spec.cadence)
            return None
        if expiry > self.cfg.end:
            self._skip("expiry_after_end", sig, fill_date=str(day), expiry=str(expiry))
            return None
        if expiry not in self._cal_set or not self.arch.expires_on(expiry):
            self._skip("missing_data", sig, fill_date=str(day), expiry=str(expiry))
            return None

        tg = target_strikes(spec, spot, vix, dte)
        if spec.structure == PCS:
            ks = self._snap(day, expiry, tg["PE"], "PE")
            if ks is None:
                self._skip("no_listed_strike", sig, fill_date=str(day), expiry=str(expiry), opt="PE")
                return None
            plan = [("PE", ks, True), ("PE", ks - spec.width, False)]
        elif spec.structure == CALL_CREDIT_SPREAD:
            kc = self._snap(day, expiry, tg["CE"], "CE")
            if kc is None:
                self._skip("no_listed_strike", sig, fill_date=str(day), expiry=str(expiry), opt="CE")
                return None
            plan = [("CE", kc, True), ("CE", kc + spec.width, False)]
        elif spec.structure == IRON_CONDOR:
            kc = self._snap(day, expiry, tg["CE"], "CE")
            kp = self._snap(day, expiry, tg["PE"], "PE")
            if kc is None or kp is None:
                self._skip("no_listed_strike", sig, fill_date=str(day), expiry=str(expiry))
                return None
            plan = [("PE", kp, True), ("PE", kp - spec.width, False),
                    ("CE", kc, True), ("CE", kc + spec.width, False)]
        else:
            kc = self._snap(day, expiry, tg["CE"], "CE")
            kp = self._snap(day, expiry, tg["PE"], "PE")
            if kc is None or kp is None:
                self._skip("no_listed_strike", sig, fill_date=str(day), expiry=str(expiry))
                return None
            plan = [("CE", kc, False), ("PE", kp, False)]

        if self.cfg.skip_zero_contract_legs:
            entry_rows = [self.arch.row(day, expiry, k, opt) for opt, k, _ in plan]
            if any(r is not None and r["contracts"] == 0 for r in entry_rows):
                self._skip("zero_contract_leg", sig, fill_date=str(day), expiry=str(expiry))
                return None

        qty = self.cfg.lots * self.lot_size
        legs: list[Leg] = []
        settles: list[float] = []
        fills: list[float] = []
        pen_entry_rs = 0.0
        for opt, k, short in plan:
            r = self.arch.row(day, expiry, k, opt)
            if r is None:
                self._skip("no_listed_strike", sig, fill_date=str(day), expiry=str(expiry), opt=opt, strike=k)
                return None
            if r["px_src"] < 0 or not np.isfinite(r["px"]):
                self._skip("no_price", sig, fill_date=str(day), expiry=str(expiry), opt=opt, strike=k)
                return None
            if r["px_src"] == 1:
                self.diag["close_fallback_entry"] += 1
            s = r["px"]
            if s < TICK:
                self.diag["settle_floored_entry"] += 1
                s = TICK
            slip = self._slip_unit(vix, k, spot, dte=dte, price=s, phase="entry")
            f = max(s - slip, TICK) if short else s + slip
            pen_entry_rs += abs(f - s) * qty
            legs.append(Leg(opt, k, short, f, f, self.cfg.lots, self.lot_size))
            settles.append(s)
            fills.append(f)

        if spec.structure in CREDIT_STRUCTURES:
            if not self._structure_ok(legs):
                self._skip("invalid_structure", sig, fill_date=str(day), expiry=str(expiry))
                return None
            # net credit per unit: short legs received, long legs paid (PCS: fills[0] - fills[1], unchanged)
            credit_fill_unit = sum(f if lg.is_short else -f for lg, f in zip(legs, fills))
            credit_settle_unit = sum(s if lg.is_short else -s for lg, s in zip(legs, settles))
            if credit_fill_unit <= 0 or credit_settle_unit <= 0:
                self._skip("non_positive_credit", sig, fill_date=str(day), expiry=str(expiry))
                return None
            # W - net credit: equal wings, so the expiry loss is at most one wing less the credit (PCS, CCS, IC)
            ml_unit = pcs_max_loss_per_unit(spec.width, credit_settle_unit)
            if not ml_unit > 0:
                self._skip("invalid_max_loss", sig, fill_date=str(day), expiry=str(expiry))
                return None
            entry_sold_rs = sum(f for lg, f in zip(legs, fills) if lg.is_short) * qty
            entry_bought_rs = sum(f for lg, f in zip(legs, fills) if not lg.is_short) * qty
            debit_unit = None
            credit_rs = credit_fill_unit * qty
            max_loss_rs = ml_unit * qty
        else:
            if plan[1][1] >= plan[0][1]:  # plan = [CE, PE]: PE strike must sit below the CE strike
                self._skip("invalid_structure", sig, fill_date=str(day), expiry=str(expiry))
                return None
            entry_sold_rs, entry_bought_rs = 0.0, sum(fills) * qty
            entry_fee_rs = self._order_fees(day, entry_sold_rs, entry_bought_rs, len(legs))["total"]
            debit_unit = ls_debit_per_unit(sum(fills), entry_fee_rs, qty)
            if not debit_unit > 0:
                self._skip("invalid_max_loss", sig, fill_date=str(day), expiry=str(expiry))
                return None
            ml_unit = debit_unit
            credit_settle_unit = -sum(settles)
            credit_rs = -sum(fills) * qty
            max_loss_rs = debit_unit * qty
        trade = Trade(strategy_name=spec.cell_id, entry_date=day, signal_date=sig, legs=legs,
                      entry_spot=spot, entry_vix=vix, lots=self.cfg.lots, lot_size=self.lot_size)

        sized_lots, ml_lot, margin_lot = self.cfg.lots, float("nan"), float("nan")
        if self._capital_on:
            # reuse the stored sizing of open positions: sized lots x per-lot max loss / margin
            com_ml = sum(st["sized_lots"] * st["max_loss_per_lot_rs"] for st in (open_states or []))
            com_mg = sum(st["sized_lots"] * st["margin_per_lot"] for st in (open_states or []))
            if spec.structure in CREDIT_STRUCTURES:
                sized_lots, ml_lot, margin_lot, why = self._capital_sizing(
                    trade, credit_settle_unit, capital=equity_cap,
                    committed_ml_rs=com_ml, committed_margin_rs=com_mg)
            else:
                sized_lots, ml_lot, margin_lot, why = self._capital_sizing(
                    trade, 0.0, debit_unit=debit_unit, capital=equity_cap,
                    committed_ml_rs=com_ml, committed_margin_rs=com_mg)
            if why is not None:
                self._skip(why, sig, fill_date=str(day), expiry=str(expiry))
                return None
            if sized_lots == 0:
                self._skip("sizing_zero", sig, fill_date=str(day), expiry=str(expiry),
                           max_loss_per_lot_rs=round(ml_lot, 2), margin_per_lot_rs=round(margin_lot, 2))
                return None
        credit_settle = sum((s if lg.is_short else -s) for lg, s in zip(legs, settles))
        return {
            "trade": trade, "strat": None, "strat_name": spec.cell_id, "expiry": expiry,
            "signal_date": sig, "signal_vix": vix, "fill_date": day,
            "entry_settle": settles, "entry_pen_rs": pen_entry_rs,
            "credit_settle": credit_settle, "tracker": None,
            "stale_marks": 0, "last_marks": list(settles), "expiry_dev_max": None,
            "last_spot": spot, "dte_at_signal": (expiry - sig).days,
            "sized_lots": sized_lots, "max_loss_per_lot_rs": ml_lot, "margin_per_lot": margin_lot,
            "mtm_per_lot": 0.0,
            "cand": {"credit_rs": credit_rs, "max_loss_rs": max_loss_rs, "ml_unit": ml_unit,
                     "dte": dte, "targets": tg, "debit": debit_unit is not None,
                     "cadence": spec.cadence, "family": spec.family, "k": spec.k, "width": spec.width},
        }

    def _candidate_mark(self, st: dict, d: date) -> None:
        """Mark an open candidate trade on session d at its EOD settle marks. Sets the mark state that
        _candidate_exit reads. The caller updates equity (capital mode) and decides the exit."""
        trade, expiry = st["trade"], st["expiry"]
        mk = self._mkt(d)
        spot = float(mk["nifty_close"]) if mk is not None and np.isfinite(mk["nifty_close"]) else st["last_spot"]
        st["last_spot"] = spot
        vix = float(mk["vix"]) if mk is not None and np.isfinite(mk["vix"]) else st["signal_vix"]
        dte = (expiry - d).days
        marks, raw_marks = [], []
        for i, leg in enumerate(trade.legs):
            r = self.arch.row(d, expiry, leg.strike, leg.option_type)
            if r is None or r["px_src"] < 0 or not np.isfinite(r["px"]):
                st["stale_marks"] += 1
                s = st["last_marks"][i]
                raw = s
            else:
                s = r["px"]
                raw = s
                if r["px_src"] == 1:
                    self.diag["close_fallback_mark"] += 1
                if r["px_src"] in (2, 3):
                    self.diag["expiry_intrinsic_mark"] += 1
                if s < TICK:
                    self.diag["settle_floored_mark"] += 1
                    s = TICK
            marks.append(s)
            raw_marks.append(raw)
        st["last_marks"] = marks
        for leg, s in zip(trade.legs, marks):
            leg.current_premium = s
        if dte <= 0:
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
        if self._capital_on:
            st["mtm_per_lot"] = sum(leg.pnl for leg in trade.legs)
        st["mark"] = {"date": d, "spot": spot, "vix": vix, "dte": dte, "marks": marks, "raw_marks": raw_marks,
                      "holding_sessions": trading_sessions_held(self._cal_index, st["fill_date"], d)}

    def _candidate_exit(self, st: dict, d: date) -> Optional[dict]:
        """Exit decision on session d for an open candidate trade (after _candidate_mark and the equity update).

        Order: expiry (cash-settled at the archive index), kill-switch force close (capital mode), profit
        target, stop loss. Target and stop compare the mark-to-market P&L on EOD settle marks with the entry
        credit on the fill basis. An exit before expiry is priced by _close (exit slippage and fees).
        """
        m = st["mark"]
        if m["dte"] <= 0:
            reason = ExitReason.EXPIRY
        elif self._capital_on and self.kill_active:
            reason = KILL_EXIT_REASON
        else:
            reason = self._candidate_rule_exit(st)
            if reason is None:
                return None
        return {"date": d, "spot": m["spot"], "vix": m["vix"], "reason": reason, "dte": m["dte"],
                "marks": m["marks"], "raw_marks": m["raw_marks"], "holding_sessions": m["holding_sessions"]}

    def _candidate_rule_exit(self, st: dict) -> Optional[str]:
        """'profit_target' or 'stop_loss' when the spec's exit rule fires on the current marks, else None."""
        spec = self.cfg.candidate
        if spec.profit_target_pct is None and spec.stop_loss_x is None:
            return None
        credit_rs = st["cand"]["credit_rs"]
        if not credit_rs > 0:
            return None
        pnl_rs = sum(leg.pnl for leg in st["trade"].legs)
        if spec.profit_target_pct is not None and pnl_rs >= spec.profit_target_pct / 100.0 * credit_rs:
            return "profit_target"
        if spec.stop_loss_x is not None and pnl_rs <= -spec.stop_loss_x * credit_rs:
            return "stop_loss"
        return None

    def _candidate_record(self, st: dict, rec: dict) -> dict:
        """Add the candidate fields (max loss, credit, cell identity) to a closed trade record."""
        c = st["cand"]
        rec.update({
            "candidate": st["strat_name"], "family": c["family"], "cadence": c["cadence"],
            "k": c["k"], "width": c["width"], "dte_at_fill": c["dte"],
            "credit_rs": c["credit_rs"], "max_loss_rs": c["max_loss_rs"],
            "max_loss_per_unit": c["ml_unit"], "debit_structure": c["debit"],
            "entry_vix": st["signal_vix"], "pricing_source": "chain",
        })
        return rec

    # ------------------------------------------------------------ main loop
    def _run_candidate(self) -> list[dict]:
        """Candidate family loop: signal on S (listed expiry day), fill F at settle, then exits and expiry.

        Per session: mark the positions opened before today, update equity (capital mode; may trip the kill
        switch), decide and close exits, fill the pending signal, record equity, then take today's signal.
        Defaults (max_concurrent=1, no exit rules, no filter) reproduce the one-position hold-to-expiry path.
        """
        cfg, spec = self.cfg, self.cfg.candidate
        pending = None
        opens: list[dict] = []
        signalled_weeks: set = set()   # ISO weeks that already took their signal (weekly_fixed_weekday)
        for d in self.cal:
            if d < cfg.start:
                continue
            marked = [st for st in opens if d > st["fill_date"]]
            for st in marked:
                self._candidate_mark(st, d)
            if self._capital_on and marked:
                self._update_equity_open(d, opens)
            closed = set()
            for st in marked:
                ex = self._candidate_exit(st, d)
                if ex is not None:
                    rec = self._candidate_record(st, self._close(st, ex))
                    self.trades.append(rec)
                    if self._capital_on:
                        self._realized_rs += rec["pnl_sized_rs"]
                    closed.add(id(st))
            if closed:
                opens = [st for st in opens if id(st) not in closed]
                if self._capital_on:
                    self._update_equity_open(d, opens)
            if pending is not None and pending["fill_day"] == d:
                eq_cap = self._equity_now(opens) if cfg.equity_based_sizing else None
                st = self._candidate_fill(pending, d, equity_cap=eq_cap, open_states=opens)
                pending = None
                if st is not None:
                    opens.append(st)
            if self._capital_on and d <= cfg.end:
                eq, mg = self._update_equity_open(d, opens)
                self.capital_curve.append((d, eq, mg))
            if d > cfg.end:
                continue
            if not self.arch.has_day(d):
                continue
            if cfg.signal_cadence == "expiry_day":
                if not self.arch.expires_on(d):  # signal only on a listed expiry day
                    continue
            elif cfg.signal_cadence == "weekly_fixed_weekday":
                # first session at or after signal_weekday in each ISO week (holidays move it to the next session)
                wk = d.isocalendar()[:2]
                if d.weekday() < cfg.signal_weekday or wk in signalled_weeks:
                    continue
                signalled_weeks.add(wk)
            self.signal_days += 1
            if self._capital_on and self.kill_active:
                self._skip("kill_switch", d)
                continue
            mk = self._mkt(d)
            if mk is None or not np.isfinite(mk["vix"]):
                self._skip("missing_data", d)
                continue
            vix = float(mk["vix"])
            if not spec.vix_in_band(vix):
                self._skip("vix_out_of_band", d, vix=vix)
                continue
            if len(opens) + (1 if pending is not None else 0) >= cfg.max_concurrent:
                self.signals_while_open += 1
                self._skip("position_open", d)
                continue
            if cfg.candidate_entry_filter is not None and not bool(cfg.candidate_entry_filter(mk)):
                self._skip("entry_filter", d)
                continue
            fill_day = self._next_session(d)
            if fill_day is None:
                self._skip("missing_data", d, note="no_next_session")
                continue
            pending = {"signal_date": d, "fill_day": fill_day, "signal_vix": vix,
                       "strategy": spec.cell_id}
        if opens:
            self.diag["open_at_end"] += 1
        return self.trades

    # ------------------------------------------------------------ main loop
    def run(self) -> list[dict]:
        if self.cfg.candidate is not None:
            return self._run_candidate()
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
                    if self._capital_on:
                        self._realized_rs += rec["pnl_sized_rs"]
                        self._update_equity(d)
                    losses = 0 if rec["pnl"] > 0 else losses + 1
                    open_st = None
            if pending is not None and pending["fill_day"] == d:
                st = self._try_fill(pending, d)
                pending = None
                if st is not None:
                    open_st = st
            if self._capital_on and d <= self.cfg.end:
                self._record_day(d, open_st)
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
            if self.kill_active:  # capital mode only: kill switch halts new entries
                self._skip("kill_switch", d)
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
            gate_score = gate_allow = None
            if self.cfg.entry_gate is not None:
                gate_allow, gate_score = self.cfg.entry_gate(d, name, vix, market_data)
                gate_allow, gate_score = bool(gate_allow), float(gate_score)
                if not gate_allow:
                    self._skip("ml_gate", d, strategy=name, vix=vix,
                               entry_gate_score=gate_score, entry_gate_allow=False)
                    continue
            fill_day = self._next_session(d)
            if fill_day is None:
                self._skip("fill_day_missing_archive", d, note="no_next_session")
                continue
            pending = {"signal_date": d, "fill_day": fill_day, "signal_vix": vix, "strategy": name}
            if self.cfg.entry_gate is not None:
                pending["entry_gate_score"] = gate_score
                pending["entry_gate_allow"] = gate_allow
        # force-close anything still open at the end of the window (diagnostic only)
        if open_st is not None:
            self.diag["open_at_end"] += 1
        return self.trades

    def _next_session(self, d: date) -> Optional[date]:
        i = self._cal_index.searchsorted(pd.Timestamp(d), side="right")
        return self.cal[i] if i < len(self.cal) else None
