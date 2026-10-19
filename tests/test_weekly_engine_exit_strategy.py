"""WeeklyBacktestEngine must reprice and exit-check open weekly trades with their entry strategy.

Regression for: WeeklyBacktestEngine.run() re-selected the strategy every day via
_select_strategy(entry_vix, today's market_data), so an open Iron Condor was repriced by
WeeklyPutCreditSpread.update_premiums (call legs priced as puts) on any day |nifty_return_5d| >= 2%.
Same defect as the CombinedBacktestEngine fix in 33dd932.
"""
from datetime import date

import pandas as pd

from config import WeeklyBacktestConfig
from backtester.weekly_engine import WeeklyBacktestEngine
from data.expiry_calendar import get_weekly_expiry_in_range
from pricing.black_scholes import OptionType, iv_from_vix, price_option
from strategies.base import TradeAction

SPOT = 22000.0
VIX = 16.0
RF = 0.065


def _engine(returns_5d) -> WeeklyBacktestEngine:
    """Mon 2026-06-01 (IC entry, calm 5d), Tue, Wed (large 5d move while the IC is open)."""
    dates = pd.bdate_range("2026-06-01", periods=len(returns_5d))
    n = len(returns_5d)
    df = pd.DataFrame({
        "nifty_close": [SPOT] * n, "nifty_high": [SPOT] * n, "nifty_low": [SPOT] * n,
        "nifty_open": [SPOT] * n, "vix": [VIX] * n, "nifty_return_5d": returns_5d,
    }, index=dates)
    return WeeklyBacktestEngine(df, WeeklyBacktestConfig(apply_costs=False))


def test_open_ic_is_repriced_as_ic_when_5d_return_is_large(monkeypatch):
    engine = _engine([0.0, 0.0, 0.03])  # Wed: entry-time rule would pick PCS
    # Force the entry-time pick to be the IC so the trade is an Iron Condor.
    monkeypatch.setattr(engine.ic, "should_enter", lambda *a, **k: TradeAction.ENTER)
    monkeypatch.setattr(engine.pcs, "should_enter", lambda *a, **k: TradeAction.HOLD)

    captured = {}
    orig_create = engine.ic.create_trade

    def _spy_create(*a, **k):
        t = orig_create(*a, **k)
        captured["trade"] = t
        return t

    monkeypatch.setattr(engine.ic, "create_trade", _spy_create)
    engine.run()

    trade = captured["trade"]
    assert trade.strategy_name == "weekly_ic"
    call_legs = [l for l in trade.legs if l.option_type == "CE"]
    put_legs = [l for l in trade.legs if l.option_type == "PE"]
    assert call_legs and put_legs

    expiry, _ = get_weekly_expiry_in_range(date(2026, 6, 1), 3, 8)
    dte = (expiry - date(2026, 6, 3)).days
    for leg in call_legs:
        iv = iv_from_vix(VIX, leg.strike, SPOT, OptionType.CALL)
        expected = price_option(SPOT, leg.strike, dte, iv, RF, OptionType.CALL).premium
        assert abs(leg.current_premium - expected) < 1e-6, leg
    for leg in put_legs:
        iv = iv_from_vix(VIX, leg.strike, SPOT, OptionType.PUT)
        expected = price_option(SPOT, leg.strike, dte, iv, RF, OptionType.PUT).premium
        assert abs(leg.current_premium - expected) < 1e-6, leg


def test_strategy_for_trade_maps_by_entry_name():
    engine = _engine([0.0])
    ic_trade = engine.ic.create_trade(date(2026, 6, 1), SPOT, VIX, 5, RF)
    pcs_trade = engine.pcs.create_trade(date(2026, 6, 1), SPOT, VIX, 5, RF)
    assert engine._strategy_for_trade(ic_trade) is engine.ic
    assert engine._strategy_for_trade(pcs_trade) is engine.pcs
