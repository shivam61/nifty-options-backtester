"""
Fetches and caches historical market data for backtesting.
Sources: Yahoo Finance for Nifty 50, India VIX, Crude Oil, USD/INR.

Cache identity is ticker-safe:
  * Files are named ``{ticker_slug}_{start}_{end}.parquet`` (see ``cache_filename``).
  * ``manifest.json`` in CACHE_DIR records, for every file this module wrote,
    its ticker, start, end and last_date. Reads only consider manifest entries
    for the requested ticker; a file that is not in the manifest is not trusted.
  * Legacy md5-named files (``md5(f"{ticker}_{start}_{end}")``) are used only as
    an exact key hit for the requested ticker/start/end.
  * Every series is checked against ``RANGES`` on load and before store.
"""

import json
import logging
import os
import re
import hashlib
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

MANIFEST_NAME = "manifest.json"
# A partial file may start up to this many calendar days after the requested start.
PARTIAL_START_TOLERANCE_DAYS = 7
# A Close jump larger than this at the splice between cached and fresh rows is treated as corruption.
SEAM_MAX_JUMP = 0.40
# Share of rows allowed outside a ticker's RANGES envelope (tolerates isolated spikes).
OUTSIDE_RANGE_MAX_FRACTION = 0.05

TICKERS = {
    "nifty": "^NSEI",
    "vix": "^INDIAVIX",
    "crude_brent": "BZ=F",
    "crude_wti": "CL=F",
    "usdinr": "INR=X",
    "gold": "GC=F",
    "dxy": "DX-Y.NYB",
    # Macro indicators
    "us_vix": "^VIX",           # US market fear gauge — global risk proxy
    "us_10y": "^TNX",           # US 10-year yield — global rate environment
    "sp500": "^GSPC",           # S&P 500 — global equity sentiment
    "nifty_bank": "^NSEBANK",   # Bank Nifty — domestic financial health
    "silver": "SI=F",           # Silver — inflation/safe haven proxy
    "nifty_it": "^CNXIT",       # IT sector — FII flow proxy (tech-heavy FII)
    # Cross-geo contagion channels (required by FeatureExtractor cross_geo group)
    "em_etf": "EEM",            # iShares MSCI Emerging Markets ETF
    "hang_seng": "^HSI",        # Hang Seng Index — China/HK equity proxy
    "europe": "^STOXX50E",      # Euro Stoxx 50 — European equity sentiment
}

# Per-ticker plausible Close range (lo, hi). A series whose median falls outside
# [lo, hi], or with more than OUTSIDE_RANGE_MAX_FRACTION of rows outside it, is
# refused on load and on store. Bounds are the union of the ranges used in
# tests/test_feature_store.py, widened so that short early-history windows
# (e.g. 2009) are not rejected.
RANGES: dict[str, tuple[float, float]] = {
    "^NSEI": (2_000, 30_000),
    "^INDIAVIX": (5, 100),
    "BZ=F": (-50, 200),
    "CL=F": (-50, 200),
    "INR=X": (40, 100),
    "GC=F": (500, 6_000),
    "DX-Y.NYB": (60, 120),
    "^VIX": (8, 90),
    "^TNX": (0, 6),
    "^GSPC": (600, 9_000),
    "^NSEBANK": (3_000, 65_000),
    "^CNXIT": (2_000, 50_000),
    "EEM": (10, 80),
    "^HSI": (8_000, 35_000),
    "^STOXX50E": (1_700, 6_700),
    "SI=F": (5, 120),
}

# Raw macro columns checked for identical or constant series in build_combined_dataset.
MACRO_GUARD_COLUMNS = (
    "crude", "usdinr", "gold", "dxy", "us_vix", "us_10y", "sp500", "nifty_bank",
    "silver", "nifty_it", "em_etf", "hang_seng", "europe", "vix", "nifty_close",
)

# Derived columns added in Phase 2b (all backward-looking). Inf from zero denominators is mapped to NaN.
P3_DERIVED_COLUMNS = (
    "dxy_change_5d", "dxy_change_20d", "gold_change_20d", "crude_spike_10d_pct",
    "vrp_change_5d", "vrp_negative", "rvol_10d_z", "range_expansion_ratio",
    "bn_ratio_change_5d", "correlation_spike_5d", "gap_magnitude_avg_5d",
    "intraday_dd_expanding_3d", "nifty_distance_from_sma20_pct", "nifty_distance_from_sma50_pct",
)


def ticker_slug(ticker: str) -> str:
    """Filesystem-safe, human-readable ticker: ^NSEI->NSEI, BZ=F->BZ_F, DX-Y.NYB->DX_Y_NYB."""
    return re.sub(r"[^A-Za-z0-9]+", "_", ticker.strip().lstrip("^")).strip("_")


def _iso(d) -> str:
    return pd.Timestamp(d).date().isoformat()


def cache_filename(ticker: str, start, end) -> str:
    return f"{ticker_slug(ticker)}_{_iso(start)}_{_iso(end)}.parquet"


def _legacy_cache_path(ticker: str, start, end) -> Path:
    """Pre-manifest md5 key. Only ever consulted as an exact hit for this ticker/start/end."""
    return CACHE_DIR / f"{hashlib.md5(f'{ticker}_{start}_{end}'.encode()).hexdigest()}.parquet"


def _manifest_path() -> Path:
    return CACHE_DIR / MANIFEST_NAME


def load_manifest() -> dict[str, dict]:
    """Return {filename: {ticker, start, end, last_date}}. Empty if missing or unreadable."""
    try:
        raw = json.loads(_manifest_path().read_text())
    except (OSError, ValueError):
        return {}
    files = raw.get("files", {}) if isinstance(raw, dict) else {}
    return {k: v for k, v in files.items() if isinstance(v, dict)}


def save_manifest(files: dict[str, dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _manifest_path().with_name(MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "files": files}, indent=2, sort_keys=True))
    os.replace(tmp, _manifest_path())


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure cached parquet frames have a DatetimeIndex."""
    if isinstance(df.index, pd.DatetimeIndex):
        return df
    try:
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    except Exception:
        pass
    return df


def _range_problem(ticker: str, df: Optional[pd.DataFrame]) -> Optional[str]:
    """Return why ``df`` is not a plausible series for ``ticker``, or None if it is."""
    if ticker not in RANGES:
        return None
    if df is None or df.empty:
        return "empty"
    if "Close" not in df.columns:
        return "no Close column"
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if close.empty:
        return "no numeric Close values"
    lo, hi = RANGES[ticker]
    med = float(close.median())
    if not (lo <= med <= hi):
        return f"median Close {med:.2f} outside [{lo}, {hi}]"
    outside = float(((close < lo) | (close > hi)).mean())
    if outside > OUTSIDE_RANGE_MAX_FRACTION:
        return f"{outside:.1%} of rows outside [{lo}, {hi}]"
    return None


def _read_checked(ticker: str, path: Path) -> Optional[pd.DataFrame]:
    """Load a cache file; return it only if non-empty, datetime-indexed and in range."""
    try:
        df = _normalize_index(pd.read_parquet(path))
    except Exception as exc:
        logger.warning("market cache %s unreadable: %s", path.name, exc)
        return None
    if not isinstance(df.index, pd.DatetimeIndex):
        return None
    problem = _range_problem(ticker, df)
    if problem:
        logger.error("market cache %s rejected for %s: %s", path.name, ticker, problem)
        return None
    return df.sort_index()


def _store_cache(ticker: str, start, end, df: pd.DataFrame) -> Optional[Path]:
    """Write ``df`` as the cache for (ticker, start, end) and register it in the manifest.

    Refuses (returns None, writes nothing) when df is empty or out of range.
    """
    if df is None or df.empty:
        return None
    problem = _range_problem(ticker, df)
    if problem:
        logger.error("refusing to cache %s %s..%s: %s", ticker, start, end, problem)
        return None
    df = _normalize_index(df).sort_index()
    filename = cache_filename(ticker, start, end)
    path = CACHE_DIR / filename
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    files = load_manifest()
    files[filename] = {
        "ticker": ticker,
        "start": _iso(start),
        "end": _iso(end),
        "last_date": _iso(df.index.max()),
    }
    save_manifest(files)
    return path


def _exact_cache_hit(ticker: str, start, end) -> Optional[pd.DataFrame]:
    """Exact (ticker, start, end) hit: manifest-listed ticker-named file, else a legacy md5 exact-key file."""
    name = cache_filename(ticker, start, end)
    meta = load_manifest().get(name)
    if meta is not None and meta.get("ticker") == ticker:
        df = _read_checked(ticker, CACHE_DIR / name)
        if df is not None and len(df) > 0:
            return df
    legacy = _legacy_cache_path(ticker, start, end)
    if legacy.exists():
        df = _read_checked(ticker, legacy)
        if df is not None and len(df) > 0:
            _store_cache(ticker, start, end, df)  # migrate to the ticker-named file
            return df
    return None


def _find_partial(ticker: str, start) -> Optional[pd.DataFrame]:
    """Newest same-ticker cached file (by manifest last_date) that covers ``start``.

    Never considers files of other tickers, and never files that are not listed in the manifest.
    """
    start_ts = pd.Timestamp(start)
    candidates = []
    for name, meta in load_manifest().items():
        if meta.get("ticker") != ticker:
            continue
        try:
            last = pd.Timestamp(meta["last_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if last < start_ts:
            continue
        candidates.append((last, name))
    for _, name in sorted(candidates, reverse=True):
        df = _read_checked(ticker, CACHE_DIR / name)
        if df is None:
            continue
        if df.index.min() > start_ts + pd.Timedelta(days=PARTIAL_START_TOLERANCE_DAYS):
            continue
        return df
    return None


def _slice_cached_range(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def _clip_to_request(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Rows of a cache frame inside the caller's [start, end]; an empty result is returned as an empty DataFrame.

    Only the returned frame is cut: cache files keep their full history.
    """
    clipped = _slice_cached_range(df, start, end)
    return clipped if not clipped.empty else pd.DataFrame()


def _seam_jump(old: pd.DataFrame, new: pd.DataFrame) -> Optional[float]:
    """Relative Close change between the last cached row and the first fresh row."""
    prev = pd.to_numeric(old["Close"], errors="coerce").dropna()
    nxt = pd.to_numeric(new["Close"], errors="coerce").dropna()
    if prev.empty or nxt.empty or float(prev.iloc[-1]) == 0:
        return None
    return abs(float(nxt.iloc[0]) / float(prev.iloc[-1]) - 1.0)


def _download(ticker: str, start, end) -> pd.DataFrame:
    try:
        data = yf.download(ticker, start=str(start), end=str(end), progress=False)
    except Exception:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)
    if len(data) == 0:
        return pd.DataFrame()
    return _normalize_index(data).sort_index()


def _fetch_yfinance(ticker: str, start: date, end: date) -> pd.DataFrame:
    # Avoid daily cache-miss: today's OHLC is incomplete until market close.
    # Normalise end to yesterday when it equals today so the cache key is
    # stable across multiple same-day runs.
    from datetime import date as _date_t
    effective_end = end if end < _date_t.today() else _date_t.today() - timedelta(days=1)

    # Exact local hit (ticker-named manifest file or legacy exact key) before any network access.
    # Every return below is cut to the caller's [start, end]; cache files keep their full history.
    exact = _exact_cache_hit(ticker, start, effective_end)
    if exact is not None:
        return _clip_to_request(exact, start, end)

    partial = _find_partial(ticker, start)
    if partial is not None and partial.index.max().date() >= end:
        return _clip_to_request(partial, start, end)

    if os.environ.get("MARKET_DATA_CACHE_ONLY", "").strip().lower() in {"1", "true", "yes"}:
        return _clip_to_request(partial, start, end) if partial is not None else pd.DataFrame()

    if partial is not None:
        last_cached = partial.index.max().date()
        fetch_start = (pd.Timestamp(last_cached) + pd.offsets.BDay(1)).date()
        tail = _download(ticker, fetch_start, end)
        if tail.empty:
            # Download failed or nothing new: serve the own-ticker partial; do not store it under the exact key.
            return _clip_to_request(partial, start, end)
        jump = _seam_jump(partial, tail)
        if jump is not None and jump > SEAM_MAX_JUMP:
            logger.warning(
                "%s: %.0f%% Close jump at the cache seam (after %s); discarding partial and refetching %s..%s",
                ticker, jump * 100, last_cached, start, end,
            )
        else:
            merged = pd.concat([partial, tail], axis=0)
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            if _range_problem(ticker, merged) is None:
                _store_cache(ticker, start, effective_end, merged)
                return _clip_to_request(merged, start, end)
            logger.error("%s: merged partial+tail out of range; refetching %s..%s", ticker, start, end)

    # Cache miss, or partial discarded: full fetch of the requested range.
    full = _download(ticker, start, end)
    if full.empty:
        # Final fallback: return empty rather than a wrong series
        # (the caller fills missing data with defaults; build_combined_dataset rejects dead columns).
        return pd.DataFrame()
    problem = _range_problem(ticker, full)
    if problem:
        logger.error("%s: fetched series rejected (%s); not stored", ticker, problem)
        return pd.DataFrame()
    _store_cache(ticker, start, effective_end, full)
    return _clip_to_request(full, start, end)


class MarketDataFetcher:
    """Fetches and preprocesses all market data needed for backtesting."""

    def __init__(self, start_date: date, end_date: date):
        self.start = start_date
        self.end = end_date
        self._data: dict[str, pd.DataFrame] = {}

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        for name, ticker in TICKERS.items():
            try:
                self._data[name] = _fetch_yfinance(ticker, self.start, self.end)
            except Exception as e:
                print(f"Warning: Could not fetch {name} ({ticker}): {e}")
                self._data[name] = pd.DataFrame()
        return self._data

    @property
    def nifty(self) -> pd.DataFrame:
        if "nifty" not in self._data:
            self._data["nifty"] = _fetch_yfinance(TICKERS["nifty"], self.start, self.end)
        return self._data["nifty"]

    @property
    def vix(self) -> pd.DataFrame:
        if "vix" not in self._data:
            self._data["vix"] = _fetch_yfinance(TICKERS["vix"], self.start, self.end)
        return self._data["vix"]

    @property
    def crude(self) -> pd.DataFrame:
        if "crude_brent" not in self._data:
            self._data["crude_brent"] = _fetch_yfinance(TICKERS["crude_brent"], self.start, self.end)
        return self._data["crude_brent"]

    @staticmethod
    def _check_macro_columns(combined: pd.DataFrame, defaulted: set[str]) -> None:
        """Refuse datasets where macro columns are dead defaults or duplicates of each other.

        Raises ValueError when a column filled entirely by a default constant is still constant,
        or when two raw macro columns are identical on more than half of the rows.
        Warns when a non-default macro column is constant.
        """
        if combined.empty:
            return
        cols = [c for c in MACRO_GUARD_COLUMNS if c in combined.columns]

        dead = [c for c in cols if c in defaulted and combined[c].nunique(dropna=True) <= 1]
        if dead:
            raise ValueError(
                "Macro column(s) filled entirely by default constants: "
                + ", ".join(f"{c}={combined[c].iloc[0]}" for c in dead)
                + ". Their tickers returned no usable data (see fetch/cache errors above); "
                "refusing to build a dataset with dead features. Run --mode refresh-data."
            )

        for c in cols:
            if c not in defaulted and combined[c].nunique(dropna=True) <= 1:
                warnings.warn(f"MarketDataFetcher: macro column {c!r} is constant", stacklevel=3)

        dupes = []
        values = {c: combined[c].to_numpy(dtype=float) for c in cols}
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                share = float(np.mean(np.isclose(values[a], values[b])))
                if share > 0.5:
                    dupes.append(f"{a}=={b} on {share:.0%} of rows")
        if dupes:
            raise ValueError(
                "Identical macro series detected (wrong-ticker data in the cache?): "
                + "; ".join(dupes)
                + ". Refusing to build the dataset. Run --mode refresh-data after fixing the cache."
            )

    def build_combined_dataset(self) -> pd.DataFrame:
        """Merges all data sources into a single DataFrame for analysis."""
        self.fetch_all()

        combined = pd.DataFrame()
        defaulted: set[str] = set()

        if len(self.nifty) > 0:
            combined["nifty_close"] = self.nifty["Close"]
            combined["nifty_high"] = self.nifty["High"]
            combined["nifty_low"] = self.nifty["Low"]
            combined["nifty_open"] = self.nifty["Open"]
            combined["nifty_volume"] = self.nifty.get("Volume", 0)

        # VIX data: yfinance ^INDIAVIX is unreliable; validate before using
        if len(self.vix) > 0:
            vix_close = self.vix["Close"]
            # Safety check: VIX should be between 5 and 150, not 10000+
            if vix_close.max() > 200:
                # Likely corrupted with index data; use default instead
                combined["vix"] = 15.0
                defaulted.add("vix")
            else:
                combined["vix"] = vix_close
        else:
            combined["vix"] = 15.0
            defaulted.add("vix")

        if len(self.crude) > 0:
            combined["crude"] = self.crude["Close"]
        else:
            combined["crude"] = 80.0
            defaulted.add("crude")

        for name in ["usdinr", "gold", "dxy", "us_vix", "us_10y", "sp500", "nifty_bank", "silver", "nifty_it", "em_etf", "hang_seng", "europe"]:
            if name in self._data and len(self._data[name]) > 0:
                combined[name] = self._data[name]["Close"]
            elif name not in combined:
                combined[name] = 0.0
                defaulted.add(name)

        combined = combined.ffill().dropna(subset=["nifty_close"])
        self._check_macro_columns(combined, defaulted)

        combined["nifty_return"] = combined["nifty_close"].pct_change()
        combined["nifty_return_5d"] = combined["nifty_close"].pct_change(5)
        combined["nifty_return_20d"] = combined["nifty_close"].pct_change(20)

        # Gap decomposition: close_to_close = overnight_gap + intraday_move
        combined["overnight_gap_pct"] = (
            (combined["nifty_open"] / combined["nifty_close"].shift(1) - 1) * 100
        )
        combined["intraday_move_pct"] = (
            (combined["nifty_close"] / combined["nifty_open"] - 1) * 100
        )
        combined["overnight_gap_abs"] = combined["overnight_gap_pct"].abs()
        combined["gap_3d_max_abs"] = combined["overnight_gap_abs"].rolling(3).max()
        combined["gap_5d_max_abs"] = combined["overnight_gap_abs"].rolling(5).max()
        combined["gap_magnitude_avg_5d"] = combined["overnight_gap_pct"].abs().rolling(5).mean()
        combined["intraday_dd_expanding_3d"] = (
            (combined["nifty_low"] - combined["nifty_open"]) / combined["nifty_open"] * 100
        ).rolling(3).min()

        # Mid-session spot proxy — permanent baseline (≈11 AM IST fill).
        # Alpha=0.40 ≈ 40% of the open→close intraday move is typically completed
        # by 11 AM on NSE (based on typical intraday pattern of Nifty).
        # Backtest fill: combined_engine uses this unconditionally for all entries.
        # Signal mode uses a live Fyers quote instead.
        _alpha = 0.40
        combined["nifty_mid_session"] = (
            combined["nifty_open"]
            + _alpha * (combined["nifty_close"] - combined["nifty_open"])
        )

        combined["nifty_sma_20"] = combined["nifty_close"].rolling(20).mean()
        combined["nifty_sma_50"] = combined["nifty_close"].rolling(50).mean()
        combined["nifty_distance_from_sma20_pct"] = (
            (combined["nifty_close"] - combined["nifty_sma_20"]) / combined["nifty_sma_20"] * 100
        )
        combined["nifty_distance_from_sma50_pct"] = (
            (combined["nifty_close"] - combined["nifty_sma_50"]) / combined["nifty_sma_50"] * 100
        )

        combined["nifty_realized_vol_10d"] = (
            combined["nifty_return"].rolling(10).std() * np.sqrt(252) * 100
        )
        combined["nifty_realized_vol_20d"] = (
            combined["nifty_return"].rolling(20).std() * np.sqrt(252) * 100
        )

        if "vix" in combined.columns:
            combined["vix_sma_10"] = combined["vix"].rolling(10).mean()
            combined["vix_change_1d"] = combined["vix"].pct_change()
            combined["vix_change_5d"] = combined["vix"].pct_change(5)
            combined["vol_risk_premium"] = combined["vix"] - combined.get(
                "nifty_realized_vol_20d", 0
            )
            combined["vrp_change_5d"] = combined["vol_risk_premium"].diff(5)
            # NaN stays NaN (not 0/False) where the VRP itself is NaN
            combined["vrp_negative"] = (
                (combined["vol_risk_premium"] < 0).astype(float).where(combined["vol_risk_premium"].notna())
            )

        combined["nifty_daily_range_pct"] = (
            (combined["nifty_high"] - combined["nifty_low"]) / combined["nifty_close"] * 100
        )

        # Realized-vol z-score (10d vol vs its own 50d history) and range expansion (5d vs 20d mean range)
        rv10 = combined["nifty_realized_vol_10d"]
        rv10_std_50 = rv10.rolling(50).std().replace(0, np.nan)
        combined["rvol_10d_z"] = (rv10 - rv10.rolling(50).mean()) / rv10_std_50
        combined["range_expansion_ratio"] = (
            combined["nifty_daily_range_pct"].rolling(5).mean()
            / combined["nifty_daily_range_pct"].rolling(20).mean().replace(0, np.nan)
        )

        if "crude" in combined.columns:
            combined["crude_change_5d"] = combined["crude"].pct_change(5)
            combined["crude_change_20d"] = combined["crude"].pct_change(20)
            # Percent move over 10 sessions; the crude_shock breaker compares abs() against 30 (%)
            combined["crude_spike_10d_pct"] = combined["crude"].pct_change(10) * 100

        # Macro indicators — derived features
        if "us_vix" in combined.columns:
            combined["us_vix_change_5d"] = combined["us_vix"].pct_change(5)
            combined["us_vix_sma_10"] = combined["us_vix"].rolling(10).mean()
            combined["global_fear_ratio"] = combined.get("vix", 15) / combined["us_vix"].replace(0, 1)

        if "us_10y" in combined.columns:
            combined["us_10y_change_5d"] = combined["us_10y"].pct_change(5)

        if "sp500" in combined.columns:
            combined["sp500_return_5d"] = combined["sp500"].pct_change(5)
            combined["sp500_return_20d"] = combined["sp500"].pct_change(20)
            if "nifty_return_5d" in combined.columns:
                combined["india_us_correlation_20d"] = (
                    combined["nifty_return"].rolling(20).corr(combined["sp500"].pct_change())
                )
                combined["correlation_spike_5d"] = combined["india_us_correlation_20d"].diff(5)

        if "usdinr" in combined.columns:
            combined["usdinr_change_5d"] = combined["usdinr"].pct_change(5)
            combined["usdinr_change_20d"] = combined["usdinr"].pct_change(20)

        if "gold" in combined.columns:
            combined["gold_change_5d"] = combined["gold"].pct_change(5)
            combined["gold_change_20d"] = combined["gold"].pct_change(20)

        if "dxy" in combined.columns:
            combined["dxy_change_5d"] = combined["dxy"].pct_change(5)
            combined["dxy_change_20d"] = combined["dxy"].pct_change(20)

        if "nifty_bank" in combined.columns:
            combined["bank_nifty_return_5d"] = combined["nifty_bank"].pct_change(5)
            if "nifty_close" in combined.columns:
                combined["bank_nifty_ratio"] = combined["nifty_bank"] / combined["nifty_close"]
                combined["bn_ratio_change_5d"] = combined["bank_nifty_ratio"].pct_change(5) * 100

        if "nifty_it" in combined.columns:
            combined["it_sector_return_5d"] = combined["nifty_it"].pct_change(5)

        if "em_etf" in combined.columns:
            combined["em_return_5d"] = combined["em_etf"].pct_change(5)
            combined["em_return_20d"] = combined["em_etf"].pct_change(20)

        if "hang_seng" in combined.columns:
            combined["china_return_5d"] = combined["hang_seng"].pct_change(5)
            combined["china_return_20d"] = combined["hang_seng"].pct_change(20)

        if "europe" in combined.columns:
            combined["europe_return_5d"] = combined["europe"].pct_change(5)

        # Cross-asset risk score
        risk_components = []
        if "vix" in combined.columns:
            risk_components.append(combined["vix"] / combined["vix"].rolling(50).mean())
        if "crude" in combined.columns:
            risk_components.append(combined["crude"] / combined["crude"].rolling(50).mean())
        if "usdinr" in combined.columns:
            risk_components.append(combined["usdinr"] / combined["usdinr"].rolling(50).mean())
        if risk_components:
            combined["macro_risk_score"] = sum(risk_components) / len(risk_components)

        # Regime classifier features
        if "vix" in combined.columns and "vix_sma_10" in combined.columns:
            combined["vix_vs_sma_ratio"] = combined["vix"] / combined["vix_sma_10"].replace(0, np.nan)

        # Bollinger Bands width
        if "nifty_close" in combined.columns:
            nifty_sma_20 = combined["nifty_close"].rolling(20).mean()
            nifty_std_20 = combined["nifty_close"].rolling(20).std()
            bb_upper = nifty_sma_20 + (2 * nifty_std_20)
            bb_lower = nifty_sma_20 - (2 * nifty_std_20)
            combined["nifty_bb_width"] = ((bb_upper - bb_lower) / nifty_sma_20) * 100

        # Drawdown features
        if "nifty_close" in combined.columns:
            rolling_max_20 = combined["nifty_close"].rolling(20).max()
            rolling_max_50 = combined["nifty_close"].rolling(50).max()
            combined["nifty_drawdown_from_20d_high_pct"] = (
                (combined["nifty_close"] - rolling_max_20) / rolling_max_20 * 100
            )
            combined["nifty_drawdown_from_50d_high_pct"] = (
                (combined["nifty_close"] - rolling_max_50) / rolling_max_50 * 100
            )

        # RSI (Relative Strength Index)
        if "nifty_close" in combined.columns:
            delta = combined["nifty_close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss.replace(0, 1e-10)
            combined["nifty_rsi_14"] = 100 - (100 / (1 + rs))

        # Volatility expansion ratio
        if "nifty_realized_vol_10d" in combined.columns and "nifty_realized_vol_20d" in combined.columns:
            combined["vol_expansion_ratio"] = (
                combined["nifty_realized_vol_10d"] / combined["nifty_realized_vol_20d"].replace(0, 1e-10)
            )

        # Crash risk scores
        if "vix" in combined.columns and "nifty_realized_vol_20d" in combined.columns:
            vix_shock = (combined["vix"] - combined["vix_sma_10"]) / combined["vix_sma_10"]
            dd_factor = combined.get("nifty_drawdown_from_20d_high_pct", 0) / -10.0
            vol_factor = (combined["nifty_realized_vol_20d"] - 15) / 15.0
            combined["crash_risk_score"] = (
                0.4 * vix_shock.fillna(0) +
                0.4 * dd_factor.fillna(0) +
                0.2 * vol_factor.fillna(0)
            ).clip(lower=0, upper=1)

            # v2: more sensitive to VIX spikes
            vix_spike = combined["vix"] > combined["vix_sma_10"] * 1.2
            combined["crash_risk_score_v2"] = combined["crash_risk_score"] * 1.5
            combined.loc[vix_spike, "crash_risk_score_v2"] = (
                combined.loc[vix_spike, "crash_risk_score"] * 2.0
            )
            combined["crash_risk_score_v2"] = combined["crash_risk_score_v2"].clip(upper=1)

        # Multi-asset stress
        if "crude" in combined.columns and "usdinr" in combined.columns and "vix" in combined.columns:
            crude_stress = (combined["crude"] - combined["crude"].rolling(50).mean()) / combined["crude"].rolling(50).std()
            inr_stress = (combined["usdinr"] - combined["usdinr"].rolling(50).mean()) / combined["usdinr"].rolling(50).std()
            vix_stress = (combined["vix"] - combined["vix"].rolling(50).mean()) / combined["vix"].rolling(50).std()
            combined["multi_asset_stress"] = (crude_stress + inr_stress + vix_stress) / 3

        # Store 50-day moving averages and std devs for all assets (for Z-score calculation)
        for asset in ["crude", "usdinr", "vix", "gold", "dxy", "us_vix", "sp500", "nifty_bank"]:
            if asset in combined.columns:
                combined[f"{asset}_sma_50"] = combined[asset].rolling(50).mean()
                combined[f"{asset}_std_50"] = combined[asset].rolling(50).std()

        # Consecutive down days
        if "nifty_return" in combined.columns:
            down_days = (combined["nifty_return"] < 0).astype(int)
            combined["nifty_consec_down_days"] = (
                down_days.groupby((down_days != down_days.shift()).cumsum()).cumsum()
            )

        # VIX acceleration
        if "vix_change_1d" in combined.columns:
            combined["vix_accel_3d_pct"] = combined["vix_change_1d"].rolling(3).sum()

        # Cross-asset composite features (used by FeatureExtractor)
        if "crude" in combined.columns and "usdinr" in combined.columns:
            crude_z = (
                (combined["crude"] - combined["crude"].rolling(50).mean())
                / combined["crude"].rolling(50).std().replace(0, 1)
            )
            inr_z = (
                (combined["usdinr"] - combined["usdinr"].rolling(50).mean())
                / combined["usdinr"].rolling(50).std().replace(0, 1)
            )
            combined["crude_inr_composite"] = crude_z + inr_z

            if "dxy" in combined.columns:
                dxy_z = (
                    (combined["dxy"] - combined["dxy"].rolling(50).mean())
                    / combined["dxy"].rolling(50).std().replace(0, 1)
                )
                combined["dxy_crude_composite"] = dxy_z + crude_z

        if "vix" in combined.columns and "us_vix" in combined.columns:
            combined["vix_premium_over_us"] = (
                combined["vix"] / combined["us_vix"].replace(0, np.nan) - 1
            )

        # FII flow proxy: IT sector leads FII activity (tech-heavy FII holdings)
        if "nifty_it" in combined.columns and "nifty_close" in combined.columns:
            combined["fii_flow_proxy"] = (
                combined["nifty_it"].pct_change(5) - combined["nifty_close"].pct_change(5)
            )
        elif "it_sector_return_5d" in combined.columns and "nifty_return_5d" in combined.columns:
            combined["fii_flow_proxy"] = (
                combined["it_sector_return_5d"] - combined["nifty_return_5d"]
            )

        # Division by zero / defaulted-constant series can yield inf; treat as missing
        _p3_cols = [c for c in P3_DERIVED_COLUMNS if c in combined.columns]
        combined[_p3_cols] = combined[_p3_cols].replace([np.inf, -np.inf], np.nan)

        # Coverage warning: alert if data starts later than requested start date
        if not combined.empty:
            actual_start = combined.index.min().date()
            if actual_start > self.start:
                gap_days = (actual_start - self.start).days
                warnings.warn(
                    f"MarketDataFetcher: data starts {actual_start} but {self.start} was requested "
                    f"({gap_days} days of history missing). "
                    f"Run 'python main.py --mode refresh-data --start {self.start}' to fetch full history.",
                    stacklevel=2,
                )

        return combined

    def clear_cache(self):
        for f in CACHE_DIR.glob("*.parquet"):
            f.unlink()
        save_manifest({})
