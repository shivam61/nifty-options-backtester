"""
Tests for the monthly expiry selector hard filters and no-trade handling.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from strategies.base import BaseStrategy, Leg, TradeAction
from strategies.expiry_selector import NoEntry, select_optimal_entry


def _priced():
    return SimpleNamespace(
        premium=1.0,
        greeks=SimpleNamespace(delta=0.0, gamma=0.0, theta=0.0, vega=0.0),
    )


class _DummyStrategy(BaseStrategy):
    def __init__(self, name: str, legs: list[Leg]):
        super().__init__(name, lots=1, lot_size=65)
        self._legs = legs

    def generate_legs(self, spot, vix, dte, risk_free_rate=0.065):
        return [replace(leg, lots=self.lots, lot_size=self.lot_size) for leg in self._legs]

    def should_enter(self, spot, vix, market_data):
        return TradeAction.ENTER

    def should_exit(self, trade, spot, vix, dte_remaining):
        return TradeAction.HOLD, None


@pytest.fixture
def selector_patches(monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector.get_upcoming_expiries",
                        lambda entry_date, count=3: [{"expiry": date(2026, 5, 26), "dte": 39}])
    monkeypatch.setattr("strategies.expiry_selector.iv_from_vix", lambda *args, **kwargs: 0.2)
    monkeypatch.setattr("strategies.expiry_selector.price_option", lambda *args, **kwargs: _priced())
    yield


def _put_spread(short_strike: float, long_strike: float, short_premium: float, long_premium: float) -> list[Leg]:
    return [
        Leg("PE", short_strike, True, short_premium, short_premium, 1, 65),
        Leg("PE", long_strike, False, long_premium, long_premium, 1, 65),
    ]


def test_negative_ev_candidate_is_rejected(selector_patches, monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector._estimate_win_prob", lambda *args, **kwargs: 0.64)
    strategies = {
        "put_credit_spread": _DummyStrategy("put_credit_spread", _put_spread(22500, 22000, 27.1, 0.0)),
    }

    decision = select_optimal_entry(
        spot=24266.5,
        vix=24.0,
        strategies=strategies,
        entry_date=date(2026, 4, 17),
        lots=6,
        eligible_strategies=["put_credit_spread"],
    )

    assert isinstance(decision, NoEntry)


def test_high_loss_credit_candidate_is_rejected(selector_patches, monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector._estimate_win_prob", lambda *args, **kwargs: 0.90)
    strategies = {
        "put_credit_spread": _DummyStrategy("put_credit_spread", _put_spread(23000, 22500, 25.0, 0.0)),
    }

    decision = select_optimal_entry(
        spot=24266.5,
        vix=24.0,
        strategies=strategies,
        entry_date=date(2026, 4, 17),
        lots=6,
        eligible_strategies=["put_credit_spread"],
    )

    assert isinstance(decision, NoEntry)


def test_strong_bullish_signal_but_no_valid_structure_returns_no_trade(selector_patches, monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector._estimate_win_prob", lambda *args, **kwargs: 0.95)
    strategies = {
        "put_credit_spread": _DummyStrategy("put_credit_spread", _put_spread(22500, 22000, 27.1, 0.0)),
        "put_credit_wide": _DummyStrategy("put_credit_wide", _put_spread(22000, 21500, 30.0, 0.0)),
    }

    decision = select_optimal_entry(
        spot=24266.5,
        vix=24.0,
        strategies=strategies,
        entry_date=date(2026, 4, 17),
        lots=6,
        eligible_strategies=["put_credit_spread", "put_credit_wide"],
    )

    assert isinstance(decision, NoEntry)


def test_positive_ev_acceptable_risk_candidate_passes(selector_patches, monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector._estimate_win_prob", lambda *args, **kwargs: 0.90)
    strategies = {
        "put_credit_spread": _DummyStrategy("put_credit_spread", _put_spread(22500, 22000, 27.1, 0.0)),
        "put_credit_wide": _DummyStrategy("put_credit_wide", _put_spread(22000, 21500, 120.0, 30.0)),
    }

    decision = select_optimal_entry(
        spot=24266.5,
        vix=24.0,
        strategies=strategies,
        entry_date=date(2026, 4, 17),
        lots=2,
        eligible_strategies=["put_credit_spread", "put_credit_wide"],
    )

    assert not isinstance(decision, NoEntry)
    assert decision.strategy_name == "put_credit_wide"
    assert decision.best.tail_adjusted_ev > 0


def test_legacy_or_unfrozen_strategy_names_are_ignored(selector_patches, monkeypatch):
    monkeypatch.setattr("strategies.expiry_selector._estimate_win_prob", lambda *args, **kwargs: 0.90)
    strategies = {
        "long_strangle": _DummyStrategy("long_strangle", _put_spread(22500, 22000, 220.0, 0.0)),
    }

    decision = select_optimal_entry(
        spot=24266.5,
        vix=24.0,
        strategies=strategies,
        entry_date=date(2026, 4, 17),
        lots=2,
        eligible_strategies=["long_strangle"],
    )

    assert isinstance(decision, NoEntry)
