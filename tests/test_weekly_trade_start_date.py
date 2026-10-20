"""
Weekly trade-start gate (WeeklyBacktestConfig.weekly_trade_start_date).

The weekly track must not signal or trade before the start date, while the engine still
sees the full history it is given. With the gate set, the equity curve, DD peaks and
reported metrics start at the first tradable day. With it unset (default None) the engine
behaves exactly as before.
"""
from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine
from strategies.base import TradeAction

START = date(2024, 6, 3)          # Monday
CAPITAL = 500_000.0


def _frame(start="2024-05-01", end="2024-07-31"):
    dates = pd.bdate_range(start, end)
    n = len(dates)
    return pd.DataFrame({
        "nifty_close": [22000.0] * n, "nifty_high": [22100.0] * n,
        "nifty_low": [21900.0] * n, "nifty_open": [22000.0] * n,
        "nifty_mid_session": [22000.0] * n, "vix": [16.0] * n,
    }, index=dates)


def _engine(weekly_start=None, data=None) -> CombinedBacktestEngine:
    eng = CombinedBacktestEngine(
        data=_frame() if data is None else data,
        monthly_config=BacktestConfig(initial_capital=CAPITAL, lot_size=65, max_lots=15),
        weekly_config=WeeklyBacktestConfig(weekly_trade_start_date=weekly_start),
        monthly_strategy=MagicMock(name="monthly"),
        exit_engine=None,
        entry_model=None,
        weekly_risk_engine=None,
    )
    eng.prod_gate.should_block_weekly_entry = MagicMock(return_value=(False, ""))
    eng._effective_allocation = MagicMock(return_value=(0.5, 0.5))
    eng._compute_weekly_dynamic_scale = MagicMock(return_value=1.0)
    eng._estimate_weekly_delta = MagicMock(return_value=0.2)
    strategy = MagicMock(name="weekly_strategy")
    strategy.should_enter.return_value = TradeAction.ENTER
    strategy.create_trade.return_value = MagicMock(net_credit=10.0, legs=[])
    eng._select_weekly_strategy = MagicMock(return_value=strategy)
    return eng


def _signal(eng, d: date) -> None:
    row = pd.Series({"nifty_close": 22000.0, "nifty_mid_session": 22000.0, "vix": 16.0})
    eng._process_weekly_entry(row, d, 22000.0, 16.0, {}, CAPITAL, 0, 0.0)


def _pending_view(eng):
    p = eng._pending_weekly_entry
    if p is None:
        return None
    return {k: v for k, v in p.items() if k != "strategy"}


def _fake_trade(entry: date, exit_: date, pnl: float) -> dict:
    return {
        "track": "weekly", "strategy": "PCS", "signal_date": entry,
        "entry_date": entry, "exit_date": exit_, "holding_days": (exit_ - entry).days,
        "total_pnl": pnl, "exit_reason": "test",
    }


# ── Config ────────────────────────────────────────────────────────────────────

def test_default_is_none_and_gate_off():
    assert WeeklyBacktestConfig().weekly_trade_start_date is None
    eng = _engine()
    assert eng._weekly_trade_start is None


def test_string_date_is_parsed():
    assert WeeklyBacktestConfig(weekly_trade_start_date="2019-02-11").weekly_trade_start_date == date(2019, 2, 11)
    assert _engine(weekly_start="2024-06-03")._weekly_trade_start == START


# ── Signals ───────────────────────────────────────────────────────────────────

def test_no_weekly_signal_before_start():
    eng = _engine(weekly_start=START)
    _signal(eng, date(2024, 5, 27))   # Monday before start
    assert eng._pending_weekly_entry is None
    _signal(eng, date(2024, 5, 28))   # Tuesday before start
    assert eng._pending_weekly_entry is None


def test_entries_on_or_after_start_match_ungated_engine():
    gated = _engine(weekly_start=START)
    ungated = _engine(weekly_start=None)
    days = [d.date() for d in pd.bdate_range("2024-06-03", "2024-07-30") if d.weekday() in (0, 1)]
    assert days, "need signal days"
    produced = 0
    for d in days:
        _signal(gated, d)
        _signal(ungated, d)
        assert _pending_view(gated) == _pending_view(ungated), d
        produced += _pending_view(ungated) is not None
    assert produced > 0, "ungated engine should produce post-start entries for the comparison"


def test_gate_does_not_touch_pre_start_state_when_unset():
    """Default None: a pre-2024 Monday still produces a pending weekly entry."""
    eng = _engine(weekly_start=None)
    _signal(eng, date(2024, 5, 27))
    assert _pending_view(eng) is not None


# ── Metrics window ────────────────────────────────────────────────────────────

def _seed_curve(eng, pre_days: int, post_days: int, pre_pnl: float):
    """Fake a finished run: pre-start equity drifts to capital + pre_pnl, post-start flat."""
    pre = [d.date() for d in pd.bdate_range(end="2024-05-31", periods=pre_days)]
    post = [d.date() for d in pd.bdate_range(START, periods=post_days)]
    dates = pre + post
    curve = [CAPITAL + pre_pnl] * pre_days + [CAPITAL + pre_pnl] * post_days
    eng.equity_curve = list(curve)
    eng.daily_pnl = [0.0] * len(curve)
    eng._curve_dates = dates
    return dates


def test_metrics_window_default_is_full_history():
    eng = _engine(weekly_start=None)
    _seed_curve(eng, 5, 5, 0.0)
    eng.weekly_completed = [_fake_trade(date(2024, 5, 2), date(2024, 5, 6), 1000.0)]
    result = eng._build_result()
    assert len(result.equity_curve) == 10
    assert len(result.daily_pnl) == 10
    assert result.weekly_trades == 1


def test_metrics_start_at_window_date_and_rebase_to_capital():
    eng = _engine(weekly_start=START)
    dates = _seed_curve(eng, 5, 5, 0.0)
    # Pre-start equity sits 2,000 above capital; the window must open at capital anyway.
    eng.equity_curve = [CAPITAL + 2000.0 + 300.0 * i for i in range(len(dates))]
    k = next(i for i, d in enumerate(dates) if d >= START)
    eq = eng.equity_curve
    eng.weekly_completed = [_fake_trade(START, date(2024, 6, 5), 100.0)]
    result = eng._build_result()
    assert len(result.equity_curve) == len(dates) - k
    assert result.equity_curve[0] == CAPITAL + (eq[k] - eq[k - 1])   # first window day = +300
    assert result.equity_curve[-1] - result.equity_curve[0] == eq[-1] - eq[k]


def test_trades_counted_only_when_they_exit_in_window():
    eng = _engine(weekly_start=START)
    _seed_curve(eng, 5, 5, 0.0)
    eng.weekly_completed = [
        _fake_trade(date(2024, 5, 20), date(2024, 5, 31), 9000.0),   # exits before start: excluded
        _fake_trade(date(2024, 6, 3), date(2024, 6, 5), 1500.0),     # inside window
    ]
    result = eng._build_result()
    assert result.weekly_trades == 1
    assert result.weekly_pnl == 1500
    assert result.total_pnl == 1500


def test_window_cagr_uses_window_length():
    eng = _engine(weekly_start=START)
    dates = _seed_curve(eng, 40, 60, 0.0)
    eng.equity_curve = [CAPITAL] * len(dates)
    eng.weekly_completed = [_fake_trade(START, date(2024, 6, 10), 50_000.0)]
    result = eng._build_result()
    n_window = len(dates) - next(i for i, d in enumerate(dates) if d >= START)
    years = n_window / 252
    expected = ((CAPITAL + 50_000.0) / CAPITAL) ** (1 / years) - 1
    assert abs(result.cagr_pct - round(expected * 100, 2)) < 0.02


# ── run() level ───────────────────────────────────────────────────────────────

def _run_with_pre_start_monthly_pnl(weekly_start):
    """Full run() over May-July 2024 with monthly P&L booked only before START and no entries."""
    eng = _engine(weekly_start=weekly_start)
    pre_schedule = {
        date(2024, 5, 1): 5000.0, date(2024, 5, 2): 5000.0, date(2024, 5, 3): 5000.0,
        date(2024, 5, 6): -3000.0,   # pre-start drawdown; equity ends at capital + 2,000
    }

    def fake_monthly_exit(row, current_date, spot, vix, market_data):
        if current_date < START and current_date in pre_schedule:
            eng._monthly_realized += pre_schedule[current_date]
        return 0.0

    eng._process_monthly_exit = fake_monthly_exit
    eng._process_monthly_entry = MagicMock(return_value=None)
    eng._process_weekly_entry = MagicMock(return_value=None)
    return eng, eng.run()


def test_run_default_curve_covers_full_history():
    eng, result = _run_with_pre_start_monthly_pnl(None)
    assert len(result.equity_curve) == len(_frame())


def test_run_window_resets_peak_and_curve_starts_at_capital():
    eng, result = _run_with_pre_start_monthly_pnl(START)
    # Pre-start realized P&L nets to +12,000 (5k+5k+5k-3k). Without the reset the peak would
    # stay at the 15,000 high-water mark; the window re-bases it to the equity at start.
    assert eng._peak_equity == CAPITAL + 12000.0
    assert eng._window_started
    assert result.equity_curve[0] == CAPITAL
    assert all(abs(v - CAPITAL) < 1e-6 for v in result.equity_curve)   # no window P&L
    assert result.max_drawdown_pct == 0.0
    assert len(result.equity_curve) == len(_frame()) - len(
        [d for d in _frame().index if d.date() < START])
