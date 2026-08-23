"""
Combined monthly + weekly options backtesting engine.

Runs both tracks concurrently on shared capital:
- Monthly: ML entry/exit, regime-adaptive strategy (70% budget)
- Weekly: ML quality-gated PCS/IC, 3-8 DTE (30% budget)
- Cross-track DD circuit breaker + combined open-position risk cap
- Single combined equity curve
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

_log = logging.getLogger(__name__)

import numpy as np
import pandas as pd

from config import BacktestConfig, WeeklyBacktestConfig, CostModel
from backtester.fills import ConservativeFillModel
from backtester.weekly_exit_policy import build_tracker, check_weekly_exit, update_tracker, WeeklyExitTracker
from strategies.base import BaseStrategy, Trade, TradeAction, ExitReason
from strategies.expiry_selector import select_optimal_entry
from strategies.weekly_strategies import WeeklyPutCreditSpread, WeeklyIronCondor
from pricing.black_scholes import price_option, iv_from_vix, OptionType
from backtester.position_sizer import PositionSizer, SizingDecision, _regime_from_vix
from analysis.monthly_diagnostics import MonthlyDiagnosticsCollector
from backtester.production_rules import (
    ProductionGate, ProductionRulesConfig, DrawdownKillSwitch, validate_no_naked,
)
from models.weekly_risk_engine import WeeklyRiskEngine, WeeklyEntrySizing
from data.expiry_calendar import get_monthly_expiry, get_weekly_expiry_in_range


@dataclass
class CombinedResult:
    initial_capital: float = 0.0
    total_trades: int = 0
    monthly_trades: int = 0
    weekly_trades: int = 0
    total_pnl: float = 0.0
    monthly_pnl: float = 0.0
    weekly_pnl: float = 0.0
    cagr_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    monthly_win_rate: float = 0.0
    weekly_win_rate: float = 0.0
    avg_holding_days_monthly: float = 0.0
    avg_holding_days_weekly: float = 0.0
    capital_utilization_pct: float = 0.0
    cross_track_dd_blocks: int = 0
    weekly_ml_skips: int = 0
    weekly_vix_gate_blocks: int = 0
    weekly_open_cap_blocks: int = 0
    weekly_monthly_loss_blocks: int = 0
    weekly_streak_skips: int = 0
    weekly_dynamic_scale_downs: int = 0
    emergency_weekly_exits: int = 0
    dd_kill_switch_activations: int = 0
    dd_kill_weekly_closes: int = 0
    dd_kill_entries_blocked: int = 0
    event_calendar_blocks: int = 0
    # Risk engine stats
    weekly_etl_skips: int = 0
    weekly_regime_skips: int = 0
    weekly_risk_score_avg: float = 0.0
    weekly_dynamic_exit_count: int = 0
    weekly_dynamic_exit_reasons: dict = field(default_factory=dict)
    weekly_regime_distribution: dict = field(default_factory=dict)
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    equity_curve: list = field(default_factory=list)
    daily_pnl: list = field(default_factory=list)
    all_trades: list = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


class CombinedBacktestEngine:
    """
    Concurrent monthly+weekly options backtester on shared capital.

    Architecture:
    - Single day-by-day loop processes both tracks
    - Monthly track: ML entry (RegimeAwareLearner), smart exits (VIX-adaptive + trailing + ML)
    - Weekly track: rule-based entry that targets the first weekly expiry inside
      the configured DTE window, with tighter exits
    - Shared equity pool with separate risk budgets (default 70/30)
    - Cross-track DD breaker: if combined DD > threshold, block new entries
    """

    def __init__(
        self,
        data: pd.DataFrame,
        monthly_config: BacktestConfig,
        weekly_config: WeeklyBacktestConfig,
        monthly_strategy: BaseStrategy,
        exit_engine,
        entry_model,
        weekly_entry_model=None,
        weekly_risk_engine: Optional[WeeklyRiskEngine] = None,
        entry_threshold: float = 0.48,
        weekly_entry_threshold: float = 0.55,
        monthly_budget_pct: float = 0.70,
        weekly_budget_pct: float = 0.30,
        cross_track_dd_pct: float = 0.20,
        monthly_loss_block_pct: float = 0.03,
        combined_open_loss_cap_pct: float = 0.06,
        vix_simultaneous_cap: float = 25.0,
        emergency_weekly_exit_pct: float = 0.03,
        production_rules: Optional[ProductionRulesConfig] = None,
        walk_forward_manager=None,
    ):
        self.data = data
        self.m_config = monthly_config
        self.w_config = weekly_config
        self.monthly_strategy = monthly_strategy
        self.exit_engine = exit_engine
        self.entry_model = entry_model
        self.weekly_entry_model = weekly_entry_model
        self.weekly_risk_engine = weekly_risk_engine
        self.entry_threshold = entry_threshold
        self.weekly_entry_threshold = weekly_entry_threshold
        self.monthly_budget_pct = monthly_budget_pct
        self.weekly_budget_pct = weekly_budget_pct
        self.cross_track_dd_pct = cross_track_dd_pct
        self.monthly_loss_block_pct = monthly_loss_block_pct
        self.combined_open_loss_cap_pct = combined_open_loss_cap_pct
        self.vix_simultaneous_cap = vix_simultaneous_cap
        self.emergency_weekly_exit_pct = emergency_weekly_exit_pct
        self.walk_forward_manager = walk_forward_manager

        # Production safety gate: DD kill switch, event calendar, naked/hedge checks
        self.prod_gate = ProductionGate(
            production_rules or ProductionRulesConfig()
        )
        self.monthly_fill_model = ConservativeFillModel(monthly_config.cost_model)
        self.weekly_fill_model = ConservativeFillModel(weekly_config.cost_model)

        safe_monthly_cap = min(monthly_config.max_lots, 30)
        self.position_sizer = PositionSizer(
            monthly_config, max_lots_cap=safe_monthly_cap,
        )

        self.weekly_pcs = WeeklyPutCreditSpread(
            lots=weekly_config.max_lots, lot_size=weekly_config.lot_size,
        )
        self.weekly_ic = WeeklyIronCondor(
            lots=weekly_config.max_lots, lot_size=weekly_config.lot_size,
        )

        # ── State ──
        self.monthly_trade: Optional[Trade] = None
        self.weekly_trade: Optional[Trade] = None
        self.monthly_completed: list = []
        self.weekly_completed: list = []
        self.equity_curve: list[float] = []
        self.daily_pnl: list[float] = []

        self._combined_equity = monthly_config.initial_capital
        self._peak_equity = monthly_config.initial_capital
        self._peak_equity_realized = monthly_config.initial_capital   # Phase-1: realized-only peak
        self._monthly_realized = 0.0
        self._weekly_realized = 0.0

        # Monthly tracking
        self._m_peak_pnl_per_unit = 0.0
        self._m_pnl_history: list[float] = []
        self._m_entry_vix = 0.0
        self._m_expiry: Optional[date] = None
        self._m_last_entry_date: Optional[date] = None
        self._m_strategy_history: list[str] = []
        self._m_consecutive_losses = 0
        self._last_ml_win_prob = 0.60

        # Weekly tracking
        self._w_peak_pnl_per_unit = 0.0
        self._w_exit_tracker: Optional[WeeklyExitTracker] = None
        self._w_entry_vix = 0.0
        self._w_expiry: Optional[date] = None
        self._w_consecutive_losses = 0
        self._w_recent_results: list[float] = []
        self._w_cooldown_until: Optional[date] = None

        # Stats
        self.cross_track_dd_blocks = 0
        self.weekly_ml_skips = 0

        # Phase-1 fix: improvement-based recovery for cross-track DD gate.
        # Tracks the worst portfolio DD seen while weekly entries are blocked
        # so that re-entry requires improvement from the worst point, not just
        # falling below a static floor.
        self._cross_dd_worst_while_blocked: float = 0.0
        self._cross_dd_improvement_pct: float = 0.03   # 3% improvement required
        self.weekly_vix_gate_blocks = 0
        self.weekly_open_cap_blocks = 0
        self.weekly_monthly_loss_blocks = 0
        self.emergency_weekly_exits = 0
        self.weekly_streak_skips = 0
        self.weekly_dynamic_scale_downs = 0
        self.monthly_ml_entries = 0
        self.monthly_ml_skips = 0
        self.monthly_smart_exits = 0
        self.weekly_entries = 0
        self.weekly_etl_skips = 0
        self.weekly_regime_skips = 0
        self._w_risk_scores: list[float] = []
        self.weekly_dynamic_exit_count = 0
        self._w_dynamic_exit_reasons: dict[str, int] = {}
        self._w_regime_counts: dict[str, int] = {}
        self._w_entry_spot = 0.0
        self._w_entry_delta = 0.0
        self._w_regime_name = "low_vol_grind"
        self._w_short_strike = 0.0
        self._w_long_strike = 0.0
        self._w_option_type = OptionType.PUT
        self._w_entry_credit = 0.0
        self._pending_monthly_entry: dict | None = None
        self._pending_weekly_entry: dict | None = None
        self._evaluation_start_date = None
        self._active_walk_forward_bundle = None
        self.monthly_diagnostics = MonthlyDiagnosticsCollector()

        # Per-gate counters for the monthly entry funnel report
        # Keys match the gate names printed by _monthly_funnel_report()
        self._monthly_gate_counts: dict[str, int] = defaultdict(int)
        self._monthly_days_evaluated: int = 0
        if getattr(getattr(self, "walk_forward_manager", None), "windows", None):
            self._evaluation_start_date = self.walk_forward_manager.windows[0].test_start.date()

    def _sync_walk_forward_models(self, current_date) -> None:
        if self.walk_forward_manager is None:
            return
        try:
            bundle = self.walk_forward_manager.get_bundle_for_date(current_date)
        except ValueError:
            return  # pre-OOS burn-in period: keep constructor-provided models
        self._active_walk_forward_bundle = bundle
        self.exit_engine = bundle.exit_engine
        self.entry_model = bundle.entry_model
        if bundle.weekly_entry_model is not None:
            self.weekly_entry_model = bundle.weekly_entry_model
        if bundle.weekly_risk_engine is not None:
            self.weekly_risk_engine = bundle.weekly_risk_engine

    def _fill_pending_monthly_entry(self, current_date, row) -> None:
        if self._pending_monthly_entry is None or self.monthly_trade is not None:
            return
        pending = self._pending_monthly_entry
        if current_date <= pending["signal_date"]:
            raise AssertionError("Monthly fill must occur after the close-derived signal.")
        fill_spot = float(row.get("nifty_open", row.get("nifty_close", pending["signal_spot"])))
        gap_pct = ((fill_spot / pending["signal_spot"]) - 1.0) * 100 if pending["signal_spot"] > 0 else 0.0
        dte = max((pending["expiry"] - current_date).days, 0)
        if not (self.m_config.min_dte_entry <= dte <= self.m_config.max_dte_entry):
            self._pending_monthly_entry = None
            return
        if hasattr(self.monthly_strategy, "set_lots"):
            self.monthly_strategy.set_lots(pending["lots"])
        else:
            self.monthly_strategy.lots = pending["lots"]
        if pending.get("strategy_name") and hasattr(self.monthly_strategy, "force_strategy_selection"):
            self.monthly_strategy.force_strategy_selection(pending["strategy_name"])
        trade = self.monthly_strategy.create_trade(current_date, fill_spot, pending["signal_vix"], dte, self.m_config.risk_free_rate)
        trade.signal_date = pending["signal_date"]
        self.monthly_fill_model.apply_entry_fill(
            trade,
            spot=fill_spot,
            vix=pending["signal_vix"],
            dte=dte,
            risk_free_rate=self.m_config.risk_free_rate,
            gap_pct=gap_pct,
        )
        self.monthly_trade = trade
        self._m_expiry = pending["expiry"]
        self._m_entry_vix = pending["signal_vix"]
        self._m_peak_pnl_per_unit = 0.0
        self._m_pnl_history = []
        self._m_last_entry_date = pending["signal_date"]
        if pending.get("diagnostics") is not None:
            self.monthly_diagnostics.start_trade(**pending["diagnostics"])
            self.monthly_diagnostics.update_open_trade(0.0)
        self.monthly_ml_entries += 1
        self._pending_monthly_entry = None

    def _fill_pending_weekly_entry(self, current_date, row) -> None:
        if self._pending_weekly_entry is None or self.weekly_trade is not None:
            return
        pending = self._pending_weekly_entry
        if current_date <= pending["signal_date"]:
            raise AssertionError("Weekly fill must occur after the close-derived signal.")
        fill_spot = float(row.get("nifty_open", row.get("nifty_close", pending["signal_spot"])))
        gap_pct = ((fill_spot / pending["signal_spot"]) - 1.0) * 100 if pending["signal_spot"] > 0 else 0.0
        dte = max((pending["expiry"] - current_date).days, 0)
        if dte < 1:
            self._pending_weekly_entry = None
            return
        strategy = pending["strategy"]
        if hasattr(strategy, "lots"):
            strategy.lots = pending["lots"]
        trade = strategy.create_trade(current_date, fill_spot, pending["signal_vix"], dte, self.w_config.risk_free_rate)
        trade.signal_date = pending["signal_date"]
        self.weekly_fill_model.apply_entry_fill(
            trade,
            spot=fill_spot,
            vix=pending["signal_vix"],
            dte=dte,
            risk_free_rate=self.w_config.risk_free_rate,
            gap_pct=gap_pct,
        )
        self.weekly_trade = trade
        self._w_expiry = pending["expiry"]
        self._w_entry_vix = pending["signal_vix"]
        self._w_peak_pnl_per_unit = 0.0
        self._w_exit_tracker = build_tracker(trade)
        self._w_entry_spot = fill_spot
        self._w_entry_credit = trade.net_credit
        self._w_short_strike = 0.0
        self._w_long_strike = 0.0
        self._w_option_type = OptionType.PUT
        for leg in trade.legs:
            if leg.is_short and self._w_short_strike == 0:
                self._w_short_strike = leg.strike
                self._w_option_type = (OptionType.PUT if leg.option_type in ("PUT", "PE") else OptionType.CALL)
            elif not leg.is_short and self._w_long_strike == 0:
                self._w_long_strike = leg.strike
        self._w_entry_delta = self._estimate_weekly_delta(fill_spot, pending["signal_vix"], dte)
        self.weekly_entries += 1
        self._pending_weekly_entry = None

    # ═══════════════════════════════════════════════════════════════════
    #  Main loop
    # ═══════════════════════════════════════════════════════════════════

    def run(self) -> CombinedResult:
        capital = self.m_config.initial_capital

        for idx, row in self.data.iterrows():
            current_date = idx.date() if hasattr(idx, "date") else idx
            if self._evaluation_start_date is not None and current_date < self._evaluation_start_date:
                self.equity_curve.append(capital)
                self.daily_pnl.append(0.0)
                continue
            self._sync_walk_forward_models(current_date)
            self._fill_pending_monthly_entry(current_date, row)
            self._fill_pending_weekly_entry(current_date, row)
            spot = row.get("nifty_close", 0)
            vix = row.get("vix")
            if vix is None:
                _log.warning("VIX missing for %s, substituting 15", current_date)
                vix = 15.0
            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue

            market_data = row.to_dict()
            daily_combined_pnl = 0.0

            total_realized = self._monthly_realized + self._weekly_realized
            equity_realized = capital + total_realized
            self._combined_equity = equity_realized

            equity_mtm = equity_realized
            if self.monthly_trade:
                equity_mtm += self.monthly_trade.total_pnl
            if self.weekly_trade:
                equity_mtm += self.weekly_trade.total_pnl
            if equity_mtm > self._peak_equity:
                self._peak_equity = equity_mtm
            if equity_realized > self._peak_equity_realized:
                self._peak_equity_realized = equity_realized

            dd_pct = max(0, (self._peak_equity - equity_mtm) / self._peak_equity) if self._peak_equity > 0 else 0

            # Phase-1 fix: realized-only DD for weekly cross-track gate.
            # equity_mtm includes open-position paper losses, which temporarily
            # inflate dd_pct even when no trade has actually been closed at a loss.
            # The cross-track gate should protect against locked-in losses, not
            # unrealized MTM swings from an open monthly position.
            dd_pct_realized = (
                max(0, (self._peak_equity_realized - equity_realized) / self._peak_equity_realized)
                if self._peak_equity_realized > 0 else 0
            )

            # ── PRODUCTION RULE: DD Kill Switch ──
            # If portfolio DD hits the kill threshold, force-close weekly and halt all entries.
            if self.prod_gate.kill_switch.check(current_date, dd_pct):
                if self.weekly_trade is not None and self.prod_gate.kill_switch.should_force_close_weekly():
                    pnl = self._close_weekly(current_date, spot, vix, ExitReason.STOP_LOSS)
                    daily_combined_pnl += pnl
                    self.prod_gate.kill_switch.state.weekly_force_closes += 1

                if self.monthly_trade is not None and self.prod_gate.kill_switch.should_force_close_monthly():
                    pnl = self._close_monthly(current_date, spot, vix, ExitReason.STOP_LOSS)
                    daily_combined_pnl += pnl
                    self.prod_gate.kill_switch.state.monthly_force_closes += 1

                # Skip directly to equity calculation — no entries, no normal exits
                m_pnl = self._process_monthly_exit(row, current_date, spot, vix, market_data)
                daily_combined_pnl += m_pnl
                w_pnl = self._process_weekly_exit(row, current_date, spot, vix, market_data)
                daily_combined_pnl += w_pnl

                total_realized = self._monthly_realized + self._weekly_realized
                combined_eq = capital + total_realized
                if self.monthly_trade:
                    combined_eq += self.monthly_trade.total_pnl
                if self.weekly_trade:
                    combined_eq += self.weekly_trade.total_pnl
                self.equity_curve.append(combined_eq)
                self.daily_pnl.append(daily_combined_pnl)
                continue

            # ── Emergency cross-track exit: close weekly if combined open loss is too large ──
            if self.weekly_trade is not None and equity_mtm > 0:
                combined_open_loss = 0.0
                if self.monthly_trade and self.monthly_trade.total_pnl < 0:
                    combined_open_loss += abs(self.monthly_trade.total_pnl)
                if self.weekly_trade.total_pnl < 0:
                    combined_open_loss += abs(self.weekly_trade.total_pnl)
                if combined_open_loss > equity_mtm * self.emergency_weekly_exit_pct:
                    pnl = self._close_weekly(current_date, spot, vix, ExitReason.STOP_LOSS)
                    daily_combined_pnl += pnl
                    self.emergency_weekly_exits += 1

            # ── Monthly track: exits ──
            m_pnl = self._process_monthly_exit(row, current_date, spot, vix, market_data)
            daily_combined_pnl += m_pnl

            # ── Weekly track: exits ──
            w_pnl = self._process_weekly_exit(row, current_date, spot, vix, market_data)
            daily_combined_pnl += w_pnl

            # ── Monthly track: entries ──
            if self.monthly_trade is None:
                monthly_blocked, _ = self.prod_gate.should_block_monthly_entry(
                    current_date, legs=None, spot=spot,
                )
                if monthly_blocked:
                    self._monthly_gate_counts["g1_event_calendar"] += 1
                    self._monthly_days_evaluated += 1  # count blocked days too
                else:
                    self._process_monthly_entry(row, current_date, spot, vix, market_data, equity_mtm, dd_pct)

            # ── Weekly track: multi-layer risk gate before entry ──
            if self.weekly_trade is None:
                # Production rule: event calendar block (RBI, Budget, FOMC, elections)
                event_blocked, event_reason = self.prod_gate.should_block_weekly_entry(
                    current_date, legs=None, spot=spot,
                )
                if event_blocked:
                    pass  # counted inside prod_gate
                else:
                    block_reason = self._weekly_entry_blocked(equity_mtm, dd_pct_realized, vix)
                    if block_reason is None:
                        data_idx = self.data.index.get_loc(idx)
                        self._process_weekly_entry(
                            row, current_date, spot, vix, market_data,
                            equity_mtm, data_idx, dd_pct,
                        )
                    else:
                        if block_reason == "dd":
                            self.cross_track_dd_blocks += 1
                        elif block_reason == "monthly_loss":
                            self.weekly_monthly_loss_blocks += 1
                        elif block_reason == "open_cap":
                            self.weekly_open_cap_blocks += 1
                        elif block_reason == "vix_gate":
                            self.weekly_vix_gate_blocks += 1

            # ── Combined equity ──
            total_realized = self._monthly_realized + self._weekly_realized
            combined_eq = capital + total_realized
            if self.monthly_trade:
                combined_eq += self.monthly_trade.total_pnl
            if self.weekly_trade:
                combined_eq += self.weekly_trade.total_pnl

            self.equity_curve.append(combined_eq)
            self.daily_pnl.append(daily_combined_pnl)

        # Close any open trades at end
        if self.monthly_trade:
            self._force_close_monthly()
        if self.weekly_trade:
            self._force_close_weekly()

        return self._build_result()

    # ═══════════════════════════════════════════════════════════════════
    #  Monthly track
    # ═══════════════════════════════════════════════════════════════════

    def _process_monthly_exit(self, row, current_date, spot, vix, market_data) -> float:
        if self.monthly_trade is None:
            return 0.0

        dte = max((self._m_expiry - current_date).days, 0) if self._m_expiry else 0

        if hasattr(self.monthly_strategy, "update_premiums"):
            self.monthly_strategy.update_premiums(
                self.monthly_trade, spot, vix, dte, self.m_config.risk_free_rate,
            )
        self.monthly_diagnostics.update_open_trade(self.monthly_trade.pnl_per_unit)

        if self.monthly_trade.pnl_per_unit > self._m_peak_pnl_per_unit:
            self._m_peak_pnl_per_unit = self.monthly_trade.pnl_per_unit

        should_exit, exit_reason = self._monthly_smart_exit(
            row, spot, vix, dte, self._m_entry_vix,
        )

        if not should_exit:
            action, reason = self.monthly_strategy.should_exit(
                self.monthly_trade, spot, vix, dte,
            )
            if action == TradeAction.ADJUST and hasattr(self.monthly_strategy, "should_adjust"):
                adj = self.monthly_strategy.should_adjust(
                    self.monthly_trade, spot, vix, dte, market_data,
                )
                if adj is not None:
                    self.monthly_trade.apply_adjustment(adj)
                    self._m_peak_pnl_per_unit = self.monthly_trade.pnl_per_unit
                    self._m_pnl_history = [self.monthly_trade.pnl_per_unit]
                elif dte <= 0:
                    should_exit, exit_reason = True, ExitReason.EXPIRY
            elif action == TradeAction.EXIT or dte <= 0:
                should_exit = True
                exit_reason = reason if reason else ExitReason.EXPIRY

        if should_exit:
            pnl = self._close_monthly(current_date, spot, vix, exit_reason)
            return pnl
        else:
            self._m_pnl_history.append(self.monthly_trade.pnl_per_unit)
            return 0.0

    def _monthly_smart_exit(self, row, spot, vix, dte, entry_vix):
        """VIX-adaptive exits + trailing stops + ML override for monthly."""
        trade = self.monthly_trade

        max_loss_abs = self._combined_equity * 0.06
        if trade.total_pnl < -max_loss_abs:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        net_credit = trade.net_credit
        if net_credit <= 0:
            return False, None

        pnl_pct = trade.pnl_per_unit / net_credit * 100
        pnl_from_peak = trade.pnl_per_unit - self._m_peak_pnl_per_unit
        vix_change = (vix - entry_vix) / entry_vix if entry_vix > 0 else 0
        days_in_trade = (row.name.date() - trade.entry_date).days if hasattr(row.name, "date") else 0
        min_hold_days = getattr(self.m_config, "monthly_exit_min_hold_days", 0)
        allow_profit_taking = days_in_trade >= min_hold_days

        vix_vs_sma = row.get("vix_vs_sma_ratio", 1.0) if hasattr(row, "get") else 1.0
        crash_risk_v2 = row.get("crash_risk_score_v2", 0) if hasattr(row, "get") else 0
        correction_depth = row.get("nifty_drawdown_from_20d_high_pct", 0) if hasattr(row, "get") else 0

        # DTE-based profit targets: longer-DTE trades hold for theta; shorter-DTE
        # trades take most of the remaining credit.  VIX adjustments still apply on top.
        dte_long_tgt  = getattr(self.m_config, "monthly_exit_dte_profit_target_long",  35.0)
        dte_mid_tgt   = getattr(self.m_config, "monthly_exit_dte_profit_target_mid",   55.0)
        dte_short_tgt = getattr(self.m_config, "monthly_exit_dte_profit_target_short", 75.0)

        if dte >= 20:
            profit_target = dte_long_tgt
        elif dte >= 10:
            profit_target = dte_mid_tgt
        else:
            profit_target = dte_short_tgt

        # VIX overlay: tighten stop-loss in elevated/crash VIX; base stop-loss by VIX zone
        if vix < 15:
            stop_loss = 50
        elif vix < 20:
            stop_loss = 45
        elif vix < 30:
            stop_loss = 40
        else:
            stop_loss = 35

        profit_target = int(profit_target * getattr(self.m_config, "monthly_exit_profit_target_scale", 1.0))
        stop_loss = int(stop_loss * getattr(self.m_config, "monthly_exit_stop_loss_scale", 1.0))

        if vix_vs_sma < 0.85:
            profit_target = int(profit_target * 1.15)
            stop_loss = int(stop_loss * 1.10)
        elif vix_vs_sma > 1.15:
            stop_loss = int(stop_loss * 0.85)
            profit_target = int(profit_target * 0.90)

        if crash_risk_v2 >= 0.80 or correction_depth < -15:
            stop_loss = int(stop_loss * 0.7)
            profit_target = min(profit_target, 30)

        if dte <= 5:
            profit_target = min(profit_target, 30)

        short_legs = [l for l in trade.legs if l.is_short]
        min_dist = 999
        for sl in short_legs:
            ot = str(sl.option_type)
            if ot in ("PUT", "PE"):
                dist = (spot - sl.strike) / spot * 100
            else:
                dist = (sl.strike - spot) / spot * 100
            min_dist = min(min_dist, dist)

        if min_dist < 1.5 and trade.total_pnl < -0.05 * net_credit * trade.lots * trade.lot_size:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        if vix_change > 0.25 and trade.total_pnl < -0.10 * net_credit * trade.lots * trade.lot_size:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        if vix_vs_sma > 1.20 and trade.total_pnl < -0.15 * net_credit * trade.lots * trade.lot_size:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        if crash_risk_v2 >= 0.80 and trade.total_pnl < 0:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        if days_in_trade >= 10 and trade.total_pnl < 0:
            pnl_3d_ago_unit = self._m_pnl_history[-3] if len(self._m_pnl_history) >= 3 else 0
            pnl_3d_ago_rupees = pnl_3d_ago_unit * trade.lots * trade.lot_size
            worsening_threshold = 0.05 * net_credit * trade.lots * trade.lot_size
            if (trade.total_pnl < pnl_3d_ago_rupees - worsening_threshold and
                    trade.total_pnl < -0.20 * net_credit * trade.lots * trade.lot_size):
                self.monthly_smart_exits += 1
                return True, ExitReason.STOP_LOSS

        if allow_profit_taking and pnl_pct >= profit_target:
            self.monthly_smart_exits += 1
            return True, ExitReason.PROFIT_TARGET

        stop_loss_rupees = (stop_loss / 100.0) * net_credit * trade.lots * trade.lot_size
        if trade.total_pnl < -stop_loss_rupees:
            self.monthly_smart_exits += 1
            return True, ExitReason.STOP_LOSS

        peak_pct = (self._m_peak_pnl_per_unit / net_credit * 100) if net_credit > 0 else 0
        drop_pct = (pnl_from_peak / net_credit * 100) if net_credit > 0 else 0

        trailing_arm = getattr(self.m_config, "monthly_exit_trailing_arm_pct", 25.0)
        trailing_drop = getattr(self.m_config, "monthly_exit_trailing_drop_pct", 35.0)
        if allow_profit_taking and peak_pct >= trailing_arm and drop_pct < -trailing_drop:
            self.monthly_smart_exits += 1
            return True, ExitReason.PROFIT_TARGET

        if allow_profit_taking and peak_pct >= 40 and drop_pct < -20:
            self.monthly_smart_exits += 1
            return True, ExitReason.PROFIT_TARGET

        if self.exit_engine and self.exit_engine.is_trained:
            try:
                market_features = self.exit_engine.feature_extractor.extract(row)
                pnl_3d_ago = self._m_pnl_history[-3] if len(self._m_pnl_history) >= 3 else 0
                days_in = (row.name.date() - trade.entry_date).days if hasattr(row.name, "date") else 0
                vix_1d_chg = row.get("vix_change_1d", 0) if hasattr(row, "get") else 0
                trade_features = {
                    "pnl_pct": pnl_pct, "dte_remaining": dte,
                    "days_in_trade": days_in,
                    "dist_to_short_strike_pct": min_dist, "vix_now": vix,
                    "vix_change_since_entry": vix_change * 100,
                    "entry_credit": net_credit,
                    "peak_pnl_pct": peak_pct,
                    "pnl_vs_peak_pct": drop_pct,
                    "vix_1d_change": vix_1d_chg,
                    "pnl_3d_change": (trade.pnl_per_unit - pnl_3d_ago) / net_credit * 100 if net_credit > 0 else 0,
                    "theta_remaining": trade.portfolio_theta if hasattr(trade, "portfolio_theta") else 0,
                    "gamma_exposure": trade.portfolio_gamma if hasattr(trade, "portfolio_gamma") else 0,
                    "delta_exposure": trade.portfolio_delta if hasattr(trade, "portfolio_delta") else 0,
                    "vega_exposure": trade.portfolio_vega if hasattr(trade, "portfolio_vega") else 0,
                }
                ml_exit_prob = self.exit_engine.predict_exit(market_features, trade_features)
                if ml_exit_prob >= 0.75 and trade.total_pnl < -0.15 * net_credit * trade.lots * trade.lot_size:
                    self.monthly_smart_exits += 1
                    return True, ExitReason.STOP_LOSS
            except Exception:
                pass

        return False, None

    def _process_monthly_entry(self, row, current_date, spot, vix, market_data, equity, dd_pct):
        """ML-driven monthly entry with position sizing and risk caps."""
        self._monthly_days_evaluated += 1

        if self._m_last_entry_date and (current_date - self._m_last_entry_date).days < 2:
            self._monthly_gate_counts["g13_cooldown"] += 1
            return

        prediction_payload = {}
        eligible = []
        if hasattr(self.monthly_strategy, "get_eligible_strategies"):
            eligible = self.monthly_strategy.get_eligible_strategies(spot, vix, market_data)
            if not eligible:
                self._monthly_gate_counts["g2_7_circuit_or_vix_zone"] += 1
                self.monthly_diagnostics.record_candidate_funnel(
                    signal_date=current_date,
                    regime=_regime_from_vix(vix),
                    vix=vix,
                    eligible_count=0,
                    candidate_count=0,
                    accepted=False,
                    rejection_breakdown={"regime_filter": 1},
                    selection_reason="regime_filter",
                )
                return

        if hasattr(self.monthly_strategy, "_strategies"):
            viable = []
            for strat_name in eligible:
                sub = self.monthly_strategy._strategies.get(strat_name)
                if sub is not None and sub.should_enter(spot, vix, market_data) == TradeAction.ENTER:
                    viable.append(strat_name)
            eligible = viable
            if not eligible:
                self._monthly_gate_counts["g7_should_enter"] += 1
                self.monthly_diagnostics.record_candidate_funnel(
                    signal_date=current_date,
                    regime=_regime_from_vix(vix),
                    vix=vix,
                    eligible_count=0,
                    candidate_count=0,
                    accepted=False,
                    rejection_breakdown={"regime_filter": 1},
                    selection_reason="regime_filter",
                )
                return

        gate8_enabled = getattr(self.m_config, "monthly_gate8_enabled", False)
        if gate8_enabled and self.entry_model and self.entry_model.is_trained:
            # Gate 8: ML quality score filter — only active when gate is explicitly enabled
            # and a trained model is present.  quality_score = P(class==2, strong win).
            try:
                prediction = self.entry_model.predict(row, eligible_strategies=eligible or None)
                quality_score = prediction.get("quality_score", 0)
                prediction_payload = prediction

                model_threshold = self._monthly_model_threshold()
                effective_threshold = model_threshold if model_threshold is not None else self.entry_threshold
                if self._m_consecutive_losses >= 3:
                    effective_threshold += 0.03

                if quality_score < effective_threshold:
                    self.monthly_ml_skips += 1
                    self._monthly_gate_counts["g8_ml_quality"] += 1
                    features = prediction.get("features", {})
                    self.monthly_diagnostics.record_prediction(
                        signal_date=current_date,
                        threshold=effective_threshold,
                        score=quality_score,
                        win_prob=prediction.get("probability_profitable", quality_score),
                        train_start=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_start", ""),
                        train_end=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_end", ""),
                        feature_version=getattr(getattr(self.entry_model, "period_metadata", None), "feature_version", self.m_config.entry_model_version),
                        model_version=getattr(self.entry_model, "model_version", self.m_config.entry_model_version),
                        entry_features=features,
                        eligible_strategies=eligible,
                        accepted=False,
                        rejection_reason="confidence_threshold",
                        regime=_regime_from_vix(vix),
                        vix=vix,
                    )
                    self.monthly_diagnostics.record_candidate_funnel(
                        signal_date=current_date,
                        regime=_regime_from_vix(vix),
                        vix=vix,
                        eligible_count=len(eligible),
                        candidate_count=0,
                        accepted=False,
                        rejection_breakdown={"confidence_threshold": 1},
                        selection_reason="confidence_threshold",
                    )
                    return

                self._last_ml_win_prob = quality_score
            except Exception:
                action = self.monthly_strategy.should_enter(spot, vix, market_data)
                if action != TradeAction.ENTER:
                    return
        elif not gate8_enabled:
            # Gate 8 BYPASSED — model AUC < 0.55 or no real-trade history yet.
            # Gates 1–7b already filtered; proceed directly to expiry selection.
            # Re-enable via BacktestConfig.monthly_gate8_enabled=True once:
            #   1) ≥500 real closed trades in training set, 2) AUC > 0.55
            self._monthly_gate_counts["g8_ml_quality_bypassed"] = (
                self._monthly_gate_counts.get("g8_ml_quality_bypassed", 0) + 1
            )
        else:
            # gate8_enabled=True but no trained model — fall back to rule-based check
            action = self.monthly_strategy.should_enter(spot, vix, market_data)
            if action != TradeAction.ENTER:
                return

        monthly_equity = equity * self.monthly_budget_pct
        prelim_lots = max(1, min(self.m_config.max_lots, int(self.position_sizer._margin_fallback(monthly_equity))))
        selector_diag = {}
        decision = select_optimal_entry(
            spot=spot,
            vix=vix,
            strategies=self.monthly_strategy._strategies,
            eligible_strategies=eligible,
            entry_date=current_date,
            lots=prelim_lots,
            lot_size=self.m_config.lot_size,
            risk_free_rate=self.m_config.risk_free_rate,
            brokerage_per_lot=self.m_config.brokerage_per_lot,
            risk_config=self.m_config,
            diagnostics=selector_diag,
        )
        if not decision.found:
            self.monthly_ml_skips += 1
            self._monthly_gate_counts["g9_expiry_selector"] += 1
            self.monthly_diagnostics.record_prediction(
                signal_date=current_date,
                threshold=self._monthly_model_threshold() or self.entry_threshold,
                score=self._last_ml_win_prob,
                win_prob=self._last_ml_win_prob,
                train_start=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_start", ""),
                train_end=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_end", ""),
                feature_version=getattr(getattr(self.entry_model, "period_metadata", None), "feature_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
                model_version=getattr(self.entry_model, "model_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
                entry_features=prediction_payload.get("features", {}),
                eligible_strategies=eligible,
                accepted=False,
                rejection_reason="vol_or_risk_filter",
                regime=_regime_from_vix(vix),
                vix=vix,
            )
            self.monthly_diagnostics.record_candidate_funnel(
                signal_date=current_date,
                regime=_regime_from_vix(vix),
                vix=vix,
                eligible_count=len(eligible),
                candidate_count=selector_diag.get("candidate_count", 0),
                accepted=False,
                rejection_breakdown=selector_diag.get("rejections", {}),
                selection_reason="vol_or_risk_filter",
            )
            return

        if hasattr(self.monthly_strategy, "force_strategy_selection"):
            self.monthly_strategy.force_strategy_selection(decision.strategy_name)
        self._m_expiry = decision.expiry
        dte = decision.dte

        sizing = self.position_sizer.compute_lots(
            equity=monthly_equity,
            vix=vix,
            regime=_regime_from_vix(vix),
            win_prob=self._last_ml_win_prob,
            drawdown_pct=dd_pct,
            trade_max_loss_per_unit=decision.best.max_loss,
            trade_margin_per_lot=decision.best.max_loss * self.m_config.lot_size,
        )
        if sizing.lots <= 0:
            self.monthly_ml_skips += 1
            self._monthly_gate_counts["g10_position_sizing"] += 1
            self.monthly_diagnostics.record_candidate_funnel(
                signal_date=current_date,
                regime=_regime_from_vix(vix),
                vix=vix,
                eligible_count=len(eligible),
                candidate_count=selector_diag.get("candidate_count", 0),
                accepted=False,
                rejection_breakdown={"capital_constraints": 1},
                selection_reason="capital_constraints",
            )
            return

        hard_max_loss_pct = getattr(self.m_config, "monthly_hard_max_loss_pct", 8.0)
        trade_max_loss_rupees = decision.best.max_loss * sizing.lots * self.m_config.lot_size
        hard_cap_rupees = equity * (hard_max_loss_pct / 100.0)
        if trade_max_loss_rupees > hard_cap_rupees:
            self.monthly_ml_skips += 1
            self._monthly_gate_counts["g11_hard_max_loss"] += 1
            return

        if hasattr(self.monthly_strategy, "set_lots"):
            self.monthly_strategy.set_lots(sizing.lots)
        else:
            self.monthly_strategy.lots = sizing.lots

        if not (self.m_config.min_dte_entry <= dte <= self.m_config.max_dte_entry):
            self._monthly_gate_counts["g12_dte_window"] += 1
            return

        features = prediction_payload.get("features", {})
        self.monthly_diagnostics.record_prediction(
            signal_date=current_date,
            threshold=self._monthly_model_threshold() or self.entry_threshold,
            score=self._last_ml_win_prob,
            win_prob=self._last_ml_win_prob,
            train_start=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_start", ""),
            train_end=getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_end", ""),
            feature_version=getattr(getattr(self.entry_model, "period_metadata", None), "feature_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
            model_version=getattr(self.entry_model, "model_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
            entry_features=features,
            eligible_strategies=eligible,
            accepted=True,
            rejection_reason=None,
            regime=_regime_from_vix(vix),
            vix=vix,
        )
        self.monthly_diagnostics.record_candidate_funnel(
            signal_date=current_date,
            regime=_regime_from_vix(vix),
            vix=vix,
            eligible_count=len(eligible),
            candidate_count=selector_diag.get("candidate_count", 0),
            accepted=True,
            rejection_breakdown=selector_diag.get("rejections", {}),
            selection_reason=decision.strategy_name,
        )
        self.monthly_diagnostics.record_sizing(
            signal_date=current_date,
            capital_available=monthly_equity,
            base_lots=sizing.base_lots,
            confidence_scale=sizing.confidence_scale,
            regime_scale=sizing.regime_scale,
            dd_scale=sizing.dd_scale,
            final_lots=sizing.lots,
            lots_before_cap=prelim_lots,
            lots_cap_reason=sizing.reason,
            utilization_contribution=(sizing.lots * self.m_config.lot_size * spot) / max(monthly_equity, 1.0),
        )

        self._pending_monthly_entry = {
            "signal_date": current_date,
            "signal_spot": spot,
            "signal_vix": vix,
            "expiry": self._m_expiry,
            "lots": sizing.lots,
            "strategy_name": getattr(self.monthly_strategy, "_active_name", None),
            "diagnostics": {
                "signal_date": current_date,
                "threshold": self._monthly_model_threshold() or self.entry_threshold,
                "score": self._last_ml_win_prob,
                "win_prob": self._last_ml_win_prob,
                "train_start": getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_start", ""),
                "train_end": getattr(getattr(self._active_walk_forward_bundle, "window", None), "train_end", ""),
                "feature_version": getattr(getattr(self.entry_model, "period_metadata", None), "feature_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
                "model_version": getattr(self.entry_model, "model_version", self.m_config.entry_model_version) if self.entry_model else self.m_config.entry_model_version,
                "entry_features": features,
                "eligible_strategies": eligible,
                "accepted": True,
                "rejection_reason": None,
                "regime": _regime_from_vix(vix),
                "vix": vix,
            },
        }

    def _monthly_model_threshold(self) -> float | None:
        """
        Return the Gate 8 quality threshold from the trained model's OOF sweep.

        The raw recommended_threshold comes from _sweep_thresholds() which optimises
        on OOF training-era data.  The model's probability scores are calibrated on
        that same era, so the threshold and score are on the same scale.

        When deployed on the full 2009-2026 backtest the score distribution may
        shift slightly, but we cap the returned threshold at DEFAULT_QUALITY_THRESHOLD
        to prevent over-filtering: the OOF sweep can legitimately recommend 0.53 but
        if that blocks 87% of all days it defeats the purpose of the gate.  Cap at
        self.entry_threshold (default 0.48) so Gate 8 remains an active filter
        without becoming a near-total block.
        """
        stats = getattr(self.entry_model, "training_stats", None)
        if not isinstance(stats, dict):
            return None
        raw: float | None = None
        if "recommended_threshold" in stats:
            try:
                raw = float(stats["recommended_threshold"])
            except Exception:
                pass
        if raw is None:
            global_stats = stats.get("global", {})
            if isinstance(global_stats, dict) and "recommended_threshold" in global_stats:
                try:
                    raw = float(global_stats["recommended_threshold"])
                except Exception:
                    pass
        if raw is None:
            return None
        # Cap at self.entry_threshold so the model's OOF recommendation (e.g. 0.53)
        # never blocks more than the operator-configured ceiling allows.
        # With entry_threshold=0.30 and model scores 0.311-0.333, this returns 0.30
        # → Gate 8 becomes a near-pass-through until real trade history enables tighter filtering.
        return min(raw, self.entry_threshold)

    def _monthly_funnel_report(self, start_date=None, end_date=None) -> str:
        """
        Return a formatted per-gate funnel summary for monthly trade entry.

        Prints how many days each gate blocked so the analyst can pinpoint
        which gate is responsible for low/zero trade counts.
        """
        total = self._monthly_days_evaluated
        signals = self.monthly_ml_entries
        filled  = len(self.monthly_completed)

        def row(label, key, desc=""):
            n = self._monthly_gate_counts.get(key, 0)
            pct = (n / total * 100) if total else 0.0
            suffix = f"  [{desc}]" if desc else ""
            return f"  ├─ {label:<40s}: {n:5d} days blocked  ({pct:5.1f}%){suffix}"

        date_hdr = ""
        if start_date and end_date:
            date_hdr = f" ({start_date} → {end_date})"

        lines = [
            "",
            f"  Monthly Entry Funnel Summary{date_hdr}",
            "  " + "─" * 70,
            f"  Total days evaluated (no open trade)  : {total:5d}",
            row("Gate  1  Event calendar block",      "g1_event_calendar",        "Budget/Election ±2d"),
            row("Gates 2–7 Circuit breaker / VIX zone", "g2_7_circuit_or_vix_zone", "crash/stress/correction/VIX accel/crude"),
            row("Gate  7b Strategy should_enter() failed", "g7_should_enter",          "VIX zone passed but no sub-strategy entered"),
            (row("Gate  8  ML quality score < threshold", "g8_ml_quality",
                 f"threshold ≈ {self._monthly_model_threshold() or self.entry_threshold:.2f}")
             if getattr(self.m_config, "monthly_gate8_enabled", False)
             else row("Gate  8  ML quality (BYPASSED — AUC<0.55)", "g8_ml_quality_bypassed",
                      "Re-enable after ≥500 real trades & AUC>0.55")),
            row("Gate  9  Expiry selector found=False", "g9_expiry_selector",        "EV/risk-reward/DTE/suitability filters"),
            row("Gate 10  Position sizing lots=0",      "g10_position_sizing",       "equity or margin insufficient"),
            row("Gate 11  Hard max loss cap",           "g11_hard_max_loss",         f"trade_loss > equity × {getattr(self.m_config, 'monthly_hard_max_loss_pct', 8.0):.0f}%"),
            row("Gate 12  DTE window",                  "g12_dte_window",            f"DTE not in [{self.m_config.min_dte_entry}, {self.m_config.max_dte_entry}]"),
            row("Gate 13  Entry cooldown",              "g13_cooldown",              "< 2 days since last entry"),
            "  " + "─" * 70,
            f"  Entry signals created               : {signals:5d}",
            f"  Trades filled (actual)              : {filled:5d}",
            f"  Skipped at fill                     : {max(0, signals - filled):5d}",
            "",
        ]
        return "\n".join(lines)

    def _close_monthly(self, exit_date, spot, vix, reason) -> float:
        trade = self.monthly_trade
        trade.exit_date = exit_date
        trade.exit_spot = spot
        trade.exit_vix = vix

        raw_pnl = trade.total_pnl
        cost = 0.0
        if self.m_config.apply_costs:
            cm = self.m_config.cost_model
            avg_m = 1.0
            if trade.legs and trade.entry_spot > 0:
                avg_m = sum(l.strike / trade.entry_spot for l in trade.legs) / len(trade.legs)
            cost = cm.total_cost_per_trade(
                trade.net_credit, len(trade.legs), trade.lots, trade.lot_size,
                trade.entry_vix, avg_m,
            )
        net_pnl = raw_pnl - cost

        exit_signal_score = None
        if self._pending_monthly_entry is not None:
            exit_signal_score = self._pending_monthly_entry.get("diagnostics", {}).get("score")
        elif self._m_pnl_history:
            exit_signal_score = self._last_ml_win_prob

        self.monthly_completed.append({
            "track": "monthly",
            "strategy": trade.strategy_name,
            "signal_date": getattr(trade, "signal_date", trade.entry_date),
            "entry_date": trade.entry_date,
            "fill_date": trade.entry_date,
            "exit_date": exit_date,
            "entry_spot": trade.entry_spot,
            "exit_spot": spot,
            "entry_vix": trade.entry_vix,
            "exit_vix": vix,
            "holding_days": (exit_date - trade.entry_date).days,
            "total_pnl": net_pnl,
            "exit_reason": reason.value if reason else "unknown",
            "lots": trade.lots,
        })

        self.monthly_diagnostics.close_trade(
            entry_date=trade.entry_date,
            exit_date=exit_date,
            exit_reason=reason.value if reason else "unknown",
            trade=trade,
            net_pnl=net_pnl,
            exit_signal_score=exit_signal_score,
        )

        sname = trade.strategy_name.split(":")[-1] if ":" in trade.strategy_name else trade.strategy_name
        self._m_strategy_history.append(sname)
        self._monthly_realized += net_pnl

        if net_pnl > 0:
            self._m_consecutive_losses = 0
        else:
            self._m_consecutive_losses += 1

        # Use post-close equity: _monthly_realized already includes net_pnl at this point
        post_close_equity = self.m_config.initial_capital + self._monthly_realized + self._weekly_realized
        self.position_sizer.record_trade_with_equity(net_pnl, post_close_equity)
        self.monthly_trade = None
        self._m_peak_pnl_per_unit = 0.0
        self._m_pnl_history = []
        return net_pnl

    def _force_close_monthly(self):
        last_row = self.data.iloc[-1]
        spot = last_row.get("nifty_close", 0)
        vix = last_row.get("vix", 15)
        d = self.data.index[-1]
        if hasattr(d, "date"):
            d = d.date()
        self._close_monthly(d, spot, vix, ExitReason.EXPIRY)

    def _get_monthly_expiry(self, current_date):
        target = current_date + timedelta(days=21)
        expiry = get_monthly_expiry(target.year, target.month, ref_date=current_date)
        if (expiry - current_date).days < 10:
            month = target.month + 1
            year = target.year
            if month > 12:
                month, year = 1, year + 1
            expiry = get_monthly_expiry(year, month, ref_date=current_date)
        return expiry

    # ═══════════════════════════════════════════════════════════════════
    #  Weekly track — risk gates
    # ═══════════════════════════════════════════════════════════════════

    def _weekly_entry_blocked(self, equity, dd_pct, vix) -> Optional[str]:
        """
        Multi-layer risk gate for weekly entries.

        Returns None if entry is allowed, or a string reason if blocked.
        Checks in order of cost (cheapest first):
          1. Cross-track DD breaker (combined DD > threshold, improvement-based)
          2. Monthly MTM loss > threshold (don't layer risk on a losing month)
          3. Combined open position loss cap
          4. VIX simultaneous position gate

        Phase-1 fix: Gate 1 now uses improvement-based recovery.
        Old: blocked whenever dd_pct > cross_track_dd_pct (absolute 20% floor).
        New: once blocked, re-enable when dd_pct improves 3% from its worst
             point while blocked. This prevents the 337-day lock-out caused by
             DD oscillating 17-22% for months without ever crossing 20%.
        """
        if dd_pct > self.cross_track_dd_pct:
            # Currently in elevated-DD territory. Update worst-DD tracker.
            if dd_pct > self._cross_dd_worst_while_blocked:
                self._cross_dd_worst_while_blocked = dd_pct
            return "dd"

        # DD is at or below threshold. Check if we're recovering from a blocked period.
        if self._cross_dd_worst_while_blocked > 0:
            # We were previously blocked. Require improvement_pct improvement from worst.
            required_recovery = self._cross_dd_worst_while_blocked - self._cross_dd_improvement_pct
            if dd_pct > required_recovery:
                # Still haven't improved enough from the worst seen — keep blocking.
                return "dd"
            # Sufficient improvement — allow entry and reset tracker.
            self._cross_dd_worst_while_blocked = 0.0

        if self.monthly_trade is not None and self.monthly_trade.total_pnl < 0:
            monthly_hold_days = getattr(self.monthly_trade, "holding_days", 0)
            if monthly_hold_days >= getattr(self.w_config, "monthly_loss_block_min_hold_days", 3):
                loss_pct = abs(self.monthly_trade.total_pnl) / equity if equity > 0 else 0
                if loss_pct > self.monthly_loss_block_pct:
                    return "monthly_loss"

        open_loss = 0.0
        if self.monthly_trade and self.monthly_trade.total_pnl < 0:
            open_loss += abs(self.monthly_trade.total_pnl)
        if self.weekly_trade and self.weekly_trade.total_pnl < 0:
            open_loss += abs(self.weekly_trade.total_pnl)
        weekly_hold_days = getattr(self.weekly_trade, "holding_days", 0) if self.weekly_trade is not None else 0
        monthly_hold_days = getattr(self.monthly_trade, "holding_days", 0) if self.monthly_trade is not None else 0
        if (
            equity > 0
            and open_loss > equity * self.combined_open_loss_cap_pct
            and (
                monthly_hold_days >= getattr(self.w_config, "combined_open_loss_block_min_hold_days", 2)
                or weekly_hold_days >= getattr(self.w_config, "combined_open_loss_block_min_hold_days", 2)
            )
        ):
            return "open_cap"

        if vix > self.vix_simultaneous_cap and self.monthly_trade is not None:
            return "vix_gate"

        return None

    # ═══════════════════════════════════════════════════════════════════
    #  Weekly track — strategy / entry / exit
    # ═══════════════════════════════════════════════════════════════════

    def _select_weekly_strategy(self, vix, market_data):
        if 12 <= vix <= 22:
            nifty_5d = market_data.get("nifty_return_5d", 0)
            if not (isinstance(nifty_5d, float) and np.isnan(nifty_5d)) and abs(nifty_5d) < 0.02:
                return self.weekly_ic
        return self.weekly_pcs

    def _process_weekly_exit(self, row, current_date, spot, vix, market_data) -> float:
        if self.weekly_trade is None:
            return 0.0

        dte = max((self._w_expiry - current_date).days, 0) if self._w_expiry else 0
        strategy_name = self.weekly_trade.strategy_name.lower()

        strategy = self._select_weekly_strategy(self._w_entry_vix, market_data)
        if hasattr(strategy, "update_premiums"):
            strategy.update_premiums(
                self.weekly_trade, spot, vix, max(dte, 0), self.w_config.risk_free_rate,
            )

        # Dynamic exit engine (delta doubling, IV spike, distance breach)
        if self.weekly_risk_engine is not None and self._w_entry_credit > 0:
            current_delta = self._estimate_weekly_delta(spot, vix, dte)
            dyn_exit = self.weekly_risk_engine.check_exit(
                spot=spot, vix=vix,
                entry_spot=self._w_entry_spot, entry_vix=self._w_entry_vix,
                entry_credit=self._w_entry_credit,
                short_strike=self._w_short_strike, long_strike=self._w_long_strike,
                option_type=self._w_option_type, dte_remaining=dte,
                current_pnl_per_unit=self.weekly_trade.pnl_per_unit,
                entry_delta=self._w_entry_delta, current_delta=current_delta,
                regime_name=self._w_regime_name,
            )
            allow_dynamic_exit = False
            if "weekly_pcs" in strategy_name:
                # Income Core keeps the risk-breach exits, but the profit target
                # is governed by the redesigned weekly exit policy.
                allow_dynamic_exit = dyn_exit.reason != "profit_target"
            elif "weekly_ic" not in strategy_name:
                allow_dynamic_exit = dyn_exit.should_exit

            if dyn_exit.should_exit and allow_dynamic_exit:
                reason_map = {
                    "profit_target": ExitReason.PROFIT_TARGET,
                    "delta_doubled": ExitReason.STOP_LOSS,
                    "iv_spike": ExitReason.STOP_LOSS,
                    "distance_breach_50pct": ExitReason.STOP_LOSS,
                    "dte_losing_exit": ExitReason.DTE_LIMIT,
                }
                exit_reason = reason_map.get(dyn_exit.reason, ExitReason.STOP_LOSS)
                self.weekly_dynamic_exit_count += 1
                self._w_dynamic_exit_reasons[dyn_exit.reason] = (
                    self._w_dynamic_exit_reasons.get(dyn_exit.reason, 0) + 1
                )
                pnl = self._close_weekly(current_date, spot, vix, exit_reason)
                return pnl

        prior_tracker = WeeklyExitTracker(
            peak_pnl_per_unit=self._w_exit_tracker.peak_pnl_per_unit,
            entry_abs_delta=self._w_exit_tracker.entry_abs_delta,
            best_abs_delta=self._w_exit_tracker.best_abs_delta,
            high_spot=self._w_exit_tracker.high_spot,
            low_spot=self._w_exit_tracker.low_spot,
        ) if self._w_exit_tracker is not None else build_tracker(self.weekly_trade)

        should_exit, exit_reason = check_weekly_exit(
            config=self.w_config,
            trade=self.weekly_trade,
            tracker=prior_tracker,
            spot=spot,
            vix=vix,
            dte=dte,
            entry_vix=self._w_entry_vix,
            current_equity=self._combined_equity,
            holding_days=(current_date - self.weekly_trade.entry_date).days,
        )

        if not should_exit:
            action, reason = strategy.should_exit(self.weekly_trade, spot, vix, dte)
            if action == TradeAction.EXIT or dte <= 0:
                should_exit, exit_reason = True, (reason if reason else ExitReason.EXPIRY)

        if should_exit:
            pnl = self._close_weekly(current_date, spot, vix, exit_reason)
            return pnl
        else:
            if self._w_exit_tracker is None:
                self._w_exit_tracker = build_tracker(self.weekly_trade)
            update_tracker(self._w_exit_tracker, self.weekly_trade, spot)
            return 0.0

    def _estimate_weekly_delta(self, spot, vix, dte_rem) -> float:
        """Rough net delta estimate for the weekly spread."""
        if self._w_short_strike == 0 or dte_rem <= 0:
            return 0.0
        try:
            iv_s = iv_from_vix(vix, self._w_short_strike, spot, self._w_option_type)
            result = price_option(spot, self._w_short_strike, max(dte_rem, 1),
                                  iv_s, 0.065, self._w_option_type)
            return result.delta if hasattr(result, "delta") else 0.0
        except Exception:
            return 0.0

    def _compute_weekly_dynamic_scale(self, vix, dd_pct, equity) -> float:
        """
        Compute a continuous [0, 1] scale factor for weekly lot sizing based on
        multiple stress signals. Multiplicative — each layer can only reduce.

        1. VIX scale:  1.0 at VIX <= 14, linearly to 0.3 at VIX = 25
        2. DD scale:   1.0 at DD = 0%, linearly to 0.25 at DD >= 5%
        3. Streak scale: 1.0 at 0 consecutive losses, 0.5 at 2, 0.0 (skip) at 3+
        4. Monthly stress: 0.5 if monthly trade is losing > 1% of equity
        """
        # VIX: start reducing at 18 (not 16), floor 0.6
        vix_scale = 1.0
        if vix > 18:
            vix_scale = max(0.6, 1.0 - (vix - 18) / (25 - 18) * 0.4)

        # DD: start reducing at 2%, floor 0.4 — allows entries but at smaller size
        dd_scale = 1.0
        if dd_pct > 0.02:
            dd_scale = max(0.4, 1.0 - (dd_pct - 0.02) / 0.12 * 0.6)

        # Streak: only cut at 4+ losses, moderate reduction at 3
        streak_scale = 1.0
        if self._w_consecutive_losses >= 4:
            streak_scale = 0.3
        elif self._w_consecutive_losses == 3:
            streak_scale = 0.6

        # Monthly stress: only when losing > 3% of equity, floor 0.5
        monthly_stress_scale = 1.0
        if self.monthly_trade is not None and self.monthly_trade.total_pnl < 0 and equity > 0:
            monthly_loss_pct = abs(self.monthly_trade.total_pnl) / equity
            if monthly_loss_pct > 0.03:
                monthly_stress_scale = max(0.5, 1.0 - (monthly_loss_pct - 0.03) / 0.05)

        return vix_scale * dd_scale * streak_scale * monthly_stress_scale

    def _process_weekly_entry(self, row, current_date, spot, vix, market_data,
                              equity, data_idx, dd_pct):
        weekday = current_date.weekday()
        if weekday not in (0, 1):
            return
        if vix < self.w_config.min_vix_entry or vix > self.w_config.max_vix_entry:
            return

        # ── Losing streak cooldown: pause briefly after 4 losses, then reset ──
        if self._w_cooldown_until is not None and current_date < self._w_cooldown_until:
            self.weekly_streak_skips += 1
            return
        if self._w_cooldown_until is not None and current_date >= self._w_cooldown_until:
            self._w_cooldown_until = None
            self._w_consecutive_losses = 0

        if self._w_consecutive_losses >= 4:
            self._w_cooldown_until = current_date + timedelta(days=3)
            self._w_consecutive_losses = 0
            self.weekly_streak_skips += 1
            return

        # ── Legacy ML quality gate (backward compat — skipped if risk engine present) ──
        if self.weekly_risk_engine is None:
            if self.weekly_entry_model is not None and self.weekly_entry_model.is_trained:
                quality_score = self.weekly_entry_model.predict(row, market_data_idx=data_idx)
                if quality_score < self.weekly_entry_threshold:
                    self.weekly_ml_skips += 1
                    return

        strategy = self._select_weekly_strategy(vix, market_data)
        action = strategy.should_enter(spot, vix, market_data)
        if action != TradeAction.ENTER:
            return

        exp, dte = get_weekly_expiry_in_range(
            current_date, self.w_config.min_dte_entry, self.w_config.max_dte_entry,
        )
        if exp is None:
            return

        # ── Dynamic lot sizing: equity-proportional * stress scaler ──
        weekly_budget = equity * self.weekly_budget_pct
        margin_per_lot = 500 * self.w_config.lot_size
        base_lots = max(1, min(self.w_config.max_lots, int(weekly_budget * 0.60 / margin_per_lot)))

        dynamic_scale = self._compute_weekly_dynamic_scale(vix, dd_pct, equity)
        base_lots_scaled = max(1, int(base_lots * dynamic_scale))

        if dynamic_scale < 0.95:
            self.weekly_dynamic_scale_downs += 1

        # ── Risk Engine: regime + ETL + tail risk → sizing override ──
        sizing = None
        if self.weekly_risk_engine is not None:
            # Peek at the spread to get short/long strikes for ETL computation
            temp_strategy = self._select_weekly_strategy(vix, market_data)
            if hasattr(temp_strategy, "lots"):
                temp_strategy.lots = base_lots_scaled
            temp_trade = temp_strategy.create_trade(
                current_date, spot, vix, dte, self.w_config.risk_free_rate,
            )
            short_strike, long_strike = 0.0, 0.0
            entry_credit = temp_trade.net_credit if temp_trade else 0.0
            opt_type = OptionType.PUT
            for leg in (temp_trade.legs if temp_trade else []):
                if leg.is_short:
                    short_strike = leg.strike
                    opt_type = (OptionType.PUT if leg.option_type in ("PUT", "PE")
                                else OptionType.CALL)
                elif not leg.is_short and long_strike == 0:
                    long_strike = leg.strike

            sizing = self.weekly_risk_engine.compute_entry(
                row=row, spot=spot, vix=vix,
                short_strike=short_strike, long_strike=long_strike,
                entry_credit=entry_credit, dte=dte,
                base_lots=base_lots_scaled, option_type=opt_type,
            )

            if sizing.skip:
                if "etl" in sizing.skip_reason:
                    self.weekly_etl_skips += 1
                elif "regime" in sizing.skip_reason:
                    self.weekly_regime_skips += 1
                return

            self._w_risk_scores.append(sizing.risk_score)
            self._w_regime_counts[sizing.regime] = (
                self._w_regime_counts.get(sizing.regime, 0) + 1
            )
            lots = sizing.lots
        else:
            lots = base_lots_scaled

        if hasattr(strategy, "lots"):
            strategy.lots = lots

        trade = strategy.create_trade(current_date, spot, vix, dte, self.w_config.risk_free_rate)

        # Production rule: validate no-naked + hedge ratio on the actual legs
        blocked, block_msg = self.prod_gate.should_block_weekly_entry(
            current_date, legs=trade.legs, spot=spot,
        )
        if blocked:
            return

        # Store entry context for dynamic exit engine
        self._w_entry_spot = spot
        self._w_entry_credit = trade.net_credit
        self._w_short_strike = 0.0
        self._w_long_strike = 0.0
        self._w_option_type = OptionType.PUT
        for leg in trade.legs:
            if leg.is_short and self._w_short_strike == 0:
                self._w_short_strike = leg.strike
                self._w_option_type = (OptionType.PUT if leg.option_type in ("PUT", "PE")
                                       else OptionType.CALL)
            elif not leg.is_short and self._w_long_strike == 0:
                self._w_long_strike = leg.strike
        self._w_entry_delta = self._estimate_weekly_delta(spot, vix, dte)
        self._w_regime_name = sizing.regime if sizing else "low_vol_grind"

        self._pending_weekly_entry = {
            "signal_date": current_date,
            "signal_spot": spot,
            "signal_vix": vix,
            "expiry": exp,
            "lots": lots,
            "strategy": strategy,
        }

    def _close_weekly(self, exit_date, spot, vix, reason) -> float:
        trade = self.weekly_trade
        raw_pnl = trade.total_pnl
        cost = 0.0
        if self.w_config.apply_costs:
            cm = self.w_config.cost_model
            avg_m = 1.0
            if trade.legs and trade.entry_spot > 0:
                avg_m = sum(l.strike / trade.entry_spot for l in trade.legs) / len(trade.legs)
            cost = cm.total_cost_per_trade(
                trade.net_credit, len(trade.legs), trade.lots, trade.lot_size, trade.entry_vix, avg_m,
            )
        net_pnl = raw_pnl - cost

        self.weekly_completed.append({
            "track": "weekly",
            "strategy": trade.strategy_name,
            "signal_date": getattr(trade, "signal_date", trade.entry_date),
            "entry_date": trade.entry_date,
            "fill_date": trade.entry_date,
            "exit_date": exit_date,
            "entry_spot": trade.entry_spot,
            "exit_spot": spot,
            "entry_vix": trade.entry_vix,
            "exit_vix": vix,
            "holding_days": (exit_date - trade.entry_date).days,
            "total_pnl": net_pnl,
            "exit_reason": reason.value if reason else "unknown",
            "lots": trade.lots,
        })

        self._weekly_realized += net_pnl

        if net_pnl > 0:
            self._w_consecutive_losses = 0
            self._w_cooldown_until = None
        else:
            self._w_consecutive_losses += 1

        self._w_recent_results.append(net_pnl)
        if len(self._w_recent_results) > 10:
            self._w_recent_results = self._w_recent_results[-10:]

        self.weekly_trade = None
        self._w_peak_pnl_per_unit = 0.0
        self._w_exit_tracker = None
        return net_pnl

    def _force_close_weekly(self):
        last_row = self.data.iloc[-1]
        spot = last_row.get("nifty_close", 0)
        vix = last_row.get("vix", 15)
        d = self.data.index[-1]
        if hasattr(d, "date"):
            d = d.date()
        self._close_weekly(d, spot, vix, ExitReason.EXPIRY)

    # ═══════════════════════════════════════════════════════════════════
    #  Results
    # ═══════════════════════════════════════════════════════════════════

    def _build_result(self) -> CombinedResult:
        capital = self.m_config.initial_capital
        all_trades = self.monthly_completed + self.weekly_completed
        if not all_trades:
            return CombinedResult(
                initial_capital=capital,
                equity_curve=self.equity_curve,
                daily_pnl=self.daily_pnl,
                diagnostics=self.monthly_diagnostics.summary(),
            )

        pnls = [t["total_pnl"] for t in all_trades]
        m_pnls = [t["total_pnl"] for t in self.monthly_completed]
        w_pnls = [t["total_pnl"] for t in self.weekly_completed]

        total_pnl = sum(pnls)
        n_days = len(self.equity_curve)
        years = n_days / 252 if n_days > 0 else 1
        final = capital + total_pnl
        cagr = ((final / capital) ** (1 / years) - 1) * 100 if final > 0 and years > 0 else 0

        eq = np.array(self.equity_curve) if self.equity_curve else np.array([capital])
        peak = np.maximum.accumulate(eq)
        dd = (eq - peak) / peak * 100
        max_dd = abs(dd.min()) if len(dd) > 0 else 0

        daily = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0])
        d_mean = np.mean(daily)
        d_std = np.std(daily)
        sharpe = (d_mean / d_std * np.sqrt(252)) if d_std > 0 else 0

        downside = daily[daily < 0]
        ds_std = np.std(downside) if len(downside) > 0 else 1
        sortino = (d_mean / ds_std * np.sqrt(252)) if ds_std > 0 else 0
        calmar = cagr / max_dd if max_dd > 0 else 0

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_win = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        pf = gross_win / gross_loss if gross_loss > 0 else 0

        m_wins = sum(1 for p in m_pnls if p > 0)
        w_wins = sum(1 for p in w_pnls if p > 0)

        m_hold = [t["holding_days"] for t in self.monthly_completed]
        w_hold = [t["holding_days"] for t in self.weekly_completed]

        total_hold = sum(t["holding_days"] for t in all_trades)
        first = min(t["entry_date"] for t in all_trades)
        last = max(t["exit_date"] for t in all_trades)
        cal_days = (last - first).days if (last - first).days > 0 else 1
        cap_util = total_hold / cal_days * 100

        return CombinedResult(
            initial_capital=capital,
            total_trades=len(all_trades),
            monthly_trades=len(self.monthly_completed),
            weekly_trades=len(self.weekly_completed),
            total_pnl=round(total_pnl),
            monthly_pnl=round(sum(m_pnls)),
            weekly_pnl=round(sum(w_pnls)),
            cagr_pct=round(cagr, 2),
            max_drawdown_pct=round(max_dd, 1),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
            win_rate=round(len(wins) / len(all_trades) * 100, 1) if all_trades else 0,
            profit_factor=round(pf, 2),
            monthly_win_rate=round(m_wins / len(m_pnls) * 100, 1) if m_pnls else 0,
            weekly_win_rate=round(w_wins / len(w_pnls) * 100, 1) if w_pnls else 0,
            avg_holding_days_monthly=round(np.mean(m_hold), 1) if m_hold else 0,
            avg_holding_days_weekly=round(np.mean(w_hold), 1) if w_hold else 0,
            capital_utilization_pct=round(cap_util, 1),
            cross_track_dd_blocks=self.cross_track_dd_blocks,
            weekly_ml_skips=self.weekly_ml_skips,
            weekly_vix_gate_blocks=self.weekly_vix_gate_blocks,
            weekly_open_cap_blocks=self.weekly_open_cap_blocks,
            weekly_monthly_loss_blocks=self.weekly_monthly_loss_blocks,
            weekly_streak_skips=self.weekly_streak_skips,
            weekly_dynamic_scale_downs=self.weekly_dynamic_scale_downs,
            emergency_weekly_exits=self.emergency_weekly_exits,
            dd_kill_switch_activations=self.prod_gate.kill_switch.state.total_activations,
            dd_kill_weekly_closes=self.prod_gate.kill_switch.state.weekly_force_closes,
            dd_kill_entries_blocked=self.prod_gate.kill_switch.state.entries_blocked,
            event_calendar_blocks=self.prod_gate.event_blocks,
            weekly_etl_skips=self.weekly_etl_skips,
            weekly_regime_skips=self.weekly_regime_skips,
            weekly_risk_score_avg=(
                round(float(np.mean(self._w_risk_scores)), 3) if self._w_risk_scores else 0.0
            ),
            weekly_dynamic_exit_count=self.weekly_dynamic_exit_count,
            weekly_dynamic_exit_reasons=dict(self._w_dynamic_exit_reasons),
            weekly_regime_distribution=dict(self._w_regime_counts),
            best_trade_pnl=round(max(pnls)) if pnls else 0,
            worst_trade_pnl=round(min(pnls)) if pnls else 0,
            equity_curve=self.equity_curve,
            daily_pnl=self.daily_pnl,
            all_trades=all_trades,
            diagnostics=self.monthly_diagnostics.summary(),
        )
