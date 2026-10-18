"""
Feature Store Integration Tests
================================
Validates that MarketDataFetcher.build_combined_dataset() produces a correct,
self-consistent feature store before it reaches model training.

Why this matters
----------------
The ML quality classifier (Gate 8) and all strategy VIX gates read directly
from this dataset. Silent data corruption (e.g., every ticker returning Nifty
price data, VIX flat at 15.0, cross-asset composites all NaN) causes:
  - AUC ≈ 0.512 (random noise — GBM has no signal)
  - VIX gates never activating/deactivating (all days look like VIX=15)
  - multi_asset_stress all-NaN (crash score v2 permanently zero)
  - global_fear_ratio ≈ 0 (India/US VIX ratio uses Nifty price ÷ Nifty price)

These tests catch those failures fast (~3s) without touching Yahoo Finance.
They use the local parquet cache exclusively (set MARKET_DATA_CACHE_ONLY=1).

Test groups
-----------
  TestFeatureStoreShape        — row count, column count, date range, index type
  TestTickerSanityRanges       — each ticker's Close is in the expected price range
  TestCrossContamination       — no non-Nifty column contains Nifty price data
  TestNaNBudget                — per-column NaN % within acceptable rolling warmup
  TestDerivedFeatures          — computed columns are well-formed (std>0, range ok)
  TestVIXFeatures              — VIX and all derived VIX series are non-flat
  TestCrossAssetComposites     — composite scores are finite and non-constant
  TestFeatureExtractorColumns  — every column FeatureExtractor.extract() reads is in the dataset
  TestP3DerivedColumns         — Phase 2b derived columns: present, finite, non-constant
  TestP3Formulas               — Phase 2b formulas on synthetic frames, zero-variance guards, look-ahead
  TestCacheIntegrity           — parquet cache files contain the right ticker data
  TestRollingWarmupNaN         — rolling-window NaN budget matches window sizes
"""

from __future__ import annotations

import os
import math
import warnings
import hashlib
import pytest
import numpy as np
import pandas as pd
from datetime import date
from pathlib import Path
from unittest.mock import patch

# Force cache-only mode so tests never hit Yahoo Finance
os.environ.setdefault("MARKET_DATA_CACHE_ONLY", "1")

from data.market_data import P3_DERIVED_COLUMNS  # noqa: E402

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Shared fixture: load dataset once per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def dataset() -> pd.DataFrame:
    """Load the full combined dataset from parquet cache (no network)."""
    from data.market_data import MarketDataFetcher
    from config import BacktestConfig

    cfg = BacktestConfig()
    fetcher = MarketDataFetcher(cfg.start_date, cfg.end_date)
    data = fetcher.build_combined_dataset()
    return data


# ---------------------------------------------------------------------------
# TestFeatureStoreShape
# ---------------------------------------------------------------------------

class TestFeatureStoreShape:
    """Basic shape, index type, and date-range checks."""

    def test_has_minimum_rows(self, dataset):
        """At least 10 years of trading days (≈2500 rows)."""
        assert len(dataset) >= 2500, (
            f"Only {len(dataset)} rows — expected ≥2500 (10yr of trading days). "
            "Parquet cache may be missing or truncated."
        )

    def test_has_minimum_columns(self, dataset):
        """At least 80 feature columns."""
        assert len(dataset.columns) >= 80, (
            f"Only {len(dataset.columns)} columns — expected ≥80 features. "
            "build_combined_dataset() may have short-circuited."
        )

    def test_index_is_datetimeindex(self, dataset):
        assert isinstance(dataset.index, pd.DatetimeIndex), (
            f"Index is {type(dataset.index).__name__}, expected DatetimeIndex"
        )

    def test_index_has_no_nulls(self, dataset):
        assert dataset.index.isna().sum() == 0, "DatetimeIndex contains NaT values"

    def test_index_is_monotonic(self, dataset):
        assert dataset.index.is_monotonic_increasing, "DatetimeIndex is not sorted"

    def test_index_has_no_duplicates(self, dataset):
        dupes = dataset.index.duplicated().sum()
        assert dupes == 0, f"DatetimeIndex has {dupes} duplicate timestamps"

    def test_start_date_covers_2009(self, dataset):
        assert dataset.index.min().year <= 2009, (
            f"Dataset starts at {dataset.index.min().date()} — expected 2009 or earlier"
        )

    def test_end_date_is_recent(self, dataset):
        """Dataset must end within the last 30 days."""
        days_old = (pd.Timestamp.today() - dataset.index.max()).days
        assert days_old <= 30, (
            f"Dataset ends at {dataset.index.max().date()} — {days_old} days old. "
            "Run --mode refresh-data to update the parquet cache."
        )

    def test_nifty_close_present(self, dataset):
        assert "nifty_close" in dataset.columns

    def test_vix_present(self, dataset):
        assert "vix" in dataset.columns


# ---------------------------------------------------------------------------
# TestTickerSanityRanges
# ---------------------------------------------------------------------------

TICKER_RANGES = {
    # (column_name, expected_median_lo, expected_median_hi, description)
    "nifty_close":  (3_000,  30_000, "Nifty 50 index"),
    "vix":          (12,     40,     "India VIX"),
    "us_vix":       (12,     35,     "US VIX (CBOE)"),
    "usdinr":       (45,     95,     "USD/INR exchange rate"),
    "gold":         (1_000,  4_500,  "Gold futures (USD/oz)"),
    "dxy":          (78,     112,    "DXY Dollar Index"),
    "sp500":        (1_000,  7_000,  "S&P 500"),
    "nifty_bank":   (5_000,  55_000, "Bank Nifty"),
    "nifty_it":     (3_000,  40_000, "Nifty IT"),
    "silver":       (12,     50,     "Silver futures (USD/oz)"),
    "crude":        (30,     110,    "Crude oil (Brent, USD/bbl)"),
    "em_etf":       (20,     65,     "EM ETF (EEM)"),
    "hang_seng":    (12_000, 33_000, "Hang Seng Index"),
    "europe":       (2_000,  6_000,  "EuroStoxx 50"),
}


class TestTickerSanityRanges:
    """Each raw price column must have median within the expected economic range."""

    @pytest.mark.parametrize("col,lo,hi,desc", [
        (col, lo, hi, desc) for col, (lo, hi, desc) in TICKER_RANGES.items()
    ])
    def test_median_in_range(self, dataset, col, lo, hi, desc):
        if col not in dataset.columns:
            pytest.skip(f"Column {col!r} not in dataset")
        med = dataset[col].dropna().median()
        assert lo <= med <= hi, (
            f"{desc} ({col}): median={med:.2f} not in [{lo}, {hi}]. "
            "Likely cross-contaminated with Nifty price data — "
            "delete the corresponding parquet cache file and re-fetch."
        )

    @pytest.mark.parametrize("col,lo,hi,desc", [
        (col, lo, hi, desc) for col, (lo, hi, desc) in TICKER_RANGES.items()
    ])
    def test_has_variance(self, dataset, col, lo, hi, desc):
        """Each ticker must not be flat (std > 0.01 × median)."""
        if col not in dataset.columns:
            pytest.skip(f"Column {col!r} not in dataset")
        s = dataset[col].dropna()
        relative_std = s.std() / (abs(s.median()) + 1e-9)
        assert relative_std > 0.01, (
            f"{desc} ({col}): relative_std={relative_std:.4f} — column is nearly flat. "
            "Parquet cache may contain stub/constant data."
        )


# ---------------------------------------------------------------------------
# TestCrossContamination
# ---------------------------------------------------------------------------

class TestCrossContamination:
    """No cross-asset column should contain Nifty price data."""

    NON_NIFTY_COLS = [
        "us_vix", "usdinr", "gold", "dxy", "sp500",
        "nifty_bank", "silver", "crude", "em_etf", "hang_seng", "europe",
    ]

    @pytest.mark.parametrize("col", NON_NIFTY_COLS)
    def test_not_nifty_data(self, dataset, col):
        """Column must not have the same median as nifty_close."""
        if col not in dataset.columns:
            pytest.skip(f"Column {col!r} not in dataset")
        nifty_med = dataset["nifty_close"].dropna().median()
        col_med = dataset[col].dropna().median()
        ratio = col_med / (nifty_med + 1e-9)
        assert not (0.8 <= ratio <= 1.2), (
            f"{col}: median={col_med:.0f} is within 20% of nifty_close median={nifty_med:.0f}. "
            f"Column contains cross-contaminated Nifty data. "
            f"Delete data/.cache/<md5>.parquet for this ticker and re-fetch."
        )

    def test_vix_not_nifty(self, dataset):
        """India VIX median must be in VIX range, not Nifty price range."""
        vix_med = dataset["vix"].dropna().median()
        assert vix_med < 100, (
            f"vix median={vix_med:.1f} — this is Nifty price data, not VIX. "
            "VIX cache file is corrupted."
        )

    def test_usdinr_not_nifty(self, dataset):
        """USD/INR must be in 40–120 range, not thousands."""
        if "usdinr" not in dataset.columns:
            pytest.skip()
        med = dataset["usdinr"].dropna().median()
        assert med < 150, (
            f"usdinr median={med:.1f} — expected 40–120. Cross-contaminated with Nifty."
        )

    def test_all_cross_assets_distinct_from_nifty(self, dataset):
        """All cross-asset columns must have mutually distinct medians."""
        cols = [c for c in self.NON_NIFTY_COLS if c in dataset.columns]
        medians = {c: dataset[c].dropna().median() for c in cols}
        # Group by 'same within 10%' — no two should be in the same group as nifty_close
        nifty_med = dataset["nifty_close"].dropna().median()
        contaminated = [c for c, m in medians.items() if 0.7 <= m / nifty_med <= 1.3]
        assert contaminated == [], (
            f"These columns appear to contain Nifty data: {contaminated}. "
            "Their parquet cache files need re-fetching."
        )


# ---------------------------------------------------------------------------
# TestNaNBudget
# ---------------------------------------------------------------------------

class TestNaNBudget:
    """NaN counts must stay within rolling-window warmup bounds."""

    # (column, max_nan_pct) — warmup only; nothing else explains NaNs
    NAN_BUDGET = {
        "nifty_close":          0.0,   # raw price — never NaN
        "nifty_high":           0.0,
        "nifty_low":            0.0,
        "nifty_open":           0.0,
        "vix":                  0.1,   # tiny alignment gap
        "nifty_return":         0.1,   # 1-day return
        "nifty_return_5d":      0.5,   # 5-day return
        "nifty_return_20d":     1.0,   # 20-day return
        "nifty_sma_20":         1.0,   # 20-day SMA
        "nifty_sma_50":         1.5,   # 50-day SMA
        "nifty_rsi_14":         0.5,   # 14-day RSI
        "nifty_bb_width":       1.0,
        "nifty_realized_vol_20d": 1.0,
        "vix_sma_10":           0.5,
        "vix_sma_50":           1.5,
        "vix_vs_sma_ratio":     0.5,
        "crash_risk_score":     0.0,   # always computed
        "crash_risk_score_v2":  0.0,
        "multi_asset_stress":   1.5,   # needs 50d rolling std
        "overnight_gap_pct":    0.1,
        # Phase 2b derived columns. Budgets = warmup rows / 4361 rows + margin.
        "dxy_change_5d":                0.2,   # 5-row warmup (0.11%)
        "dxy_change_20d":               0.6,   # 20 rows (0.46%)
        "gold_change_20d":              0.6,   # 20 rows
        "crude_spike_10d_pct":          0.3,   # 10 rows (0.23%)
        "vrp_change_5d":                0.7,   # 20-row VRP warmup + 5 (0.57%)
        "vrp_negative":                 0.6,   # 20-row VRP warmup (0.46%)
        "rvol_10d_z":                   1.5,   # 10 + 50 rows (1.35%)
        "range_expansion_ratio":        0.5,   # 20-row range warmup (0.44%)
        "bn_ratio_change_5d":           0.2,   # 5 rows
        "correlation_spike_5d":         0.7,   # 20 + 5 rows (0.57%)
        "gap_magnitude_avg_5d":         0.2,   # 5 rows
        "intraday_dd_expanding_3d":     0.1,   # 3 rows
        "nifty_distance_from_sma20_pct": 0.5,  # 20 rows (0.44%)
        "nifty_distance_from_sma50_pct": 1.2,  # 50 rows (1.12%)
    }

    @pytest.mark.parametrize("col,max_pct", NAN_BUDGET.items())
    def test_nan_within_budget(self, dataset, col, max_pct):
        if col not in dataset.columns:
            pytest.skip(f"Column {col!r} not in dataset")
        nan_pct = dataset[col].isnull().mean() * 100
        assert nan_pct <= max_pct + 0.1, (
            f"{col}: {nan_pct:.2f}% NaN (budget: {max_pct:.1f}%). "
            "Excess NaN suggests upstream ticker data is missing."
        )

    def test_no_all_nan_columns(self, dataset):
        """No column should be entirely NaN."""
        all_nan = [c for c in dataset.columns if dataset[c].isnull().all()]
        assert all_nan == [], (
            f"Completely-NaN columns: {all_nan}. "
            "These features will contribute nothing to the model."
        )

    def test_crash_score_has_no_nan(self, dataset):
        assert dataset["crash_risk_score"].isnull().sum() == 0, (
            "crash_risk_score has NaN — the crash score formula is broken"
        )

    def test_multi_asset_stress_not_all_nan(self, dataset):
        non_null = dataset["multi_asset_stress"].notnull().sum()
        assert non_null > len(dataset) * 0.95, (
            f"multi_asset_stress has only {non_null} non-null rows out of {len(dataset)}. "
            "Likely caused by a cross-asset ticker being flat/wrong."
        )


# ---------------------------------------------------------------------------
# TestDerivedFeatures
# ---------------------------------------------------------------------------

class TestDerivedFeatures:
    """Computed/derived columns must be well-formed."""

    def test_nifty_return_is_percentage_not_price(self, dataset):
        """Daily return must be in (-30%, +30%) range, not price levels."""
        s = dataset["nifty_return"].dropna()
        assert s.abs().max() < 0.30, (
            f"nifty_return max={s.abs().max():.4f} — looks like price, not return"
        )

    def test_rsi_bounds(self, dataset):
        """RSI must be in [0, 100]."""
        s = dataset["nifty_rsi_14"].dropna()
        assert s.min() >= 0 and s.max() <= 100, (
            f"nifty_rsi_14 out of [0,100]: [{s.min():.2f}, {s.max():.2f}]"
        )

    def test_crash_score_bounds(self, dataset):
        for col in ("crash_risk_score", "crash_risk_score_v2"):
            s = dataset[col].dropna()
            assert s.min() >= 0.0 and s.max() <= 1.0, (
                f"{col} out of [0,1]: [{s.min():.4f}, {s.max():.4f}]"
            )

    def test_drawdown_is_non_positive(self, dataset):
        for col in ("nifty_drawdown_from_20d_high_pct", "nifty_drawdown_from_50d_high_pct"):
            if col not in dataset.columns:
                continue
            s = dataset[col].dropna()
            assert s.max() <= 0.001, (
                f"{col} has positive values (max={s.max():.4f}) — "
                "drawdown from high must be ≤ 0"
            )

    def test_overnight_gap_is_percentage(self, dataset):
        """overnight_gap_pct is in percentage-point units (* 100).
        Normal range is roughly −10% to +10%; extreme moves like circuit breakers
        can hit ±15%.  Anything above 20% would be a price-level unit error."""
        s = dataset["overnight_gap_pct"].dropna()
        assert s.abs().max() < 20.0, (
            f"overnight_gap_pct max abs={s.abs().max():.4f} — "
            "expected percentage-points (<20), got price-level values"
        )
        # Also confirm it's not fractional (which would mean missing the ×100)
        assert s.abs().max() > 0.1, (
            f"overnight_gap_pct max abs={s.abs().max():.6f} — "
            "looks like a fraction not percentage-points (missing ×100?)"
        )

    def test_vol_risk_premium_reasonable(self, dataset):
        """VRP = VIX − realized vol; expected range roughly −40 to +40."""
        if "vol_risk_premium" not in dataset.columns:
            pytest.skip()
        s = dataset["vol_risk_premium"].dropna()
        assert s.min() > -60 and s.max() < 60, (
            f"vol_risk_premium range [{s.min():.1f}, {s.max():.1f}] looks unreasonable"
        )

    def test_bb_width_positive(self, dataset):
        s = dataset["nifty_bb_width"].dropna()
        assert (s > 0).all(), "nifty_bb_width has non-positive values"

    def test_consec_down_days_non_negative(self, dataset):
        s = dataset["nifty_consec_down_days"].dropna()
        assert s.min() >= 0 and s.max() <= 30, (
            f"nifty_consec_down_days out of [0,30]: [{s.min()}, {s.max()}]"
        )

    def test_realized_vol_positive(self, dataset):
        for col in ("nifty_realized_vol_10d", "nifty_realized_vol_20d"):
            if col not in dataset.columns:
                continue
            s = dataset[col].dropna()
            assert (s > 0).all(), f"{col} has non-positive values"


# ---------------------------------------------------------------------------
# TestVIXFeatures
# ---------------------------------------------------------------------------

class TestVIXFeatures:
    """VIX and all derived VIX series must be non-flat and in valid range."""

    def test_vix_not_constant(self, dataset):
        std = dataset["vix"].std()
        assert std > 2.0, (
            f"vix std={std:.4f} — VIX is nearly flat. "
            "The India VIX parquet cache is corrupted (likely contains Nifty data). "
            "Delete data/.cache/<md5 for ^INDIAVIX>.parquet and re-fetch."
        )

    def test_vix_range(self, dataset):
        s = dataset["vix"].dropna()
        assert s.min() < 15 and s.max() > 30, (
            f"vix range [{s.min():.1f}, {s.max():.1f}] is implausibly narrow. "
            "Real India VIX spans ~9–84 over 17 years."
        )

    def test_vix_sees_2020_spike(self, dataset):
        """India VIX spiked above 60 during March 2020 COVID crash."""
        mar2020 = dataset.loc["2020-03-01":"2020-04-30", "vix"].dropna()
        if len(mar2020) == 0:
            pytest.skip("No 2020-03 data in dataset")
        assert mar2020.max() > 50, (
            f"VIX max in Mar-Apr 2020 = {mar2020.max():.1f} — expected >50 (COVID spike). "
            "VIX data is wrong or missing for this period."
        )

    def test_vix_sma_tracks_vix(self, dataset):
        """10-day VIX SMA must be correlated with VIX (r > 0.95)."""
        s = dataset[["vix", "vix_sma_10"]].dropna()
        if len(s) < 100:
            pytest.skip()
        corr = s["vix"].corr(s["vix_sma_10"])
        assert corr > 0.95, f"vix vs vix_sma_10 correlation={corr:.3f} — expected >0.95"

    def test_vix_vs_sma_ratio_centered_near_one(self, dataset):
        """vix / vix_sma_10 should be centred near 1.0."""
        s = dataset["vix_vs_sma_ratio"].dropna()
        assert 0.8 <= s.median() <= 1.2, (
            f"vix_vs_sma_ratio median={s.median():.3f} — expected near 1.0"
        )

    def test_vix_change_not_flat(self, dataset):
        std = dataset["vix_change_1d"].dropna().std()
        assert std > 0.01, (
            f"vix_change_1d std={std:.6f} — flat. Derived from constant VIX."
        )

    def test_us_vix_not_nifty(self, dataset):
        """US VIX must not have Nifty price data (common cross-contamination)."""
        if "us_vix" not in dataset.columns:
            pytest.skip()
        med = dataset["us_vix"].dropna().median()
        assert med < 100, (
            f"us_vix median={med:.1f} — looks like Nifty prices, not VIX. "
            "The ^VIX parquet cache is cross-contaminated."
        )

    def test_vix_premium_over_us_range(self, dataset):
        """India VIX premium over US VIX: typically −2 to +20."""
        if "vix_premium_over_us" not in dataset.columns:
            pytest.skip()
        s = dataset["vix_premium_over_us"].dropna()
        assert s.min() > -10 and s.max() < 30, (
            f"vix_premium_over_us range [{s.min():.2f},{s.max():.2f}] out of expected [-10,30]"
        )
        assert s.std() > 0.1, (
            f"vix_premium_over_us std={s.std():.4f} — flat. Both VIX series are contaminated."
        )


# ---------------------------------------------------------------------------
# TestCrossAssetComposites
# ---------------------------------------------------------------------------

class TestCrossAssetComposites:
    """Composite scores built from cross-asset data must be non-trivial."""

    def test_multi_asset_stress_has_variance(self, dataset):
        s = dataset["multi_asset_stress"].dropna()
        assert s.std() > 0.1, (
            f"multi_asset_stress std={s.std():.4f} — flat or near-zero. "
            "Requires crude, usdinr, and vix to all vary. Check cross-asset caches."
        )

    def test_multi_asset_stress_range(self, dataset):
        s = dataset["multi_asset_stress"].dropna()
        assert s.min() < -0.5 and s.max() > 0.5, (
            f"multi_asset_stress range [{s.min():.2f},{s.max():.2f}] too narrow. "
            "Expected to span ≈ −3 to +3 over a 17-year period."
        )

    def test_global_fear_ratio_range(self, dataset):
        if "global_fear_ratio" not in dataset.columns:
            pytest.skip()
        s = dataset["global_fear_ratio"].dropna()
        assert s.min() > 0.1 and s.max() < 10, (
            f"global_fear_ratio range [{s.min():.3f},{s.max():.3f}] out of [0.1,10]. "
            "Likely one of us_vix or vix is still cross-contaminated."
        )

    def test_crude_inr_composite_not_flat(self, dataset):
        if "crude_inr_composite" not in dataset.columns:
            pytest.skip()
        s = dataset["crude_inr_composite"].dropna()
        assert s.std() > 0.1, (
            f"crude_inr_composite std={s.std():.4f} — flat. Crude or INR data is wrong."
        )

    def test_india_us_correlation_not_constant_one(self, dataset):
        """India/US 20d correlation must vary; constant 1.0 = cross-contamination."""
        if "india_us_correlation_20d" not in dataset.columns:
            pytest.skip()
        s = dataset["india_us_correlation_20d"].dropna()
        assert s.std() > 0.01, (
            f"india_us_correlation_20d std={s.std():.6f} — always {s.iloc[0]:.2f}. "
            "Both Nifty and sp500 are likely the same (Nifty) data."
        )
        assert s.min() < 0.9, (
            f"india_us_correlation_20d min={s.min():.3f} — never drops below 0.9. "
            "Real India/US correlation varies from ~−0.3 to ~+0.9."
        )

    def test_fii_flow_proxy_not_all_zeros(self, dataset):
        if "fii_flow_proxy" not in dataset.columns:
            pytest.skip()
        s = dataset["fii_flow_proxy"].dropna()
        nonzero = (s.abs() > 1e-6).mean()
        assert nonzero > 0.3, (
            f"fii_flow_proxy is zero {(1-nonzero)*100:.1f}% of the time. "
            "This proxy (dxy_change × usdinr_change) should vary with FX moves."
        )


# ---------------------------------------------------------------------------
# TestFeatureExtractorColumns
# ---------------------------------------------------------------------------

# Option-derived columns that FeatureExtractor reads but that cannot be derived from
# spot/VIX/macro data (no historical NSE option chain). Deliberately NOT in the dataset.
EXCLUDED_OPTION_COLUMNS = (
    "iv_rv_term_spread",
    "iv_rv_term_spread_5d_chg",
    "iv_rv_term_spread_z",
    "iv_skew_proxy",
    "iv_skew_proxy_z",
    "theta_quality",
    "vega_regime",
    "vega_regime_5d_chg",
    "institutional_hedge_proxy",
    "global_contagion_score",   # no spec
    "vix_volatility_10d",       # ambiguous spec
    "regime_stability_10d",     # ambiguous spec
)

# Extractor sources allowed to be absent from the dataset (sentiment comes from a
# separate news/price-action module; geopolitical_risk is not read by extract()).
EXTRACTOR_SOURCES_NOT_IN_DATASET_OK = {"sentiment_proxy", "geopolitical_risk"}


def _extractor_source_columns() -> set[str]:
    """Column names FeatureExtractor.extract() reads, parsed from its AST.

    Collects the string literal first argument of ``_get("...")`` and ``row.get("...")``.
    """
    import ast
    import inspect
    import textwrap
    from models.trade_learner import FeatureExtractor

    tree = ast.parse(textwrap.dedent(inspect.getsource(FeatureExtractor.extract)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            continue
        f = node.func
        is_get = isinstance(f, ast.Name) and f.id == "_get"
        is_row_get = (isinstance(f, ast.Attribute) and f.attr == "get"
                      and isinstance(f.value, ast.Name) and f.value.id == "row")
        if is_get or is_row_get:
            names.add(node.args[0].value)
    return names


class TestFeatureExtractorColumns:
    """
    FeatureExtractor (models/trade_learner.py) builds 82 features (trade=None)
    from the combined dataset.  All required source columns must be present.
    """

    def test_all_extractor_features_present(self, dataset):
        """Every source column FeatureExtractor.extract() reads must exist in the dataset.

        The source names are parsed from the extract() AST (``_get("...")`` and
        ``row.get("...")`` calls), so new features are checked without editing this test.
        """
        sources = _extractor_source_columns()
        assert len(sources) >= 60, (
            f"AST parse found only {len(sources)} extractor source columns; "
            "extract() may have been restructured - update _extractor_source_columns()."
        )
        allowed_missing = set(EXCLUDED_OPTION_COLUMNS) | EXTRACTOR_SOURCES_NOT_IN_DATASET_OK
        missing = sources - set(dataset.columns)
        unexpected = sorted(missing - allowed_missing)
        assert unexpected == [], (
            f"FeatureExtractor reads columns absent from the dataset: {unexpected}. "
            "Add them to build_combined_dataset() (look-ahead-safe) or, if they need option "
            "data, document them in EXCLUDED_OPTION_COLUMNS."
        )

    def test_excluded_option_columns_really_excluded(self, dataset):
        """The documented exclusions must be read by the extractor (so the list is honest)
        and must stay absent from the dataset (no placeholder columns)."""
        sources = _extractor_source_columns()
        not_read = sorted(set(EXCLUDED_OPTION_COLUMNS) - sources)
        assert not_read == [], f"EXCLUDED_OPTION_COLUMNS not read by extract(): {not_read}"
        placeholders = [c for c in EXCLUDED_OPTION_COLUMNS if c in dataset.columns]
        assert placeholders == [], (
            f"Option-derived columns present in dataset: {placeholders}. "
            "They cannot be derived from spot/VIX data; remove the placeholders and update the list."
        )

    def test_overnight_gap_pct_col_name(self, dataset):
        """
        FeatureExtractor reads 'overnight_gap_pct'.  An older cache uses
        'nifty_gap_pct' — this test catches the rename regression.
        """
        assert "overnight_gap_pct" in dataset.columns, (
            "'overnight_gap_pct' column missing. "
            "Delete cache and regenerate — older parquet had 'nifty_gap_pct'."
        )
        assert "nifty_gap_pct" not in dataset.columns, (
            "'nifty_gap_pct' still present — dataset uses old column name. "
            "FeatureExtractor will produce NaN for overnight_gap_pct."
        )

    def test_crash_score_v2_present(self, dataset):
        assert "crash_risk_score_v2" in dataset.columns, (
            "crash_risk_score_v2 missing — Gate 6 (crash score v2 ≥ 0.80) will always pass"
        )

    def test_multi_asset_stress_present(self, dataset):
        assert "multi_asset_stress" in dataset.columns, (
            "multi_asset_stress missing — circuit breaker gate will never fire"
        )


# ---------------------------------------------------------------------------
# TestCacheIntegrity
# ---------------------------------------------------------------------------

class TestCacheIntegrity:
    """Parquet cache files contain data matching their ticker's expected range."""

    CACHE_DIR = Path("data/.cache")

    def _load_cache(self, ticker: str, start="2009-01-01") -> pd.DataFrame | None:
        from datetime import date, timedelta
        from data.market_data import cache_filename
        eff_end = date.today() - timedelta(days=1)
        path = self.CACHE_DIR / cache_filename(ticker, start, eff_end)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        return df

    @pytest.mark.parametrize("ticker,lo,hi", [
        ("^INDIAVIX",   9,    90),
        ("^VIX",        9,    85),
        ("INR=X",       43,   97),
        ("GC=F",        800,  5400),
        ("DX-Y.NYB",    72,   115),
        ("^GSPC",       600,  8000),
        ("^NSEBANK",    3000, 65000),
        ("^CNXIT",      2000, 46000),
    ])
    def test_cache_file_close_range(self, ticker, lo, hi):
        """Each ticker's parquet cache must contain Close data in the expected range."""
        df = self._load_cache(ticker)
        if df is None:
            pytest.skip(f"No cache file for {ticker} with today's effective_end")
        if "Close" not in df.columns:
            pytest.fail(f"{ticker} cache has no 'Close' column: {list(df.columns)}")
        close = df["Close"].dropna()
        assert len(close) > 100, f"{ticker} cache has only {len(close)} rows"
        med = close.median()
        assert lo <= med <= hi, (
            f"{ticker}: median Close={med:.1f} not in [{lo},{hi}]. "
            "Cache contains wrong data (likely cross-contaminated with Nifty). "
            "Delete this file and re-run --mode refresh-data."
        )

    def test_vix_cache_not_nifty(self):
        """India VIX cache must not have Nifty price values (common corruption)."""
        df = self._load_cache("^INDIAVIX")
        if df is None:
            pytest.skip("No ^INDIAVIX cache for today's effective_end")
        close = df["Close"].dropna()
        assert close.max() < 150, (
            f"^INDIAVIX cache Close max={close.max():.1f} — "
            "this is Nifty price data, not VIX. Cache is corrupted."
        )

    def test_nifty_cache_not_vix(self):
        """Nifty cache must not have VIX-range values."""
        df = self._load_cache("^NSEI")
        if df is None:
            pytest.skip("No ^NSEI cache for today's effective_end")
        close = df["Close"].dropna()
        assert close.median() > 1000, (
            f"^NSEI cache Close median={close.median():.1f} — "
            "expected >1000 (Nifty is in thousands, not single digits)."
        )

    def test_cross_asset_dedicated_caches_not_nifty(self):
        """
        The dedicated parquet cache for each non-Nifty ticker must NOT contain
        Nifty price data.  This detects the corruption pattern where yfinance
        returns a MultiIndex DataFrame and it gets stored without ticker labelling.
        """
        non_nifty = {
            "^INDIAVIX": (5, 100),       # India VIX
            "^VIX":      (5, 90),        # US VIX
            "INR=X":     (40, 120),      # USD/INR
            "GC=F":      (500, 5500),    # Gold
            "DX-Y.NYB":  (70, 120),      # DXY
            "^GSPC":     (500, 8000),    # S&P 500
        }
        contaminated = []
        for ticker, (lo, hi) in non_nifty.items():
            df = self._load_cache(ticker)
            if df is None or "Close" not in df.columns:
                continue  # cache missing — other tests cover this
            close = df["Close"].dropna()
            med = close.median()
            if not (lo <= med <= hi):
                contaminated.append(f"{ticker}: median={med:.0f} (expected [{lo},{hi}])")

        assert contaminated == [], (
            "Cross-asset ticker caches contain wrong data:\n"
            + "\n".join(f"  {c}" for c in contaminated)
            + "\nLikely caused by MultiIndex column flattening bug in a prior fetch. "
            "Delete the listed cache files and re-fetch."
        )


# ---------------------------------------------------------------------------
# TestRollingWarmupNaN
# ---------------------------------------------------------------------------

class TestRollingWarmupNaN:
    """
    Rolling-window features are NaN during warmup.  After warmup ends the
    rest of the column must be non-NaN.  This catches ticker fetch failures
    that silently produce all-NaN columns after the warmup period.
    """

    ROLLING_COLS = {
        # (column, window_days) — first `window_days` rows may be NaN
        "nifty_sma_20":              20,
        "nifty_sma_50":              50,
        "nifty_realized_vol_20d":    20,
        "vix_sma_10":                10,
        "vix_sma_50":                50,
        "nifty_bb_width":            20,
        "nifty_drawdown_from_50d_high_pct": 50,
        "multi_asset_stress":        50,
    }

    @pytest.mark.parametrize("col,window", ROLLING_COLS.items())
    def test_post_warmup_non_nan(self, dataset, col, window):
        """After the warmup window, ≥98% of rows must be non-NaN."""
        if col not in dataset.columns:
            pytest.skip(f"Column {col!r} not in dataset")
        post_warmup = dataset.iloc[window + 5:][col]
        nan_pct = post_warmup.isnull().mean() * 100
        assert nan_pct <= 2.0, (
            f"{col}: {nan_pct:.2f}% NaN after warmup window {window}d. "
            "This suggests the underlying ticker data is missing or corrupted "
            "beyond just the rolling warmup."
        )

    def test_crash_score_post_warmup_complete(self, dataset):
        """crash_risk_score should be 100% non-NaN after row 0."""
        nan_count = dataset["crash_risk_score"].isnull().sum()
        assert nan_count == 0, (
            f"crash_risk_score has {nan_count} NaN rows — "
            "it should always be computable from vix and nifty_close alone."
        )


# ---------------------------------------------------------------------------
# TestP3DerivedColumns  (Phase 2b: columns requested by FeatureExtractor)
# ---------------------------------------------------------------------------

class TestP3DerivedColumns:
    """Columns added in build_combined_dataset() for Phase 2b, on the real cache."""

    def test_all_p3_columns_present(self, dataset):
        missing = [c for c in P3_DERIVED_COLUMNS if c not in dataset.columns]
        assert missing == [], f"Phase 2b columns missing from dataset: {missing}"

    def test_no_inf(self, dataset):
        cols = [c for c in P3_DERIVED_COLUMNS if c in dataset.columns]
        vals = dataset[cols].to_numpy(dtype=float)
        n_inf = int(np.isinf(vals).sum())
        assert n_inf == 0, f"{n_inf} inf values in Phase 2b columns (should be NaN)"

    def test_not_constant(self, dataset):
        constant = [c for c in P3_DERIVED_COLUMNS
                    if c in dataset.columns and dataset[c].nunique(dropna=True) <= 1]
        assert constant == [], f"Constant Phase 2b columns: {constant}"

    def test_post_warmup_mostly_finite(self, dataset):
        """After 60 rows of warmup every Phase 2b column must be >= 98% non-NaN."""
        tail = dataset.iloc[60:]
        for c in P3_DERIVED_COLUMNS:
            if c not in dataset.columns:
                continue
            nan_pct = tail[c].isnull().mean() * 100
            assert nan_pct <= 2.0, f"{c}: {nan_pct:.2f}% NaN after 60-row warmup"


# ---------------------------------------------------------------------------
# TestP3Formulas  (synthetic frames: no cache, no network)
# ---------------------------------------------------------------------------

def _synthetic_frames(n: int = 260, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Deterministic raw ticker frames shaped like the parquet cache."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)

    def walk(start: float, vol: float) -> np.ndarray:
        return start * np.exp(np.cumsum(rng.normal(0.0, vol, n)))

    close = walk(20_000.0, 0.01)
    open_ = close * (1 + rng.normal(0.0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0.0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0.0, 0.003, n)))
    frames = {
        "nifty": pd.DataFrame({"Open": open_, "High": high, "Low": low,
                               "Close": close, "Volume": 1e6}, index=idx),
        "vix": pd.DataFrame({"Close": walk(15.0, 0.03)}, index=idx),
        "crude_brent": pd.DataFrame({"Close": walk(75.0, 0.015)}, index=idx),
    }
    for name, start, vol in [
        ("usdinr", 80.0, 0.003), ("gold", 1800.0, 0.008), ("dxy", 100.0, 0.004),
        ("us_vix", 16.0, 0.03), ("us_10y", 2.0, 0.01), ("sp500", 4000.0, 0.01),
        ("nifty_bank", 40_000.0, 0.012), ("silver", 25.0, 0.015),
        ("nifty_it", 30_000.0, 0.012), ("em_etf", 40.0, 0.008),
        ("hang_seng", 20_000.0, 0.01), ("europe", 4000.0, 0.01),
    ]:
        frames[name] = pd.DataFrame({"Close": walk(start, vol)}, index=idx)
    return frames


def _build_from_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Run the real build_combined_dataset() on in-memory frames (fetch_all stubbed out)."""
    from datetime import date
    from data.market_data import MarketDataFetcher

    fetcher = MarketDataFetcher(date(2020, 1, 1), date(2030, 1, 1))
    fetcher._data = {k: v.copy() for k, v in frames.items()}
    with patch.object(fetcher, "fetch_all", return_value=fetcher._data):
        return fetcher.build_combined_dataset()


@pytest.fixture(scope="module")
def synthetic_dataset() -> pd.DataFrame:
    return _build_from_frames(_synthetic_frames())


def _assert_series_matches(actual: pd.Series, expected: pd.Series, name: str) -> None:
    pd.testing.assert_series_equal(
        actual.astype(float), expected.astype(float),
        check_names=False, check_freq=False, rtol=1e-10, atol=1e-12,
        obj=name,
    )


class TestP3Formulas:

    def test_crude_spike_10d_pct_is_percent(self):
        """Crude 100 -> 130 step: 10-session change is +30 (percent), not 0.3."""
        frames = _synthetic_frames()
        idx = frames["vix"].index
        crude = np.full(len(idx), 100.0)
        crude[10:] = 130.0
        frames["crude_brent"] = pd.DataFrame({"Close": crude}, index=idx)
        d = _build_from_frames(frames)
        assert d["crude_spike_10d_pct"].iloc[10] == pytest.approx(30.0)
        assert d["crude_spike_10d_pct"].iloc[19] == pytest.approx(30.0)
        assert d["crude_spike_10d_pct"].iloc[20] == pytest.approx(0.0)
        assert np.isnan(d["crude_spike_10d_pct"].iloc[9])

    def test_dxy_and_gold_changes_are_fractions(self):
        frames = _synthetic_frames()
        idx = frames["vix"].index
        n = len(idx)
        frames["dxy"] = pd.DataFrame({"Close": 100.0 * 1.01 ** np.arange(n)}, index=idx)
        frames["gold"] = pd.DataFrame({"Close": 1800.0 * 1.02 ** np.arange(n)}, index=idx)
        d = _build_from_frames(frames)
        assert d["dxy_change_5d"].iloc[30] == pytest.approx(1.01 ** 5 - 1)
        assert d["dxy_change_20d"].iloc[30] == pytest.approx(1.01 ** 20 - 1)
        assert d["gold_change_20d"].iloc[30] == pytest.approx(1.02 ** 20 - 1)

    def test_vrp_columns_match_definition(self, synthetic_dataset):
        d = synthetic_dataset
        vrp = d["vol_risk_premium"]
        _assert_series_matches(d["vrp_change_5d"], vrp.diff(5), "vrp_change_5d")
        expected_neg = (vrp < 0).astype(float).where(vrp.notna())
        _assert_series_matches(d["vrp_negative"], expected_neg, "vrp_negative")
        assert d["vrp_negative"].isna().equals(vrp.isna()), "vrp_negative NaN must mirror VRP NaN"

    def test_rvol_10d_z_definition(self, synthetic_dataset):
        d = synthetic_dataset
        rv = d["nifty_realized_vol_10d"]
        expected = (rv - rv.rolling(50).mean()) / rv.rolling(50).std().replace(0, np.nan)
        _assert_series_matches(d["rvol_10d_z"], expected, "rvol_10d_z")

    def test_range_expansion_definition(self, synthetic_dataset):
        d = synthetic_dataset
        r = d["nifty_daily_range_pct"]
        expected = r.rolling(5).mean() / r.rolling(20).mean().replace(0, np.nan)
        _assert_series_matches(d["range_expansion_ratio"], expected, "range_expansion_ratio")

    def test_bn_ratio_change_5d_definition(self, synthetic_dataset):
        d = synthetic_dataset
        expected = d["bank_nifty_ratio"].pct_change(5) * 100
        _assert_series_matches(d["bn_ratio_change_5d"], expected, "bn_ratio_change_5d")

    def test_correlation_spike_definition(self, synthetic_dataset):
        d = synthetic_dataset
        expected = d["india_us_correlation_20d"].diff(5)
        _assert_series_matches(d["correlation_spike_5d"], expected, "correlation_spike_5d")

    def test_gap_magnitude_definition(self, synthetic_dataset):
        d = synthetic_dataset
        expected = d["overnight_gap_pct"].abs().rolling(5).mean()
        _assert_series_matches(d["gap_magnitude_avg_5d"], expected, "gap_magnitude_avg_5d")

    def test_intraday_dd_expanding_definition(self, synthetic_dataset):
        d = synthetic_dataset
        expected = ((d["nifty_low"] - d["nifty_open"]) / d["nifty_open"] * 100).rolling(3).min()
        _assert_series_matches(d["intraday_dd_expanding_3d"], expected, "intraday_dd_expanding_3d")

    def test_distance_from_sma_definition(self, synthetic_dataset):
        d = synthetic_dataset
        c = d["nifty_close"]
        _assert_series_matches(
            d["nifty_distance_from_sma20_pct"],
            (c - d["nifty_sma_20"]) / d["nifty_sma_20"] * 100,
            "nifty_distance_from_sma20_pct",
        )
        _assert_series_matches(
            d["nifty_distance_from_sma50_pct"],
            (c - d["nifty_sma_50"]) / d["nifty_sma_50"] * 100,
            "nifty_distance_from_sma50_pct",
        )

    def test_zero_variance_guards_yield_nan_not_inf(self):
        """Flat Nifty (zero realized vol, zero range) must give NaN, never inf."""
        frames = _synthetic_frames()
        nifty = frames["nifty"].copy()
        nifty[["Open", "High", "Low", "Close"]] = 20_000.0
        frames["nifty"] = nifty
        d = _build_from_frames(frames)
        cols = [c for c in P3_DERIVED_COLUMNS if c in d.columns]
        assert not np.isinf(d[cols].to_numpy(dtype=float)).any()
        assert d["rvol_10d_z"].iloc[60:].isna().all()
        assert d["range_expansion_ratio"].iloc[30:].isna().all()

    def test_look_ahead_truncation_is_identical(self):
        """Value at day t must not change when the input stops at day t."""
        frames = _synthetic_frames(n=260)
        full = _build_from_frames(frames)
        for t in (40, 80, 120, 180, 230):
            truncated = _build_from_frames({k: v.iloc[: t + 1] for k, v in frames.items()})
            stamp = full.index[t]
            assert truncated.index[-1] == stamp
            for c in P3_DERIVED_COLUMNS:
                a = truncated[c].iloc[-1]
                b = full.loc[stamp, c]
                assert np.isclose(a, b, rtol=1e-12, atol=0.0, equal_nan=True), (
                    f"{c} at {stamp.date()} changes when future rows are removed: {a} vs {b}"
                )
