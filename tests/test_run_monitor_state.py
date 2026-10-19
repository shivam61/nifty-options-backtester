"""
run_monitor must evaluate each active trade with its own exit strategy and with the
entry VIX/spot stored in the journal.

Regression for:
  - one RegimeAdaptiveStrategy shared across trades: evaluate_exit only selects a
    sub-strategy while _active_strategy is None, so the first trade's sub-strategy
    priced every later trade (an Iron Condor was exit-checked as a Put Credit Spread);
  - weekly trades exit-checked with the monthly strategy;
  - entry_vix/entry_spot taken from today's market data instead of the journal.

The data layer (market data, exit model, Fyers, NSE) is mocked; nothing hits the network.
"""
import logging
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import exits
import main
from config import BacktestConfig
from models import trade_monitor
from models.trade_monitor import ActiveTrade, TradeLeg, add_trade_from_legs, load_active_trades
from strategies.multi_strategy import RegimeAdaptiveStrategy
from strategies.weekly_strategies import WeeklyIronCondor, WeeklyPutCreditSpread

SPOT = 22000.0
VIX = 16.0


def _pcs_legs():
    return [TradeLeg("SELL", 21500, "PE", 130, 120.0), TradeLeg("BUY", 21000, "PE", 130, 60.0)]


def _ic_legs():
    return _pcs_legs() + [TradeLeg("SELL", 22500, "CE", 130, 100.0), TradeLeg("BUY", 23000, "CE", 130, 50.0)]


def _trade(tid, legs, strategy_code=None, entry_vix=None, entry_spot=None):
    return ActiveTrade(
        trade_id=tid,
        entry_date=str(date.today() - timedelta(days=2)),
        expiry_date=str(date.today() + timedelta(days=20)),
        legs=[vars(l) for l in legs],
        strategy_code=strategy_code,
        entry_vix=entry_vix,
        entry_spot=entry_spot,
    )


def _market_frame():
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=30)
    return pd.DataFrame({
        "nifty_close": [SPOT] * len(idx),
        "nifty_open": [SPOT] * len(idx),
        "nifty_mid_session": [SPOT] * len(idx),
        "vix": [VIX] * len(idx),
        "vix_vs_sma_ratio": [1.0] * len(idx),
        "crash_risk_score_v2": [0.0] * len(idx),
        "nifty_drawdown_from_20d_high_pct": [0.0] * len(idx),
    }, index=idx)


def _run(trades, config=None):
    """Run run_monitor on the given trades; return the evaluate_exit call kwargs in order."""
    config = config or BacktestConfig()
    real_evaluate = exits.evaluate_exit
    with patch.dict(sys.modules, {"fyers_apiv3": None}), \
         patch.object(main, "_check_fyers_token_and_warn", MagicMock()), \
         patch.object(main, "load_env", MagicMock()), \
         patch.object(main, "load_active_trades", MagicMock(return_value=trades)), \
         patch.object(main, "save_active_trades", MagicMock()), \
         patch.object(main, "_print_exit_recommendation", MagicMock()), \
         patch.object(main, "MarketDataFetcher") as fetcher_cls, \
         patch.object(main, "ExitStrategyEngine") as engine_cls, \
         patch("data.option_chain.NSEOptionChainFetcher") as nse_cls, \
         patch("exits.evaluate_exit", wraps=real_evaluate) as spy:
        fetcher_cls.return_value.build_combined_dataset.return_value = _market_frame()
        engine_cls.load.side_effect = FileNotFoundError
        engine_cls.return_value = MagicMock(is_trained=False)
        nse_cls.return_value.fetch.side_effect = RuntimeError("offline")
        main.run_monitor(config)
    return spy.call_args_list


def test_each_trade_gets_its_own_strategy_instance_by_type():
    pcs = _trade("monthly_pcs", _pcs_legs())
    weekly_ic = _trade("weekly_ic_1", _ic_legs(), strategy_code="weekly_ic")
    calls = _run([pcs, weekly_ic])

    assert len(calls) == 2
    s_monthly, s_weekly = calls[0].kwargs["strategy"], calls[1].kwargs["strategy"]
    assert isinstance(s_monthly, RegimeAdaptiveStrategy)
    assert isinstance(s_weekly, WeeklyIronCondor)
    assert s_monthly is not s_weekly


def test_monthly_sub_strategy_does_not_leak_into_next_trade():
    """Two monthly trades of different types: each must be routed to its own sub-strategy."""
    pcs = _trade("monthly_pcs", _pcs_legs())
    ic = _trade("monthly_ic", _ic_legs())
    calls = _run([pcs, ic])

    s_first, s_second = calls[0].kwargs["strategy"], calls[1].kwargs["strategy"]
    assert s_first._active_name == "put_credit_spread"
    assert s_second._active_name == "iron_condor"


def test_weekly_trade_is_priced_with_weekly_strategy_not_monthly():
    weekly_pcs = _trade("weekly_pcs_1", _pcs_legs(), strategy_code="weekly_pcs")
    calls = _run([weekly_pcs])
    assert isinstance(calls[0].kwargs["strategy"], WeeklyPutCreditSpread)


def test_mutating_one_trades_strategy_does_not_affect_another():
    cfg = BacktestConfig()
    t_pcs = _trade("a", _pcs_legs())
    t_ic = _trade("b", _ic_legs())

    s_a = main._monitor_strategy_for_trade(t_pcs, cfg)
    s_b = main._monitor_strategy_for_trade(t_ic, cfg)
    assert s_a is not s_b

    exits.evaluate_exit(strategy=s_a, trade_adapter=exits.TradeAdapter(t_pcs, 0.0, 0.0, entry_vix=VIX),
                        spot=SPOT, vix=VIX, dte=20, entry_spot=SPOT, entry_vix=VIX)
    assert s_a._active_name == "put_credit_spread"
    assert s_b._active_strategy is None and s_b._active_name is None

    exits.evaluate_exit(strategy=s_b, trade_adapter=exits.TradeAdapter(t_ic, 0.0, 0.0, entry_vix=VIX),
                        spot=SPOT, vix=VIX, dte=20, entry_spot=SPOT, entry_vix=VIX)
    assert s_b._active_name == "iron_condor"
    assert s_a._active_name == "put_credit_spread"


def test_entry_vix_and_spot_come_from_journal():
    t = _trade("with_entry", _pcs_legs(), entry_vix=14.0, entry_spot=21000.0)
    calls = _run([t])

    kw = calls[0].kwargs
    assert kw["entry_vix"] == 14.0
    assert kw["entry_spot"] == 21000.0
    assert kw["trade_adapter"].entry_vix == 14.0


def test_missing_entry_context_falls_back_to_current_with_warning(caplog):
    t = _trade("legacy", _pcs_legs())  # no stored entry context
    with caplog.at_level(logging.WARNING, logger=main.__name__):
        calls = _run([t])

    kw = calls[0].kwargs
    assert kw["entry_vix"] == VIX
    assert kw["entry_spot"] == SPOT
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "legacy" in messages and "entry_vix" in messages and "entry_spot" in messages


def test_entry_context_round_trips_through_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_monitor, "TRADES_FILE", tmp_path / "active_trades.json")
    add_trade_from_legs(
        trade_id="rt", entry_date="2026-10-01", expiry_date="2026-10-29",
        leg_strings=["SELL 21500 PE 130 @ 120", "BUY 21000 PE 130 @ 60"],
        entry_vix=14.5, entry_spot=21888.0,
    )
    loaded = load_active_trades()
    assert loaded[0].entry_vix == 14.5
    assert loaded[0].entry_spot == 21888.0

    # Journals written before these fields existed still load, with None
    import json
    path = trade_monitor.TRADES_FILE
    data = json.loads(path.read_text())
    for t in data["trades"]:
        t.pop("entry_vix", None)
        t.pop("entry_spot", None)
    path.write_text(json.dumps(data))
    legacy = load_active_trades()[0]
    assert legacy.entry_vix is None and legacy.entry_spot is None


@pytest.mark.parametrize("code,expected", [
    (None, RegimeAdaptiveStrategy),
    ("put_credit_spread", RegimeAdaptiveStrategy),
    ("weekly_ic", WeeklyIronCondor),
    ("weekly_pcs", WeeklyPutCreditSpread),
])
def test_strategy_selection_by_code(code, expected):
    t = _trade("x", _pcs_legs(), strategy_code=code)
    assert isinstance(main._monitor_strategy_for_trade(t, BacktestConfig()), expected)
