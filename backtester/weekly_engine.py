"""
Weekly options backtesting engine.

Simplified engine for 3-8 DTE weekly Nifty options.
No ML entry/exit — pure rule-based for Phase 1 edge validation.
Tighter exits, VIX gates, and capital protection tuned for gamma risk.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from config import WeeklyBacktestConfig, CostModel
from backtester.weekly_exit_policy import build_tracker, check_weekly_exit, update_tracker, WeeklyExitTracker
from pricing.black_scholes import OptionType, iv_from_vix, price_option
from strategies.base import Trade, TradeAction, ExitReason
from strategies.weekly_strategies import WeeklyPutCreditSpread, WeeklyIronCondor
from data.expiry_calendar import get_weekly_expiry_in_range


@dataclass
class WeeklyTradeResult:
    strategy: str
    entry_date: date
    exit_date: date
    entry_spot: float
    exit_spot: float
    entry_vix: float
    exit_vix: float
    dte_at_entry: int
    holding_days: int
    net_credit: float
    total_pnl: float
    total_pnl_pct: float
    exit_reason: str
    lots: int
    max_risk: float
    stop_loss_fill_adjustment: float = 0.0
    stop_loss_fill_worsened: bool = False


@dataclass
class WeeklyBacktestResult:
    total_trades: int = 0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    cagr_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_pnl_per_trade: float = 0.0
    avg_holding_days: float = 0.0
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    capital_utilization_pct: float = 0.0
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    daily_pnl: list = field(default_factory=list)
    strategy_breakdown: dict = field(default_factory=dict)
    exit_reason_breakdown: dict = field(default_factory=dict)
    stop_loss_exits_affected: int = 0


class WeeklyBacktestEngine:
    """
    Event-driven backtester for weekly options.

    Key differences from SmartBacktestEngine:
    - Targets the first weekly expiry in the configured 3-8 DTE entry window
    - Entry on Monday/Tuesday only (weekday 0 or 1)
    - VIX band gate: no entry below 10 or above 25
    - Tighter exits: 50% profit, 100% stop, trailing 30/25
    - Hard close by Wednesday EOD (DTE <= 1)
    - No ML model — rule-based only for Phase 1
    - Alternates between PCS and IC based on VIX level
    """

    def __init__(self, data: pd.DataFrame, config: WeeklyBacktestConfig):
        self.data = data
        self.config = config
        self.cost_model = config.cost_model if config.apply_costs else None

        self.pcs = WeeklyPutCreditSpread(lots=config.max_lots, lot_size=config.lot_size)
        self.ic = WeeklyIronCondor(lots=config.max_lots, lot_size=config.lot_size)

        self.open_trade: Optional[Trade] = None
        self.completed_trades: list[WeeklyTradeResult] = []
        self.equity_curve: list[float] = []
        self.daily_pnl: list[float] = []
        self._current_equity = config.initial_capital
        self._peak_equity = config.initial_capital
        self._exit_tracker: Optional[WeeklyExitTracker] = None
        self._days_in_market = 0

    def _price_trade_debit(self, trade: Trade, spot: float, vix: float, dte: int) -> float:
        """Price the current close-out debit for a multi-leg trade."""
        debit = 0.0
        for leg in trade.legs:
            option_type = OptionType.CALL if leg.option_type in ("CE", "CALL") else OptionType.PUT
            iv = iv_from_vix(vix, leg.strike, spot, option_type)
            premium = price_option(
                spot, leg.strike, max(dte, 0), iv, self.config.risk_free_rate, option_type,
            ).premium
            debit += premium if leg.is_short else -premium
        return debit

    def _realize_exit_pnl(
        self,
        trade: Trade,
        exit_reason: Optional[ExitReason],
        row_idx: int,
        trigger_spot: float,
        trigger_vix: float,
        dte: int,
    ) -> tuple[float, float, bool]:
        """
        Compute realized exit P&L.

        Baseline uses the current mark-to-market. Realism mode only changes
        stop-loss fills: close at the worse of trigger mark and next open mark,
        then apply an extra stop-loss-only slippage penalty per unit.
        """
        qty = trade.lots * trade.lot_size
        trigger_debit = trade.current_debit
        fill_debit = trigger_debit
        fill_adjustment = 0.0
        fill_worsened = False

        if (
            exit_reason == ExitReason.STOP_LOSS
            and self.config.stop_loss_fill_policy == "worst_of_trigger_and_next_open"
        ):
            next_open_debit = trigger_debit
            next_idx = row_idx + 1
            if next_idx < len(self.data):
                next_row = self.data.iloc[next_idx]
                next_open_spot = next_row.get("nifty_open", trigger_spot)
                next_vix_proxy = next_row.get("vix", trigger_vix)
                if not pd.isna(next_open_spot) and not pd.isna(next_vix_proxy):
                    next_open_debit = self._price_trade_debit(
                        trade, float(next_open_spot), float(next_vix_proxy), max(dte - 1, 0),
                    )

            fill_debit = max(trigger_debit, next_open_debit)
            fill_adjustment += max(0.0, fill_debit - trigger_debit) * qty

            penalty_per_unit = max(0.0, self.config.stop_loss_slippage_penalty_per_unit)
            if penalty_per_unit > 0:
                fill_debit += penalty_per_unit
                fill_adjustment += penalty_per_unit * qty

            fill_worsened = fill_adjustment > 0

        raw_pnl = (trade.net_credit - fill_debit) * qty
        cost = self._apply_costs(trade)
        return raw_pnl - cost, fill_adjustment, fill_worsened

    def _select_strategy(self, vix: float, market_data: dict):
        """VIX-based strategy selection for weeklies."""
        if 12 <= vix <= 22:
            nifty_5d = market_data.get("nifty_return_5d", 0)
            if not (isinstance(nifty_5d, float) and np.isnan(nifty_5d)) and abs(nifty_5d) < 0.02:
                return self.ic
        return self.pcs

    def _apply_costs(self, trade: Trade) -> float:
        """Calculate transaction costs for a trade."""
        if not self.cost_model:
            return 0.0
        return self.cost_model.total_cost_per_trade(
            net_credit=trade.net_credit,
            num_legs=len(trade.legs),
            lots=trade.lots,
            lot_size=trade.lot_size,
            vix=trade.entry_vix,
        )

    def run(self) -> WeeklyBacktestResult:
        """Execute weekly options backtest."""
        equity = self.config.initial_capital
        expiry_date: Optional[date] = None
        entry_vix = 0.0

        for row_idx, (idx, row) in enumerate(self.data.iterrows()):
            current_date = idx.date() if hasattr(idx, "date") else idx
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            market_data = row.to_dict()
            daily_trade_pnl = 0.0

            if self.open_trade is not None:
                self._days_in_market += 1
                dte = (expiry_date - current_date).days if expiry_date else 0

                strategy = self._select_strategy(entry_vix, market_data)
                if hasattr(strategy, "update_premiums"):
                    strategy.update_premiums(
                        self.open_trade, spot, vix, max(dte, 0),
                        self.config.risk_free_rate,
                    )

                prior_tracker = WeeklyExitTracker(
                    peak_pnl_per_unit=self._exit_tracker.peak_pnl_per_unit,
                    entry_abs_delta=self._exit_tracker.entry_abs_delta,
                    best_abs_delta=self._exit_tracker.best_abs_delta,
                    high_spot=self._exit_tracker.high_spot,
                    low_spot=self._exit_tracker.low_spot,
                ) if self._exit_tracker is not None else build_tracker(self.open_trade)

                should_exit, exit_reason = check_weekly_exit(
                    config=self.config,
                    trade=self.open_trade,
                    tracker=prior_tracker,
                    spot=spot,
                    vix=vix,
                    dte=dte,
                    entry_vix=entry_vix,
                    current_equity=self._current_equity,
                    holding_days=(current_date - self.open_trade.entry_date).days,
                )

                if not should_exit:
                    action, reason = strategy.should_exit(self.open_trade, spot, vix, dte)
                    if action == TradeAction.EXIT or dte <= 0:
                        should_exit = True
                        exit_reason = reason if reason else ExitReason.EXPIRY

                if should_exit:
                    net_pnl, fill_adjustment, fill_worsened = self._realize_exit_pnl(
                        self.open_trade, exit_reason, row_idx, float(spot), float(vix), max(dte, 0),
                    )

                    result = WeeklyTradeResult(
                        strategy=self.open_trade.strategy_name,
                        entry_date=self.open_trade.entry_date,
                        exit_date=current_date,
                        entry_spot=self.open_trade.entry_spot,
                        exit_spot=spot,
                        entry_vix=self.open_trade.entry_vix,
                        exit_vix=vix,
                        dte_at_entry=(expiry_date - self.open_trade.entry_date).days if expiry_date else 0,
                        holding_days=(current_date - self.open_trade.entry_date).days,
                        net_credit=self.open_trade.net_credit,
                        total_pnl=net_pnl,
                        total_pnl_pct=(net_pnl / self.open_trade.max_loss * 100) if self.open_trade.max_loss > 0 else 0,
                        exit_reason=exit_reason.value if exit_reason else "unknown",
                        lots=self.open_trade.lots,
                        max_risk=self.open_trade.max_risk,
                        stop_loss_fill_adjustment=fill_adjustment,
                        stop_loss_fill_worsened=fill_worsened,
                    )
                    self.completed_trades.append(result)
                    daily_trade_pnl = net_pnl
                    self.open_trade = None
                    self._exit_tracker = None
                else:
                    if self._exit_tracker is None:
                        self._exit_tracker = build_tracker(self.open_trade)
                    update_tracker(self._exit_tracker, self.open_trade, spot)
                    daily_trade_pnl = self.open_trade.total_pnl

            elif self.open_trade is None:
                weekday = current_date.weekday()
                if weekday not in (0, 1):
                    pass
                elif vix < self.config.min_vix_entry or vix > self.config.max_vix_entry:
                    pass
                else:
                    strategy = self._select_strategy(vix, market_data)
                    action = strategy.should_enter(spot, vix, market_data)

                    if action == TradeAction.ENTER:
                        exp, dte = get_weekly_expiry_in_range(
                            current_date, self.config.min_dte_entry, self.config.max_dte_entry,
                        )
                        if exp is not None:
                            trade = strategy.create_trade(
                                current_date, spot, vix, dte, self.config.risk_free_rate,
                            )
                            self.open_trade = trade
                            expiry_date = exp
                            entry_vix = vix
                            self._exit_tracker = build_tracker(trade)

            realized = sum(t.total_pnl for t in self.completed_trades)
            equity = self.config.initial_capital + realized
            if self.open_trade:
                equity += self.open_trade.total_pnl
            self._current_equity = self.config.initial_capital + realized

            self.equity_curve.append(equity)
            self.daily_pnl.append(daily_trade_pnl)

            if equity > self._peak_equity:
                self._peak_equity = equity

        if self.open_trade:
            last_row = self.data.iloc[-1]
            spot = last_row.get("nifty_close", 0)
            vix = last_row.get("vix", 15)
            last_date = self.data.index[-1]
            if hasattr(last_date, "date"):
                last_date = last_date.date()

            pnl = self.open_trade.total_pnl
            cost = self._apply_costs(self.open_trade)
            result = WeeklyTradeResult(
                strategy=self.open_trade.strategy_name,
                entry_date=self.open_trade.entry_date,
                exit_date=last_date,
                entry_spot=self.open_trade.entry_spot,
                exit_spot=spot,
                entry_vix=self.open_trade.entry_vix,
                exit_vix=vix,
                dte_at_entry=0,
                holding_days=(last_date - self.open_trade.entry_date).days,
                net_credit=self.open_trade.net_credit,
                total_pnl=pnl - cost,
                total_pnl_pct=0,
                exit_reason="expiry",
                lots=self.open_trade.lots,
                max_risk=self.open_trade.max_risk,
            )
            self.completed_trades.append(result)
            self.open_trade = None
            self._exit_tracker = None

        return self._build_result()

    def _build_result(self) -> WeeklyBacktestResult:
        trades = self.completed_trades
        if not trades:
            return WeeklyBacktestResult(equity_curve=self.equity_curve, daily_pnl=self.daily_pnl)

        pnls = [t.total_pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total_pnl = sum(pnls)
        total_return_pct = total_pnl / self.config.initial_capital * 100

        n_days = len(self.equity_curve)
        years = n_days / 252 if n_days > 0 else 1
        final_equity = self.config.initial_capital + total_pnl
        cagr = ((final_equity / self.config.initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0

        eq = np.array(self.equity_curve) if self.equity_curve else np.array([self.config.initial_capital])
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100
        max_dd = abs(dd.min()) if len(dd) > 0 else 0

        daily = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0])
        daily_mean = np.mean(daily)
        daily_std = np.std(daily)
        sharpe = (daily_mean / daily_std * np.sqrt(252)) if daily_std > 0 else 0

        downside = daily[daily < 0]
        downside_std = np.std(downside) if len(downside) > 0 else 1
        sortino = (daily_mean / downside_std * np.sqrt(252)) if downside_std > 0 else 0
        calmar = cagr / max_dd if max_dd > 0 else 0

        gross_win = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        pf = gross_win / gross_loss if gross_loss > 0 else 0

        max_consec_w, max_consec_l, cur_w, cur_l = 0, 0, 0, 0
        for p in pnls:
            if p > 0:
                cur_w += 1
                cur_l = 0
            else:
                cur_l += 1
                cur_w = 0
            max_consec_w = max(max_consec_w, cur_w)
            max_consec_l = max(max_consec_l, cur_l)

        total_hold = sum(t.holding_days for t in trades)
        calendar_days = (trades[-1].exit_date - trades[0].entry_date).days if len(trades) > 1 else 1
        capital_util = total_hold / calendar_days * 100 if calendar_days > 0 else 0

        strat_breakdown = {}
        exit_breakdown = {}
        for t in trades:
            s = t.strategy
            if s not in strat_breakdown:
                strat_breakdown[s] = {"trades": 0, "wins": 0, "total_pnl": 0, "pnls": []}
            strat_breakdown[s]["trades"] += 1
            if t.total_pnl > 0:
                strat_breakdown[s]["wins"] += 1
            strat_breakdown[s]["total_pnl"] += t.total_pnl
            strat_breakdown[s]["pnls"].append(t.total_pnl)
            exit_breakdown[t.exit_reason] = exit_breakdown.get(t.exit_reason, 0) + 1

        return WeeklyBacktestResult(
            total_trades=len(trades),
            total_pnl=round(total_pnl),
            total_return_pct=round(total_return_pct, 2),
            cagr_pct=round(cagr, 2),
            max_drawdown_pct=round(max_dd, 1),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
            win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0,
            profit_factor=round(pf, 2),
            avg_pnl_per_trade=round(total_pnl / len(trades)) if trades else 0,
            avg_holding_days=round(total_hold / len(trades), 1) if trades else 0,
            best_trade_pnl=round(max(pnls)) if pnls else 0,
            worst_trade_pnl=round(min(pnls)) if pnls else 0,
            max_consecutive_wins=max_consec_w,
            max_consecutive_losses=max_consec_l,
            capital_utilization_pct=round(capital_util, 1),
            trades=trades,
            equity_curve=self.equity_curve,
            daily_pnl=self.daily_pnl,
            strategy_breakdown=strat_breakdown,
            exit_reason_breakdown=exit_breakdown,
            stop_loss_exits_affected=sum(1 for t in trades if getattr(t, "stop_loss_fill_worsened", False)),
        )
