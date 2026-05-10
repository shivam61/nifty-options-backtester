"""
Tests for pricing/black_scholes.py

Covers:
- Call/put pricing sanity (positive premium, correct intrinsic)
- Put-call parity relationship
- Greeks sign conventions (delta, theta, vega)
- IV smile model (OTM puts have higher IV than ATM)
- Edge cases (deep ITM, deep OTM, near-expiry)
"""

import pytest
import numpy as np

from pricing.black_scholes import (
    price_option, iv_from_vix, price_spread,
    OptionType, OptionPrice, OptionGreeks,
)


# ---------------------------------------------------------------------------
# Basic pricing
# ---------------------------------------------------------------------------

class TestPriceOption:

    def test_call_premium_positive(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.premium > 0

    def test_put_premium_positive(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.PUT)
        assert result.premium > 0

    def test_atm_call_has_zero_intrinsic(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.intrinsic == 0.0

    def test_itm_call_has_positive_intrinsic(self):
        result = price_option(22500, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.intrinsic > 0
        assert result.intrinsic == pytest.approx(500.0, abs=1.0)

    def test_itm_put_has_positive_intrinsic(self):
        result = price_option(21500, 22000, 21, 15.0, 0.065, OptionType.PUT)
        assert result.intrinsic > 0
        assert result.intrinsic == pytest.approx(500.0, abs=1.0)

    def test_otm_call_intrinsic_is_zero(self):
        result = price_option(22000, 23000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.intrinsic == 0.0

    def test_otm_put_intrinsic_is_zero(self):
        result = price_option(22000, 21000, 21, 15.0, 0.065, OptionType.PUT)
        assert result.intrinsic == 0.0

    def test_time_value_is_nonnegative(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.time_value >= 0

    def test_higher_iv_means_higher_premium(self):
        low_iv = price_option(22000, 22000, 21, 12.0, 0.065, OptionType.CALL)
        high_iv = price_option(22000, 22000, 21, 25.0, 0.065, OptionType.CALL)
        assert high_iv.premium > low_iv.premium

    def test_longer_dte_means_higher_premium(self):
        short = price_option(22000, 22000, 7, 15.0, 0.065, OptionType.CALL)
        long = price_option(22000, 22000, 45, 15.0, 0.065, OptionType.CALL)
        assert long.premium > short.premium

    def test_zero_dte_returns_intrinsic(self):
        call = price_option(22500, 22000, 0, 15.0, 0.065, OptionType.CALL)
        assert call.premium == pytest.approx(500.0, abs=5.0)

    def test_deep_otm_put_has_small_premium(self):
        result = price_option(22000, 18000, 21, 15.0, 0.065, OptionType.PUT)
        assert result.premium < 5.0

    def test_returns_option_price_dataclass(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert isinstance(result, OptionPrice)
        assert isinstance(result.greeks, OptionGreeks)
        assert result.dte == 21
        assert result.iv == 15.0


# ---------------------------------------------------------------------------
# Put-call parity
# ---------------------------------------------------------------------------

class TestPutCallParity:

    def test_atm_parity(self):
        """C - P ≈ S - K*exp(-rT) for ATM options."""
        S, K, dte, iv, r = 22000, 22000, 30, 15.0, 0.065
        call = price_option(S, K, dte, iv, r, OptionType.CALL)
        put = price_option(S, K, dte, iv, r, OptionType.PUT)
        T = dte / 365.0
        expected_diff = S - K * np.exp(-r * T)
        actual_diff = call.premium - put.premium
        assert actual_diff == pytest.approx(expected_diff, rel=0.01)


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------

class TestGreeks:

    def test_call_delta_between_0_and_1(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert 0.0 < result.greeks.delta < 1.0

    def test_put_delta_between_neg1_and_0(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.PUT)
        assert -1.0 < result.greeks.delta < 0.0

    def test_atm_call_delta_near_05(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.greeks.delta == pytest.approx(0.55, abs=0.1)

    def test_gamma_positive_for_all_options(self):
        call = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        put = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.PUT)
        assert call.greeks.gamma > 0
        assert put.greeks.gamma > 0

    def test_theta_negative_for_atm_options(self):
        """ATM options lose value with time (theta < 0)."""
        call = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert call.greeks.theta < 0

    def test_vega_positive(self):
        result = price_option(22000, 22000, 21, 15.0, 0.065, OptionType.CALL)
        assert result.greeks.vega > 0


# ---------------------------------------------------------------------------
# IV from VIX (smile model)
# ---------------------------------------------------------------------------

class TestIVFromVix:

    def test_atm_call_iv_equals_vix(self):
        iv = iv_from_vix(15.0, 22000, 22000, OptionType.CALL)
        assert iv == pytest.approx(15.0, abs=0.01)

    def test_atm_put_iv_equals_vix(self):
        iv = iv_from_vix(15.0, 22000, 22000, OptionType.PUT)
        assert iv == pytest.approx(15.0, abs=0.01)

    def test_otm_put_has_higher_iv_than_atm(self):
        """Volatility skew: OTM puts have higher IV."""
        atm_iv = iv_from_vix(15.0, 22000, 22000, OptionType.PUT)
        otm_iv = iv_from_vix(15.0, 20000, 22000, OptionType.PUT)
        assert otm_iv > atm_iv

    def test_otm_call_has_higher_iv_than_atm(self):
        atm_iv = iv_from_vix(15.0, 22000, 22000, OptionType.CALL)
        otm_iv = iv_from_vix(15.0, 24000, 22000, OptionType.CALL)
        assert otm_iv > atm_iv

    def test_put_skew_steeper_than_call(self):
        """Equity markets: put skew is steeper than call skew."""
        call_skew = iv_from_vix(15.0, 24000, 22000, OptionType.CALL) - 15.0
        put_skew = iv_from_vix(15.0, 20000, 22000, OptionType.PUT) - 15.0
        assert put_skew > call_skew

    def test_iv_scales_with_vix(self):
        low = iv_from_vix(12.0, 20000, 22000, OptionType.PUT)
        high = iv_from_vix(25.0, 20000, 22000, OptionType.PUT)
        assert high > low


# ---------------------------------------------------------------------------
# Spread pricing
# ---------------------------------------------------------------------------

class TestPriceSpread:

    def test_bull_put_spread_has_positive_credit(self):
        spread = price_spread(22000, 21000, 20000, 21, 15.0, 0.065, OptionType.PUT)
        assert spread["net_credit"] > 0

    def test_max_loss_equals_width_minus_credit(self):
        spread = price_spread(22000, 21000, 20000, 21, 15.0, 0.065, OptionType.PUT)
        assert spread["max_loss"] == pytest.approx(
            spread["width"] - spread["net_credit"], abs=0.1
        )

    def test_call_credit_spread_has_positive_credit(self):
        spread = price_spread(22000, 23000, 24000, 21, 15.0, 0.065, OptionType.CALL)
        assert spread["net_credit"] > 0

    def test_short_option_decays_faster_than_long(self):
        """Short leg (closer to ATM) has more theta than long leg (further OTM)."""
        spread = price_spread(22000, 21000, 20000, 21, 15.0, 0.065, OptionType.PUT)
        short_theta = abs(spread["short"].greeks.theta)
        long_theta = abs(spread["long"].greeks.theta)
        assert short_theta > long_theta
