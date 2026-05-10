"""
Position sizing: margin-based compounding, vol-target, regime scaling,
drawdown protection, and coarse ML confidence tier.

Architecture:
    base_lots        = margin compounding (cold start) or vol-target (warmed up)
    final_lots       = base_lots * regime_scale * dd_scale * confidence_scale

The edge comes from strategy structure + exits + risk control.
The entry model is a coarse filter (3-tier), not a precision instrument.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import BacktestConfig


# ── Regime multipliers (calibrated to Nifty options backtest 2009-2026) ──

REGIME_SCALE = {
    "LOW_VOL":  1.00,
    "HIGH_VOL": 0.75,
    "CRASH":    0.40,
    "TRENDING": 0.90,
}

_VIX_REGIME_BREAKPOINTS = [
    (14.0, "LOW_VOL"),
    (18.0, "TRENDING"),
    (25.0, "HIGH_VOL"),
    (999.0, "CRASH"),
]

# ── Drawdown scaler thresholds ──

_DD_BANDS = [
    (0.05, 1.00),
    (0.10, 0.85),
    (0.15, 0.65),
    (1.00, 0.45),
]

_VOL_WARMUP = 20


@dataclass
class SizingDecision:
    """Transparent record of how lot count was determined."""
    lots: int
    base_lots: float
    confidence_scale: float
    regime_scale: float
    dd_scale: float
    reason: str


@dataclass
class _TradeReturn:
    """Stores a trade's P&L and the equity at entry for accurate return calc."""
    pnl: float
    equity_at_entry: float

    @property
    def ret(self) -> float:
        return self.pnl / self.equity_at_entry if self.equity_at_entry > 0 else 0.0


def _regime_from_vix(vix: float) -> str:
    for threshold, label in _VIX_REGIME_BREAKPOINTS:
        if vix < threshold:
            return label
    return "CRASH"


def _drawdown_scale(dd_pct: float) -> float:
    """Progressive de-risking based on portfolio drawdown percentage (0-1)."""
    for upper, scale in _DD_BANDS:
        if dd_pct <= upper:
            return scale
    return 0.25


def _confidence_scale(win_prob: float) -> float:
    """
    Coarse 3-tier scaler from ML entry model's calibrated quality score.

    Calibrated scores cluster around 0.50-0.60, so use thresholds that
    match the post-gate distribution. Trades already passed the quality
    gate (0.55), so sizing shouldn't double-penalise them.
    """
    if win_prob > 0.65:
        return 1.15
    elif win_prob > 0.55:
        return 1.0
    else:
        return 0.90


class PositionSizer:
    """
    Computes position size using margin/vol base with regime, drawdown,
    and ML confidence scalers.

    Parameters
    ----------
    config : BacktestConfig
        Provides lot_size, max_lots, brokerage etc.
    target_annual_vol : float
        Annualised return volatility target (default 15%).
    max_lots_cap : int
        Hard ceiling on lots regardless of what formulas say.
    """

    def __init__(
        self,
        config: BacktestConfig,
        target_annual_vol: float = 0.15,
        max_lots_cap: int = 0,
    ):
        self.config = config
        self.target_annual_vol = target_annual_vol
        self.max_lots_cap = max_lots_cap if max_lots_cap > 0 else getattr(config, 'max_lots', 200)
        self._model_version = getattr(config, "entry_model_version", "v4")
        self._trade_returns: list[_TradeReturn] = []

    # ── Public API ──────────────────────────────────────────────────────

    def compute_lots(
        self,
        equity: float,
        vix: float,
        regime: str,
        win_prob: float,
        drawdown_pct: float,
        trade_max_loss_per_unit: float | None = None,
        trade_margin_per_lot: float | None = None,
    ) -> SizingDecision:
        """
        Determine position size.

        Parameters
        ----------
        equity        Current portfolio value (initial_capital + realised P&L).
        vix           Current India VIX reading.
        regime        Market regime label or empty string for VIX fallback.
        win_prob      ML entry model's win probability (for confidence tier).
        drawdown_pct  Current drawdown from peak equity, as a fraction (0-1).
        """
        if equity <= 0:
            return SizingDecision(1, 1.0, 1.0, 1.0, 1.0, "equity <= 0, floor")

        regime_label = regime if regime in REGIME_SCALE else _regime_from_vix(vix)
        r_scale = self._regime_scale(regime_label)
        dd_scale = self._drawdown_scale(drawdown_pct)
        c_scale = _confidence_scale(win_prob)

        base = self._base_lots(equity)

        raw = base * r_scale * dd_scale * c_scale

        hard_cap = self.max_lots_cap
        risk_cap = None
        margin_cap = None

        if trade_max_loss_per_unit is not None and trade_max_loss_per_unit > 0:
            risk_pct = getattr(self.config, "monthly_max_risk_per_trade_pct", self.config.max_risk_per_trade_pct)
            risk_budget = equity * (risk_pct / 100.0)
            risk_per_lot = trade_max_loss_per_unit * self.config.lot_size
            risk_cap = int(risk_budget / risk_per_lot) if risk_per_lot > 0 else 0
            hard_cap = min(hard_cap, risk_cap)

        margin_pct = getattr(self.config, "monthly_max_margin_per_trade_pct", 20.0)
        if trade_margin_per_lot is not None and trade_margin_per_lot > 0:
            margin_budget = equity * (margin_pct / 100.0)
            margin_cap = int(margin_budget / trade_margin_per_lot)
            hard_cap = min(hard_cap, margin_cap)

        if trade_max_loss_per_unit is not None or trade_margin_per_lot is not None:
            if hard_cap <= 0:
                parts = [f"base {base:.1f}", f"regime={regime_label}({r_scale}x)"]
                if c_scale != 1.0:
                    parts.append(f"conf {c_scale:.1f}x")
                if risk_cap is not None:
                    parts.append(f"risk_cap={risk_cap}")
                if margin_cap is not None:
                    parts.append(f"margin_cap={margin_cap}")
                return SizingDecision(
                    lots=0,
                    base_lots=round(base, 2),
                    confidence_scale=c_scale,
                    regime_scale=r_scale,
                    dd_scale=dd_scale,
                    reason=" | ".join(parts) + " | budget too small",
                )
            lots = max(1, min(int(raw), hard_cap))
        else:
            lots = max(1, min(int(raw), hard_cap))

        parts = [f"base {base:.1f}"]
        if c_scale != 1.0:
            parts.append(f"conf {c_scale:.1f}x")
        parts.append(f"regime={regime_label}({r_scale}x)")
        if risk_cap is not None:
            parts.append(f"risk_cap={risk_cap}")
        if margin_cap is not None:
            parts.append(f"margin_cap={margin_cap}")
        if dd_scale < 1.0:
            parts.append(f"dd({dd_scale}x)")
        reason = " | ".join(parts)

        return SizingDecision(
            lots=lots,
            base_lots=round(base, 2),
            confidence_scale=c_scale,
            regime_scale=r_scale,
            dd_scale=dd_scale,
            reason=reason,
        )

    def record_trade_with_equity(self, pnl: float, equity_at_entry: float) -> None:
        """Store trade result with the equity at the time of entry for vol-target."""
        self._trade_returns.append(_TradeReturn(pnl, equity_at_entry))

    # ── Base lots (margin compounding → vol target) ─────────────────────

    def _base_lots(self, equity: float) -> float:
        margin_lots = self._margin_fallback(equity)
        if len(self._trade_returns) < _VOL_WARMUP:
            return margin_lots
        vol_lots = self._vol_target_lots(equity)
        return vol_lots if vol_lots > 0 else margin_lots

    def _regime_scale(self, regime_label: str) -> float:
        """
        Resolve regime scaling from config when present.

        This keeps the default behavior explicit while allowing controlled
        relaxation in experiments without touching the sizing logic again.
        """
        overrides = {
            "LOW_VOL": getattr(self.config, "monthly_low_vol_scale", REGIME_SCALE["LOW_VOL"]),
            "TRENDING": getattr(self.config, "monthly_trending_scale", REGIME_SCALE["TRENDING"]),
            "HIGH_VOL": getattr(self.config, "monthly_high_vol_scale", REGIME_SCALE["HIGH_VOL"]),
            "CRASH": getattr(self.config, "monthly_crash_scale", REGIME_SCALE["CRASH"]),
        }
        return overrides.get(regime_label, REGIME_SCALE.get(regime_label, 0.90))

    def _drawdown_scale(self, dd_pct: float) -> float:
        """Config-aware drawdown scaling with the same band structure."""
        bands = [
            (0.05, getattr(self.config, "monthly_dd_scale_1", 1.00)),
            (0.10, getattr(self.config, "monthly_dd_scale_2", 0.85)),
            (0.15, getattr(self.config, "monthly_dd_scale_3", 0.65)),
            (1.00, getattr(self.config, "monthly_dd_scale_4", 0.45)),
        ]
        for upper, scale in bands:
            if dd_pct <= upper:
                return scale
        return bands[-1][1]

    def _vol_target_lots(self, equity: float) -> float:
        """
        Size so portfolio annualised vol stays near target.

        Uses exponential-decay-weighted std of recent trade returns,
        with each return computed against the equity at that trade's entry.
        """
        window = self._trade_returns[-60:]
        returns = [tr.ret for tr in window]

        n = len(returns)
        alpha = 2.0 / (n + 1)
        weights = [(1 - alpha) ** (n - 1 - i) for i in range(n)]
        w_sum = sum(weights)
        w_mean = sum(w * r for w, r in zip(weights, returns)) / w_sum
        w_var = sum(w * (r - w_mean) ** 2 for w, r in zip(weights, returns)) / w_sum
        realised_vol_per_trade = math.sqrt(w_var) if w_var > 0 else 0.001

        avg_hold_days = 14.0
        trades_per_year = 252.0 / avg_hold_days
        annualised_vol = realised_vol_per_trade * math.sqrt(trades_per_year)

        if annualised_vol < 0.001:
            return self._margin_fallback(equity)

        scale = self.target_annual_vol / annualised_vol
        base = self._margin_fallback(equity)
        return max(1.0, base * scale)

    def _margin_fallback(self, equity: float) -> float:
        """Margin-based compounding (the original sizing logic)."""
        margin_per_lot = 500 * self.config.lot_size
        alloc_pct = 0.80
        return max(1.0, equity * alloc_pct / margin_per_lot)
