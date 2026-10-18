"""Regression pins for the cache-corruption incident.

Incident: on an exact-key cache miss the loader picked ANY cached parquet whose price
range fitted the requested ticker. Ranges overlap across tickers, so a ^VIX-like file was
served as BZ=F (crude) and a Brent-like file as ^VIX for ~17 years of history.

Guarantees pinned here (complements TestMarketDataCacheIdentity in test_data.py):
  * a ticker never borrows another ticker's cached file (manifest identity, not price range);
  * a dataset with an identical or default-filled macro column is refused, including under
    MARKET_DATA_CACHE_ONLY=1;
  * no environment variable or parameter switches the guards off;
  * scripts/check_cache_health.sh fails on a corrupted cache and passes on a clean one.

Offline only: yf.download is stubbed, and CACHE_DIR is redirected to tmp_path.
"""

import ast
import inspect
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
MD_SRC = REPO / "data" / "market_data.py"
HEALTH_SH = REPO / "scripts" / "check_cache_health.sh"

START, END = date(2023, 1, 2), date(2024, 3, 1)
IDX = pd.bdate_range(START, END)

BASES = {
    "^NSEI": 22000, "^INDIAVIX": 15, "BZ=F": 80, "CL=F": 75, "INR=X": 83, "GC=F": 2000,
    "DX-Y.NYB": 100, "^VIX": 18, "^TNX": 4, "^GSPC": 4500, "^NSEBANK": 48000,
    "^CNXIT": 35000, "EEM": 40, "^HSI": 20000, "^STOXX50E": 4000, "SI=F": 25,
}


def _ohlc(index, close):
    close = np.asarray(close, dtype=float)
    return pd.DataFrame({"Open": close - 1.0, "High": close + 1.0, "Low": close - 1.0,
                         "Close": close, "Volume": np.arange(len(index)) + 1.0}, index=index)


def _synthetic(ticker):
    """Deterministic, in-range random walk per ticker (distinct across tickers)."""
    rng = np.random.RandomState(sum(map(ord, ticker)))
    return _ohlc(IDX, BASES[ticker] * np.cumprod(1 + rng.normal(0, 0.005, len(IDX))))


def _vix_like():
    # ^VIX-like, values 10..60: inside RANGES["^VIX"] and RANGES["BZ=F"]
    return _ohlc(IDX, 35 + 25 * np.sin(np.arange(len(IDX)) / 15.0))


def _brent_like():
    # BZ=F-like, values 25..85: inside RANGES["BZ=F"] and RANGES["^VIX"]; overlaps _vix_like on 25..60
    return _ohlc(IDX, 55 + 30 * np.sin(np.arange(len(IDX)) / 23.0))


def _populate(md, overrides=None, skip=()):
    """Write one valid cache file per TICKERS entry (exact key START..END) into the fixture's CACHE_DIR."""
    overrides = overrides or {}
    for ticker in md.TICKERS.values():
        if ticker in skip:
            continue
        series = overrides.get(ticker)
        if series is None:
            series = _synthetic(ticker)
        assert md._store_cache(ticker, START, END, series) is not None, f"fixture for {ticker} out of range"


def _build(md):
    return md.MarketDataFetcher(date(2023, 1, 2), END).build_combined_dataset()


def _stub_download(monkeypatch, md):
    calls = []

    def _dl(ticker, start, end, progress=False):
        calls.append((ticker, str(start), str(end)))
        return pd.DataFrame()

    monkeypatch.setattr(md.yf, "download", _dl)
    return calls


@pytest.fixture
def md(tmp_path, monkeypatch):
    from data import market_data
    monkeypatch.setattr(market_data, "CACHE_DIR", tmp_path)
    monkeypatch.delenv("MARKET_DATA_CACHE_ONLY", raising=False)  # each test sets this explicitly
    return market_data


# ---------------------------------------------------------------------------
# 1. The incident itself: wrong-ticker files must never be served
# ---------------------------------------------------------------------------

class TestIncidentTickerIdentity:

    def test_premise_both_series_pass_the_range_guard(self, md):
        # The incident only works because a wrong-ticker series passes the price-range guard.
        # If this stops holding, the identity tests below are checking a weaker case.
        assert md._range_problem("BZ=F", _vix_like()) is None
        assert md._range_problem("^VIX", _brent_like()) is None

    def test_missing_crude_never_borrows_vix_file(self, md, monkeypatch):
        md._store_cache("^VIX", START, END, _vix_like())
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("BZ=F", START, END).empty

        monkeypatch.delenv("MARKET_DATA_CACHE_ONLY")
        calls = _stub_download(monkeypatch, md)
        assert md._fetch_yfinance("BZ=F", START, END).empty
        assert calls == [("BZ=F", "2023-01-02", "2024-03-01")]

    def test_missing_vix_never_borrows_crude_file(self, md, monkeypatch):
        md._store_cache("BZ=F", START, END, _brent_like())
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("^VIX", START, END).empty

        monkeypatch.delenv("MARKET_DATA_CACHE_ONLY")
        calls = _stub_download(monkeypatch, md)
        assert md._fetch_yfinance("^VIX", START, END).empty
        assert calls == [("^VIX", "2023-01-02", "2024-03-01")]

    def test_file_named_for_requested_ticker_but_owned_by_another_is_ignored(self, md, tmp_path, monkeypatch):
        # Filename is BZ=F's own key; content and manifest owner are ^VIX.
        name = md.cache_filename("BZ=F", START, END)
        _vix_like().to_parquet(tmp_path / name)
        md.save_manifest({name: {"ticker": "^VIX", "start": "2023-01-02", "end": "2024-03-01",
                                 "last_date": str(IDX[-1].date())}})
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("BZ=F", START, END).empty

    def test_unlisted_file_is_never_trusted(self, md, tmp_path, monkeypatch):
        # Own-ticker name and own-ticker content, but no manifest entry: not trusted.
        _brent_like().to_parquet(tmp_path / md.cache_filename("BZ=F", START, END))
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("BZ=F", START, END).empty


# ---------------------------------------------------------------------------
# 2. Dataset-level refusal, including under MARKET_DATA_CACHE_ONLY=1
# ---------------------------------------------------------------------------

class TestIncidentBuildRefusesSplicedMacro:

    def test_clean_cache_builds_with_distinct_macro_columns(self, md, monkeypatch):
        _populate(md, overrides={"^VIX": _vix_like()})
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        data = _build(md)
        assert len(data) > 0
        assert not np.allclose(data["crude"], data["us_vix"])

    def test_crude_file_missing_refuses_build_instead_of_splicing_vix(self, md, monkeypatch):
        # The incident's failure mode: crude has no own file, a ^VIX file exists.
        _populate(md, overrides={"^VIX": _vix_like()}, skip={"BZ=F"})
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        with pytest.raises(ValueError, match="default constants.*crude"):
            _build(md)

    def test_brent_file_holding_vix_copy_refuses_build(self, md, monkeypatch):
        # The incident itself: crude stored as a copy of US VIX.
        _populate(md, overrides={"^VIX": _vix_like(), "BZ=F": _vix_like()})
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        with pytest.raises(ValueError, match=r"Identical macro series.*crude==us_vix"):
            _build(md)

    def test_out_of_range_cache_file_is_rejected_under_cache_only(self, md, tmp_path, monkeypatch):
        _populate(md)
        name = md.cache_filename("^INDIAVIX", START, END)
        _synthetic("^NSEI").to_parquet(tmp_path / name)  # Nifty-level prices under the VIX key
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        assert md._fetch_yfinance("^INDIAVIX", START, END).empty
        with pytest.raises(ValueError, match="default constants.*vix"):
            _build(md)

    @pytest.mark.parametrize("extra_env", [
        {},
        {"MARKET_DATA_SKIP_CHECKS": "1", "MARKET_DATA_NO_RANGE_CHECK": "1",
         "MARKET_DATA_ALLOW_DUPLICATES": "1", "MARKET_DATA_STRICT": "0"},
    ])
    def test_corrupted_build_refused_whatever_env(self, md, monkeypatch, extra_env):
        _populate(md, overrides={"^VIX": _vix_like(), "BZ=F": _vix_like()})
        monkeypatch.setenv("MARKET_DATA_CACHE_ONLY", "1")
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)
        with pytest.raises(ValueError, match="Identical macro series"):
            _build(md)


# ---------------------------------------------------------------------------
# 3. No switch can disable the guards (static + signature)
# ---------------------------------------------------------------------------

class TestGuardsCannotBeSwitchedOff:

    def test_only_cache_only_env_var_is_read(self):
        src = MD_SRC.read_text()
        names = re.findall(r'(?:environ(?:\.get)?|getenv)\s*[\(\[]\s*["\']([A-Za-z_]+)["\']', src)
        mentions = len(re.findall(r"\benviron\b|\bgetenv\b", src))  # whole words: not "environment" in comments
        assert mentions == len(names), "environment accessed in a way this test cannot see"
        assert set(names) == {"MARKET_DATA_CACHE_ONLY"}

    def test_public_entry_points_take_no_guard_switches(self, md):
        assert list(inspect.signature(md.MarketDataFetcher.build_combined_dataset).parameters) == ["self"]
        assert list(inspect.signature(md.MarketDataFetcher.__init__).parameters) == \
            ["self", "start_date", "end_date"]

    def test_every_return_in_build_follows_macro_check(self):
        # build_combined_dataset must not return a frame before _check_macro_columns has run.
        tree = ast.parse(MD_SRC.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "build_combined_dataset")
        checks = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "_check_macro_columns"]
        returns = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert len(checks) == 1
        assert returns and all(r > checks[0] for r in returns), (checks, returns)


# ---------------------------------------------------------------------------
# 4. scripts/check_cache_health.sh: exit semantics on real subprocess runs
# ---------------------------------------------------------------------------

class TestCheckCacheHealthScript:

    def _run(self, cache_dir, asof):
        env = {k: v for k, v in os.environ.items() if k != "MARKET_DATA_CACHE_ONLY"}
        env.update({"CACHE_DIR": str(cache_dir), "START": "2023-01-02",
                    "MAX_STALE_DAYS": "5", "ASOF": asof, "PYTHON": sys.executable})
        return subprocess.run(["bash", str(HEALTH_SH)], cwd=str(REPO), env=env,
                              capture_output=True, text=True, timeout=900)

    def test_passes_on_clean_cache(self, md, tmp_path):
        _populate(md)  # in-band synthetic series for every ticker (us_vix band is 12-35)
        r = self._run(tmp_path, asof=str(END))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "cache-health: PASS rc=0" in r.stdout

    def test_refuses_corrupted_cache(self, md, tmp_path):
        _populate(md, overrides={"^VIX": _vix_like(), "BZ=F": _vix_like()})
        r = self._run(tmp_path, asof=str(END))
        assert r.returncode == 2, r.stdout + r.stderr
        assert "cache-health: ERROR rc=2" in r.stdout

    def test_fails_when_cache_is_stale(self, md, tmp_path):
        _populate(md, overrides={"^VIX": _vix_like()})
        r = self._run(tmp_path, asof="2024-06-01")
        assert r.returncode == 1, r.stdout + r.stderr
        assert "cache-health: FAIL rc=1" in r.stdout
