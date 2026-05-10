"""
Multi-expiry strategy evaluator.

Instead of locking into a single target DTE, evaluates each eligible strategy
across 2-3 upcoming monthly expiries and selects the (strategy, expiry)
combination with the highest risk-adjusted expected value.

Scoring formula per (strategy, expiry) pair:
    EV = credit_collected × win_probability_estimate
       - max_loss × (1 - win_probability_estimate)

    Score = EV / sqrt(DTE)          # time-efficiency
          × theta_quality            # short leg decays faster than long
          × (1 - txn_drag)           # penalise short-DTE (frequent re-entry)
          + vega_bonus               # reward vega-positive in low IV
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from config import BacktestConfig
from data.expiry_calendar import get_monthly_expiry, get_upcoming_expiries
from pricing.black_scholes import price_option, iv_from_vix, OptionType
from strategies.base import BaseStrategy, TradeAction
from strategies.universe import ACTIVE_MONTHLY_STRATEGY_SET


@dataclass
class ExpiryCandidate:
    expiry: date
    dte: int
    strategy_name: str
    net_credit: float
    max_loss: float
    net_theta: float
    net_vega: float
    net_delta: float
    win_prob_estimate: float
    ev: float
    score: float
    reasoning: list[str]
    tail_risk_penalty: float = 0.0
    tail_adjusted_ev: float = 0.0
    risk_reward_ratio: float = 0.0
    min_short_dist_pct: float = 0.0
    regime: str = ""


def _vix_regime(vix: float) -> str:
    if vix < 14:
        return "LOW_VOL"
    if vix < 18:
        return "TRENDING"
    if vix < 25:
        return "HIGH_VOL"
    return "CRASH"


def _min_short_distance_pct(vix: float, config: BacktestConfig) -> float:
    regime = _vix_regime(vix)
    if regime == "LOW_VOL":
        return config.monthly_min_short_dist_pct_low_vol
    if regime == "TRENDING":
        return config.monthly_min_short_dist_pct_trending
    if regime == "HIGH_VOL":
        return config.monthly_min_short_dist_pct_high_vol
    return config.monthly_min_short_dist_pct_crash


def _regime_suitability(strategy_name: str, regime: str, vix: float) -> float:
    table = {
        "LOW_VOL": {
            "calendar_spread": 1.00,
            "iron_condor": 0.85,
            "put_credit_wide": 0.60,
            "put_credit_spread": 0.45,
            "broken_wing_butterfly": 0.25,
        },
        "TRENDING": {
            "put_credit_wide": 1.00,
            "put_credit_spread": 0.80,
            "iron_condor": 0.65,
            "broken_wing_butterfly": 0.40,
            "calendar_spread": 0.35,
        },
        "HIGH_VOL": {
            "put_credit_wide": 1.00,
            "iron_condor": 0.92,
            "broken_wing_butterfly": 0.78,
            "put_credit_spread": 0.62,
            "calendar_spread": 0.20,
        },
        "CRASH": {
            "broken_wing_butterfly": 0.82,
            "put_credit_wide": 0.38,
            "put_credit_spread": 0.22,
            "iron_condor": 0.25,
            "calendar_spread": 0.10,
        },
    }
    return table.get(regime, {}).get(strategy_name, 0.0)


def _tail_risk_penalty(
    *,
    strategy_name: str,
    net_credit: float,
    max_loss: float,
    min_short_dist_pct: float,
    min_short_dist_threshold: float,
    vix: float,
    dte: int,
    regime: str,
) -> float:
    """
    Penalise structures that are too asymmetric for the regime or too close
    to spot. This is a conservative proxy for overnight gap-down + IV expansion
    stress when a full stress-test is not available.
    """
    if net_credit <= 0 or max_loss <= 0:
        return float("inf")

    loss_credit_ratio = max_loss / max(net_credit, 1e-9)
    asymmetry = max(0.0, loss_credit_ratio - 1.0)
    distance_deficit = max(0.0, min_short_dist_threshold - min_short_dist_pct)
    vol_expansion = 1.0 + max(0.0, vix - 18.0) / 20.0
    gap_shock = min(0.20, 0.04 + max(0.0, 30 - dte) * 0.002 + max(0.0, vix - 20.0) * 0.003)

    base = max_loss * (
        0.02
        + 0.02 * asymmetry
        + 0.01 * distance_deficit
        + gap_shock * vol_expansion
    )

    regime_penalty = {
        "put_credit_spread": 1.15,
        "put_credit_wide": 0.92,
        "iron_condor": 0.80,
        "broken_wing_butterfly": 0.70,
        "calendar_spread": 0.65,
    }.get(strategy_name, 1.0)

    if regime == "HIGH_VOL" and strategy_name == "put_credit_spread":
        regime_penalty *= 1.15
    if regime == "CRASH" and strategy_name in {"put_credit_spread", "put_credit_wide"}:
        regime_penalty *= 1.25

    return base * regime_penalty


def _estimate_win_prob(
    vix: float, dte: int, net_credit: float, max_loss: float,
    distance_to_short_pct: float,
) -> float:
    """
    Heuristic win probability based on strike distance, VIX, and DTE.
    Not a replacement for ML — used for expiry comparison scoring only.

    Based on empirical observations:
    - 1 SD OTM with 21 DTE ≈ 68% probability of expiring worthless
    - Probability scales roughly linearly with SD distance
    - Higher VIX = wider expected move = lower probability at same strike
    """
    if max_loss <= 0:
        return 0.5

    annual_vol = vix / 100.0
    period_vol = annual_vol * math.sqrt(dte / 252.0)
    sd_distance = distance_to_short_pct / (period_vol * 100.0) if period_vol > 0 else 1.0

    base_prob = min(0.95, 0.50 + 0.18 * sd_distance)

    risk_reward = net_credit / max_loss if max_loss > 0 else 0
    rr_bonus = min(0.05, risk_reward * 0.10)

    return min(0.95, max(0.20, base_prob + rr_bonus))


STRATEGY_WIN_RATE_PRIORS = {
    "calendar_spread": 0.81,
    "put_credit_spread": 0.61,
    "broken_wing_butterfly": 0.39,
    "put_credit_wide": 0.75,
}


def _score_candidate(
    c: ExpiryCandidate, vix: float, brokerage_per_lot: float = 40.0,
    lots: int = 2, lot_size: int = 65,
) -> float:
    """
    Composite score blending EV, tail risk, regime suitability, capital
    efficiency, and directional edge.
    """
    if c.dte <= 0:
        return -999.0

    hist_wr = STRATEGY_WIN_RATE_PRIORS.get(c.strategy_name, 0.50)
    blended_wp = 0.55 * hist_wr + 0.45 * c.win_prob_estimate
    ev = c.net_credit * blended_wp - c.max_loss * (1 - blended_wp)
    tail_adj_ev = ev - c.tail_risk_penalty
    time_eff = tail_adj_ev / math.sqrt(c.dte) if c.dte > 0 else 0

    txn_cost = brokerage_per_lot * lots * 4
    credit_total = c.net_credit * lots * lot_size
    txn_drag = txn_cost / max(credit_total, 1.0) if credit_total > 0 else 0.5

    capital_efficiency = c.net_credit / max(c.max_loss, 1.0)
    directional_edge = max(-0.5, min(0.5, blended_wp - 0.5))
    regime_bonus = _regime_suitability(c.strategy_name, c.regime, vix)

    vega_bonus = 0.0
    if vix < 15 and c.net_vega > 0:
        vega_bonus = min(0.1, c.net_vega * 0.01)
    elif vix > 25 and c.net_vega < 0:
        vega_bonus = min(0.05, abs(c.net_vega) * 0.005)

    longer_dte_bonus = 0.0
    if c.dte >= 30:
        longer_dte_bonus = 0.05
    if c.dte >= 45:
        longer_dte_bonus = 0.10

    strike_dist_penalty = 0.0

    score = (
        tail_adj_ev
        + 0.20 * time_eff
        + 4.0 * capital_efficiency
        + 2.5 * directional_edge
        + 3.0 * regime_bonus
        + vega_bonus
        + longer_dte_bonus
        + strike_dist_penalty
        - (c.tail_risk_penalty * 0.15)
        - (c.max_loss / max(c.net_credit, 1.0) - 1.0) * 0.30
        - txn_drag * 2.0
    )

    return round(score, 4)


class ExpirySelector:
    """
    Evaluates multiple expiries for each eligible strategy and returns
    the best (strategy, expiry) pair.

    Usage:
        selector = ExpirySelector(spot=22000, vix=16, eligible=["put_credit_spread", ...])
        best = selector.select_best(entry_date=date.today(), strategies=strategy_dict)
        # best.strategy_name, best.expiry, best.dte, best.score
    """

    def __init__(
        self,
        spot: float,
        vix: float,
        eligible_strategies: list[str],
        lots: int = 2,
        lot_size: int = 65,
        risk_free_rate: float = 0.065,
        brokerage_per_lot: float = 40.0,
        num_expiries: int = 3,
        risk_config: BacktestConfig | None = None,
    ):
        self.spot = spot
        self.vix = vix
        self.eligible = [s for s in eligible_strategies if s in ACTIVE_MONTHLY_STRATEGY_SET]
        self.lots = lots
        self.lot_size = lot_size
        self.risk_free_rate = risk_free_rate
        self.brokerage_per_lot = brokerage_per_lot
        self.num_expiries = num_expiries
        self.risk_config = risk_config or BacktestConfig()

    def evaluate_all(
        self,
        entry_date: date,
        strategies: dict[str, BaseStrategy],
        diagnostics: dict | None = None,
    ) -> list[ExpiryCandidate]:
        """
        Evaluate every (strategy, expiry) combination and return scored list.
        """
        expiries = get_upcoming_expiries(entry_date, count=self.num_expiries)
        candidates = []

        if diagnostics is not None:
            diagnostics.setdefault("candidate_count", 0)
            diagnostics.setdefault("accepted_count", 0)
            diagnostics.setdefault("rejections", {})
            diagnostics.setdefault("candidate_rows", [])

        for exp_info in expiries:
            expiry = exp_info["expiry"]
            dte = exp_info["dte"]

            if dte < 7 or dte > 60:
                continue

            for strat_name in self.eligible:
                strat = strategies.get(strat_name)
                if strat is None:
                    continue

                candidate = self._evaluate_single(
                    strat, strat_name, expiry, dte, diagnostics=diagnostics
                )
                if candidate is not None:
                    candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def select_best(
        self,
        entry_date: date,
        strategies: dict[str, BaseStrategy],
        diagnostics: dict | None = None,
    ) -> Optional[ExpiryCandidate]:
        """
        Return the single best (strategy, expiry) combination,
        or None if no viable candidate exists.
        """
        candidates = self.evaluate_all(entry_date, strategies, diagnostics=diagnostics)
        return candidates[0] if candidates else None

    def _evaluate_single(
        self,
        strategy: BaseStrategy,
        strat_name: str,
        expiry: date,
        dte: int,
        diagnostics: dict | None = None,
    ) -> Optional[ExpiryCandidate]:
        """Price one strategy at one expiry and compute its score."""
        try:
            old_lots = strategy.lots
            strategy.lots = self.lots

            legs = strategy.generate_legs(
                self.spot, self.vix, dte, self.risk_free_rate,
            )
            strategy.lots = old_lots

            if not legs:
                return None

            if diagnostics is not None:
                diagnostics["candidate_count"] = diagnostics.get("candidate_count", 0) + 1

            net_credit = sum(
                l.entry_premium if l.is_short else -l.entry_premium
                for l in legs
            )

            short_legs = [l for l in legs if l.is_short]
            long_legs = [l for l in legs if not l.is_short]

            max_width = 0
            for sl in short_legs:
                for ll in long_legs:
                    if sl.option_type == ll.option_type:
                        max_width = max(max_width, abs(sl.strike - ll.strike))
            max_loss = max(0, max_width - net_credit) if max_width > 0 else abs(net_credit) * 5

            net_theta = 0.0
            net_vega = 0.0
            net_delta = 0.0
            for l in legs:
                ot = OptionType.CALL if l.option_type == "CE" else OptionType.PUT
                iv = iv_from_vix(self.vix, l.strike, self.spot, ot)
                leg_dte = dte
                if hasattr(strategy, "dte_gap") and not l.is_short:
                    leg_dte = dte + strategy.dte_gap

                priced = price_option(
                    self.spot, l.strike, leg_dte, iv, self.risk_free_rate, ot,
                )
                sign = -1 if l.is_short else 1
                ratio = l.lots / self.lots if self.lots > 0 else 1
                net_theta += -sign * priced.greeks.theta * ratio
                net_vega += sign * priced.greeks.vega * ratio
                net_delta += sign * priced.greeks.delta * ratio

            min_short_dist_pct = 100.0
            for sl in short_legs:
                if sl.option_type in ("PE", "PUT"):
                    dist = (self.spot - sl.strike) / self.spot * 100
                else:
                    dist = (sl.strike - self.spot) / self.spot * 100
                min_short_dist_pct = min(min_short_dist_pct, dist)
            regime = _vix_regime(self.vix)
            min_short_dist_threshold = _min_short_distance_pct(self.vix, self.risk_config)

            win_prob = _estimate_win_prob(
                self.vix, dte, net_credit, max_loss, min_short_dist_pct,
            )

            hist_wr = STRATEGY_WIN_RATE_PRIORS.get(strat_name, 0.50)
            blended_wp = 0.6 * hist_wr + 0.4 * win_prob
            ev = net_credit * blended_wp - max_loss * (1 - blended_wp)
            risk_reward_ratio = max_loss / max(net_credit, 1e-9)
            tail_penalty = _tail_risk_penalty(
                strategy_name=strat_name,
                net_credit=net_credit,
                max_loss=max_loss,
                min_short_dist_pct=min_short_dist_pct,
                min_short_dist_threshold=min_short_dist_threshold,
                vix=self.vix,
                dte=dte,
                regime=regime,
            )
            tail_adjusted_ev = ev - tail_penalty

            raw_ev_floor = getattr(self.risk_config, "monthly_min_raw_ev", -250.0)
            tail_ev_floor = getattr(self.risk_config, "monthly_min_tail_adjusted_ev", -1000.0)

            if ev < raw_ev_floor:
                if diagnostics is not None:
                    diagnostics["rejections"]["risk_constraints"] = diagnostics["rejections"].get("risk_constraints", 0) + 1
                return None
            if risk_reward_ratio > self.risk_config.monthly_max_loss_to_credit_ratio:
                if diagnostics is not None:
                    diagnostics["rejections"]["risk_constraints"] = diagnostics["rejections"].get("risk_constraints", 0) + 1
                return None
            if min_short_dist_pct < min_short_dist_threshold:
                if diagnostics is not None:
                    diagnostics["rejections"]["vol_filter"] = diagnostics["rejections"].get("vol_filter", 0) + 1
                return None
            if tail_adjusted_ev < tail_ev_floor:
                if diagnostics is not None:
                    diagnostics["rejections"]["risk_constraints"] = diagnostics["rejections"].get("risk_constraints", 0) + 1
                return None
            if _regime_suitability(strat_name, regime, self.vix) < 0.3:
                if diagnostics is not None:
                    diagnostics["rejections"]["regime_filter"] = diagnostics["rejections"].get("regime_filter", 0) + 1
                return None

            reasoning = []
            if dte >= 30:
                reasoning.append(f"Longer DTE ({dte}d) = more theta runway, fewer trades")
            if net_theta > 0:
                reasoning.append(f"Net theta +{net_theta:.2f}/day favours seller")
            if self.vix < 15 and net_vega > 0:
                reasoning.append("Vega-positive in low-IV environment")
            if blended_wp > 0.7:
                reasoning.append(f"High blended win probability ({blended_wp:.0%})")
            if hist_wr >= 0.70:
                reasoning.append(f"Historically strong strategy ({hist_wr:.0%} WR)")
            reasoning.append(f"Tail-adjusted EV {tail_adjusted_ev:+.2f} after gap/vol penalty")

            candidate = ExpiryCandidate(
                expiry=expiry,
                dte=dte,
                strategy_name=strat_name,
                net_credit=round(net_credit, 2),
                max_loss=round(max_loss, 2),
                net_theta=round(net_theta, 4),
                net_vega=round(net_vega, 4),
                net_delta=round(net_delta, 4),
                win_prob_estimate=round(blended_wp, 3),
                ev=round(ev, 2),
                score=0.0,
                reasoning=reasoning,
                tail_risk_penalty=round(tail_penalty, 2),
                tail_adjusted_ev=round(tail_adjusted_ev, 2),
                risk_reward_ratio=round(risk_reward_ratio, 2),
                min_short_dist_pct=round(min_short_dist_pct, 2),
                regime=regime,
            )
            candidate.score = _score_candidate(
                candidate, self.vix, self.brokerage_per_lot,
                self.lots, self.lot_size,
            )
            if diagnostics is not None:
                diagnostics["accepted_count"] = diagnostics.get("accepted_count", 0) + 1
                diagnostics["candidate_rows"].append({
                    "expiry": str(expiry),
                    "dte": int(dte),
                    "strategy_name": strat_name,
                    "net_credit": round(net_credit, 2),
                    "max_loss": round(max_loss, 2),
                    "win_prob": round(blended_wp, 3),
                    "ev": round(ev, 2),
                    "score": round(candidate.score, 4),
                    "tail_adjusted_ev": round(tail_adjusted_ev, 2),
                    "regime": regime,
                    "min_short_dist_pct": round(min_short_dist_pct, 2),
                })
            return candidate

        except Exception:
            return None


# ── Shared entry-point used by both backtest engine and signal mode ──

@dataclass
class EntryDecision:
    """Result of the unified multi-expiry entry evaluation."""
    strategy_name: str
    expiry: date
    dte: int
    best: ExpiryCandidate
    all_candidates: list[ExpiryCandidate]

    @property
    def found(self) -> bool:
        return True


class NoEntry:
    """Sentinel when ExpirySelector finds no viable candidate."""
    found: bool = False
    strategy_name: str = "no_trade"
    all_candidates: list = ()


def select_optimal_entry(
    spot: float,
    vix: float,
    strategies: dict[str, BaseStrategy],
    entry_date: date,
    lots: int,
    strategy_name: str | None = None,
    eligible_strategies: list[str] | None = None,
    lot_size: int = 65,
    risk_free_rate: float = 0.065,
    brokerage_per_lot: float = 40.0,
    risk_config: BacktestConfig | None = None,
    diagnostics: dict | None = None,
) -> EntryDecision | NoEntry:
    """
    Single shared function for multi-expiry optimisation.

    Both ``SmartBacktestEngine.run()`` and ``run_signal()`` call this
    to ensure identical strategy-selection and expiry-scoring logic.

    Returns an ``EntryDecision`` with the best candidate, or ``NoEntry``
    if no viable (strategy, expiry) pair was found.
    """
    effective_eligible = eligible_strategies or ([strategy_name] if strategy_name else [])
    effective_eligible = [s for s in effective_eligible if s in ACTIVE_MONTHLY_STRATEGY_SET]
    selector = ExpirySelector(
        spot=spot,
        vix=vix,
        eligible_strategies=effective_eligible,
        lots=lots,
        lot_size=lot_size,
        risk_free_rate=risk_free_rate,
        brokerage_per_lot=brokerage_per_lot,
        risk_config=risk_config,
    )
    candidates = selector.evaluate_all(entry_date, strategies, diagnostics=diagnostics)

    if not candidates:
        return NoEntry()

    best = candidates[0]
    return EntryDecision(
        strategy_name=best.strategy_name,
        expiry=best.expiry,
        dte=best.dte,
        best=best,
        all_candidates=candidates,
    )
