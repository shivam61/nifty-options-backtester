"""
Tests for data modules: expiry_calendar.py, news_sentiment.py, config.py

Covers:
- Expiry date calculations (monthly, weekly, best-for-DTE)
- Sentiment scoring
- Config dataclass defaults and risk score math
"""

import pytest
import numpy as np
import pandas as pd
import hashlib
from datetime import date, timedelta
from pathlib import Path

from data.expiry_calendar import (
    get_all_thursdays, get_monthly_expiry, get_weekly_expiries,
    get_monthly_expiries, get_next_monthly_expiry, get_best_expiry_for_dte,
    get_upcoming_expiries, get_weekly_expiry_in_range,
)
from data.news_sentiment import (
    score_headline, score_headlines,
    compute_price_action_sentiment, compute_geopolitical_risk_index,
    SentimentScore,
)
from config import BacktestConfig, MarketRegime


# ---------------------------------------------------------------------------
# Expiry calendar
# ---------------------------------------------------------------------------

class TestExpiryCalendar:
    # Pre-2024-04-04: expiry is Thursday (weekday 3)
    # 2024-04-04 .. 2025-08-31: expiry is Monday (weekday 0)
    # 2025-09-01 onward: expiry is Tuesday (weekday 1)

    def test_all_thursdays_in_april_2023(self):
        """get_all_thursdays is a legacy helper — always returns Thursdays."""
        thursdays = get_all_thursdays(2023, 4)
        assert all(d.weekday() == 3 for d in thursdays)
        assert len(thursdays) >= 4

    def test_monthly_expiry_pre_cutover_is_thursday(self):
        exp = get_monthly_expiry(2023, 4)
        assert exp.weekday() == 3
        next_week = exp + timedelta(days=7)
        assert next_week.month != 4

    def test_monthly_expiry_monday_era(self):
        exp = get_monthly_expiry(2026, 4)
        assert exp.weekday() == 1  # Tuesday
        next_week = exp + timedelta(days=7)
        assert next_week.month != 4

    def test_monthly_expiry_monday_transition_era(self):
        exp = get_monthly_expiry(2025, 8)
        assert exp.weekday() == 0  # Monday

    def test_monthly_expiry_tuesday_era(self):
        exp = get_monthly_expiry(2026, 12)
        assert exp.weekday() == 1  # Tuesday
        assert exp.month == 12

    def test_weekly_expiries_all_thursdays_pre_cutover(self):
        start = date(2023, 4, 1)
        end = date(2023, 4, 30)
        weeklies = get_weekly_expiries(start, end)
        assert all(d.weekday() == 3 for d in weeklies)

    def test_weekly_expiries_all_tuesdays_current_era(self):
        start = date(2026, 4, 1)
        end = date(2026, 4, 30)
        weeklies = get_weekly_expiries(start, end)
        assert all(d.weekday() == 1 for d in weeklies)

    def test_monthly_expiries_in_range_pre_cutover(self):
        start = date(2023, 1, 1)
        end = date(2023, 6, 30)
        monthlies = get_monthly_expiries(start, end)
        assert len(monthlies) == 6
        assert all(d.weekday() == 3 for d in monthlies)

    def test_monthly_expiries_in_range_post_cutover(self):
        start = date(2026, 1, 1)
        end = date(2026, 6, 30)
        monthlies = get_monthly_expiries(start, end)
        assert len(monthlies) == 6
        assert all(d.weekday() == 1 for d in monthlies)

    def test_next_monthly_expiry_pre_cutover(self):
        today = date(2023, 4, 8)
        exp = get_next_monthly_expiry(today)
        assert exp >= today
        assert exp.weekday() == 3

    def test_next_monthly_expiry_post_cutover(self):
        today = date(2026, 4, 8)
        exp = get_next_monthly_expiry(today)
        assert exp >= today
        assert exp.weekday() == 1  # Tuesday

    def test_best_expiry_for_dte_21(self):
        today = date(2026, 4, 8)
        exp, actual_dte = get_best_expiry_for_dte(today, 21)
        assert exp > today
        assert actual_dte > 0
        assert abs(actual_dte - 21) < 25

    def test_weekly_expiry_in_range_can_skip_near_expiry(self):
        exp, dte = get_weekly_expiry_in_range(date(2026, 4, 13), 3, 8)
        assert exp is not None
        assert exp == date(2026, 4, 21)
        assert dte == 8

    def test_upcoming_expiries_count(self):
        today = date(2026, 4, 8)
        upcoming = get_upcoming_expiries(today, count=4)
        assert len(upcoming) == 4
        for item in upcoming:
            assert "expiry" in item


# ---------------------------------------------------------------------------
# Market data cache preference
# ---------------------------------------------------------------------------

class TestMarketDataCachePreference:

    def test_prefers_local_parquet_cache_before_network(self, tmp_path, monkeypatch):
        from data import market_data

        market_data._cached_parquet_paths.cache_clear()
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        idx = pd.date_range("2024-01-01", periods=60, freq="B")
        df = pd.DataFrame({
            "Open": np.linspace(22000, 22400, len(idx)),
            "High": np.linspace(22100, 22500, len(idx)),
            "Low": np.linspace(21900, 22300, len(idx)),
            "Close": np.linspace(22050, 22450, len(idx)),
            "Volume": np.arange(len(idx)) + 1,
        }, index=idx)
        df.to_parquet(tmp_path / "cached_series.parquet")

        called = {"download": False}

        def _fail_download(*args, **kwargs):
            called["download"] = True
            raise AssertionError("network should not be called when cache exists")

        monkeypatch.setattr(market_data.yf, "download", _fail_download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))

        assert not called["download"]
        assert len(loaded) == len(df)
        assert loaded.index.min() == df.index.min()
        assert loaded.index.max() == df.index.max()

    def test_extends_partial_cache_and_updates_exact_cache(self, tmp_path, monkeypatch):
        from data import market_data

        market_data._cached_parquet_paths.cache_clear()
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        partial_idx = pd.bdate_range("2024-01-01", periods=20)
        partial = pd.DataFrame({
            "Open": np.linspace(22000, 22100, len(partial_idx)),
            "High": np.linspace(22100, 22200, len(partial_idx)),
            "Low": np.linspace(21900, 22000, len(partial_idx)),
            "Close": np.linspace(22050, 22150, len(partial_idx)),
            "Volume": np.arange(len(partial_idx)) + 1,
        }, index=partial_idx)
        partial.to_parquet(tmp_path / "partial.parquet")

        tail_idx = pd.bdate_range("2024-01-29", "2024-02-15")
        tail = pd.DataFrame({
            "Open": np.linspace(22110, 22220, len(tail_idx)),
            "High": np.linspace(22210, 22320, len(tail_idx)),
            "Low": np.linspace(22010, 22120, len(tail_idx)),
            "Close": np.linspace(22160, 22270, len(tail_idx)),
            "Volume": np.arange(len(tail_idx)) + 100,
        }, index=tail_idx)

        called = {"download": 0}

        def _download(ticker, start, end, progress=False):
            called["download"] += 1
            assert ticker == "^NSEI"
            assert start == "2024-01-29"
            assert end == "2024-02-15"
            return tail

        monkeypatch.setattr(market_data.yf, "download", _download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))
        exact_path = market_data._cache_path(
            hashlib.md5("^NSEI_2024-01-01_2024-02-15".encode()).hexdigest()
        )

        assert called["download"] == 1
        assert loaded.index.min() == partial.index.min()
        assert loaded.index.max() == tail.index.max()
        assert len(loaded) == len(pd.concat([partial, tail]).index.unique())
        assert exact_path.exists()

    def test_returns_partial_cache_when_download_fails(self, tmp_path, monkeypatch):
        from data import market_data

        market_data._cached_parquet_paths.cache_clear()
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        partial_idx = pd.bdate_range("2024-01-01", periods=20)
        partial = pd.DataFrame({
            "Open": np.linspace(22000, 22100, len(partial_idx)),
            "High": np.linspace(22100, 22200, len(partial_idx)),
            "Low": np.linspace(21900, 22000, len(partial_idx)),
            "Close": np.linspace(22050, 22150, len(partial_idx)),
            "Volume": np.arange(len(partial_idx)) + 1,
        }, index=partial_idx)
        partial.to_parquet(tmp_path / "partial.parquet")

        def _download(*args, **kwargs):
            raise OSError("offline")

        monkeypatch.setattr(market_data.yf, "download", _download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))

        assert len(loaded) == len(partial)
        assert loaded.index.max() == partial.index.max()


# ---------------------------------------------------------------------------
# News sentiment
# ---------------------------------------------------------------------------

class TestSentimentScoring:

    def test_negative_headline(self):
        result = score_headline("Markets crash amid war fears and recession")
        assert result.score < 0
        assert result.magnitude > 0
        assert len(result.key_factors) > 0

    def test_positive_headline(self):
        result = score_headline("Ceasefire deal reached, markets rally on peace hopes")
        assert result.score > 0

    def test_neutral_headline(self):
        result = score_headline("The weather is nice today")
        assert result.score == 0.0
        assert result.category == "neutral"

    def test_geopolitical_category(self):
        result = score_headline("Russia launches military attack on border")
        assert result.category == "geopolitical"

    def test_economic_category(self):
        result = score_headline("RBI announces surprise rate cut in monetary policy")
        assert result.category == "economic"

    def test_aggregate_headlines(self):
        headlines = [
            "Markets crash on war fears",
            "Peace talks resume, ceasefire possible",
            "RBI holds rates steady",
        ]
        result = score_headlines(headlines)
        assert isinstance(result, SentimentScore)
        assert -1.0 <= result.score <= 1.0

    def test_empty_headlines(self):
        result = score_headlines([])
        assert result.score == 0.0
        assert result.category == "neutral"


class TestPriceActionSentiment:

    def test_returns_series(self, market_data):
        result = compute_price_action_sentiment(market_data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(market_data)

    def test_bounded_between_neg1_and_1(self, market_data):
        result = compute_price_action_sentiment(market_data)
        assert result.min() >= -1.0
        assert result.max() <= 1.0


class TestGeopoliticalRiskIndex:

    def test_returns_series(self, market_data):
        result = compute_geopolitical_risk_index(market_data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(market_data)

    def test_bounded_between_0_and_1(self, market_data):
        result = compute_geopolitical_risk_index(market_data)
        assert result.min() >= 0.0
        assert result.max() <= 1.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestBacktestConfig:

    def test_defaults(self):
        c = BacktestConfig()
        assert c.initial_capital == 500_000
        assert c.lot_size == 65
        assert c.max_lots == 200
        assert c.risk_free_rate == 0.065
        assert c.vix_low == 14.0
        assert c.vix_extreme == 28.0

    def test_custom_values(self):
        c = BacktestConfig(initial_capital=1_000_000, max_lots=10)
        assert c.initial_capital == 1_000_000
        assert c.max_lots == 10


class TestMarketRegime:

    def test_risk_score_low_in_calm(self):
        r = MarketRegime(vix_level="low", trend="bullish", crude_impact="positive",
                         fii_flow="buying", event_risk="low")
        assert r.risk_score < 0.1

    def test_risk_score_high_in_crisis(self):
        r = MarketRegime(vix_level="extreme", trend="bearish", crude_impact="negative",
                         fii_flow="selling", event_risk="high")
        assert r.risk_score > 0.7

    def test_risk_score_bounded(self):
        r = MarketRegime(vix_level="extreme", trend="bearish", crude_impact="negative",
                         fii_flow="selling", event_risk="high")
        assert 0.0 <= r.risk_score <= 1.0

    def test_recommended_strategy_no_trade_in_extreme(self):
        r = MarketRegime(vix_level="extreme", trend="bearish", crude_impact="negative",
                         fii_flow="selling", event_risk="high")
        assert r.recommended_strategy == "no_trade"

    def test_recommended_strategy_aggressive_in_calm(self):
        r = MarketRegime(vix_level="low", trend="bullish", crude_impact="positive",
                         fii_flow="buying", event_risk="low")
        assert r.recommended_strategy == "aggressive_iron_condor"

    def test_default_regime_is_neutral(self):
        r = MarketRegime()
        assert r.vix_level == "medium"
        assert r.trend == "neutral"
        score = r.risk_score
        assert 0.1 < score < 0.5
