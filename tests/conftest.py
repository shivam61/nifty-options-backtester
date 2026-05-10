"""
Shared fixtures for the nifty-options-backtester test suite.

Provides synthetic market data, trade objects, and config objects
so that tests never depend on network calls or cached files.
"""

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta

from config import BacktestConfig, MarketRegime
from strategies.base import Leg, Trade


# ---------------------------------------------------------------------------
# Synthetic market data
# ---------------------------------------------------------------------------

def _make_market_data(
    n_days: int = 200,
    start_date: str = "2024-01-01",
    base_nifty: float = 22000.0,
    base_vix: float = 14.0,
) -> pd.DataFrame:
    """
    Build a minimal but complete synthetic market DataFrame that mirrors
    the column schema produced by MarketDataFetcher.build_combined_dataset().

    Returns a DataFrame indexed by DatetimeIndex with all columns that
    strategies, feature extractors, and the backtest engine expect.
    """
    rng = np.random.RandomState(42)
    dates = pd.bdate_range(start=start_date, periods=n_days)

    nifty_returns = rng.normal(0.0004, 0.012, n_days)
    nifty_close = base_nifty * np.cumprod(1 + nifty_returns)
    nifty_high = nifty_close * (1 + rng.uniform(0.002, 0.015, n_days))
    nifty_low = nifty_close * (1 - rng.uniform(0.002, 0.015, n_days))
    nifty_open = nifty_close * (1 + rng.normal(0, 0.003, n_days))

    vix = base_vix + np.cumsum(rng.normal(0, 0.3, n_days))
    vix = np.clip(vix, 8, 45)

    crude = 75 + np.cumsum(rng.normal(0, 0.5, n_days))
    usdinr = 83 + np.cumsum(rng.normal(0, 0.05, n_days))
    gold = 2000 + np.cumsum(rng.normal(0, 5, n_days))
    sp500 = 5000 + np.cumsum(rng.normal(0, 15, n_days))
    us_vix = 15 + np.cumsum(rng.normal(0, 0.2, n_days))
    us_vix = np.clip(us_vix, 8, 50)
    us_10y = 4.0 + np.cumsum(rng.normal(0, 0.01, n_days))
    nifty_bank = nifty_close * (2.1 + rng.normal(0, 0.01, n_days))
    dxy = 104 + np.cumsum(rng.normal(0, 0.1, n_days))
    em_etf = 40 + np.cumsum(rng.normal(0, 0.2, n_days))
    hang_seng = 17000 + np.cumsum(rng.normal(0, 100, n_days))
    europe = 60 + np.cumsum(rng.normal(0, 0.3, n_days))

    df = pd.DataFrame({
        "nifty_close": nifty_close,
        "nifty_high": nifty_high,
        "nifty_low": nifty_low,
        "nifty_open": nifty_open,
        "nifty_volume": rng.randint(100_000, 500_000, n_days),
        "vix": vix,
        "crude": crude,
        "usdinr": usdinr,
        "gold": gold,
        "sp500": sp500,
        "us_vix": us_vix,
        "us_10y": us_10y,
        "nifty_bank": nifty_bank,
        "dxy": dxy,
        "em_etf": em_etf,
        "hang_seng": hang_seng,
        "europe": europe,
    }, index=dates)

    df["nifty_return"] = df["nifty_close"].pct_change()
    df["nifty_return_5d"] = df["nifty_close"].pct_change(5)
    df["nifty_return_20d"] = df["nifty_close"].pct_change(20)
    df["nifty_sma_20"] = df["nifty_close"].rolling(20).mean()
    df["nifty_sma_50"] = df["nifty_close"].rolling(50).mean()

    df["nifty_realized_vol_10d"] = df["nifty_return"].rolling(10).std() * np.sqrt(252) * 100
    df["nifty_realized_vol_20d"] = df["nifty_return"].rolling(20).std() * np.sqrt(252) * 100

    df["vix_sma_10"] = df["vix"].rolling(10).mean()
    df["vix_change_1d"] = df["vix"].pct_change()
    df["vix_change_5d"] = df["vix"].pct_change(5)
    df["vix_vs_sma_ratio"] = df["vix"] / df["vix_sma_10"].replace(0, 1)
    df["vol_risk_premium"] = df["vix"] - df["nifty_realized_vol_20d"]

    df["nifty_daily_range_pct"] = (df["nifty_high"] - df["nifty_low"]) / df["nifty_close"] * 100

    delta = df["nifty_close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-10)
    df["nifty_rsi_14"] = 100 - (100 / (1 + rs))

    bb_sma = df["nifty_close"].rolling(20).mean()
    bb_std = df["nifty_close"].rolling(20).std()
    df["nifty_bb_width"] = (2 * bb_std / bb_sma * 100).fillna(3.0)

    df["overnight_gap_pct"] = (df["nifty_open"] - df["nifty_close"].shift(1)) / df["nifty_close"].shift(1) * 100
    df["nifty_distance_from_sma20_pct"] = (df["nifty_close"] - df["nifty_sma_20"]) / df["nifty_sma_20"] * 100
    df["nifty_distance_from_sma50_pct"] = (df["nifty_close"] - df["nifty_sma_50"]) / df["nifty_sma_50"] * 100

    df["crude_change_5d"] = df["crude"].pct_change(5)
    df["crude_change_20d"] = df["crude"].pct_change(20)
    df["usdinr_change_5d"] = df["usdinr"].pct_change(5)
    df["usdinr_change_20d"] = df["usdinr"].pct_change(20)
    df["gold_change_5d"] = df["gold"].pct_change(5)
    df["gold_change_20d"] = df["gold"].pct_change(20)
    df["sp500_return_5d"] = df["sp500"].pct_change(5)
    df["sp500_return_20d"] = df["sp500"].pct_change(20)
    df["us_vix_change_5d"] = df["us_vix"].pct_change(5)
    df["us_10y_change_5d"] = df["us_10y"].pct_change(5)
    df["bank_nifty_return_5d"] = df["nifty_bank"].pct_change(5)
    df["bank_nifty_ratio"] = df["nifty_bank"] / df["nifty_close"]
    df["dxy_change_5d"] = df["dxy"].pct_change(5)
    df["dxy_change_20d"] = df["dxy"].pct_change(20)
    df["em_return_5d"] = df["em_etf"].pct_change(5)
    df["em_return_20d"] = df["em_etf"].pct_change(20)
    df["china_return_5d"] = df["hang_seng"].pct_change(5)
    df["china_return_20d"] = df["hang_seng"].pct_change(20)
    df["europe_return_5d"] = df["europe"].pct_change(5)
    df["vix_premium_over_us"] = df["vix"] / df["us_vix"].replace(0, 1) - 1

    crude_z = (df["crude"] - df["crude"].rolling(50).mean()) / df["crude"].rolling(50).std().replace(0, 1)
    inr_z = (df["usdinr"] - df["usdinr"].rolling(50).mean()) / df["usdinr"].rolling(50).std().replace(0, 1)
    df["crude_inr_composite"] = crude_z + inr_z

    dxy_z = (df["dxy"] - df["dxy"].rolling(50).mean()) / df["dxy"].rolling(50).std().replace(0, 1)
    df["dxy_crude_composite"] = dxy_z + crude_z
    df["fii_flow_proxy"] = rng.normal(0, 0.02, n_days)

    df["vix_accel_3d_pct"] = df["vix"].pct_change(3) * 100
    df["crude_spike_10d_pct"] = df["crude"].pct_change(10) * 100

    daily_ret = df["nifty_close"].pct_change()
    streak = 0
    consec = np.zeros(n_days, dtype=int)
    for i, r in enumerate(daily_ret):
        if pd.notna(r) and r < 0:
            streak += 1
        else:
            streak = 0
        consec[i] = streak
    df["nifty_consec_down_days"] = consec

    rolling_high_20 = df["nifty_close"].rolling(20).max()
    df["nifty_drawdown_from_20d_high_pct"] = (df["nifty_close"] - rolling_high_20) / rolling_high_20 * 100
    rolling_high_50 = df["nifty_close"].rolling(50).max()
    df["nifty_drawdown_from_50d_high_pct"] = (df["nifty_close"] - rolling_high_50) / rolling_high_50 * 100

    df["vol_expansion_ratio"] = df["nifty_realized_vol_10d"] / df["nifty_realized_vol_20d"].replace(0, 1)
    df["crash_risk_score"] = 0.0
    df["crash_risk_score_v2"] = 0.05
    df["multi_asset_stress"] = 0.1
    df["vrp_change_5d"] = df["vol_risk_premium"].diff(5)
    df["vrp_negative"] = (df["vol_risk_premium"] < 0).astype(float)
    df["rvol_10d_z"] = (
        (df["nifty_realized_vol_10d"] - df["nifty_realized_vol_10d"].rolling(50).mean())
        / df["nifty_realized_vol_10d"].rolling(50).std().replace(0, 1)
    )

    range_sma5 = df["nifty_daily_range_pct"].rolling(5).mean()
    range_sma20 = df["nifty_daily_range_pct"].rolling(20).mean()
    df["range_expansion_ratio"] = range_sma5 / range_sma20.replace(0, 1)
    df["bn_ratio_change_5d"] = (df["nifty_bank"] / df["nifty_close"]).pct_change(5) * 100
    df["india_us_correlation_20d"] = df["nifty_return"].rolling(20).corr(df["sp500"].pct_change())
    df["correlation_spike_5d"] = df["india_us_correlation_20d"].diff(5)
    df["gap_magnitude_avg_5d"] = df["overnight_gap_pct"].abs().rolling(5).mean()
    df["intraday_dd_expanding_3d"] = (
        (df["nifty_low"] - df["nifty_open"]) / df["nifty_open"] * 100
    ).rolling(3).min()

    from data.news_sentiment import compute_price_action_sentiment
    df["sentiment_proxy"] = compute_price_action_sentiment(df)
    df["global_contagion_score"] = rng.normal(0, 0.1, n_days)

    return df.ffill().bfill()


@pytest.fixture
def market_data():
    """200-day synthetic market dataset with all derived features."""
    return _make_market_data(n_days=200)


@pytest.fixture
def short_market_data():
    """60-day small dataset for fast tests."""
    return _make_market_data(n_days=60, start_date="2024-06-01")


@pytest.fixture
def config():
    """Default backtest config."""
    return BacktestConfig(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 10, 15),
        initial_capital=500_000,
        max_lots=2,
        lot_size=65,
    )


@pytest.fixture
def sample_trade() -> Trade:
    """A sample iron-condor-style trade with 4 legs."""
    return Trade(
        strategy_name="iron_condor_v2",
        entry_date=date(2024, 6, 1),
        legs=[
            Leg("CE", 23000, True, 120.0, 120.0, 2, 65),
            Leg("CE", 24000, False, 30.0, 30.0, 2, 65),
            Leg("PE", 21000, True, 100.0, 100.0, 2, 65),
            Leg("PE", 20000, False, 25.0, 25.0, 2, 65),
        ],
        entry_spot=22000.0,
        entry_vix=15.0,
        lots=2,
        lot_size=65,
    )
