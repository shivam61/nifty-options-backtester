"""Open weekly trades must be repriced and exit-checked with the strategy they were entered with.

Regression for: _process_weekly_exit re-selected the strategy every day from TODAY's
nifty_return_5d, so an open Iron Condor was repriced as a Put Credit Spread (call legs got put
prices) on any day |5d return| >= 2%.
"""
from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine
from pricing.black_scholes import OptionType, iv_from_vix, price_option

ENTRY = date(2026, 6, 1)
SPOT = 22000.0
VIX = 16.0
RF = 0.065


def _engine() -> CombinedBacktestEngine:
    dates = pd.bdate_range("2026-05-25", periods=20)
    df = pd.DataFrame({
        "nifty_close": [SPOT] * 20, "nifty_high": [SPOT] * 20, "nifty_low": [SPOT] * 20,
        "nifty_open": [SPOT] * 20, "nifty_mid_session": [SPOT] * 20, "vix": [VIX] * 20,
    }, index=dates)
    return CombinedBacktestEngine(
        data=df,
        monthly_config=BacktestConfig(initial_capital=500_000, lot_size=65, max_lots=15),
        weekly_config=WeeklyBacktestConfig(),
        monthly_strategy=MagicMock(name="s"),
        exit_engine=None, entry_model=None, weekly_risk_engine=None,
    )


def _open_ic(engine, expiry):
    trade = engine.weekly_ic.create_trade(ENTRY, SPOT, VIX, 5, RF)
    engine.weekly_trade = trade
    engine._w_expiry = expiry
    engine._w_entry_vix = VIX
    engine._w_entry_spot = SPOT
    engine._w_exit_tracker = None
    return trade


def test_open_ic_is_repriced_as_ic_when_5d_return_is_large():
    engine = _engine()
    expiry = date(2026, 6, 6)
    trade = _open_ic(engine, expiry)
    assert trade.strategy_name == "weekly_ic"
    call_legs = [l for l in trade.legs if l.option_type == "CE"]
    put_legs = [l for l in trade.legs if l.option_type == "PE"]
    assert call_legs and put_legs

    # Today: a +3% five-day move, which the entry-time selector maps to PCS.
    md = {"nifty_return_5d": 0.03}
    today = date(2026, 6, 3)
    dte = (expiry - today).days
    engine._process_weekly_exit(pd.Series({"nifty_mid_session": SPOT}), today, SPOT, VIX, md)

    for leg in call_legs:
        iv = iv_from_vix(VIX, leg.strike, SPOT, OptionType.CALL)
        expected = price_option(SPOT, leg.strike, dte, iv, RF, OptionType.CALL).premium
        assert abs(leg.current_premium - expected) < 1e-6, leg
    for leg in put_legs:
        iv = iv_from_vix(VIX, leg.strike, SPOT, OptionType.PUT)
        expected = price_option(SPOT, leg.strike, dte, iv, RF, OptionType.PUT).premium
        assert abs(leg.current_premium - expected) < 1e-6, leg


def test_open_pcs_stays_pcs_when_5d_return_is_calm():
    engine = _engine()
    expiry = date(2026, 6, 6)
    trade = engine.weekly_pcs.create_trade(ENTRY, SPOT, VIX, 5, RF)
    engine.weekly_trade = trade
    engine._w_expiry = expiry
    engine._w_entry_vix = VIX
    engine._w_entry_spot = SPOT
    engine._w_exit_tracker = None
    today = date(2026, 6, 3)
    engine._process_weekly_exit(pd.Series({"nifty_mid_session": SPOT}), today, SPOT, VIX,
                                {"nifty_return_5d": 0.0})
    dte = (expiry - today).days
    for leg in trade.legs:
        ot = OptionType.CALL if leg.option_type == "CE" else OptionType.PUT
        iv = iv_from_vix(VIX, leg.strike, SPOT, ot)
        expected = price_option(SPOT, leg.strike, dte, iv, RF, ot).premium
        assert abs(leg.current_premium - expected) < 1e-6, leg
