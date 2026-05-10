"""
Black-Scholes option pricing model for estimating Nifty option premiums.
Used in backtesting where historical option chain data isn't available.
Includes Greeks calculation for risk management.
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass
from enum import Enum


class OptionType(Enum):
    CALL = "CE"
    PUT = "PE"


@dataclass
class OptionGreeks:
    delta: float
    gamma: float
    theta: float  # per day
    vega: float   # per 1% IV change
    rho: float


@dataclass
class OptionPrice:
    premium: float
    intrinsic: float
    time_value: float
    greeks: OptionGreeks
    iv: float
    dte: int


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    return (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))


def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.0
    return _d1(S, K, T, r, sigma) - sigma * np.sqrt(T)


def price_option(
    spot: float,
    strike: float,
    dte: int,
    iv: float,
    risk_free_rate: float = 0.065,
    option_type: OptionType = OptionType.CALL,
) -> OptionPrice:
    """
    Price a European option using Black-Scholes.

    Args:
        spot: Current underlying price
        strike: Option strike price
        dte: Days to expiration
        iv: Implied volatility (as percentage, e.g. 25 for 25%)
        risk_free_rate: Annual risk-free rate (decimal)
        option_type: CALL or PUT
    """
    T = max(dte / 365.0, 1e-10)
    sigma = iv / 100.0
    S, K, r = spot, strike, risk_free_rate

    d1 = _d1(S, K, T, r, sigma)
    d2 = _d2(S, K, T, r, sigma)

    if option_type == OptionType.CALL:
        premium = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        intrinsic = max(S - K, 0)
        delta = norm.cdf(d1)
    else:
        premium = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        intrinsic = max(K - S, 0)
        delta = norm.cdf(d1) - 1

    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T)) if T > 0 and sigma > 0 else 0
    theta = (
        -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        - r * K * np.exp(-r * T) * norm.cdf(d2 if option_type == OptionType.CALL else -d2)
        * (1 if option_type == OptionType.CALL else -1)
    ) / 365.0
    vega = S * norm.pdf(d1) * np.sqrt(T) / 100.0
    rho_val = (
        K * T * np.exp(-r * T) * norm.cdf(d2 if option_type == OptionType.CALL else -d2)
        * (1 if option_type == OptionType.CALL else -1)
    ) / 100.0

    greeks = OptionGreeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho_val)

    return OptionPrice(
        premium=round(premium, 2),
        intrinsic=round(intrinsic, 2),
        time_value=round(premium - intrinsic, 2),
        greeks=greeks,
        iv=iv,
        dte=dte,
    )


def iv_from_vix(
    vix: float,
    strike: float,
    spot: float,
    option_type: OptionType = OptionType.CALL,
    dte: int = 21,
) -> float:
    """
    Estimate strike-level IV from VIX using an enhanced volatility smile model.

    v3 improvements over v2:
    - Steeper put skew (0.35 vs 0.25) matching NSE empirical data
    - Term structure: shorter DTE = higher IV (Nifty vol term structure)
    - Minimum IV floor to prevent zero-premium pricing artifacts
    """
    moneyness = strike / spot

    if option_type == OptionType.CALL:
        if moneyness > 1.0:
            skew_adjustment = 1.0 + 0.18 * (moneyness - 1.0) * 10
        else:
            skew_adjustment = 1.0
    else:
        if moneyness < 1.0:
            skew_adjustment = 1.0 + 0.35 * (1.0 - moneyness) * 10
        else:
            skew_adjustment = 1.0

    # Term structure: shorter DTE options trade at higher IV
    if dte <= 7:
        term_adj = 1.08
    elif dte <= 14:
        term_adj = 1.04
    elif dte <= 30:
        term_adj = 1.00
    else:
        term_adj = 0.97

    iv = vix * skew_adjustment * term_adj
    return max(iv, 5.0)  # floor: 5% IV minimum


def price_spread(
    spot: float,
    short_strike: float,
    long_strike: float,
    dte: int,
    vix: float,
    risk_free_rate: float = 0.065,
    option_type: OptionType = OptionType.CALL,
) -> dict:
    """Price a vertical spread (bull put or bear call)."""
    short_iv = iv_from_vix(vix, short_strike, spot, option_type, dte)
    long_iv = iv_from_vix(vix, long_strike, spot, option_type, dte)

    short_option = price_option(spot, short_strike, dte, short_iv, risk_free_rate, option_type)
    long_option = price_option(spot, long_strike, dte, long_iv, risk_free_rate, option_type)

    credit = short_option.premium - long_option.premium
    width = abs(short_strike - long_strike)
    max_loss = width - credit
    breakeven = (
        short_strike + credit if option_type == OptionType.CALL else short_strike - credit
    )

    return {
        "short": short_option,
        "long": long_option,
        "net_credit": round(credit, 2),
        "max_loss": round(max_loss, 2),
        "max_profit": round(credit, 2),
        "breakeven": round(breakeven, 2),
        "risk_reward": round(credit / max_loss, 3) if max_loss > 0 else float("inf"),
        "width": width,
        "net_delta": round(short_option.greeks.delta - long_option.greeks.delta, 4),
        "net_theta": round(short_option.greeks.theta - long_option.greeks.theta, 2),
        "net_vega": round(short_option.greeks.vega - long_option.greeks.vega, 2),
    }
