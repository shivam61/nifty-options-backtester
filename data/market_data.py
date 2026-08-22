"""
Fetches and caches historical market data for backtesting.
Sources: Yahoo Finance for Nifty 50, India VIX, Crude Oil, USD/INR.
"""

import os
import hashlib
from functools import lru_cache
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

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


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.parquet"


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


@lru_cache(maxsize=1)
def _cached_parquet_paths() -> tuple[str, ...]:
    return tuple(str(p) for p in CACHE_DIR.glob("*.parquet"))


def _ticker_hint_score(ticker: str, df: pd.DataFrame) -> float:
    """Heuristic score to pick the best local cache for a requested ticker."""
    if df.empty or "Close" not in df.columns:
        return float("-inf")

    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if close.empty:
        return float("-inf")

    median = float(close.median())
    last = float(close.iloc[-1])
    rows = len(close)
    score = 0.0

    if rows >= 250:
        score += 1.0
    if rows >= 1000:
        score += 2.0
    if {"Open", "High", "Low"}.issubset(df.columns):
        score += 0.5

    if ticker == "^NSEI":
        if 2000 <= median <= 100000:
            score += 4.0
        if 2000 <= last <= 100000:
            score += 2.0
    elif ticker == "^INDIAVIX":
        if 2 <= median <= 120:
            score += 4.0
        if 2 <= last <= 120:
            score += 2.0
    elif ticker in {"BZ=F", "CL=F"}:
        if 10 <= median <= 250:
            score += 4.0
        if 10 <= last <= 250:
            score += 2.0
    elif ticker == "INR=X":
        if 40 <= median <= 120:
            score += 4.0
        if 40 <= last <= 120:
            score += 2.0
    elif ticker == "GC=F":
        if 1000 <= median <= 100000:
            score += 4.0
        if 1000 <= last <= 100000:
            score += 2.0
    elif ticker == "DX-Y.NYB":
        if 50 <= median <= 150:
            score += 4.0
        if 50 <= last <= 150:
            score += 2.0
    elif ticker == "^VIX":
        if 2 <= median <= 100:
            score += 4.0
    elif ticker == "^TNX":
        if 0 <= median <= 20:
            score += 4.0
    elif ticker in {"^GSPC", "^NSEBANK", "^HSI", "^STOXX50E", "EEM"}:
        if median > 100:
            score += 4.0

    return score


def _load_best_cached_series(ticker: str, start: date, end: date) -> pd.DataFrame | None:
    """Find the best local parquet cache covering the requested date range."""
    best_score = float("-inf")
    best_df: pd.DataFrame | None = None
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    for path_str in _cached_parquet_paths():
        path = Path(path_str)
        try:
            df = _normalize_index(pd.read_parquet(path))
        except Exception:
            continue
        if df.empty or "Close" not in df.columns:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            continue
        if df.index.min() > start_ts or df.index.max() < end_ts:
            continue

        score = _ticker_hint_score(ticker, df)
        if score > best_score:
            best_score = score
            best_df = df

    return best_df


def _load_best_cached_overlap(ticker: str, start: date, end: date) -> pd.DataFrame | None:
    """
    Find the best local parquet cache that overlaps the requested date range.

    This is used as a fallback when no cache fully covers the requested window.
    """
    best_score = float("-inf")
    best_df: pd.DataFrame | None = None
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)

    for path_str in _cached_parquet_paths():
        path = Path(path_str)
        try:
            df = _normalize_index(pd.read_parquet(path))
        except Exception:
            continue
        if df.empty or "Close" not in df.columns:
            continue
        if not isinstance(df.index, pd.DatetimeIndex):
            continue
        if df.index.max() < start_ts or df.index.min() > end_ts:
            continue

        score = _ticker_hint_score(ticker, df)
        if score > best_score:
            best_score = score
            best_df = df

    if best_df is None:
        return None
    return best_df.sort_index()


def _slice_cached_range(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def _store_cache(path: Path, df: pd.DataFrame) -> None:
    if df.empty:
        return
    df = _normalize_index(df).sort_index()
    df.to_parquet(path)
    _cached_parquet_paths.cache_clear()


def _fetch_yfinance(ticker: str, start: date, end: date) -> pd.DataFrame:
    # Avoid daily cache-miss: today's OHLC is incomplete until market close.
    # Normalise end to yesterday when it equals today so the cache key is
    # stable across multiple same-day runs.
    from datetime import date as _date_t
    effective_end = end if end < _date_t.today() else _date_t.today() - timedelta(days=1)
    cache_key = hashlib.md5(f"{ticker}_{start}_{effective_end}".encode()).hexdigest()
    path = _cache_path(cache_key)

    # Prefer exact or broad local cache before any network access.
    if path.exists():
        df = _normalize_index(pd.read_parquet(path))
        if len(df) > 0:
            return df

    cached = _load_best_cached_series(ticker, start, end)
    if cached is not None and len(cached) > 0:
        return cached

    partial = _load_best_cached_overlap(ticker, start, end)
    if partial is not None and len(partial) > 0:
        if partial.index.max().date() >= end:
            return partial

    if os.environ.get("MARKET_DATA_CACHE_ONLY", "").strip().lower() in {"1", "true", "yes"}:
        return partial if partial is not None else pd.DataFrame()

    # Cache miss or expired — fetch from Yahoo
    fetch_start = start
    if partial is not None and len(partial) > 0:
        last_cached = partial.index.max().date()
        if last_cached < end:
            fetch_start = (pd.Timestamp(last_cached) + pd.offsets.BDay(1)).date()

    try:
        data = yf.download(ticker, start=str(fetch_start), end=str(end), progress=False)
    except Exception:
        data = pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)

    merged = data
    if partial is not None and len(partial) > 0:
        merged = pd.concat([partial, data], axis=0)
        merged = merged[~merged.index.duplicated(keep="last")]
        merged = merged.sort_index()

    if len(merged) > 0:
        merged = _normalize_index(merged)
        _store_cache(path, merged)
        return merged

    # Final fallback: return empty rather than potentially wrong cache
    # (the caller will fill missing data with sensible defaults like vix=15)
    return pd.DataFrame()


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

    def build_combined_dataset(self) -> pd.DataFrame:
        """Merges all data sources into a single DataFrame for analysis."""
        self.fetch_all()

        combined = pd.DataFrame()

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
            else:
                combined["vix"] = vix_close
        else:
            combined["vix"] = 15.0

        if len(self.crude) > 0:
            combined["crude"] = self.crude["Close"]
        else:
            combined["crude"] = combined.get("crude", 0).fillna(80.0)

        for name in ["usdinr", "gold", "dxy", "us_vix", "us_10y", "sp500", "nifty_bank", "silver", "nifty_it", "em_etf", "hang_seng", "europe"]:
            if name in self._data and len(self._data[name]) > 0:
                combined[name] = self._data[name]["Close"]
            elif name not in combined:
                combined[name] = 0.0

        combined = combined.ffill().dropna(subset=["nifty_close"])

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

        combined["nifty_sma_20"] = combined["nifty_close"].rolling(20).mean()
        combined["nifty_sma_50"] = combined["nifty_close"].rolling(50).mean()

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

        combined["nifty_daily_range_pct"] = (
            (combined["nifty_high"] - combined["nifty_low"]) / combined["nifty_close"] * 100
        )

        if "crude" in combined.columns:
            combined["crude_change_5d"] = combined["crude"].pct_change(5)
            combined["crude_change_20d"] = combined["crude"].pct_change(20)

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

        if "usdinr" in combined.columns:
            combined["usdinr_change_5d"] = combined["usdinr"].pct_change(5)
            combined["usdinr_change_20d"] = combined["usdinr"].pct_change(20)

        if "gold" in combined.columns:
            combined["gold_change_5d"] = combined["gold"].pct_change(5)

        if "nifty_bank" in combined.columns:
            combined["bank_nifty_return_5d"] = combined["nifty_bank"].pct_change(5)
            if "nifty_close" in combined.columns:
                combined["bank_nifty_ratio"] = combined["nifty_bank"] / combined["nifty_close"]

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

        # Coverage warning: alert if data starts later than requested start date
        if not combined.empty:
            actual_start = combined.index.min().date()
            if actual_start > self.start:
                gap_days = (actual_start - self.start).days
                import warnings
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
