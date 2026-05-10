"""
Core backtesting engine. Iterates through historical data day-by-day,
enters/exits trades based on strategy rules, and tracks P&L.
"""

from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, Trade, TradeAction, ExitReason
from strategies.expiry_selector import select_optimal_entry
from pricing.black_scholes import price_option, iv_from_vix, OptionType
from config import BacktestConfig, CostModel
from backtester.position_sizer import PositionSizer, SizingDecision, _regime_from_vix
from backtester.entry_engine import EntryDecisionEngine
from backtester.fills import ConservativeFillModel


@dataclass
class TradeResult:
    """Result of a single completed trade."""
    signal_date: Optional[date]
    entry_date: date
    exit_date: date
    strategy: str
    entry_spot: float
    exit_spot: float
    entry_vix: float
    exit_vix: float
    net_credit: float
    pnl_per_unit: float
    total_pnl: float
    pnl_pct: float
    exit_reason: str
    holding_days: int
    legs_detail: str
    max_drawdown_during: float = 0.0


@dataclass
class BacktestResult:
    """Aggregate results of a backtest run."""
    strategy_name: str
    start_date: date
    end_date: date
    initial_capital: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    max_drawdown: float
    max_drawdown_pct: float
    win_rate: float
    avg_pnl_per_trade: float
    avg_return_per_trade_pct: float
    avg_holding_days: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    total_return_pct: float
    cagr_pct: float
    volatility_annual_pct: float
    payoff_ratio: float
    expectancy: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    best_trade_pnl: float
    worst_trade_pnl: float
    best_month_pnl: float
    worst_month_pnl: float
    avg_win_holding_days: float
    avg_loss_holding_days: float
    trades: list[TradeResult] = field(default_factory=list)
    equity_curve: Optional[pd.Series] = None
    daily_pnl: Optional[pd.Series] = None
    monthly_pnl: Optional[pd.Series] = None
    yearly_pnl: Optional[pd.Series] = None
    diagnostics: dict = field(default_factory=dict)

    def summary(self) -> str:
        years = max((self.end_date - self.start_date).days / 365.25, 0.1)
        lines = [
            f"\n{'=' * 80}",
            f"  BACKTEST RESULTS: {self.strategy_name}",
            f"  Period: {self.start_date} to {self.end_date} ({years:.1f} years)",
            f"  Initial Capital: ₹{self.initial_capital:,.0f}",
            f"{'=' * 80}",
            f"",
            f"  ── RETURN METRICS ──",
            f"  Total P&L:              ₹{self.total_pnl:>12,.0f}",
            f"  Total Return:           {self.total_return_pct:>11.2f}%",
            f"  CAGR:                   {self.cagr_pct:>11.2f}%",
            f"  Avg Return/Trade:       {self.avg_return_per_trade_pct:>11.2f}%  (₹{self.avg_pnl_per_trade:,.0f})",
            f"",
            f"  ── RISK METRICS ──",
            f"  Max Drawdown:           ₹{self.max_drawdown:>12,.0f}  ({self.max_drawdown_pct:.1f}%)",
            f"  Volatility (Ann.):      {self.volatility_annual_pct:>11.2f}%",
            f"  Sharpe Ratio:           {self.sharpe_ratio:>11.2f}",
            f"  Sortino Ratio:          {self.sortino_ratio:>11.2f}",
            f"  Calmar Ratio:           {self.calmar_ratio:>11.2f}",
            f"",
            f"  ── TRADE STATS ──",
            f"  Total Trades:           {self.total_trades:>11}",
            f"  Win Rate:               {self.win_rate:>10.1f}%  ({self.winning_trades}W / {self.losing_trades}L)",
            f"  Avg Win:                ₹{self.avg_win:>12,.0f}  (hold {self.avg_win_holding_days:.0f}d)",
            f"  Avg Loss:               ₹{self.avg_loss:>12,.0f}  (hold {self.avg_loss_holding_days:.0f}d)",
            f"  Payoff Ratio:           {self.payoff_ratio:>11.2f}x  (avg win / avg loss)",
            f"  Expectancy:             ₹{self.expectancy:>12,.0f}  per trade",
            f"  Profit Factor:          {self.profit_factor:>11.2f}",
            f"  Avg Holding Days:       {self.avg_holding_days:>11.1f}",
            f"",
            f"  ── STREAKS & EXTREMES ──",
            f"  Max Consecutive Wins:   {self.max_consecutive_wins:>11}",
            f"  Max Consecutive Losses: {self.max_consecutive_losses:>11}",
            f"  Best Single Trade:      ₹{self.best_trade_pnl:>12,.0f}",
            f"  Worst Single Trade:     ₹{self.worst_trade_pnl:>12,.0f}",
            f"  Best Month:             ₹{self.best_month_pnl:>12,.0f}",
            f"  Worst Month:            ₹{self.worst_month_pnl:>12,.0f}",
            f"{'=' * 80}",
        ]
        return "\n".join(lines)


class BacktestEngine:
    """
    Event-driven backtesting engine.
    Steps through each trading day, checks entry/exit conditions,
    prices options using Black-Scholes with VIX as IV proxy.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        config: BacktestConfig = BacktestConfig(),
        target_dte: int = 21,
    ):
        self.strategy = strategy
        self.data = data.copy()
        self.config = config
        self.target_dte = target_dte
        self.completed_trades: list[TradeResult] = []
        self.open_trade: Optional[Trade] = None
        self.equity_curve: list[float] = []
        self.daily_pnl: list[float] = []
        self.peak_equity: float = config.initial_capital
        self.fill_model = ConservativeFillModel(config.cost_model)
        self._pending_entry = None
        self._pending_exit = None
        self._evaluation_start_date = None
        if getattr(getattr(self, "walk_forward_manager", None), "windows", None):
            self._evaluation_start_date = self.walk_forward_manager.windows[0].test_start.date()

    def _get_expiry_date(self, current_date: date) -> date:
        """Find the monthly expiry closest to target DTE, respecting the NSE Thursday→Monday cutover."""
        from data.expiry_calendar import get_best_expiry_for_dte
        expiry, _ = get_best_expiry_for_dte(current_date, self.target_dte)
        return expiry

    def _calculate_dte(self, current_date: date, expiry: date) -> int:
        return max((expiry - current_date).days, 0)

    def _sync_walk_forward_models(self, current_date) -> None:
        return None

    def _fill_pending_exit(self, current_date, row) -> float:
        return 0.0

    def _fill_pending_entry(self, current_date, row) -> None:
        return None

    def run(self) -> BacktestResult:
        """Execute the backtest."""
        equity = self.config.initial_capital
        expiry_date: Optional[date] = None
        trade_max_dd = 0.0
        trade_peak_pnl = 0.0

        for idx, row in self.data.iterrows():
            current_date = idx.date() if hasattr(idx, "date") else idx
            if self._evaluation_start_date is not None and current_date < self._evaluation_start_date:
                self.equity_curve.append(equity)
                self.daily_pnl.append(0.0)
                continue
            self._sync_walk_forward_models(current_date)
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            market_data = row.to_dict()
            daily_trade_pnl = 0.0

            if self._pending_exit is not None:
                daily_trade_pnl += self._fill_pending_exit(current_date, row)

            if self._pending_entry is not None and self.open_trade is None:
                self._fill_pending_entry(current_date, row)

            if self.open_trade is not None:
                self._capital_stats["days_with_open_trade"] += 1
                dte = self._calculate_dte(current_date, expiry_date) if expiry_date else 0

                if hasattr(self.strategy, "update_premiums"):
                    self.strategy.update_premiums(
                        self.open_trade, spot, vix, dte, self.config.risk_free_rate
                    )

                current_pnl = self.open_trade.total_pnl
                if current_pnl > trade_peak_pnl:
                    trade_peak_pnl = current_pnl
                dd = trade_peak_pnl - current_pnl
                if dd > trade_max_dd:
                    trade_max_dd = dd

                action, reason = self.strategy.should_exit(
                    self.open_trade, spot, vix, dte
                )

                if action == TradeAction.ADJUST and hasattr(self.strategy, "should_adjust"):
                    adj = self.strategy.should_adjust(
                        self.open_trade, spot, vix, dte, market_data,
                    )
                    if adj is not None:
                        self.open_trade.apply_adjustment(adj)
                        expiry_date = self._get_expiry_date(current_date)
                        daily_trade_pnl = self.open_trade.total_pnl
                    elif dte <= 0:
                        daily_trade_pnl = self.open_trade.total_pnl
                        self._close_trade(current_date, spot, vix, ExitReason.EXPIRY, trade_max_dd)
                        trade_max_dd = 0.0
                        trade_peak_pnl = 0.0
                    else:
                        daily_trade_pnl = self.open_trade.total_pnl
                elif action == TradeAction.EXIT or dte <= 0:
                    if reason is None:
                        reason = ExitReason.EXPIRY
                    daily_trade_pnl = self.open_trade.total_pnl
                    self._close_trade(current_date, spot, vix, reason, trade_max_dd)
                    trade_max_dd = 0.0
                    trade_peak_pnl = 0.0
                else:
                    daily_trade_pnl = self.open_trade.total_pnl

            elif self.open_trade is None:
                # Circuit breaker guard applies even in naive mode
                cb_blocked = False
                if hasattr(self.strategy, "get_eligible_strategies"):
                    eligible = self.strategy.get_eligible_strategies(spot, vix, market_data)
                    if not eligible:
                        cb_blocked = True

                if not cb_blocked:
                    action = self.strategy.should_enter(spot, vix, market_data)

                    if action == TradeAction.ENTER:
                        expiry_date = self._get_expiry_date(current_date)
                        dte = self._calculate_dte(current_date, expiry_date)

                        if self.config.min_dte_entry <= dte <= self.config.max_dte_entry:
                            self.open_trade = self.strategy.create_trade(
                                current_date, spot, vix, dte, self.config.risk_free_rate
                            )
                            trade_max_dd = 0.0
                            trade_peak_pnl = 0.0

            equity = self.config.initial_capital + sum(t.total_pnl for t in self.completed_trades)
            if self.open_trade:
                equity += self.open_trade.total_pnl

            self.equity_curve.append(equity)
            self.daily_pnl.append(daily_trade_pnl)

            if equity > self.peak_equity:
                self.peak_equity = equity

        if self._pending_exit and self.open_trade:
            last_row = self.data.iloc[-1]
            last_date = self.data.index[-1]
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            self._fill_pending_exit(last_date + timedelta(days=1), last_row)

        if self.open_trade:
            last_row = self.data.iloc[-1]
            spot = last_row.get("nifty_close", 0)
            vix = last_row.get("vix", 15)
            last_date = self.data.index[-1]
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            self._close_trade(last_date, spot, vix, ExitReason.EXPIRY, trade_max_dd)

        return self._build_result()

    def _close_trade(self, exit_date, spot, vix, reason, max_dd, raw_pnl_override: float | None = None):
        trade = self.open_trade
        trade.exit_date = exit_date
        trade.exit_spot = spot
        trade.exit_vix = vix
        trade.exit_reason = reason

        legs_detail = " | ".join(
            f"{'S' if l.is_short else 'B'} {l.strike} {l.option_type} "
            f"entry={l.entry_premium:.1f} exit={l.current_premium:.1f}"
            for l in trade.legs
        )

        raw_pnl = trade.total_pnl if raw_pnl_override is None else raw_pnl_override

        # v3: deduct realistic transaction costs
        cost_deduction = 0.0
        if getattr(self.config, 'apply_costs', False):
            cost_model = getattr(self.config, 'cost_model', None)
            if cost_model is not None:
                avg_moneyness = 1.0
                if trade.legs and trade.entry_spot > 0:
                    avg_moneyness = sum(l.strike / trade.entry_spot for l in trade.legs) / len(trade.legs)
                cost_deduction = cost_model.total_cost_per_trade(
                    net_credit=trade.net_credit,
                    num_legs=len(trade.legs),
                    lots=trade.lots,
                    lot_size=trade.lot_size,
                    vix=getattr(trade, 'entry_vix', 15.0),
                    avg_moneyness=avg_moneyness,
                )
        net_pnl = raw_pnl - cost_deduction

        net_pnl_pct = (net_pnl / trade.max_loss * 100) if trade.max_loss != 0 else 0.0

        result = TradeResult(
            signal_date=getattr(trade, "signal_date", trade.entry_date),
            entry_date=trade.entry_date,
            exit_date=exit_date,
            strategy=trade.strategy_name,
            entry_spot=trade.entry_spot,
            exit_spot=spot,
            entry_vix=trade.entry_vix,
            exit_vix=vix,
            net_credit=trade.net_credit,
            pnl_per_unit=trade.pnl_per_unit,
            total_pnl=net_pnl,
            pnl_pct=net_pnl_pct,
            exit_reason=reason.value if reason else "unknown",
            holding_days=(exit_date - trade.entry_date).days,
            legs_detail=legs_detail,
            max_drawdown_during=max_dd,
        )
        self.completed_trades.append(result)
        # v4: track strategy for concentration
        if hasattr(self, '_strategy_history'):
            strat_name = trade.strategy_name.split(":")[-1] if ":" in trade.strategy_name else trade.strategy_name
            self._strategy_history.append(strat_name)
        self.open_trade = None
        if self._entry_decision_engine is not None:
            self._entry_decision_engine.record_outcome(result.total_pnl > 0)

    def _build_result(self) -> BacktestResult:
        trades = self.completed_trades
        start = self._evaluation_start_date or self.data.index[0]
        end = self.data.index[-1]
        start_dt = start.date() if hasattr(start, "date") else start
        end_dt = end.date() if hasattr(end, "date") else end
        capital = self.config.initial_capital

        empty = BacktestResult(
            strategy_name=self.strategy.name,
            start_date=start_dt, end_date=end_dt,
            initial_capital=capital,
            total_trades=0, winning_trades=0, losing_trades=0,
            total_pnl=0, max_drawdown=0, max_drawdown_pct=0,
            win_rate=0, avg_pnl_per_trade=0, avg_return_per_trade_pct=0,
            avg_holding_days=0, avg_win=0, avg_loss=0,
            profit_factor=0, sharpe_ratio=0, sortino_ratio=0,
            calmar_ratio=0, total_return_pct=0, cagr_pct=0,
            volatility_annual_pct=0, payoff_ratio=0, expectancy=0,
            max_consecutive_wins=0, max_consecutive_losses=0,
            best_trade_pnl=0, worst_trade_pnl=0,
            best_month_pnl=0, worst_month_pnl=0,
            avg_win_holding_days=0, avg_loss_holding_days=0,
            diagnostics={},
        )
        if not trades:
            return empty

        wins = [t for t in trades if t.total_pnl > 0]
        losses = [t for t in trades if t.total_pnl <= 0]
        total_pnl = sum(t.total_pnl for t in trades)

        gross_profit = sum(t.total_pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.total_pnl for t in losses)) if losses else 1

        # Equity curve & drawdown
        equity_series = pd.Series(self.equity_curve)
        peak = equity_series.cummax()
        drawdown = equity_series - peak
        max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0
        max_dd_pct = (max_dd / peak[drawdown.idxmin()] * 100) if max_dd > 0 and len(peak) > 0 else 0

        # Returns
        total_return_pct = (total_pnl / capital) * 100
        years = max((end_dt - start_dt).days / 365.25, 0.1)
        final_equity = capital + total_pnl
        cagr = ((final_equity / capital) ** (1 / years) - 1) * 100 if final_equity > 0 else 0

        # Daily returns for risk metrics (MTM-based)
        equity_s = pd.Series(self.equity_curve)
        daily_equity_changes = equity_s.diff().fillna(0)
        daily_returns_pct = daily_equity_changes / equity_s.shift(1).fillna(capital)
        daily_returns_pct = daily_returns_pct.replace([float("inf"), float("-inf")], 0).fillna(0)

        sharpe = 0.0
        sortino = 0.0
        vol_annual = 0.0
        if len(daily_returns_pct) > 1:
            mean_r = daily_returns_pct.mean()
            std_r = daily_returns_pct.std()
            if std_r > 0:
                sharpe = (mean_r / std_r) * (252 ** 0.5)
            vol_annual = std_r * (252 ** 0.5) * 100
            downside = daily_returns_pct[daily_returns_pct < 0]
            downside_std = downside.std() if len(downside) > 1 else 0.001
            if downside_std > 0:
                sortino = (mean_r / downside_std) * (252 ** 0.5)

        daily_returns = pd.Series(self.daily_pnl)

        calmar = cagr / max_dd_pct if max_dd_pct > 0 else 0

        # Per-trade return %
        avg_return_pct = np.mean([t.pnl_pct for t in trades]) if trades else 0

        # Payoff ratio & expectancy
        avg_win = np.mean([t.total_pnl for t in wins]) if wins else 0
        avg_loss_val = np.mean([t.total_pnl for t in losses]) if losses else 0
        payoff = abs(avg_win / avg_loss_val) if avg_loss_val != 0 else float("inf")
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss_val)

        # Consecutive wins/losses
        max_con_wins, max_con_losses = 0, 0
        cur_wins, cur_losses = 0, 0
        for t in trades:
            if t.total_pnl > 0:
                cur_wins += 1
                cur_losses = 0
                max_con_wins = max(max_con_wins, cur_wins)
            else:
                cur_losses += 1
                cur_wins = 0
                max_con_losses = max(max_con_losses, cur_losses)

        # Holding days by win/loss
        avg_win_hold = np.mean([t.holding_days for t in wins]) if wins else 0
        avg_loss_hold = np.mean([t.holding_days for t in losses]) if losses else 0

        # Monthly P&L
        monthly_pnl = None
        best_month = 0.0
        worst_month = 0.0
        trade_df = pd.DataFrame([
            {"date": t.exit_date, "pnl": t.total_pnl} for t in trades
        ])
        if len(trade_df) > 0:
            trade_df["date"] = pd.to_datetime(trade_df["date"])
            trade_df = trade_df.set_index("date")
            monthly_pnl = trade_df["pnl"].resample("ME").sum()
            if len(monthly_pnl) > 0:
                best_month = monthly_pnl.max()
                worst_month = monthly_pnl.min()

        # Yearly P&L
        yearly_pnl = None
        if len(trade_df) > 0:
            yearly_pnl = trade_df["pnl"].resample("YE").sum()

        total_days = max(len(self.equity_curve), 1)
        flat_days = self._capital_stats["flat_days"]
        open_days = self._capital_stats["days_with_open_trade"]
        avg_deployed_capital = self._capital_stats["deployed_capital_sum"] / max(open_days, 1)
        avg_allowed_capital = self._capital_stats["allowed_capital_sum"] / max(open_days, 1)
        capital_utilization = (avg_deployed_capital / avg_allowed_capital * 100) if avg_allowed_capital > 0 else 0.0
        avg_lots = round(float(np.mean([d.lots for d in self.sizing_decisions])), 1) if self.sizing_decisions else 0.0
        avg_regime_lots = {
            regime: round(float(np.mean(values)), 1)
            for regime, values in self._regime_lots.items()
            if values
        }
        avg_components = {
            "base_lots": round(self._sizing_component_sums["base_lots"] / max(len(self.sizing_decisions), 1), 3),
            "confidence_scale": round(self._sizing_component_sums["confidence_scale"] / max(len(self.sizing_decisions), 1), 3),
            "regime_scale": round(self._sizing_component_sums["regime_scale"] / max(len(self.sizing_decisions), 1), 3),
            "dd_scale": round(self._sizing_component_sums["dd_scale"] / max(len(self.sizing_decisions), 1), 3),
        }
        gate_counts = dict(self._gate_stats)
        if self._entry_decision_engine is not None:
            gate_counts.update({
                f"ml_{k}": v for k, v in getattr(self._entry_decision_engine, "skip_reasons", {}).items()
            })
        if hasattr(self.strategy, "_circuit_breaker_reason_counts"):
            gate_counts.update({
                f"cb_{k}": v for k, v in getattr(self.strategy, "_circuit_breaker_reason_counts", {}).items()
            })
        opportunity_waterfall = {
            "raw_candidate_days": self._opportunity_stats.get("raw_candidate_days", 0),
            "ml_scored_days": self._opportunity_stats.get("ml_scored_days", 0),
            "ml_pass_days": self._opportunity_stats.get("ml_pass_days", 0),
            "strategy_ranked_days": self._opportunity_stats.get("strategy_ranked_days", 0),
            "sized_days": self._opportunity_stats.get("sized_days", 0),
            "queued_entries": self._opportunity_stats.get("queued_entries", 0),
            "executed_trades": len(trades),
        }

        return BacktestResult(
            strategy_name=self.strategy.name,
            start_date=start_dt,
            end_date=end_dt,
            initial_capital=capital,
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            total_pnl=round(total_pnl, 0),
            max_drawdown=round(max_dd, 0),
            max_drawdown_pct=round(max_dd_pct, 1),
            win_rate=round(win_rate, 1),
            avg_pnl_per_trade=round(total_pnl / len(trades), 0),
            avg_return_per_trade_pct=round(avg_return_pct, 2),
            avg_holding_days=round(np.mean([t.holding_days for t in trades]), 1),
            avg_win=round(avg_win, 0),
            avg_loss=round(avg_loss_val, 0),
            profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
            total_return_pct=round(total_return_pct, 2),
            cagr_pct=round(cagr, 2),
            volatility_annual_pct=round(vol_annual, 2),
            payoff_ratio=round(payoff, 2),
            expectancy=round(expectancy, 0),
            max_consecutive_wins=max_con_wins,
            max_consecutive_losses=max_con_losses,
            best_trade_pnl=round(max(t.total_pnl for t in trades), 0),
            worst_trade_pnl=round(min(t.total_pnl for t in trades), 0),
            best_month_pnl=round(best_month, 0),
            worst_month_pnl=round(worst_month, 0),
            avg_win_holding_days=round(avg_win_hold, 1),
            avg_loss_holding_days=round(avg_loss_hold, 1),
            trades=trades,
            equity_curve=equity_series,
            daily_pnl=daily_returns,
            monthly_pnl=monthly_pnl,
            yearly_pnl=yearly_pnl,
            diagnostics={
                "capital_utilization_pct": round(capital_utilization, 1),
                "flat_days": flat_days,
                "flat_days_pct": round(flat_days / total_days * 100, 1) if total_days > 0 else 0.0,
                "open_days": open_days,
                "avg_deployed_capital": round(avg_deployed_capital, 0),
                "avg_allowed_capital": round(avg_allowed_capital, 0),
                "avg_lots": avg_lots,
                "avg_lots_by_regime": avg_regime_lots,
                "avg_sizing_components": avg_components,
                "gate_rejections": gate_counts,
                "opportunity_waterfall": opportunity_waterfall,
                "sizing_decisions": len(self.sizing_decisions),
            },
        )


class SmartBacktestEngine(BacktestEngine):
    """
    Enhanced backtest engine that uses the ML exit model for daily exit decisions.

    Instead of fixed profit/stop rules, every day it evaluates:
    - Market features (32 features: volatility, macro, cross-geo, etc.)
    - Trade-specific features (P&L %, strike proximity, theta, velocity)
    - ML classifier: probability that holding further improves outcome
    - ML regressor: predicted final P&L

    Walk-forward approach: trains exit model on data BEFORE the trade period,
    then uses it for decisions during the trade — no look-ahead bias.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        config: BacktestConfig = BacktestConfig(),
        target_dte: int = 21,
        exit_engine=None,
        entry_model=None,
        entry_threshold: float = 0.50,
        compound: bool = True,
        max_lots_cap: int = 200,
        walk_forward_manager=None,
    ):
        super().__init__(strategy, data, config, target_dte)
        self.exit_engine = exit_engine
        self.entry_model = entry_model
        self.walk_forward_manager = walk_forward_manager
        self.entry_threshold = entry_threshold
        self.compound = compound
        self.max_lots_cap = max_lots_cap
        self.base_lots = strategy.lots
        self.ml_exit_count = 0
        self.rule_exit_count = 0
        self.ml_entry_count = 0
        self.ml_skip_count = 0
        self.capital_cap_exits = 0
        self.circuit_breaker_blocks = 0
        self.multi_expiry_selections = 0
        self._trade_peak_pnl_per_unit = 0.0
        self._trade_pnl_history = []
        self._pending_entry: dict | None = None
        self._pending_exit: dict | None = None
        self._current_equity = config.initial_capital
        self._peak_equity = config.initial_capital
        self._last_ml_win_prob = 0.60
        self._equity_at_trade_entry = config.initial_capital
        self.cooldown_skips = 0
        self.loss_streak_skips = 0
        # EntryDecisionEngine owns cooldown/loss-streak state; backtest syncs
        # counters from it after each check() call.
        self._entry_decision_engine: EntryDecisionEngine | None = None
        if entry_model and getattr(entry_model, "is_trained", False):
            self._entry_decision_engine = EntryDecisionEngine(
                entry_model=entry_model,
                strategy=strategy,
                entry_threshold=entry_threshold,
                cooldown_days=2,
                max_loss_streak=3,
                loss_streak_bump=0.03,
            )
        self.position_sizer = PositionSizer(
            config, max_lots_cap=max_lots_cap,
        )
        self.sizing_decisions: list[SizingDecision] = []
        self._stats: dict = {}
        self._evaluation_start_date = None
        if getattr(self.walk_forward_manager, "windows", None):
            self._evaluation_start_date = self.walk_forward_manager.windows[0].test_start.date()
        # v4: portfolio Greeks tracking
        self._portfolio_greeks_history = []
        self._strategy_history = []  # track last N strategy selections
        self._opportunity_stats: dict[str, int] = {}
        self._gate_stats: dict[str, int] = {}
        self._capital_stats = {
            "deployed_capital_sum": 0.0,
            "allowed_capital_sum": 0.0,
            "days_with_open_trade": 0,
            "flat_days": 0,
        }
        self._regime_lots: dict[str, list[int]] = {}
        self._sizing_component_sums = {
            "base_lots": 0.0,
            "confidence_scale": 0.0,
            "regime_scale": 0.0,
            "dd_scale": 0.0,
        }

    def _sync_walk_forward_models(self, current_date) -> None:
        if self.walk_forward_manager is None:
            return
        bundle = self.walk_forward_manager.get_bundle_for_date(current_date)
        self.exit_engine = bundle.exit_engine
        self.entry_model = bundle.entry_model
        if self.entry_model is not None:
            setattr(self.entry_model, "regime_rerank_enabled", getattr(self.config, "monthly_enable_regime_rerank", True))
            setattr(self.entry_model, "regime_rerank_strength", getattr(self.config, "monthly_regime_rerank_strength", 0.18))
        if self.entry_model and getattr(self.entry_model, "is_trained", False):
            if self._entry_decision_engine is None:
                self._entry_decision_engine = EntryDecisionEngine(
                    entry_model=self.entry_model,
                    strategy=self.strategy,
                    entry_threshold=self.entry_threshold,
                    cooldown_days=2,
                    max_loss_streak=3,
                    loss_streak_bump=0.03,
                )
            else:
                self._entry_decision_engine.entry_model = self.entry_model

    def _fill_pending_exit(self, current_date, row) -> float:
        if self._pending_exit is None or self.open_trade is None:
            return 0.0
        signal = self._pending_exit
        if current_date <= signal["signal_date"]:
            raise AssertionError("Exit fill must occur after the close-derived exit signal.")
        fill_spot = float(row.get("nifty_open", row.get("nifty_close", signal["signal_spot"])))
        gap_pct = ((fill_spot / signal["signal_spot"]) - 1.0) * 100 if signal["signal_spot"] > 0 else 0.0
        dte = self._calculate_dte(current_date, signal["expiry_date"]) if signal["expiry_date"] else 0
        raw_pnl, _ = self.fill_model.close_trade_pnl(
            self.open_trade,
            spot=fill_spot,
            vix=signal["signal_vix"],
            dte=max(dte, 0),
            risk_free_rate=self.config.risk_free_rate,
            gap_pct=gap_pct,
        )
        for leg in self.open_trade.legs:
            leg.current_premium = leg.entry_premium
        self.open_trade.exit_date = current_date
        self.open_trade.exit_spot = fill_spot
        self.open_trade.exit_vix = signal["signal_vix"]
        daily_trade_pnl = raw_pnl
        closed_strat = getattr(self.open_trade, "strategy_name", "")
        self._close_trade(current_date, fill_spot, signal["signal_vix"], signal["reason"], signal["trade_max_dd"], raw_pnl_override=raw_pnl)
        self.position_sizer.record_trade_with_equity(daily_trade_pnl, self._equity_at_trade_entry)
        self._pending_exit = None
        self._trade_peak_pnl_per_unit = 0.0
        self._trade_pnl_history = []
        return daily_trade_pnl

    def _fill_pending_entry(self, current_date, row) -> None:
        if self._pending_entry is None or self.open_trade is not None:
            return
        pending = self._pending_entry
        if current_date <= pending["signal_date"]:
            raise AssertionError("Entry fill must occur after the close-derived entry signal.")
        fill_spot = float(row.get("nifty_open", row.get("nifty_close", pending["signal_spot"])))
        gap_pct = ((fill_spot / pending["signal_spot"]) - 1.0) * 100 if pending["signal_spot"] > 0 else 0.0
        dte = self._calculate_dte(current_date, pending["expiry_date"])
        if dte < self.config.min_dte_entry:
            self._pending_entry = None
            return
        if hasattr(self.strategy, "set_lots"):
            self.strategy.set_lots(pending["lots"])
        else:
            self.strategy.lots = pending["lots"]
        if pending.get("strategy_name") and hasattr(self.strategy, "force_strategy_selection"):
            self.strategy.force_strategy_selection(pending["strategy_name"])
        trade = self.strategy.create_trade(current_date, fill_spot, pending["signal_vix"], dte, self.config.risk_free_rate)
        trade.signal_date = pending["signal_date"]
        self.fill_model.apply_entry_fill(
            trade,
            spot=fill_spot,
            vix=pending["signal_vix"],
            dte=dte,
            risk_free_rate=self.config.risk_free_rate,
            gap_pct=gap_pct,
        )
        if hasattr(self.config, "max_portfolio_delta"):
            trade_delta = abs(trade.portfolio_delta) if hasattr(trade, "portfolio_delta") else 0
            trade_vega = abs(trade.portfolio_vega) if hasattr(trade, "portfolio_vega") else 0
            if trade_delta > self.config.max_portfolio_delta or trade_vega > self.config.max_portfolio_vega:
                self._stats["greeks_cap_blocks"] = self._stats.get("greeks_cap_blocks", 0) + 1
                self._pending_entry = None
                return
        if hasattr(self.config, "max_strategy_concentration_pct"):
            lookback = getattr(self.config, "strategy_lookback_trades", 20)
            recent = self._strategy_history[-lookback:] if self._strategy_history else []
            if len(recent) >= lookback:
                strat_name = trade.strategy_name.split(":")[-1] if ":" in trade.strategy_name else trade.strategy_name
                count = sum(1 for s in recent if s == strat_name)
                conc_cap = self.config.max_strategy_concentration_pct
                if count / len(recent) * 100 > conc_cap:
                    self._stats["concentration_blocks"] = self._stats.get("concentration_blocks", 0) + 1
                    self._pending_entry = None
                    return
        self.open_trade = trade
        self._equity_at_trade_entry = pending["equity_at_signal"]
        self._capital_stats["deployed_capital_sum"] += trade.max_loss
        self._capital_stats["allowed_capital_sum"] += pending.get("allowed_capital", 0.0)
        self._pending_entry = None
        self._trade_peak_pnl_per_unit = 0.0
        self._trade_pnl_history = []

    def run(self) -> BacktestResult:
        """Execute backtest with ML-driven exit decisions."""
        equity = self.config.initial_capital
        expiry_date: Optional[date] = None
        trade_max_dd = 0.0
        trade_peak_pnl = 0.0
        trade_entry_spot = 0.0
        trade_entry_vix = 0.0

        for idx, row in self.data.iterrows():
            current_date = idx.date() if hasattr(idx, "date") else idx
            if self._evaluation_start_date is not None and current_date < self._evaluation_start_date:
                self.equity_curve.append(equity)
                self.daily_pnl.append(0.0)
                continue
            self._sync_walk_forward_models(current_date)
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)

            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            market_data = row.to_dict()
            daily_trade_pnl = 0.0

            if self._pending_exit is not None:
                daily_trade_pnl += self._fill_pending_exit(current_date, row)

            if self._pending_entry is not None and self.open_trade is None:
                self._fill_pending_entry(current_date, row)

            if self.open_trade is not None:
                dte = self._calculate_dte(current_date, expiry_date) if expiry_date else 0

                if hasattr(self.strategy, "update_premiums"):
                    self.strategy.update_premiums(
                        self.open_trade, spot, vix, dte, self.config.risk_free_rate
                    )

                current_pnl = self.open_trade.total_pnl
                if current_pnl > trade_peak_pnl:
                    trade_peak_pnl = current_pnl
                dd = trade_peak_pnl - current_pnl
                if dd > trade_max_dd:
                    trade_max_dd = dd

                should_exit, exit_reason = self._smart_exit_check(
                    row, spot, vix, dte, trade_entry_spot, trade_entry_vix,
                )

                if not should_exit:
                    action, reason = self.strategy.should_exit(
                        self.open_trade, spot, vix, dte
                    )
                    if action == TradeAction.ADJUST and hasattr(self.strategy, "should_adjust"):
                        adj = self.strategy.should_adjust(
                            self.open_trade, spot, vix, dte, market_data,
                        )
                        if adj is not None:
                            self.open_trade.apply_adjustment(adj)
                            expiry_date = self._get_expiry_date(current_date)
                            # Reset exit tracking after roll so trailing-stop
                            # doesn't fire on stale peak from pre-roll P&L
                            self._trade_peak_pnl_per_unit = self.open_trade.pnl_per_unit
                            self._trade_pnl_history = [self.open_trade.pnl_per_unit]
                        elif dte <= 0:
                            should_exit = True
                            exit_reason = ExitReason.EXPIRY
                            self.rule_exit_count += 1
                    elif action == TradeAction.EXIT or dte <= 0:
                        should_exit = True
                        exit_reason = reason if reason else ExitReason.EXPIRY
                        self.rule_exit_count += 1

                if should_exit:
                    self._pending_exit = {
                        "signal_date": current_date,
                        "signal_spot": spot,
                        "signal_vix": vix,
                        "reason": exit_reason,
                        "trade_max_dd": trade_max_dd,
                        "expiry_date": expiry_date,
                    }
                    daily_trade_pnl = self.open_trade.total_pnl
                else:
                    daily_trade_pnl = self.open_trade.total_pnl
                    self._trade_pnl_history.append(self.open_trade.pnl_per_unit)
                    if self.open_trade.pnl_per_unit > self._trade_peak_pnl_per_unit:
                        self._trade_peak_pnl_per_unit = self.open_trade.pnl_per_unit
            else:
                self._capital_stats["flat_days"] += 1

            if self.open_trade is None:
                should_enter_trade = False
                self._opportunity_stats["raw_candidate_days"] = self._opportunity_stats.get("raw_candidate_days", 0) + 1

                if self._entry_decision_engine is not None:
                    # All entry logic (circuit breaker, ML, PCS floor) lives in
                    # EntryDecisionEngine — same code path as signal mode.
                    _ed = self._entry_decision_engine.check(row, spot, vix, market_data)
                    should_enter_trade = _ed.should_enter
                    self._last_ml_win_prob = _ed.win_prob
                    if _ed.skip_reason == "circuit_breaker":
                        self.circuit_breaker_blocks += 1
                    if _ed.skip_reason:
                        self._gate_stats[_ed.skip_reason] = self._gate_stats.get(_ed.skip_reason, 0) + 1
                    # Sync cumulative counters so reporters see correct values
                    self.ml_skip_count = self._entry_decision_engine.ml_skip_count
                    self.ml_entry_count = self._entry_decision_engine.ml_entry_count
                    self.cooldown_skips = self._entry_decision_engine.cooldown_skips
                    self.loss_streak_skips = self._entry_decision_engine.loss_streak_skips
                    self._opportunity_stats["ml_scored_days"] = self._opportunity_stats.get("ml_scored_days", 0) + 1
                    if should_enter_trade:
                        self._opportunity_stats["ml_pass_days"] = self._opportunity_stats.get("ml_pass_days", 0) + 1
                else:
                    # Rule-based fallback when no trained entry model is provided
                    if hasattr(self.strategy, "get_eligible_strategies"):
                        eligible = self.strategy.get_eligible_strategies(spot, vix, market_data)
                        if not eligible:
                            self.circuit_breaker_blocks += 1
                            self._gate_stats["circuit_breaker"] = self._gate_stats.get("circuit_breaker", 0) + 1
                        else:
                            action = self.strategy.should_enter(spot, vix, market_data)
                            should_enter_trade = (action == TradeAction.ENTER)
                    else:
                        action = self.strategy.should_enter(spot, vix, market_data)
                        should_enter_trade = (action == TradeAction.ENTER)

                if should_enter_trade:
                    self._opportunity_stats["strategy_ranked_days"] = self._opportunity_stats.get("strategy_ranked_days", 0) + 1
                    realized_pnl = sum(t.total_pnl for t in self.completed_trades)
                    current_equity = self.config.initial_capital + realized_pnl
                    if current_equity > self._peak_equity:
                        self._peak_equity = current_equity
                    dd_pct = max(0.0, (self._peak_equity - current_equity) / self._peak_equity)
                    eligible = []
                    if hasattr(self.strategy, "get_eligible_strategies"):
                        eligible = self.strategy.get_eligible_strategies(spot, vix, market_data)
                        if hasattr(self.strategy, "_strategies"):
                            filtered = []
                            for strat_name in eligible:
                                sub = self.strategy._strategies.get(strat_name)
                                if sub is not None and sub.should_enter(spot, vix, market_data) == TradeAction.ENTER:
                                    filtered.append(strat_name)
                            eligible = filtered
                    if not eligible and hasattr(self.strategy, "_strategies"):
                        should_enter_trade = False
                    decision = None
                    if should_enter_trade:
                        prelim_lots = max(1, int(self.position_sizer._margin_fallback(current_equity)))
                        entry_strat_name = ""
                        if hasattr(self.strategy, "_strategies") and eligible:
                            decision = select_optimal_entry(
                                spot=spot,
                                vix=vix,
                                strategies=self.strategy._strategies,
                                eligible_strategies=eligible,
                                entry_date=current_date,
                                lots=prelim_lots,
                                lot_size=self.config.lot_size,
                                risk_free_rate=self.config.risk_free_rate,
                                brokerage_per_lot=self.config.brokerage_per_lot,
                                risk_config=self.config,
                            )
                            if not decision.found:
                                should_enter_trade = False
                                self._gate_stats["expiry_selection_failed"] = self._gate_stats.get("expiry_selection_failed", 0) + 1
                            else:
                                expiry_date = decision.expiry
                                dte = decision.dte
                                entry_strat_name = decision.strategy_name
                                self.multi_expiry_selections += 1
                                if hasattr(self.strategy, "force_strategy_selection"):
                                    self.strategy.force_strategy_selection(entry_strat_name)
                        else:
                            expiry_date = self._get_expiry_date(current_date)
                            dte = self._calculate_dte(current_date, expiry_date)

                        if should_enter_trade:
                            sizing = self.position_sizer.compute_lots(
                                equity=current_equity,
                                vix=vix,
                                regime=_regime_from_vix(vix),
                                win_prob=self._last_ml_win_prob,
                                drawdown_pct=dd_pct,
                                trade_max_loss_per_unit=decision.best.max_loss if decision else None,
                                trade_margin_per_lot=(decision.best.max_loss * self.config.lot_size) if decision else None,
                            )
                            new_lots = sizing.lots
                            if new_lots <= 0:
                                should_enter_trade = False
                                self._gate_stats["sizing_reject"] = self._gate_stats.get("sizing_reject", 0) + 1
                            else:
                                self.sizing_decisions.append(sizing)
                                self._opportunity_stats["sized_days"] = self._opportunity_stats.get("sized_days", 0) + 1
                                self._sizing_component_sums["base_lots"] += sizing.base_lots
                                self._sizing_component_sums["confidence_scale"] += sizing.confidence_scale
                                self._sizing_component_sums["regime_scale"] += sizing.regime_scale
                                self._sizing_component_sums["dd_scale"] += sizing.dd_scale
                                regime_key = _regime_from_vix(vix)
                                self._regime_lots.setdefault(regime_key, []).append(sizing.lots)

                if should_enter_trade and self.config.min_dte_entry <= dte <= self.config.max_dte_entry:
                    strategy_name = getattr(self.strategy, "_active_name", None)
                    self._pending_entry = {
                        "signal_date": current_date,
                        "signal_spot": spot,
                        "signal_vix": vix,
                        "expiry_date": expiry_date,
                        "lots": new_lots,
                        "strategy_name": strategy_name,
                        "equity_at_signal": current_equity,
                        "allowed_capital": current_equity * (getattr(self.config, "monthly_max_margin_per_trade_pct", 20.0) / 100.0),
                    }
                    self._opportunity_stats["queued_entries"] = self._opportunity_stats.get("queued_entries", 0) + 1

            realized = sum(t.total_pnl for t in self.completed_trades)
            equity = self.config.initial_capital + realized
            if self.open_trade:
                equity += self.open_trade.total_pnl
            self._current_equity = self.config.initial_capital + realized

            self.equity_curve.append(equity)
            self.daily_pnl.append(daily_trade_pnl)

            # v4: record portfolio Greeks
            if self.open_trade and hasattr(self, '_portfolio_greeks_history'):
                self._portfolio_greeks_history.append({
                    'date': current_date,
                    'delta': self.open_trade.portfolio_delta if hasattr(self.open_trade, 'portfolio_delta') else 0,
                    'vega': self.open_trade.portfolio_vega if hasattr(self.open_trade, 'portfolio_vega') else 0,
                    'gamma': self.open_trade.portfolio_gamma if hasattr(self.open_trade, 'portfolio_gamma') else 0,
                    'theta': self.open_trade.portfolio_theta if hasattr(self.open_trade, 'portfolio_theta') else 0,
                })

            if equity > self.peak_equity:
                self.peak_equity = equity

        if self.open_trade:
            last_row = self.data.iloc[-1]
            spot = last_row.get("nifty_close", 0)
            vix = last_row.get("vix", 15)
            last_date = self.data.index[-1]
            if hasattr(last_date, "date"):
                last_date = last_date.date()
            self._close_trade(last_date, spot, vix, ExitReason.EXPIRY, trade_max_dd)

        if self._stats.get("greeks_cap_blocks", 0) > 0:
            print(f"  Greeks cap blocks: {self._stats['greeks_cap_blocks']}")
        if self._stats.get("concentration_blocks", 0) > 0:
            print(f"  Strategy concentration blocks: {self._stats['concentration_blocks']}")
        if self._stats.get("starvation_loosens", 0) > 0:
            print(f"  Starvation guard activations: {self._stats['starvation_loosens']}")

        return self._build_result()

    def _ml_entry_check(self, row, spot, vix, market_data) -> bool:
        """Thin compatibility wrapper — delegates entirely to EntryDecisionEngine."""
        if self._entry_decision_engine is None:
            return False
        decision = self._entry_decision_engine.check(row, spot, vix, market_data)
        self._last_ml_win_prob = decision.win_prob
        if decision.skip_reason == "circuit_breaker":
            self.circuit_breaker_blocks += 1
        self.ml_skip_count = self._entry_decision_engine.ml_skip_count
        self.ml_entry_count = self._entry_decision_engine.ml_entry_count
        self.cooldown_skips = self._entry_decision_engine.cooldown_skips
        self.loss_streak_skips = self._entry_decision_engine.loss_streak_skips
        return decision.should_enter

    def _smart_exit_check(self, row, spot, vix, dte, entry_spot, entry_vix):
        """
        Adaptive exit using VIX-regime-based targets + trailing stop + ML override.

        Instead of fixed 50%/70% profit/stop for all regimes, adapts:
        - Calm market (VIX<15): wider targets, let theta work
        - Normal (15-20): standard targets
        - Elevated (20-30): tighter targets, book profits faster
        - Extreme (30+): very tight, quick in/out

        Plus trailing stop: if P&L drops 35%+ from peak after capturing >25% of credit.

        Capital protection: no single trade can lose more than 6% of current
        equity, ensuring one bad trade cannot wipe out many winning trades.
        """
        trade = self.open_trade
        if trade is None:
            return False, None

        # --- CAPITAL PROTECTION: absolute max loss per trade ---
        max_loss_pct_of_capital = 0.06
        max_loss_abs = self._current_equity * max_loss_pct_of_capital
        if trade.total_pnl < -max_loss_abs:
            self.capital_cap_exits += 1
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        net_credit = trade.net_credit
        pnl_per_unit = trade.pnl_per_unit

        if net_credit <= 0:
            return False, None

        pnl_pct = (pnl_per_unit / net_credit * 100)
        days_in = (row.name.date() - trade.entry_date).days if hasattr(row.name, "date") else 0

        short_legs = [l for l in trade.legs if l.is_short]
        min_dist = 999
        for sl in short_legs:
            ot = sl.option_type.name if hasattr(sl.option_type, "name") else str(sl.option_type)
            if ot in ("PUT", "PE"):
                dist = (spot - sl.strike) / spot * 100
            else:
                dist = (sl.strike - spot) / spot * 100
            min_dist = min(min_dist, dist)

        pnl_from_peak = pnl_per_unit - self._trade_peak_pnl_per_unit
        vix_change = (vix - entry_vix) / entry_vix if entry_vix > 0 else 0

        crash_risk = row.get("crash_risk_score", 0) if hasattr(row, "get") else 0
        consec_down = row.get("nifty_consec_down_days", 0) if hasattr(row, "get") else 0
        correction_depth = row.get("nifty_drawdown_from_20d_high_pct", 0) if hasattr(row, "get") else 0
        vix_vs_sma = row.get("vix_vs_sma_ratio", 1.0) if hasattr(row, "get") else 1.0

        # VIX-adaptive profit and stop targets
        if vix < 15:
            profit_target, stop_loss = 60, 80
        elif vix < 20:
            profit_target, stop_loss = 50, 65
        elif vix < 30:
            profit_target, stop_loss = 40, 55
        else:
            profit_target, stop_loss = 30, 45

        # VIX trend modulation: collapsing VIX = safer for credit sellers,
        # surging VIX = danger rising fast
        if vix_vs_sma < 0.85:
            profit_target = int(profit_target * 1.15)
            stop_loss = int(stop_loss * 1.10)
        elif vix_vs_sma > 1.15:
            stop_loss = int(stop_loss * 0.85)
            profit_target = int(profit_target * 0.90)

        # Crash-mode tightening: when extreme signals fire mid-trade,
        # reduce stop loss by 30% to cut losses faster
        crash_risk_v2 = row.get("crash_risk_score_v2", 0) if hasattr(row, "get") else 0
        if crash_risk_v2 >= 0.80 or correction_depth < -15:
            stop_loss = int(stop_loss * 0.7)
            profit_target = min(profit_target, 30)

        # Near-expiry: tighten targets regardless
        if dte <= 5:
            profit_target = min(profit_target, 30)

        # === Hard rules (no ML needed) ===

        # Strike proximity danger: spot within 1.5% of short strike while losing
        if min_dist < 1.5 and pnl_pct < -5:
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        # VIX spike: VIX jumped >25% since entry, cut losses
        if vix_change > 0.25 and pnl_pct < -10:
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        # VIX trend surge: VIX rapidly above its recent average while losing
        if vix_vs_sma > 1.20 and pnl_pct < -15:
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        # Extreme crash in progress: if losing at all, exit immediately
        if crash_risk_v2 >= 0.80 and pnl_pct < 0:
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        # VIX-adaptive profit target
        if pnl_pct >= profit_target:
            self.ml_exit_count += 1
            return True, ExitReason.PROFIT_TARGET

        # VIX-adaptive stop loss
        if pnl_pct < -stop_loss:
            self.ml_exit_count += 1
            return True, ExitReason.STOP_LOSS

        # === Trailing stop ===
        # If we captured good profit and it's eroding, lock it in
        peak_pct = (self._trade_peak_pnl_per_unit / net_credit * 100) if net_credit > 0 else 0
        drop_from_peak_pct = (pnl_from_peak / net_credit * 100) if net_credit > 0 else 0

        if peak_pct >= 25 and drop_from_peak_pct < -35:
            self.ml_exit_count += 1
            return True, ExitReason.PROFIT_TARGET

        # Gentler trailing stop for smaller profits
        if peak_pct >= 40 and drop_from_peak_pct < -20:
            self.ml_exit_count += 1
            return True, ExitReason.PROFIT_TARGET

        # === ML override (only when model is confident) ===
        if self.exit_engine and self.exit_engine.is_trained:
            try:
                market_features = self.exit_engine.feature_extractor.extract(row)
                pnl_3d_ago = self._trade_pnl_history[-3] if len(self._trade_pnl_history) >= 3 else 0
                vix_1d_chg = row.get("vix_change_1d", 0) if hasattr(row, "get") else 0
                trade_features = {
                    "pnl_pct": pnl_pct, "dte_remaining": dte, "days_in_trade": days_in,
                    "dist_to_short_strike_pct": min_dist, "vix_now": vix,
                    "vix_change_since_entry": vix_change,
                    "vix_vs_sma_ratio_now": vix_vs_sma if not pd.isna(vix_vs_sma) else 1.0,
                    "vix_1d_change_now": vix_1d_chg if not pd.isna(vix_1d_chg) else 0.0,
                    "spot_change_since_entry": (spot - entry_spot) / entry_spot * 100 if entry_spot > 0 else 0,
                    "pnl_velocity": pnl_per_unit / max(days_in, 1),
                    "credit_captured_pct": pnl_pct,
                    "max_loss_proximity": abs(pnl_per_unit) / (net_credit * 3) if pnl_per_unit < 0 else 0,
                    "theta_estimate": net_credit / max(dte + days_in, 1),
                    "pnl_from_peak": pnl_from_peak,
                    "pnl_velocity_3d": (pnl_per_unit - pnl_3d_ago) / 3 if days_in >= 3 else pnl_per_unit / max(days_in, 1),
                    "days_since_peak": len(self._trade_pnl_history) - max(
                        (i for i, p in enumerate(self._trade_pnl_history) if p >= self._trade_peak_pnl_per_unit),
                        default=len(self._trade_pnl_history)
                    ) if self._trade_pnl_history else 0,
                }
                all_features = {**market_features, **trade_features}
                X = pd.DataFrame([all_features]).reindex(
                    columns=self.exit_engine.exit_feature_cols, fill_value=0
                ).fillna(0).replace([float("inf"), float("-inf")], 0)
                probs = self.exit_engine.exit_classifier.predict_proba(X)[0]
                classes = list(self.exit_engine.exit_classifier.classes_)
                ml_exit_prob = probs[classes.index(1)] if 1 in classes else 0.0

                if ml_exit_prob >= 0.75 and pnl_pct < -15:
                    self.ml_exit_count += 1
                    return True, ExitReason.STOP_LOSS
            except Exception:
                pass

        return False, None
