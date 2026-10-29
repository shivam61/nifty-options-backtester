"""Adapters that turn the walk-forward ML models into ChainConfig entry/exit gates.

Fold layout: <fold_root>/<Y>/{weekly_entry.pkl, exit_model.pkl, meta.json}, models trained to Dec 31 of
Y-1 (scripts/train_ml_cutoff.py). The model used for a decision is chosen by the decision date's year and
its meta.json train_end must precede that date.

Look-ahead control (prereg Amendment 1): every series not closed before 15:30 IST on the signal date is
lagged one trading row for gate features (LAG_COLUMNS); India-session series are untouched. Missing or NaN
features raise, except the explicit allowlists below.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

LAG_COLUMNS = [
    "crude", "usdinr", "gold", "dxy", "us_vix", "us_10y", "sp500", "silver", "em_etf", "europe",
    "crude_change_5d", "crude_change_20d", "crude_spike_10d_pct",
    "us_vix_change_5d", "us_vix_sma_10", "global_fear_ratio", "us_10y_change_5d",
    "sp500_return_5d", "sp500_return_20d", "india_us_correlation_20d", "correlation_spike_5d",
    "usdinr_change_5d", "usdinr_change_20d", "gold_change_5d", "gold_change_20d",
    "dxy_change_5d", "dxy_change_20d", "em_return_5d", "em_return_20d", "europe_return_5d",
    "macro_risk_score", "multi_asset_stress",
    "crude_sma_50", "crude_std_50", "usdinr_sma_50", "usdinr_std_50", "gold_sma_50", "gold_std_50",
    "dxy_sma_50", "dxy_std_50", "us_vix_sma_50", "us_vix_std_50", "sp500_sma_50", "sp500_std_50",
    "crude_inr_composite", "dxy_crude_composite", "vix_premium_over_us", "fii_flow_proxy",
]

# Closed before 15:30 IST on the signal date (or computed only from such series).
# hang_seng closes ~13:30 IST. nifty_mid_session uses the same-day close and is never a gate feature.
INDIA_COLUMNS = [
    "nifty_close", "nifty_high", "nifty_low", "nifty_open", "nifty_volume", "vix", "nifty_bank",
    "nifty_it", "hang_seng", "nifty_return", "nifty_return_5d", "nifty_return_20d", "overnight_gap_pct",
    "intraday_move_pct", "overnight_gap_abs", "gap_3d_max_abs", "gap_5d_max_abs",
    "gap_magnitude_avg_5d", "intraday_dd_expanding_3d", "nifty_mid_session", "nifty_sma_20",
    "nifty_sma_50", "nifty_distance_from_sma20_pct", "nifty_distance_from_sma50_pct",
    "nifty_realized_vol_10d", "nifty_realized_vol_20d", "vix_sma_10", "vix_change_1d", "vix_change_5d",
    "vol_risk_premium", "vrp_change_5d", "vrp_negative", "nifty_daily_range_pct", "rvol_10d_z",
    "range_expansion_ratio", "bank_nifty_return_5d", "bank_nifty_ratio", "bn_ratio_change_5d",
    "it_sector_return_5d", "china_return_5d", "china_return_20d", "vix_vs_sma_ratio", "nifty_bb_width",
    "nifty_drawdown_from_20d_high_pct", "nifty_drawdown_from_50d_high_pct", "nifty_rsi_14",
    "vol_expansion_ratio", "crash_risk_score", "crash_risk_score_v2", "vix_sma_50", "vix_std_50",
    "nifty_bank_sma_50", "nifty_bank_std_50", "nifty_consec_down_days", "vix_accel_3d_pct",
]

# Weekly feature read as row["nifty_return_1d"]; the column is absent from the frame, so it is the
# constant 0 in training and inference alike (prereg Amendment 1b).
WEEKLY_CONST_ZERO_COLUMN = "nifty_return_1d"
WEEKLY_CONST_ZERO_FEATURE = "nifty_1d_return"

EXIT_ENTRY_PROB_DEFAULT = 0.75
EXIT_PNL_PCT_DEFAULT = -15.0


def lag_non_india_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with every LAG_COLUMNS column shifted one row; all columns must be classified."""
    unknown = set(df.columns) - set(LAG_COLUMNS) - set(INDIA_COLUMNS)
    if unknown:
        raise ValueError(f"unclassified market columns (lag or India-session?): {sorted(unknown)}")
    out = df.copy()
    cols = [c for c in LAG_COLUMNS if c in out.columns]
    out[cols] = out[cols].shift(1)
    return out


def load_gate_market(end: date, start: date = date(2009, 1, 1)) -> pd.DataFrame:
    """Combined feature frame from the repo cache only, with the non-India columns lagged one row."""
    os.environ["MARKET_DATA_CACHE_ONLY"] = "1"
    from data.market_data import MarketDataFetcher

    raw = MarketDataFetcher(start, end).build_combined_dataset()
    if WEEKLY_CONST_ZERO_COLUMN in raw.columns:
        raise AssertionError(f"{WEEKLY_CONST_ZERO_COLUMN} now exists; Amendment 1b no longer describes it")
    out = lag_non_india_columns(raw)
    out.index = pd.to_datetime(out.index).normalize()
    return out


def _as_ts(d) -> pd.Timestamp:
    return pd.Timestamp(d).normalize()


class _FoldModels:
    """Lazy per-year model loader. Model for decision date d is the one trained to Dec 31 of d.year-1."""

    def __init__(self, fold_root, filename: str, loader, market_df: pd.DataFrame):
        self.root = Path(fold_root)
        self.filename = filename
        self.loader = loader
        self.market_df = market_df
        self._cache: dict[int, object] = {}

    def get(self, d):
        year = _as_ts(d).year
        if year not in self._cache:
            fold = self.root / str(year)
            meta_path = fold / "meta.json"
            if not meta_path.exists():
                raise FileNotFoundError(f"no fold for decision year {year}: {meta_path}")
            meta = json.loads(meta_path.read_text())
            if pd.Timestamp(meta["train_end"]) >= pd.Timestamp(year, 1, 1):
                raise AssertionError(f"fold {year} trained to {meta['train_end']}: not out of sample")
            if pd.Timestamp(meta["max_row_date"]) > pd.Timestamp(meta["train_end"]):
                raise AssertionError(f"fold {year} used rows after its cutoff")
            self._cache[year] = self.loader(self.market_df.copy(), fold / self.filename)
        return self._cache[year]


def _finite_or_raise(values: dict, names, where: str, allow_zero: frozenset = frozenset()) -> np.ndarray:
    out = []
    for n in names:
        if n not in values:
            if n in allow_zero:
                out.append(0.0)
                continue
            raise KeyError(f"{where}: feature {n!r} not produced")
        v = values[n]
        if v is None or (isinstance(v, float) and not np.isfinite(v)) or not np.isfinite(float(v)):
            if n in allow_zero:
                out.append(0.0)
                continue
            raise ValueError(f"{where}: feature {n!r} is {v!r} (missing/non-finite)")
        out.append(float(v))
    return np.array(out, dtype=float).reshape(1, -1)


def _prob_one(clf, X: pd.DataFrame) -> float:
    classes = list(clf.classes_)
    if 1 not in classes:
        raise ValueError("classifier has no positive class")
    return float(clf.predict_proba(X)[0][classes.index(1)])


def make_entry_gate(fold_root, market_df: pd.DataFrame, threshold: float = 0.55):
    """entry_gate(date, strategy_name, vix, market_row) -> (allow, score); allow = score >= threshold."""
    from models.weekly_entry_learner import WeeklyEntryLearner

    models = _FoldModels(fold_root, "weekly_entry.pkl",
                         lambda mdf, p: WeeklyEntryLearner.load(mdf, p), market_df)
    allow_zero = frozenset({WEEKLY_CONST_ZERO_FEATURE})

    def entry_gate(d, strategy_name, vix, market_row):
        ts = _as_ts(d)
        lr = models.get(ts)
        ext = lr.feature_extractor
        if ts not in ext.data.index:
            raise KeyError(f"entry gate: signal date {ts.date()} not in market frame")
        idx = ext.data.index.get_loc(ts)
        row = ext.data.iloc[idx]
        base = ext.extract(row)
        if base is None:
            raise ValueError(f"entry gate: base features unavailable on {ts.date()}")
        feats = {**base, **lr._extract_weekly_features(row, ext.data, idx)}
        x = _finite_or_raise(feats, lr.selected_features, f"entry gate {ts.date()}", allow_zero)
        X = pd.DataFrame(x, columns=lr.selected_features)
        score = _prob_one(lr.quality_classifier, X)
        return score >= threshold, score

    entry_gate.models = models
    return entry_gate


EXIT_ALWAYS_NAN = frozenset([
    "global_contagion_score", "iv_rv_term_spread", "iv_rv_term_spread_5d_chg", "iv_rv_term_spread_z",
    "iv_skew_proxy", "iv_skew_proxy_z", "theta_quality", "vega_regime", "vega_regime_5d_chg",
    "institutional_hedge_proxy", "vix_volatility_10d", "regime_stability_10d",
])


def _exit_always_nan_names() -> frozenset:
    return EXIT_ALWAYS_NAN


def _assert_all_nan(engine, market_df: pd.DataFrame, names: frozenset) -> None:
    """The allowlisted exit features must be NaN on every sampled row (else they are not 'always missing')."""
    ext = engine.feature_extractor
    for i in range(60, len(ext.data), 7):
        f = ext.extract(ext.data.iloc[i])
        if f is None:
            continue
        live = [n for n in names if n in f and f[n] is not None and np.isfinite(float(f[n]))]
        if live:
            raise AssertionError(f"exit allowlist features are not always NaN: {live} at {ext.data.index[i]}")


def trade_exit_features(ctx: dict, hist: dict) -> dict:
    """Map a chain-engine gate ctx to the exit model's trade features (trade_monitor.train_from_simulations).

    Units are per option unit (Rs per unit of the structure), like the training snapshots. hist maps
    holding session -> per-unit mark P&L for this trade and is updated in place.
    """
    trade = ctx["trade"]
    qty = trade.lots * trade.lot_size
    d = int(ctx["holding_sessions"])
    credit_u = ctx["entry_credit_rs"] / qty
    pnl_u = ctx["mark_pnl_rs"] / qty
    spot, entry_spot = ctx["spot"], ctx["entry_spot"]
    vix, entry_vix = ctx["vix"], ctx["entry_vix"]
    if not (credit_u > 0 and spot > 0 and entry_spot > 0 and entry_vix > 0):
        raise ValueError(f"degenerate exit ctx on {ctx['date']}")

    hist[d] = pnl_u
    peak = max([0.0] + [v for k, v in hist.items() if k <= d])
    pnl_pct = pnl_u / credit_u * 100
    if d >= 3:
        if (d - 3) not in hist and (d - 3) > 0:
            raise ValueError(f"pnl history gap at session {d - 3} for trade filled {ctx['fill_date']}")
        pnl_3ago = 0.0 if d - 3 <= 0 else hist[d - 3]
        vel3 = (pnl_u - pnl_3ago) / 3
    else:
        vel3 = pnl_u / max(d, 1)
    if peak > 0:
        first = min(k for k, v in hist.items() if k <= d and v == peak)
        days_since_peak = d - first
    else:
        days_since_peak = 0

    dists = []
    for opt, k in ctx["short_strikes"]:
        dists.append((spot - k) / spot * 100 if opt == "PE" else (k - spot) / spot * 100)
    widths = []
    for leg in trade.legs:
        if leg.is_short:
            longs = [l.strike for l in trade.legs if (not l.is_short) and l.option_type == leg.option_type]
            if not longs:
                raise ValueError("short leg without a protective long leg")
            widths.append(abs(leg.strike - min(longs, key=lambda k: abs(k - leg.strike))))
    max_loss_u = max(widths) - credit_u
    return {
        "pnl_pct": pnl_pct,
        "dte_remaining": ctx["dte"],
        "days_in_trade": d,
        "dist_to_short_strike_pct": min(dists),
        "vix_now": vix,
        "vix_change_since_entry": (vix - entry_vix) / entry_vix,
        "spot_change_since_entry": (spot - entry_spot) / entry_spot * 100,
        "pnl_velocity": pnl_u / d if d > 0 else 0.0,
        "credit_captured_pct": pnl_pct,
        "max_loss_proximity": abs(pnl_u) / max_loss_u if pnl_u < 0 and max_loss_u > 0 else 0.0,
        "theta_estimate": credit_u / max(ctx["holding_days"] + ctx["dte"], 1),
        "pnl_from_peak": pnl_u - peak,
        "pnl_velocity_3d": vel3,
        "days_since_peak": days_since_peak,
    }


def make_exit_gate(fold_root, market_df: pd.DataFrame,
                   prob_threshold: float = EXIT_ENTRY_PROB_DEFAULT,
                   pnl_pct_threshold: float = EXIT_PNL_PCT_DEFAULT):
    """exit_gate(ctx) -> (exit_now, prob); exit_now = prob >= prob_threshold and pnl_pct < pnl_pct_threshold."""
    from models.trade_monitor import ExitStrategyEngine

    allow_zero = _exit_always_nan_names()
    if len(allow_zero) != 12:
        raise AssertionError(f"expected 12 always-NaN exit features, got {len(allow_zero)}")

    def _load(mdf, path):
        eng = ExitStrategyEngine.load(mdf, path)
        _assert_all_nan(eng, mdf, allow_zero)
        return eng

    models = _FoldModels(fold_root, "exit_model.pkl", _load, market_df)
    state = {"key": None, "hist": {}}

    def exit_gate(ctx):
        ts = _as_ts(ctx["date"])
        eng = models.get(ts)
        ext = eng.feature_extractor
        if ts not in ext.data.index:
            raise KeyError(f"exit gate: date {ts.date()} not in market frame")
        row = ext.data.loc[ts]
        market = ext.extract(row)
        if market is None:
            raise ValueError(f"exit gate: market features unavailable on {ts.date()}")
        key = ctx["fill_date"]
        if state["key"] != key:
            state["key"], state["hist"] = key, {}
        tf = trade_exit_features(ctx, state["hist"])
        vs = row.get("vix_vs_sma_ratio")
        v1 = row.get("vix_change_1d")
        tf["vix_vs_sma_ratio_now"] = 1.0 if vs is None or pd.isna(vs) else float(vs)
        tf["vix_1d_change_now"] = 0.0 if v1 is None or pd.isna(v1) else float(v1)
        feats = {**market, **tf}
        cols = list(eng.exit_classifier.feature_name_) if hasattr(eng.exit_classifier, "feature_name_") else None
        cols = cols or getattr(eng, "exit_feature_cols")
        x = _finite_or_raise(feats, cols, f"exit gate {ts.date()}", allow_zero)
        prob = _prob_one(eng.exit_classifier, pd.DataFrame(x, columns=cols))
        return (prob >= prob_threshold and tf["pnl_pct"] < pnl_pct_threshold), prob

    exit_gate.models = models
    return exit_gate
