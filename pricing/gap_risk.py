"""
Gap Risk Model — models overnight gaps as discontinuities, not returns.

First principle: close-to-close return is NOT a continuous process.
  close_to_close = overnight_gap + intraday_move
  overnight_gap  = open_t / close_{t-1} - 1
  intraday_move  = close_t / open_t - 1

This module:
  1. Decomposes historical data into gap + intraday distributions
  2. Fits tail percentiles (P95, P99, P99.5) for gap events
  3. Models the IV shock that accompanies large gaps:
       IV_new = IV * (1 + k * |gap|),  k ≈ 2-4
  4. Reprices an option spread under gap + IV shock to compute true worst-case
     loss — the number a stop-loss CANNOT protect you from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from pricing.black_scholes import price_option, iv_from_vix, OptionType


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GapDistribution:
    """Statistical profile of overnight gaps from historical data."""
    n_samples: int = 0
    mean_gap_pct: float = 0.0
    std_gap_pct: float = 0.0
    mean_intraday_pct: float = 0.0
    std_intraday_pct: float = 0.0
    # Tail percentiles — these are the numbers that matter
    gap_p95_down: float = 0.0    # 95th percentile downside gap (negative)
    gap_p99_down: float = 0.0    # 99th percentile downside gap
    gap_p995_down: float = 0.0   # 99.5th percentile downside gap
    gap_p95_up: float = 0.0      # 95th percentile upside gap
    gap_p99_up: float = 0.0
    gap_p995_up: float = 0.0
    gap_max_down: float = 0.0    # worst historical gap
    gap_max_up: float = 0.0
    # Conditional: gap distribution when VIX is already elevated (> 20)
    high_vix_mean_gap: float = 0.0
    high_vix_std_gap: float = 0.0
    high_vix_p99_down: float = 0.0


@dataclass
class GapScenarioResult:
    """Result of repricing a position under a gap + IV shock scenario."""
    gap_pct: float
    iv_shock_pct: float
    spot_after_gap: float
    vix_after_shock: float
    pnl_per_unit: float
    loss_vs_entry_credit_pct: float
    exceeds_max_loss: bool


@dataclass
class GapStressReport:
    """Full stress test output for a single trade."""
    entry_credit: float
    theoretical_max_loss: float
    scenarios: list[GapScenarioResult] = field(default_factory=list)
    worst_case_loss_per_unit: float = 0.0
    worst_case_gap_pct: float = 0.0
    true_risk_per_unit: float = 0.0
    true_risk_total: float = 0.0


# ── Gap Risk Model ────────────────────────────────────────────────────────────

GAP_SCENARIOS_PCT = [-1.0, -2.0, -3.0, -5.0, -8.0, 1.0, 2.0, 3.0, 5.0]

# IV shock coefficient: IV_new = IV * (1 + k * |gap|)
# Empirically, k ≈ 2.5 for NIFTY. During COVID, a 10% gap doubled IV → k ≈ 2.
# For extreme tails (> 5% gap), k can reach 4.
IV_SHOCK_K_DEFAULT = 2.5
IV_SHOCK_K_EXTREME = 4.0  # used when |gap| > 5%


class GapRiskModel:
    """
    Builds a gap distribution from historical OHLC data and uses it to
    stress-test option positions under realistic discontinuity scenarios.
    """

    def __init__(self, iv_shock_k: float = IV_SHOCK_K_DEFAULT):
        self.iv_shock_k = iv_shock_k
        self.distribution: Optional[GapDistribution] = None
        self._gap_series: Optional[pd.Series] = None
        self._intraday_series: Optional[pd.Series] = None

    # ── 1. Fit from historical data ──────────────────────────────────────

    def fit(self, data: pd.DataFrame) -> GapDistribution:
        """
        Decompose historical close-to-close returns into overnight gaps and
        intraday moves, then compute the full distribution profile.

        Expects columns: nifty_open, nifty_close. Optionally: vix.
        """
        required = {"nifty_open", "nifty_close"}
        if not required.issubset(data.columns):
            raise ValueError(f"Data must contain columns: {required}")

        close_prev = data["nifty_close"].shift(1)
        open_curr = data["nifty_open"]
        close_curr = data["nifty_close"]

        overnight_gap = (open_curr / close_prev - 1) * 100  # in %
        intraday_move = (close_curr / open_curr - 1) * 100

        overnight_gap = overnight_gap.dropna().replace([np.inf, -np.inf], np.nan).dropna()
        intraday_move = intraday_move.dropna().replace([np.inf, -np.inf], np.nan).dropna()

        self._gap_series = overnight_gap
        self._intraday_series = intraday_move

        down_gaps = overnight_gap[overnight_gap < 0]
        up_gaps = overnight_gap[overnight_gap > 0]

        dist = GapDistribution(
            n_samples=len(overnight_gap),
            mean_gap_pct=float(overnight_gap.mean()),
            std_gap_pct=float(overnight_gap.std()),
            mean_intraday_pct=float(intraday_move.mean()),
            std_intraday_pct=float(intraday_move.std()),

            gap_p95_down=float(np.percentile(down_gaps, 5)) if len(down_gaps) > 0 else 0,
            gap_p99_down=float(np.percentile(down_gaps, 1)) if len(down_gaps) > 0 else 0,
            gap_p995_down=float(np.percentile(down_gaps, 0.5)) if len(down_gaps) > 0 else 0,
            gap_p95_up=float(np.percentile(up_gaps, 95)) if len(up_gaps) > 0 else 0,
            gap_p99_up=float(np.percentile(up_gaps, 99)) if len(up_gaps) > 0 else 0,
            gap_p995_up=float(np.percentile(up_gaps, 99.5)) if len(up_gaps) > 0 else 0,
            gap_max_down=float(overnight_gap.min()),
            gap_max_up=float(overnight_gap.max()),
        )

        # Conditional distribution: gaps when VIX > 20 (stressed markets gap harder)
        if "vix" in data.columns:
            vix_aligned = data["vix"].reindex(overnight_gap.index)
            high_vix_mask = vix_aligned > 20
            high_vix_gaps = overnight_gap[high_vix_mask]
            if len(high_vix_gaps) > 10:
                dist.high_vix_mean_gap = float(high_vix_gaps.mean())
                dist.high_vix_std_gap = float(high_vix_gaps.std())
                hv_down = high_vix_gaps[high_vix_gaps < 0]
                if len(hv_down) > 5:
                    dist.high_vix_p99_down = float(np.percentile(hv_down, 1))

        self.distribution = dist
        return dist

    # ── 2. IV Shock Model ────────────────────────────────────────────────

    def iv_after_gap(self, current_vix: float, gap_pct: float) -> float:
        """
        Compute post-gap IV.
        IV_new = VIX * (1 + k * |gap|)

        k scales up for extreme gaps (> 5%): crashes don't just move IV linearly,
        they cause regime shifts in the vol surface.
        """
        abs_gap = abs(gap_pct) / 100.0  # convert from % to decimal
        k = IV_SHOCK_K_EXTREME if abs(gap_pct) > 5.0 else self.iv_shock_k
        shocked_vix = current_vix * (1.0 + k * abs_gap)
        return min(shocked_vix, 120.0)  # cap at 120% IV (2020 COVID peak was ~90)

    # ── 3. Stress-test a Spread Position ─────────────────────────────────

    def stress_test_spread(
        self,
        spot: float,
        vix: float,
        short_strike: float,
        long_strike: float,
        dte: int,
        entry_credit: float,
        option_type: OptionType,
        lots: int = 1,
        lot_size: int = 65,
        risk_free_rate: float = 0.065,
        scenarios_pct: Optional[list[float]] = None,
    ) -> GapStressReport:
        """
        Reprice a vertical spread under multiple gap + IV shock scenarios.
        Returns the true worst-case loss — the risk your stop-loss cannot protect.
        """
        if scenarios_pct is None:
            scenarios_pct = GAP_SCENARIOS_PCT

        width = abs(short_strike - long_strike)
        theoretical_max_loss = width - entry_credit

        report = GapStressReport(
            entry_credit=entry_credit,
            theoretical_max_loss=theoretical_max_loss,
        )

        for gap_pct in scenarios_pct:
            gap_decimal = gap_pct / 100.0
            spot_after = spot * (1.0 + gap_decimal)
            vix_after = self.iv_after_gap(vix, gap_pct)

            s_iv = iv_from_vix(vix_after, short_strike, spot_after, option_type, dte)
            l_iv = iv_from_vix(vix_after, long_strike, spot_after, option_type, dte)
            s_prem = price_option(spot_after, short_strike, dte, s_iv, risk_free_rate, option_type).premium
            l_prem = price_option(spot_after, long_strike, dte, l_iv, risk_free_rate, option_type).premium

            current_debit = s_prem - l_prem
            pnl_per_unit = entry_credit - current_debit

            result = GapScenarioResult(
                gap_pct=gap_pct,
                iv_shock_pct=((vix_after / vix) - 1.0) * 100,
                spot_after_gap=spot_after,
                vix_after_shock=vix_after,
                pnl_per_unit=pnl_per_unit,
                loss_vs_entry_credit_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
                exceeds_max_loss=(pnl_per_unit < 0 and abs(pnl_per_unit) > theoretical_max_loss),
            )
            report.scenarios.append(result)

        if report.scenarios:
            worst = min(report.scenarios, key=lambda s: s.pnl_per_unit)
            report.worst_case_loss_per_unit = abs(min(worst.pnl_per_unit, 0))
            report.worst_case_gap_pct = worst.gap_pct
            report.true_risk_per_unit = max(report.worst_case_loss_per_unit, theoretical_max_loss)
            report.true_risk_total = report.true_risk_per_unit * lots * lot_size

        return report

    def stress_test_iron_condor(
        self,
        spot: float,
        vix: float,
        sc_strike: float,
        lc_strike: float,
        sp_strike: float,
        lp_strike: float,
        dte: int,
        entry_credit: float,
        lots: int = 1,
        lot_size: int = 65,
        risk_free_rate: float = 0.065,
        scenarios_pct: Optional[list[float]] = None,
    ) -> GapStressReport:
        """Stress-test an iron condor (4 legs) under gap + IV shock."""
        if scenarios_pct is None:
            scenarios_pct = GAP_SCENARIOS_PCT

        width = max(abs(sc_strike - lc_strike), abs(sp_strike - lp_strike))
        theoretical_max_loss = width - entry_credit

        report = GapStressReport(
            entry_credit=entry_credit,
            theoretical_max_loss=theoretical_max_loss,
        )

        for gap_pct in scenarios_pct:
            gap_decimal = gap_pct / 100.0
            spot_after = spot * (1.0 + gap_decimal)
            vix_after = self.iv_after_gap(vix, gap_pct)

            sc_iv = iv_from_vix(vix_after, sc_strike, spot_after, OptionType.CALL, dte)
            lc_iv = iv_from_vix(vix_after, lc_strike, spot_after, OptionType.CALL, dte)
            sp_iv = iv_from_vix(vix_after, sp_strike, spot_after, OptionType.PUT, dte)
            lp_iv = iv_from_vix(vix_after, lp_strike, spot_after, OptionType.PUT, dte)

            sc_p = price_option(spot_after, sc_strike, dte, sc_iv, risk_free_rate, OptionType.CALL).premium
            lc_p = price_option(spot_after, lc_strike, dte, lc_iv, risk_free_rate, OptionType.CALL).premium
            sp_p = price_option(spot_after, sp_strike, dte, sp_iv, risk_free_rate, OptionType.PUT).premium
            lp_p = price_option(spot_after, lp_strike, dte, lp_iv, risk_free_rate, OptionType.PUT).premium

            current_debit = (sc_p - lc_p) + (sp_p - lp_p)
            pnl_per_unit = entry_credit - current_debit

            result = GapScenarioResult(
                gap_pct=gap_pct,
                iv_shock_pct=((vix_after / vix) - 1.0) * 100,
                spot_after_gap=spot_after,
                vix_after_shock=vix_after,
                pnl_per_unit=pnl_per_unit,
                loss_vs_entry_credit_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
                exceeds_max_loss=(pnl_per_unit < 0 and abs(pnl_per_unit) > theoretical_max_loss),
            )
            report.scenarios.append(result)

        if report.scenarios:
            worst = min(report.scenarios, key=lambda s: s.pnl_per_unit)
            report.worst_case_loss_per_unit = abs(min(worst.pnl_per_unit, 0))
            report.worst_case_gap_pct = worst.gap_pct
            report.true_risk_per_unit = max(report.worst_case_loss_per_unit, theoretical_max_loss)
            report.true_risk_total = report.true_risk_per_unit * lots * lot_size

        return report

    # ── 4. Inject gap into a daily simulation step ───────────────────────

    def apply_overnight_gap(
        self,
        prev_close: float,
        current_open: float,
        current_vix: float,
    ) -> tuple[float, float]:
        """
        Compute the actual overnight gap and the IV that should be used for
        repricing at the open. Call this at the start of each sim day.

        Returns: (gap_pct, vix_at_open)
        """
        if prev_close <= 0:
            return 0.0, current_vix

        gap_pct = (current_open / prev_close - 1.0) * 100.0
        if abs(gap_pct) < 0.3:
            return gap_pct, current_vix

        vix_at_open = self.iv_after_gap(current_vix, gap_pct)
        return gap_pct, vix_at_open

    # ── 5. Pretty-print ──────────────────────────────────────────────────

    def print_distribution(self) -> None:
        if self.distribution is None:
            print("  No distribution fitted. Call .fit(data) first.")
            return

        d = self.distribution
        print(f"\n  {'='*65}")
        print(f"  GAP RISK DISTRIBUTION  ({d.n_samples} trading days)")
        print(f"  {'='*65}")
        print(f"  {'Metric':<35} {'Value':>10}")
        print(f"  {'-'*50}")
        print(f"  {'Mean overnight gap':<35} {d.mean_gap_pct:>+10.3f}%")
        print(f"  {'Std overnight gap':<35} {d.std_gap_pct:>10.3f}%")
        print(f"  {'Mean intraday move':<35} {d.mean_intraday_pct:>+10.3f}%")
        print(f"  {'Std intraday move':<35} {d.std_intraday_pct:>10.3f}%")
        print(f"  {'-'*50}")
        print(f"  {'Downside gap P95':<35} {d.gap_p95_down:>+10.3f}%")
        print(f"  {'Downside gap P99':<35} {d.gap_p99_down:>+10.3f}%")
        print(f"  {'Downside gap P99.5':<35} {d.gap_p995_down:>+10.3f}%")
        print(f"  {'Worst historical gap down':<35} {d.gap_max_down:>+10.3f}%")
        print(f"  {'-'*50}")
        print(f"  {'Upside gap P95':<35} {d.gap_p95_up:>+10.3f}%")
        print(f"  {'Upside gap P99':<35} {d.gap_p99_up:>+10.3f}%")
        print(f"  {'Upside gap P99.5':<35} {d.gap_p995_up:>+10.3f}%")
        print(f"  {'Worst historical gap up':<35} {d.gap_max_up:>+10.3f}%")
        if d.high_vix_p99_down != 0:
            print(f"  {'-'*50}")
            print(f"  {'[High VIX >20] Mean gap':<35} {d.high_vix_mean_gap:>+10.3f}%")
            print(f"  {'[High VIX >20] Std gap':<35} {d.high_vix_std_gap:>10.3f}%")
            print(f"  {'[High VIX >20] P99 down gap':<35} {d.high_vix_p99_down:>+10.3f}%")

    @staticmethod
    def print_stress_report(report: GapStressReport, label: str = "") -> None:
        title = f"GAP STRESS TEST{f' — {label}' if label else ''}"
        print(f"\n  {'='*75}")
        print(f"  {title}")
        print(f"  {'='*75}")
        print(f"  Entry credit: {report.entry_credit:.2f} | "
              f"Theoretical max loss: {report.theoretical_max_loss:.2f}")
        print()
        print(f"  {'Gap':>6}  {'IV Shock':>9}  {'Spot After':>11}  {'VIX After':>10}  "
              f"{'PnL/unit':>10}  {'vs Credit':>10}  {'Breach?':>8}")
        print(f"  {'-'*72}")
        for s in report.scenarios:
            breach_str = "YES" if s.exceeds_max_loss else ""
            print(f"  {s.gap_pct:>+5.1f}%  {s.iv_shock_pct:>+8.1f}%  {s.spot_after_gap:>11,.0f}  "
                  f"{s.vix_after_shock:>9.1f}  {s.pnl_per_unit:>+10.1f}  "
                  f"{s.loss_vs_entry_credit_pct:>+9.0f}%  {breach_str:>8}")
        print(f"  {'-'*72}")
        print(f"  Worst-case gap: {report.worst_case_gap_pct:+.1f}%  ->  "
              f"loss/unit: {report.worst_case_loss_per_unit:.1f}  |  "
              f"TRUE RISK (total): {report.true_risk_total:,.0f}")
