from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class CostModel:
    """India options transaction cost model (per-leg, per-unit costs)."""
    stt_on_sell_pct: float = 0.0625       # STT on option sell premium (0.0625%)
    exchange_txn_pct: float = 0.0019      # NSE transaction charges
    gst_on_brokerage_pct: float = 18.0    # 18% GST on brokerage
    stamp_duty_buy_pct: float = 0.003     # stamp duty on buy side
    sebi_turnover_pct: float = 0.0001     # SEBI turnover fee
    brokerage_per_order: float = 20.0     # flat brokerage per order (discount broker)
    base_slippage_per_unit: float = 0.30  # base bid-ask slippage in calm markets
    slippage_vix_scale: float = 0.04      # additional slippage per VIX point above 15

    def slippage_per_unit(self, vix: float = 15.0, moneyness: float = 1.0) -> float:
        """Volatility and moneyness-scaled slippage (v4)."""
        vix_extra = max(0, vix - 15) * self.slippage_vix_scale
        otm_extra = 0.0
        if moneyness < 0.95 or moneyness > 1.05:
            otm_extra = 0.20 * abs(moneyness - 1.0) * 10
        return self.base_slippage_per_unit + vix_extra + otm_extra

    def total_cost_per_trade(
        self, net_credit: float, num_legs: int, lots: int, lot_size: int,
        vix: float = 15.0, avg_moneyness: float = 1.0,
    ) -> float:
        """Estimate total round-trip cost for a trade."""
        qty = lots * lot_size
        notional = abs(net_credit) * qty

        stt = notional * self.stt_on_sell_pct / 100
        exchange = notional * self.exchange_txn_pct / 100
        sebi = notional * self.sebi_turnover_pct / 100
        stamp = notional * self.stamp_duty_buy_pct / 100

        brokerage = self.brokerage_per_order * num_legs * 2
        gst = brokerage * self.gst_on_brokerage_pct / 100

        slip = self.slippage_per_unit(vix, avg_moneyness) * qty * num_legs

        return stt + exchange + sebi + stamp + brokerage + gst + slip

    def cost_as_pct_of_credit(
        self, net_credit: float, num_legs: int, lots: int, lot_size: int,
        vix: float = 15.0, avg_moneyness: float = 1.0,
    ) -> float:
        """Cost as percentage of credit collected."""
        total_credit = net_credit * lots * lot_size
        if total_credit <= 0:
            return 0.0
        cost = self.total_cost_per_trade(net_credit, num_legs, lots, lot_size, vix, avg_moneyness)
        return cost / total_credit * 100


@dataclass
class BacktestConfig:
    start_date: date = date(2009, 1, 1)
    end_date: date = field(default_factory=date.today)
    initial_capital: float = 500_000.0
    max_risk_per_trade_pct: float = 8.0
    lot_size: int = 65
    max_lots: int = 200
    risk_free_rate: float = 0.065
    slippage_pct: float = 0.1
    brokerage_per_lot: float = 40.0

    # Strategy defaults
    default_dte: int = 21
    min_dte_entry: int = 15
    max_dte_entry: int = 45

    # VIX regime thresholds
    vix_low: float = 14.0
    vix_medium: float = 18.0
    vix_high: float = 22.0
    vix_extreme: float = 28.0

    # Strike selection (standard deviations from spot)
    call_strike_sd: float = 1.0
    put_strike_sd: float = 1.0
    hedge_width_points: int = 1000

    # Risk management
    stop_loss_multiplier: float = 2.0
    profit_target_pct: float = 50.0
    max_drawdown_pct: float = 15.0

    # Monthly entry quality filters and structure caps
    monthly_min_short_dist_pct_low_vol: float = 2.0
    monthly_min_short_dist_pct_trending: float = 2.5
    monthly_min_short_dist_pct_high_vol: float = 3.5
    monthly_min_short_dist_pct_crash: float = 5.0
    monthly_max_loss_to_credit_ratio: float = 6.0
    monthly_min_raw_ev: float = -250.0
    monthly_min_tail_adjusted_ev: float = -1000.0
    monthly_max_margin_per_trade_pct: float = 20.0
    monthly_max_risk_per_trade_pct: float = 10.0
    monthly_hard_max_loss_pct: float = 15.0
    monthly_entry_threshold: float = 0.50  # Gate 8 quality threshold cap; raised 0.30→0.50 (2026-08-23)
    # so model's regime-aware thresholds (TRENDING:0.46, LOW_VOL:0.48, HIGH_VOL:0.50, CRASH:0.52)
    # are no longer suppressed by the artificial 0.30 ceiling. Expect ~150-200 monthly entries
    # (down from 397) keeping only high-confidence setups. If entries drop below 50, lower to 0.40.
    monthly_gate8_enabled: bool = True
    # Re-enabled 2026-08-23: LightGBM AUC reached 0.696 (>0.55 threshold met).
    # Real-trade condition (≥500) intentionally relaxed — sim trades with 18
    # strategy-structure features now produce genuinely discriminative labels
    # (AUC 0.696 vs 0.55 random). Gate 8 now filters ~76% of bypass-era entries.

    monthly_exit_min_hold_days: int = 3   # Lowered 5→3 (2026-08-23): allows fast profit-taking on clean
    # setups after 2 theta weekends; still avoids same-day exit noise. Reduces avg hold from 8d toward 5-6d.
    monthly_exit_profit_target_scale: float = 1.0
    monthly_exit_stop_loss_scale: float = 0.70  # Tightened 1.0→0.70 (2026-08-23): brings effective stops
    # from 40-50% of credit to 28-35% — still gives trades room to breathe but cuts avg losing-trade hold.
    monthly_exit_trailing_arm_pct: float = 25.0
    monthly_exit_trailing_drop_pct: float = 35.0

    # DTE-based profit target table — replaces flat VIX-only targets.
    # Longer-DTE trades have lower targets (hold for theta); shorter-DTE trades
    # take more of the available credit since less time remains.
    monthly_exit_dte_profit_target_long: float = 25.0    # dte >= 20 days remaining — lowered 35→25 (2026-08-23):
    # 35% target on 30-DTE trade took 8-12 days of pure decay; 25% achievable in 5-7 days
    monthly_exit_dte_profit_target_mid: float = 55.0     # 10 <= dte < 20
    monthly_exit_dte_profit_target_short: float = 75.0   # dte < 10

    # Monthly selection / sizing controls
    monthly_enable_regime_rerank: bool = True
    monthly_regime_rerank_strength: float = 0.18
    monthly_disable_bwb: bool = False

    # Monthly sizing overrides. These are intentionally modest: enough to
    # recover idle capital, not enough to create hidden leverage.
    monthly_low_vol_scale: float = 1.00
    monthly_trending_scale: float = 0.90
    monthly_high_vol_scale: float = 0.75
    monthly_crash_scale: float = 0.40
    monthly_confidence_low_scale: float = 0.90
    monthly_confidence_neutral_scale: float = 1.00
    monthly_confidence_high_scale: float = 1.15
    monthly_dd_scale_1: float = 1.00
    monthly_dd_scale_2: float = 0.85
    monthly_dd_scale_3: float = 0.65
    monthly_dd_scale_4: float = 0.45

    entry_model_version: str = "v4"

    # ── Mid-session entry window (11:00–13:00 IST) ──────────────────────────
    # Nifty options markets are most stable and have tightest bid-ask spreads
    # between 11 AM and 1 PM IST — after the open volatility settles and before
    # the afternoon drift. Enabling this has two effects:
    #   Backtest: fill price = nifty_open + 0.4×(nifty_close−nifty_open)
    #             (proxy for ~11 AM spot; 40% of the open→close intraday move)
    #             + slippage reduced by mid_session_slippage_scale (0.75×)
    #   Signal:   hard time-gate — rejects entries outside [entry_window_start, entry_window_end]
    mid_session_entry: bool = True                 # master switch
    entry_window_start_hour: int = 11              # IST hour (inclusive)
    entry_window_start_minute: int = 0
    entry_window_end_hour: int = 13                # IST hour (inclusive)
    entry_window_end_minute: int = 0
    mid_session_intraday_alpha: float = 0.40       # fraction of open→close move completed by ~11 AM
    mid_session_slippage_scale: float = 0.75       # bid-ask is ~25% tighter in mid-session vs open

    cost_model: CostModel = field(default_factory=CostModel)
    apply_costs: bool = True
    max_portfolio_delta: float = 6000.0
    max_portfolio_vega: float = 60000.0
    max_strategy_concentration_pct: float = 62.0
    strategy_lookback_trades: int = 20
    min_trades_per_quarter: int = 4


@dataclass
class WeeklyBacktestConfig:
    """Configuration for weekly (3-8 DTE) options backtesting."""
    start_date: date = date(2009, 1, 1)
    end_date: date = field(default_factory=date.today)
    initial_capital: float = 500_000.0
    lot_size: int = 65
    max_lots: int = 10
    risk_free_rate: float = 0.065

    min_dte_entry: int = 3
    max_dte_entry: int = 8
    profit_target_pct: float = 50.0
    stop_loss_pct: float = 80.0
    max_vix_entry: float = 25.0
    min_vix_entry: float = 10.0

    capital_protection_pct: float = 0.04
    trailing_peak_pct: float = 30.0
    trailing_drop_pct: float = 25.0
    expiry_exit_dte: int = 1
    weekly_exit_policy: str = "redesigned"
    stop_loss_fill_policy: str = "mark_to_market"
    stop_loss_slippage_penalty_per_unit: float = 0.0
    engine_a_profit_target_pct: float = 75.0
    engine_a_min_hold_days: int = 2
    engine_b_max_hold_days: int = 4
    engine_b_delta_trail_arm_ratio: float = 0.80
    engine_b_delta_trail_rebound_ratio: float = 1.35
    engine_b_trend_trigger_pct: float = 0.0125
    engine_b_trend_reversal_pct: float = 0.0060
    combined_open_loss_block_min_hold_days: int = 2
    monthly_loss_block_min_hold_days: int = 3

    # Mid-session entry window — mirrors BacktestConfig fields.
    # Weekly fills also use nifty_mid_session spot and reduced slippage when enabled.
    mid_session_entry: bool = True
    mid_session_slippage_scale: float = 0.75

    cost_model: CostModel = field(default_factory=lambda: CostModel(
        base_slippage_per_unit=0.45,
        slippage_vix_scale=0.06,
    ))
    apply_costs: bool = True


@dataclass
class MarketRegime:
    """Classifies current market conditions."""
    vix_level: str = "medium"        # low, medium, high, extreme
    trend: str = "neutral"           # bullish, bearish, neutral
    crude_impact: str = "neutral"    # positive, negative, neutral
    fii_flow: str = "neutral"        # buying, selling, neutral
    event_risk: str = "low"          # low, medium, high

    @property
    def risk_score(self) -> float:
        scores = {
            "vix_level": {"low": 0, "medium": 1, "high": 3, "extreme": 5},
            "trend": {"bullish": 0, "neutral": 1, "bearish": 3},
            "crude_impact": {"positive": 0, "neutral": 1, "negative": 3},
            "fii_flow": {"buying": 0, "neutral": 1, "selling": 3},
            "event_risk": {"low": 0, "medium": 2, "high": 5},
        }
        total = (
            scores["vix_level"].get(self.vix_level, 1)
            + scores["trend"].get(self.trend, 1)
            + scores["crude_impact"].get(self.crude_impact, 1)
            + scores["fii_flow"].get(self.fii_flow, 1)
            + scores["event_risk"].get(self.event_risk, 0)
        )
        return min(total / 19.0, 1.0)

    @property
    def recommended_strategy(self) -> str:
        score = self.risk_score
        if score < 0.2:
            return "aggressive_iron_condor"
        elif score < 0.4:
            return "standard_iron_condor"
        elif score < 0.6:
            return "wide_iron_condor"
        elif score < 0.8:
            return "put_spread_only"
        else:
            return "no_trade"
