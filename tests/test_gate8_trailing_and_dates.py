"""Regression: trailing-percentile Gate 8 and Windows-safe date labels."""
from datetime import date
from types import SimpleNamespace

from backtester.combined_engine import CombinedBacktestEngine
from config import BacktestConfig
from data.expiry_calendar import format_expiry_label
from src.utils.dates import parse_cdsl_archive_input


def _stub(pct=0.8, min_obs=5):
    e = CombinedBacktestEngine.__new__(CombinedBacktestEngine)
    e.m_config = SimpleNamespace(
        monthly_gate8_trailing_pctile=pct, monthly_gate8_trailing_min_obs=min_obs
    )
    return e


def test_config_defaults():
    c = BacktestConfig()
    assert c.monthly_gate8_trailing_pctile == 0.80
    assert c.monthly_gate8_trailing_min_obs == 60


def test_warmup_blocks_then_uses_prior_scores_only():
    e = _stub()
    for s in (0.1, 0.2, 0.3, 0.4, 0.5):
        assert e._gate8_trailing_threshold(s) == float("inf")
    thr = e._gate8_trailing_threshold(0.9)
    assert 0.4 <= thr <= 0.5  # P80 of [0.1..0.5], excludes the current 0.9


def test_disabled_returns_none():
    assert _stub(pct=0.0)._gate8_trailing_threshold(0.5) is None


def test_date_labels_portable():
    assert format_expiry_label(date(2026, 4, 7)) == "7 Apr 2026"
    assert parse_cdsl_archive_input(date(2026, 4, 7)) == "April 7, 2026"
