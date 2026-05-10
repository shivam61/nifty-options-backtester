"""
Signal generator that classifies market regime and generates trade signals.
Learns from historical patterns to determine optimal entry/exit conditions.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from config import MarketRegime


@dataclass
class TradeSignal:
    """Generated trade signal with confidence and reasoning."""
    action: str              # "enter_iron_condor", "enter_put_spread", "no_trade", "exit"
    confidence: float        # 0.0 to 1.0
    regime: MarketRegime
    reasoning: list[str]
    suggested_params: dict   # strike distances, widths, DTE, etc.


class SignalGenerator:
    """
    Generates trade signals based on multi-factor analysis.

    Factors analyzed:
    1. VIX Level & Trend (primary)
    2. VIX-Realized Vol Spread (volatility risk premium)
    3. Nifty Trend (SMA crossovers, momentum)
    4. Crude Oil Impact
    5. Market Range (daily range as % of spot)
    6. Historical Pattern Matching
    """

    def __init__(self, historical_data: pd.DataFrame):
        self.data = historical_data
        self._learn_patterns()

    def _learn_patterns(self):
        """Analyze historical data to learn profitable patterns."""
        df = self.data.copy()

        self.vix_percentiles = {}
        if "vix" in df.columns:
            vix_clean = df["vix"].dropna()
            for p in [10, 25, 50, 75, 90]:
                self.vix_percentiles[p] = np.percentile(vix_clean, p)

        self.avg_daily_range = df.get("nifty_daily_range_pct", pd.Series([1.5])).mean()

        if "vix" in df.columns and "nifty_return" in df.columns:
            df["vix_bucket"] = pd.cut(
                df["vix"],
                bins=[0, 12, 15, 18, 22, 28, 50],
                labels=["very_low", "low", "medium", "high", "very_high", "extreme"],
            )

            self.regime_stats = {}
            for regime in df["vix_bucket"].dropna().unique():
                mask = df["vix_bucket"] == regime
                subset = df[mask]
                self.regime_stats[regime] = {
                    "avg_daily_return": subset["nifty_return"].mean(),
                    "vol": subset["nifty_return"].std() * np.sqrt(252) * 100,
                    "avg_range": subset.get("nifty_daily_range_pct", pd.Series([1.5])).mean(),
                    "count": len(subset),
                    "mean_reversion_5d": self._calc_mean_reversion(subset),
                }

        if "vix" in df.columns:
            vix = df["vix"].dropna()
            self.vix_mean = vix.mean()
            self.vix_std = vix.std()
            self.vix_mean_reversion_rate = self._calc_vix_mean_reversion(df)

    def _calc_mean_reversion(self, df: pd.DataFrame) -> float:
        """How likely is the market to revert after big moves in this regime."""
        if "nifty_return" not in df.columns or len(df) < 10:
            return 0.0
        returns = df["nifty_return"].dropna()
        big_down = returns[returns < -0.01]
        if len(big_down) < 3:
            return 0.0
        future_5d = df["nifty_return_5d"].shift(-5).dropna()
        aligned = pd.concat([returns, future_5d], axis=1).dropna()
        if len(aligned) < 5:
            return 0.0
        return aligned.iloc[:, 1][aligned.iloc[:, 0] < -0.01].mean()

    def _calc_vix_mean_reversion(self, df: pd.DataFrame) -> float:
        """Calculate VIX mean reversion speed."""
        if "vix" not in df.columns:
            return 0.5
        vix = df["vix"].dropna()
        if len(vix) < 20:
            return 0.5
        above_mean = vix[vix > vix.mean()]
        if len(above_mean) < 5:
            return 0.5
        days_to_revert = []
        above_start = None
        for i, (idx, v) in enumerate(vix.items()):
            if v > vix.mean() * 1.1 and above_start is None:
                above_start = i
            elif v <= vix.mean() and above_start is not None:
                days_to_revert.append(i - above_start)
                above_start = None
        return np.mean(days_to_revert) if days_to_revert else 20.0

    def classify_regime(self, row: pd.Series) -> MarketRegime:
        """Classify current market conditions into a regime."""
        vix = row.get("vix")
        if vix is None or pd.isna(vix):
            vix = 15
        nifty_return_5d = row.get("nifty_return_5d", 0)
        crude_change = row.get("crude_change_5d", 0)
        daily_range = row.get("nifty_daily_range_pct", 1.5)

        if vix < 14:
            vix_level = "low"
        elif vix < 22:
            vix_level = "medium"
        elif vix < 28:
            vix_level = "high"
        else:
            vix_level = "extreme"

        if nifty_return_5d > 0.02:
            trend = "bullish"
        elif nifty_return_5d < -0.02:
            trend = "bearish"
        else:
            trend = "neutral"

        if not pd.isna(crude_change):
            if crude_change > 0.05:
                crude_impact = "negative"
            elif crude_change < -0.05:
                crude_impact = "positive"
            else:
                crude_impact = "neutral"
        else:
            crude_impact = "neutral"

        if daily_range > 3.0:
            event_risk = "high"
        elif daily_range > 2.0:
            event_risk = "medium"
        else:
            event_risk = "low"

        return MarketRegime(
            vix_level=vix_level,
            trend=trend,
            crude_impact=crude_impact,
            event_risk=event_risk,
        )

    def generate_signal(self, row: pd.Series) -> TradeSignal:
        """Generate a trade signal based on current market data."""
        regime = self.classify_regime(row)
        reasoning = []
        confidence = 0.5

        raw_vix = row.get("vix")
        vix = raw_vix if raw_vix is not None and not pd.isna(raw_vix) else 15
        vix_change_5d = row.get("vix_change_5d", 0)
        vol_risk_premium = row.get("vol_risk_premium", 0)
        nifty_return_5d = row.get("nifty_return_5d", 0)
        daily_range = row.get("nifty_daily_range_pct", 1.5)
        raw_spot = row.get("nifty_close")
        spot = raw_spot if raw_spot is not None and not pd.isna(raw_spot) else 0

        # Factor 1: VIX level and percentile
        if hasattr(self, "vix_percentiles") and self.vix_percentiles:
            if vix > self.vix_percentiles.get(75, 22):
                reasoning.append(f"VIX at {vix:.1f} is above 75th percentile — rich premiums to sell")
                confidence += 0.1
            elif vix < self.vix_percentiles.get(25, 14):
                reasoning.append(f"VIX at {vix:.1f} is below 25th percentile — premiums too thin")
                confidence -= 0.2

        # Factor 2: VIX trend (mean reversion signal)
        if not pd.isna(vix_change_5d):
            if vix_change_5d > 0.20:
                reasoning.append("VIX spiking +20% in 5 days — wait for stabilization")
                confidence -= 0.15
            elif vix_change_5d < -0.10:
                reasoning.append("VIX declining — mean reversion in progress, good entry")
                confidence += 0.15
            elif -0.05 <= vix_change_5d <= 0.05:
                reasoning.append("VIX stable — safe to enter")
                confidence += 0.05

        # Factor 3: Volatility Risk Premium
        if not pd.isna(vol_risk_premium) and vol_risk_premium > 0:
            if vol_risk_premium > 5:
                reasoning.append(f"VRP of {vol_risk_premium:.1f} — implied vol much higher than realized, edge in selling")
                confidence += 0.15
            elif vol_risk_premium > 2:
                reasoning.append(f"VRP of {vol_risk_premium:.1f} — moderate edge in selling premium")
                confidence += 0.05

        # Factor 4: Market trend
        if abs(nifty_return_5d) > 0.05:
            reasoning.append(f"Nifty moved {nifty_return_5d*100:.1f}% in 5 days — too volatile for Iron Condor")
            confidence -= 0.15
        elif abs(nifty_return_5d) < 0.02:
            reasoning.append("Nifty range-bound — ideal for Iron Condor")
            confidence += 0.1

        # Factor 5: Daily range
        if daily_range > 3.0:
            reasoning.append(f"Daily range {daily_range:.1f}% — extreme intraday moves, skip")
            confidence -= 0.2
        elif daily_range < 1.5:
            reasoning.append(f"Daily range {daily_range:.1f}% — calm market, good for premium selling")
            confidence += 0.05

        # Factor 6: Crude oil
        crude_change = row.get("crude_change_5d", 0)
        if not pd.isna(crude_change) and abs(crude_change) > 0.10:
            reasoning.append(f"Crude moved {crude_change*100:.1f}% in 5 days — macro headwind")
            confidence -= 0.1

        confidence = max(0.0, min(1.0, confidence))

        action = regime.recommended_strategy
        if confidence < 0.3:
            action = "no_trade"

        # Suggest parameters based on regime
        # Multipliers calibrated to real trader behavior (0.15-0.40 SD)
        if regime.vix_level == "high":
            call_sd, put_sd = 0.25, 0.35
            hedge_width = 1000
            dte = 28
        elif regime.vix_level == "extreme":
            call_sd, put_sd = 0.20, 0.30
            hedge_width = 1000
            dte = 21
        elif regime.vix_level == "medium":
            call_sd, put_sd = 0.30, 0.30
            hedge_width = 1000
            dte = 21
        else:
            call_sd, put_sd = 0.40, 0.40
            hedge_width = 500
            dte = 14

        suggested_params = {
            "call_sd": call_sd,
            "put_sd": put_sd,
            "hedge_width": hedge_width,
            "target_dte": dte,
            "lots": 2,
            "profit_target_pct": 50 if regime.vix_level in ("high", "extreme") else 40,
        }

        return TradeSignal(
            action=action,
            confidence=confidence,
            regime=regime,
            reasoning=reasoning,
            suggested_params=suggested_params,
        )

    def analyze_regime_performance(self) -> pd.DataFrame:
        """Analyze historical performance characteristics per VIX regime."""
        if not hasattr(self, "regime_stats"):
            return pd.DataFrame()

        rows = []
        for regime, stats in self.regime_stats.items():
            rows.append({
                "VIX Regime": regime,
                "Avg Daily Return": f"{stats['avg_daily_return']*100:.3f}%",
                "Annualized Vol": f"{stats['vol']:.1f}%",
                "Avg Daily Range": f"{stats['avg_range']:.2f}%",
                "Trading Days": stats["count"],
                "Mean Reversion 5d": f"{stats['mean_reversion_5d']*100:.2f}%",
            })
        return pd.DataFrame(rows)
