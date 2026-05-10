from datetime import date

import pandas as pd

from backtester.weekly_engine import WeeklyBacktestEngine
from config import WeeklyBacktestConfig
from strategies.base import ExitReason, Leg, Trade


def _stop_loss_trade() -> Trade:
    return Trade(
        strategy_name="weekly_pcs",
        entry_date=date(2024, 6, 3),
        legs=[
            Leg("PE", 22000, True, 140.0, 155.0, 1, 50, delta=-0.35),
            Leg("PE", 21600, False, 40.0, 50.0, 1, 50, delta=-0.12),
        ],
        entry_spot=22300.0,
        entry_vix=16.0,
        lots=1,
        lot_size=50,
    )


def test_stop_loss_realism_uses_worse_of_trigger_and_next_open():
    data = pd.DataFrame(
        {
            "nifty_open": [22320.0, 21720.0],
            "nifty_close": [22240.0, 21780.0],
            "vix": [16.0, 24.0],
        },
        index=pd.to_datetime(["2024-06-03", "2024-06-04"]),
    )

    baseline_engine = WeeklyBacktestEngine(
        data,
        WeeklyBacktestConfig(
            initial_capital=500_000.0,
            max_lots=1,
            lot_size=50,
            apply_costs=False,
            stop_loss_fill_policy="mark_to_market",
            stop_loss_slippage_penalty_per_unit=0.0,
        ),
    )
    realism_engine = WeeklyBacktestEngine(
        data,
        WeeklyBacktestConfig(
            initial_capital=500_000.0,
            max_lots=1,
            lot_size=50,
            apply_costs=False,
            stop_loss_fill_policy="worst_of_trigger_and_next_open",
            stop_loss_slippage_penalty_per_unit=2.0,
        ),
    )

    trade = _stop_loss_trade()
    baseline_pnl, baseline_adjustment, baseline_worsened = baseline_engine._realize_exit_pnl(
        trade, ExitReason.STOP_LOSS, 0, 22240.0, 16.0, 3,
    )
    realism_pnl, realism_adjustment, realism_worsened = realism_engine._realize_exit_pnl(
        trade, ExitReason.STOP_LOSS, 0, 22240.0, 16.0, 3,
    )

    assert baseline_adjustment == 0.0
    assert bool(baseline_worsened) is False
    assert bool(realism_worsened) is True
    assert realism_adjustment >= 2.0 * trade.lots * trade.lot_size
    assert realism_pnl < baseline_pnl
