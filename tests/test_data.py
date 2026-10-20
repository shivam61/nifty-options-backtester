"""
Tests for data modules: expiry_calendar.py, news_sentiment.py, config.py

Covers:
- Expiry date calculations (monthly, weekly, best-for-DTE)
- Sentiment scoring
- Config dataclass defaults and risk score math
"""

import pytest
import json
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
    # Up to 2025-08-28: weekly and monthly expiry is Thursday (weekday 3)
    # 2025-09-02 onward: weekly and monthly expiry is Tuesday (weekday 1)
    # There was no Monday era (see tests/test_expiry_calendar_vs_archive.py).

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

    def test_monthly_expiry_tuesday_era_april_2026(self):
        exp = get_monthly_expiry(2026, 4)
        assert exp.weekday() == 1  # Tuesday
        next_week = exp + timedelta(days=7)
        assert next_week.month != 4

    def test_monthly_expiry_last_thursday_before_switch(self):
        exp = get_monthly_expiry(2025, 8)
        assert exp == date(2025, 8, 28)  # last Thursday, still Thursday era

    def test_monthly_expiry_first_tuesday_after_switch(self):
        exp = get_monthly_expiry(2025, 9)
        assert exp == date(2025, 9, 30)  # last Tuesday, Tuesday era

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
        # 2026-04-14 (Tuesday) was a holiday: its expiry moved to Monday 2026-04-13
        assert weeklies == [date(2026, 4, 7), date(2026, 4, 13), date(2026, 4, 21), date(2026, 4, 28)]

    def test_monthly_expiries_in_range_pre_cutover(self):
        start = date(2023, 1, 1)
        end = date(2023, 6, 30)
        monthlies = get_monthly_expiries(start, end)
        assert len(monthlies) == 6
        # Jan 2023 (Republic Day Thursday) -> Wed 01-25; Mar 2023 (Ram Navami Thursday) -> Wed 03-29
        shifted = {date(2023, 1, 25), date(2023, 3, 29), date(2023, 6, 28)}
        assert all(d.weekday() == 3 or d in shifted for d in monthlies)
        assert monthlies[-1] == date(2023, 6, 28)

    def test_monthly_expiries_in_range_post_cutover(self):
        start = date(2026, 1, 1)
        end = date(2026, 6, 30)
        monthlies = get_monthly_expiries(start, end)
        assert len(monthlies) == 6
        # March 2026 monthly moved to Monday 2026-03-30 (Tuesday 2026-03-31 holiday)
        assert all(d.weekday() == 1 or d == date(2026, 3, 30) for d in monthlies)
        assert monthlies[2] == date(2026, 3, 30)

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

def _ohlc(index, close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({
        "Open": close - 10.0,
        "High": close + 20.0,
        "Low": close - 20.0,
        "Close": close,
        "Volume": np.arange(len(index)) + 1,
    }, index=index)


def _nifty_like(index, base=22050.0, step=5.0):
    return _ohlc(index, base + np.arange(len(index)) * step)


def _vix_like(index, base=14.0):
    return _ohlc(index, base + np.sin(np.arange(len(index)) / 5.0))


class TestMarketDataCachePreference:

    def test_prefers_local_parquet_cache_before_network(self, tmp_path, monkeypatch):
        from data import market_data

        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        idx = pd.date_range("2024-01-01", periods=60, freq="B")
        df = _ohlc(idx, np.linspace(22050, 22450, len(idx)))
        market_data._store_cache("^NSEI", date(2024, 1, 1), date(2024, 2, 15), df)

        called = {"download": False}

        def _fail_download(*args, **kwargs):
            called["download"] = True
            raise AssertionError("network should not be called when cache exists")

        monkeypatch.setattr(market_data.yf, "download", _fail_download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))

        assert not called["download"]
        # the file holds rows past the requested end; only the window [start, end] is returned
        expected = df.loc[:"2024-02-15"]
        assert len(loaded) == len(expected)
        assert loaded.index.min() == df.index.min()
        assert loaded.index.max() == pd.Timestamp("2024-02-15")
        assert len(pd.read_parquet(tmp_path / "NSEI_2024-01-01_2024-02-15.parquet")) == len(df)

    def test_extends_partial_cache_and_updates_exact_cache(self, tmp_path, monkeypatch):
        from data import market_data

        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        partial_idx = pd.bdate_range("2024-01-01", periods=20)
        partial = _ohlc(partial_idx, np.linspace(22050, 22150, len(partial_idx)))
        market_data._store_cache("^NSEI", date(2024, 1, 1), date(2024, 1, 26), partial)

        tail_idx = pd.bdate_range("2024-01-29", "2024-02-15")
        tail = _ohlc(tail_idx, np.linspace(22160, 22270, len(tail_idx)))

        called = {"download": 0}

        def _download(ticker, start, end, progress=False):
            called["download"] += 1
            assert ticker == "^NSEI"
            assert start == "2024-01-29"
            assert end == "2024-02-15"
            return tail

        monkeypatch.setattr(market_data.yf, "download", _download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))
        exact_path = tmp_path / "NSEI_2024-01-01_2024-02-15.parquet"

        assert called["download"] == 1
        assert loaded.index.min() == partial.index.min()
        assert loaded.index.max() == tail.index.max()
        assert len(loaded) == len(pd.concat([partial, tail]).index.unique())
        assert exact_path.exists()
        assert "NSEI_2024-01-01_2024-02-15.parquet" in market_data.load_manifest()

    def test_returns_partial_cache_when_download_fails(self, tmp_path, monkeypatch):
        from data import market_data

        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        partial_idx = pd.bdate_range("2024-01-01", periods=20)
        partial = _ohlc(partial_idx, np.linspace(22050, 22150, len(partial_idx)))
        market_data._store_cache("^NSEI", date(2024, 1, 1), date(2024, 1, 26), partial)

        def _download(*args, **kwargs):
            raise OSError("offline")

        monkeypatch.setattr(market_data.yf, "download", _download)

        loaded = market_data._fetch_yfinance("^NSEI", date(2024, 1, 1), date(2024, 2, 15))

        assert len(loaded) == len(partial)
        assert loaded.index.max() == partial.index.max()


class TestMarketDataCacheIdentity:
    """Offline tests for ticker-safe cache identity, range guards, seam check and guard columns."""

    START, END = date(2024, 1, 1), date(2024, 2, 15)

    @pytest.fixture
    def md(self, tmp_path, monkeypatch):
        from data import market_data
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
        return market_data

    def _no_download(self, monkeypatch, md):
        calls = []

        def _fail(ticker, start, end, progress=False):
            calls.append((ticker, str(start), str(end)))
            return pd.DataFrame()

        monkeypatch.setattr(md.yf, "download", _fail)
        return calls

    # (a) ties between different tickers' files never cross tickers
    def test_tie_between_two_tickers_never_crosses(self, md, tmp_path, monkeypatch):
        idx = pd.bdate_range(self.START, self.END)
        md._store_cache("^GSPC", self.START, self.END, _ohlc(idx, np.linspace(4000, 4300, len(idx))))
        md._store_cache("^HSI", self.START, self.END, _ohlc(idx, np.linspace(20000, 20300, len(idx))))
        assert (tmp_path / "GSPC_2024-01-01_2024-02-15.parquet").exists()

        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("^NSEI", self.START, self.END).empty

        monkeypatch.delenv("MARKET_DATA_CACHE_ONLY")
        calls = self._no_download(monkeypatch, md)
        result = md._fetch_yfinance("^NSEI", self.START, self.END)
        assert result.empty
        # Download is attempted for the requested ticker from the requested start: no foreign partial was used.
        assert calls == [("^NSEI", "2024-01-01", "2024-02-15")]

    # (b) out-of-range series are rejected on load and on store
    def test_out_of_range_file_rejected_on_load(self, md, tmp_path, monkeypatch):
        idx = pd.bdate_range(self.START, self.END)
        bad = _nifty_like(idx)  # Nifty-level prices under the India VIX ticker
        name = md.cache_filename("^INDIAVIX", self.START, self.END)
        bad.to_parquet(tmp_path / name)
        md.save_manifest({name: {"ticker": "^INDIAVIX", "start": "2024-01-01",
                                 "end": "2024-02-15", "last_date": str(idx[-1].date())}})

        good = _vix_like(idx)
        calls = []

        def _download(ticker, start, end, progress=False):
            calls.append(ticker)
            return good

        monkeypatch.setattr(md.yf, "download", _download)
        loaded = md._fetch_yfinance("^INDIAVIX", self.START, self.END)

        assert calls == ["^INDIAVIX"]
        assert loaded["Close"].max() < 100
        assert loaded["Close"].median() < 100

    def test_out_of_range_download_is_never_stored(self, md, tmp_path, monkeypatch):
        idx = pd.bdate_range(self.START, self.END)
        bad = _nifty_like(idx)

        def _download(ticker, start, end, progress=False):
            return bad

        monkeypatch.setattr(md.yf, "download", _download)
        result = md._fetch_yfinance("^INDIAVIX", self.START, self.END)

        assert result.empty
        assert not (tmp_path / md.cache_filename("^INDIAVIX", self.START, self.END)).exists()
        assert md.load_manifest() == {}

    def test_store_cache_refuses_out_of_range(self, md, tmp_path):
        idx = pd.bdate_range(self.START, self.END)
        assert md._store_cache("^VIX", self.START, self.END, _nifty_like(idx)) is None
        assert list(tmp_path.glob("*.parquet")) == []
        assert md.load_manifest() == {}

    # (c) identical or dead macro columns are refused by build_combined_dataset
    @staticmethod
    def _fake_frames(md, monkeypatch, overrides=None, drop=()):
        overrides = overrides or {}
        bases = {
            "^NSEI": 22000, "^INDIAVIX": 15, "BZ=F": 80, "CL=F": 75, "INR=X": 83, "GC=F": 2000,
            "DX-Y.NYB": 100, "^VIX": 18, "^TNX": 4, "^GSPC": 4500, "^NSEBANK": 48000,
            "^CNXIT": 35000, "EEM": 40, "^HSI": 20000, "^STOXX50E": 4000, "SI=F": 25,
        }
        idx = pd.bdate_range("2023-01-02", periods=300)

        def _series(ticker):
            if ticker in overrides:
                return overrides[ticker](idx)
            seed = sum(map(ord, ticker))
            rng = np.random.RandomState(seed)
            walk = bases[ticker] * np.cumprod(1 + rng.normal(0, 0.005, len(idx)))
            return _ohlc(idx, walk)

        def _fake_fetch(ticker, start, end):
            if ticker in drop:
                return pd.DataFrame()
            return _series(ticker)

        monkeypatch.setattr(md, "_fetch_yfinance", _fake_fetch)

    def test_identical_macro_columns_raise(self, md, monkeypatch):
        # ^VIX (us_vix) returns exactly the Brent (BZ=F) series -> two raw macro columns identical
        brent_walk = lambda idx: _ohlc(
            idx,
            80 * np.cumprod(1 + np.random.RandomState(sum(map(ord, "BZ=F"))).normal(0, 0.005, len(idx))),
        )
        self._fake_frames(md, monkeypatch, overrides={"^VIX": brent_walk})
        fetcher = md.MarketDataFetcher(date(2023, 1, 2), date(2024, 3, 1))
        with pytest.raises(ValueError, match="Identical macro series"):
            fetcher.build_combined_dataset()

    def test_entirely_default_macro_column_raises(self, md, monkeypatch):
        self._fake_frames(md, monkeypatch, drop={"EEM"})
        fetcher = md.MarketDataFetcher(date(2023, 1, 2), date(2024, 3, 1))
        with pytest.raises(ValueError, match="default constants.*em_etf"):
            fetcher.build_combined_dataset()

    def test_distinct_macro_columns_build(self, md, monkeypatch):
        self._fake_frames(md, monkeypatch)
        fetcher = md.MarketDataFetcher(date(2023, 1, 2), date(2024, 3, 1))
        data = fetcher.build_combined_dataset()
        assert {"nifty_close", "vix", "crude", "em_etf", "us_vix"} <= set(data.columns)
        assert len(data) > 0

    # (d) manifest round trip and naming
    def test_manifest_round_trip(self, md, tmp_path):
        idx = pd.bdate_range(self.START, self.END)
        md._store_cache("^NSEI", self.START, self.END, _nifty_like(idx))
        md._store_cache("BZ=F", self.START, self.END, _ohlc(idx, np.linspace(70, 90, len(idx))))

        assert (tmp_path / "manifest.json").exists()
        expected = {
            "NSEI_2024-01-01_2024-02-15.parquet": {
                "ticker": "^NSEI", "start": "2024-01-01", "end": "2024-02-15",
                "last_date": str(idx[-1].date()),
            },
            "BZ_F_2024-01-01_2024-02-15.parquet": {
                "ticker": "BZ=F", "start": "2024-01-01", "end": "2024-02-15",
                "last_date": str(idx[-1].date()),
            },
        }
        assert md.load_manifest() == expected
        # A fresh read from disk (no in-process state) gives the same mapping.
        assert json.loads((tmp_path / "manifest.json").read_text())["files"] == expected

    def test_slugs_are_readable_and_unique(self, md):
        assert md.cache_filename("^NSEI", self.START, self.END) == "NSEI_2024-01-01_2024-02-15.parquet"
        assert md.cache_filename("BZ=F", self.START, self.END) == "BZ_F_2024-01-01_2024-02-15.parquet"
        assert md.cache_filename("DX-Y.NYB", self.START, self.END) == "DX_Y_NYB_2024-01-01_2024-02-15.parquet"
        slugs = {md.ticker_slug(t) for t in md.TICKERS.values()}
        assert len(slugs) == len(md.TICKERS)
        assert set(md.RANGES) == set(md.TICKERS.values())

    # (e) a seam jump discards the partial and refetches the whole range
    def test_seam_jump_discards_partial(self, md, tmp_path, monkeypatch):
        partial_idx = pd.bdate_range("2024-01-01", "2024-01-26")
        md._store_cache("^NSEI", self.START, date(2024, 1, 26),
                        _nifty_like(partial_idx, base=22050, step=5))

        full_idx = pd.bdate_range(self.START, self.END)
        good_full = _nifty_like(full_idx, base=22050, step=5)
        calls = []

        def _download(ticker, start, end, progress=False):
            calls.append(str(start))
            if str(start) == "2024-01-29":
                # Bad tail: +58% at the seam (inside the Nifty range, so only the seam check can catch it)
                return _ohlc(pd.bdate_range("2024-01-29", "2024-02-15"), np.full(14, 35000.0))
            return good_full

        monkeypatch.setattr(md.yf, "download", _download)
        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert calls == ["2024-01-29", "2024-01-01"]
        assert len(loaded) == len(good_full)
        assert loaded["Close"].max() < 30000
        stored = pd.read_parquet(tmp_path / "NSEI_2024-01-01_2024-02-15.parquet")
        assert stored["Close"].max() < 30000

    # (f) legacy md5 key: exact hit only, and only for the ticker that produced the key
    def test_legacy_md5_exact_hit_accepted_only_for_own_ticker(self, md, tmp_path, monkeypatch):
        import hashlib
        idx = pd.bdate_range(self.START, self.END)
        legacy_nifty = tmp_path / (hashlib.md5("^NSEI_2024-01-01_2024-02-15".encode()).hexdigest() + ".parquet")
        _nifty_like(idx).to_parquet(legacy_nifty)

        calls = self._no_download(monkeypatch, md)
        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)
        assert calls == []
        assert len(loaded) == len(idx)
        # The hit is migrated to the ticker-named file and registered in the manifest.
        assert md.load_manifest()["NSEI_2024-01-01_2024-02-15.parquet"]["ticker"] == "^NSEI"

        # The same legacy file is not used for another ticker with the same dates.
        calls = self._no_download(monkeypatch, md)
        other = md._fetch_yfinance("^INDIAVIX", self.START, self.END)
        assert calls == [("^INDIAVIX", "2024-01-01", "2024-02-15")]
        assert other.empty

    def test_legacy_md5_file_with_bad_range_is_refused(self, md, tmp_path, monkeypatch):
        import hashlib
        idx = pd.bdate_range(self.START, self.END)
        legacy = tmp_path / (hashlib.md5("^INDIAVIX_2024-01-01_2024-02-15".encode()).hexdigest() + ".parquet")
        _nifty_like(idx).to_parquet(legacy)
        calls = self._no_download(monkeypatch, md)
        assert md._fetch_yfinance("^INDIAVIX", self.START, self.END).empty
        assert calls == [("^INDIAVIX", "2024-01-01", "2024-02-15")]

    # (g) cache-only mode returns own-ticker partial and never another ticker's
    def test_cache_only_returns_own_ticker_partial_only(self, md, tmp_path, monkeypatch):
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        full_idx = pd.bdate_range(self.START, self.END)
        md._store_cache("^GSPC", self.START, self.END, _ohlc(full_idx, np.linspace(4000, 4300, len(full_idx))))
        own_idx = pd.bdate_range(self.START, "2024-01-26")
        md._store_cache("^NSEI", self.START, date(2024, 1, 26), _nifty_like(own_idx))
        calls = self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)
        assert calls == []
        assert loaded.index.max() == own_idx[-1]
        assert loaded["Close"].min() > 2000  # Nifty prices, not the S&P file

        assert md._fetch_yfinance("^INDIAVIX", self.START, self.END).empty
        assert calls == []


class TestPurgeShortParquets:

    def test_purges_only_listed_late_starting_files(self, tmp_path, monkeypatch):
        import main as main_module
        from data import market_data
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)

        late_idx = pd.bdate_range("2024-02-01", "2024-02-15")
        ok_idx = pd.bdate_range("2024-01-02", "2024-02-15")
        market_data._store_cache("^NSEI", date(2024, 1, 1), date(2024, 2, 15), _nifty_like(late_idx))
        market_data._store_cache("^VIX", date(2024, 1, 1), date(2024, 2, 15),
                                 _ohlc(ok_idx, np.linspace(15, 16, len(ok_idx))))
        unlisted = tmp_path / "unlisted.parquet"
        _nifty_like(late_idx).to_parquet(unlisted)

        cleared = main_module._purge_short_parquets(date(2024, 1, 1))

        assert cleared == 1
        assert not (tmp_path / "NSEI_2024-01-01_2024-02-15.parquet").exists()
        assert (tmp_path / "VIX_2024-01-01_2024-02-15.parquet").exists()
        assert unlisted.exists()
        assert list(market_data.load_manifest()) == ["VIX_2024-01-01_2024-02-15.parquet"]

    def test_tolerates_first_trading_day_a_few_days_late(self, tmp_path, monkeypatch):
        import main as main_module
        from data import market_data
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
        idx = pd.bdate_range("2024-01-03", "2024-02-15")  # 2 days after a Monday 2024-01-01 request
        market_data._store_cache("^GSPC", date(2024, 1, 1), date(2024, 2, 15),
                                 _ohlc(idx, np.linspace(4000, 4300, len(idx))))
        assert main_module._purge_short_parquets(date(2024, 1, 1)) == 0
        assert (tmp_path / "GSPC_2024-01-01_2024-02-15.parquet").exists()


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


# ---------------------------------------------------------------------------
# _fetch_yfinance returns only the requested [start, end] window
# ---------------------------------------------------------------------------

class TestFetchReturnsRequestedWindow:
    START, END = date(2024, 1, 1), date(2024, 2, 15)
    LONG_END = date(2024, 3, 29)

    @pytest.fixture
    def md(self, tmp_path, monkeypatch):
        from data import market_data
        monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
        monkeypatch.delenv("MARKET_DATA_CACHE_ONLY", raising=False)
        return market_data

    @staticmethod
    def _no_download(monkeypatch, md):
        calls = []

        def _fail(ticker, start, end, progress=False):
            calls.append((ticker, str(start), str(end)))
            return pd.DataFrame()

        monkeypatch.setattr(md.yf, "download", _fail)
        return calls

    def _store_long(self, md, start=None, end=None):
        start = start or self.START
        end = end or self.LONG_END
        idx = pd.bdate_range(start, end)
        df = _nifty_like(idx)
        md._store_cache("^NSEI", start, end, df)
        return df

    # (1) requested end earlier than cached last date
    def test_end_earlier_than_cached_last_date_is_clipped(self, md, tmp_path, monkeypatch):
        stored = self._store_long(md)
        calls = self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert calls == []
        assert not loaded.empty
        assert loaded.index.max() <= pd.Timestamp(self.END)
        assert loaded.index.max() == pd.Timestamp(self.END)
        # the cache file still holds the full history
        on_disk = pd.read_parquet(tmp_path / "NSEI_2024-01-01_2024-03-29.parquet")
        assert on_disk.index.max() == stored.index.max()
        assert len(on_disk) == len(stored)

    def test_fresh_download_is_clipped_but_stored_in_full(self, md, tmp_path, monkeypatch):
        idx = pd.bdate_range(self.START, self.LONG_END)
        full = _nifty_like(idx)
        monkeypatch.setattr(md.yf, "download", lambda *a, **k: full)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert loaded.index.max() == pd.Timestamp(self.END)
        stored = pd.read_parquet(tmp_path / "NSEI_2024-01-01_2024-02-15.parquet")
        assert stored.index.max() == pd.Timestamp(self.LONG_END)

    # (2) start trimming
    def test_rows_before_requested_start_are_dropped(self, md, monkeypatch):
        early = date(2023, 12, 20)
        self._store_long(md, start=early, end=self.LONG_END)
        self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert loaded.index.min() >= pd.Timestamp(self.START)
        assert loaded.index.min() == pd.bdate_range(self.START, self.END)[0]

    def test_file_starting_within_tolerance_after_start_is_kept(self, md, monkeypatch):
        late = self.START + timedelta(days=3)
        self._store_long(md, start=late, end=self.LONG_END)
        self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert not loaded.empty
        assert loaded.index.min() == pd.Timestamp(late)
        assert loaded.index.max() == pd.Timestamp(self.END)

    # (3) cache-only mode with an older end
    def test_cache_only_mode_clips_to_older_end(self, md, tmp_path, monkeypatch):
        self._store_long(md)
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        calls = self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert calls == []
        assert loaded.index.max() == pd.Timestamp(self.END)
        assert pd.read_parquet(tmp_path / "NSEI_2024-01-01_2024-03-29.parquet").index.max() == pd.Timestamp(self.LONG_END)

    def test_cache_only_partial_shorter_than_end_is_clipped_not_extended(self, md, monkeypatch):
        self._store_long(md, end=date(2024, 2, 1))
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert loaded.index.max() == pd.Timestamp(date(2024, 2, 1))

    def test_cache_only_miss_returns_empty(self, md, monkeypatch):
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        self._no_download(monkeypatch, md)

        assert md._fetch_yfinance("^NSEI", self.START, self.END).empty

    # (4) exact hit with a newer same-ticker partial also available
    def test_exact_hit_wins_over_newer_partial_and_is_clipped(self, md, tmp_path, monkeypatch):
        exact_df = self._store_long(md, end=self.END)
        self._store_long(md, end=self.LONG_END)
        calls = self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert calls == []
        assert loaded.index.max() == pd.Timestamp(self.END)
        assert len(loaded) == len(exact_df)
        assert loaded.index.equals(exact_df.index)

    # (5) output unchanged when end >= last cached date
    def test_output_unchanged_when_end_covers_cache(self, md, monkeypatch):
        stored = self._store_long(md, end=self.END)
        self._no_download(monkeypatch, md)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        pd.testing.assert_frame_equal(loaded, stored, check_freq=False)

    def test_partial_extension_still_merges_and_clips(self, md, tmp_path, monkeypatch):
        partial_idx = pd.bdate_range(self.START, "2024-01-26")
        partial = _nifty_like(partial_idx)
        md._store_cache("^NSEI", self.START, date(2024, 1, 26), partial)
        tail_idx = pd.bdate_range("2024-01-29", self.LONG_END)
        tail = _nifty_like(tail_idx, base=22200.0)
        monkeypatch.setattr(md.yf, "download", lambda *a, **k: tail)

        loaded = md._fetch_yfinance("^NSEI", self.START, self.END)

        assert loaded.index.max() == pd.Timestamp(self.END)
        assert loaded.index.min() == partial.index.min()
        assert len(loaded) == len(pd.bdate_range(self.START, self.END))

    # (6) build_combined_dataset never exposes rows past the requested end
    def test_build_combined_dataset_respects_requested_end(self, md, monkeypatch):
        idx = pd.bdate_range("2023-01-02", "2024-04-30")
        for ticker in md.TICKERS.values():
            seed = sum(map(ord, ticker))
            rng = np.random.RandomState(seed)
            base = {"^NSEI": 22000, "^INDIAVIX": 15, "BZ=F": 80, "CL=F": 75, "INR=X": 83, "GC=F": 2000,
                    "DX-Y.NYB": 100, "^VIX": 18, "^TNX": 4, "^GSPC": 4500, "^NSEBANK": 48000,
                    "^CNXIT": 35000, "EEM": 40, "^HSI": 20000, "^STOXX50E": 4000, "SI=F": 25}[ticker]
            walk = base * np.cumprod(1 + rng.normal(0, 0.005, len(idx)))
            md._store_cache(ticker, idx[0].date(), idx[-1].date(), _ohlc(idx, walk))
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        requested_end = date(2024, 3, 1)

        dataset = md.MarketDataFetcher(date(2023, 1, 2), requested_end).build_combined_dataset()

        assert not dataset.empty
        assert dataset.index.max() <= pd.Timestamp(requested_end)
        assert dataset.index.max() == pd.Timestamp(requested_end)
