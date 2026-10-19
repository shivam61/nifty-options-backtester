"""
Phase 2.2 — releasable drawdown locks (opt-in via rearm days).

Both DD locks are absorbing when the account is flat: with no open trades
MTM == realized, so the DD that tripped a lock cannot improve. With
rearm_days=0 (default) that behaviour is preserved and pinned here. With
rearm_days=N > 0 a lock is released after N consecutive flat trading days
and the peak it is measured against is re-based to the current equity.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from config import BacktestConfig, WeeklyBacktestConfig
from backtester.combined_engine import CombinedBacktestEngine
from backtester.production_rules import ProductionRulesConfig, DrawdownKillSwitch

CAPITAL = 500_000.0


def _make_engine(cross_days=0, kill_days=0, kill_cooldown_days=5):
    dates = pd.bdate_range("2026-01-01", periods=5)
    df = pd.DataFrame({
        "nifty_close": [22000.0] * 5, "nifty_high": [22100.0] * 5,
        "nifty_low": [21900.0] * 5, "nifty_open": [22000.0] * 5,
        "vix": [16.0] * 5,
    }, index=dates)
    cfg = BacktestConfig(initial_capital=CAPITAL, lot_size=65, max_lots=15)
    rules = ProductionRulesConfig(
        dd_kill_pct=0.20,
        dd_recovery_pct=0.16,
        dd_cooldown_days=kill_cooldown_days,
        cross_dd_rearm_days=cross_days,
        kill_switch_rearm_days=kill_days,
    )
    return CombinedBacktestEngine(
        data=df,
        monthly_config=cfg,
        weekly_config=WeeklyBacktestConfig(),
        monthly_strategy=MagicMock(name="s"),
        exit_engine=None,
        entry_model=None,
        weekly_risk_engine=None,
        cross_track_dd_pct=0.15,
        production_rules=rules,
    )


def _step(engine, d, eq_realized, eq_mtm=None):
    """One day of the same ordering as CombinedBacktestEngine.run()."""
    eq_mtm = eq_realized if eq_mtm is None else eq_mtm
    if eq_mtm > engine._peak_equity:
        engine._peak_equity = eq_mtm
    if eq_realized > engine._peak_equity_realized:
        engine._peak_equity_realized = eq_realized
    engine._apply_dd_lock_rearm(d, eq_realized, eq_mtm)
    peak = engine._peak_equity
    peak_r = engine._peak_equity_realized
    dd = max(0.0, (peak - eq_mtm) / peak) if peak > 0 else 0.0
    dd_r = max(0.0, (peak_r - eq_realized) / peak_r) if peak_r > 0 else 0.0
    killed = engine.prod_gate.kill_switch.check(d, dd)
    if killed:
        block = "kill"
    elif engine.weekly_trade is not None:
        block = "open_trade"
    else:
        block = engine._weekly_entry_blocked(eq_mtm, dd_r, 16.0)
    return {"killed": killed, "block": block, "dd": dd, "dd_r": dd_r}


def _days(start, n):
    return [d.date() if hasattr(d, "date") else d
            for d in pd.bdate_range(start, periods=n)]


# ───────────────────────────── defaults ─────────────────────────────

class TestDefaultsPreserved:

    def test_config_defaults_are_zero(self):
        cfg = ProductionRulesConfig()
        assert cfg.cross_dd_rearm_days == 0
        assert cfg.kill_switch_rearm_days == 0

    def test_cross_track_flat_blocked_account_stays_blocked(self):
        engine = _make_engine(cross_days=0)
        days = _days("2026-03-02", 40)
        peak = CAPITAL
        eq = 0.82 * peak  # 18% realized DD, flat
        results = [_step(engine, d, eq) for d in days]
        assert all(r["block"] == "dd" for r in results)
        assert engine.dd_lock_releases == 0
        assert engine._peak_equity_realized == CAPITAL  # never re-based

    def test_kill_switch_flat_active_stays_active(self):
        engine = _make_engine(kill_days=0)
        days = _days("2026-03-02", 40)
        eq = 0.79 * CAPITAL  # 21% MTM DD -> kill switch trips on day 0
        results = [_step(engine, d, eq) for d in days]
        assert results[0]["killed"] is True
        assert all(r["killed"] for r in results)
        assert engine.prod_gate.kill_switch.state.is_active
        assert engine.dd_lock_releases == 0
        assert engine._peak_equity == CAPITAL


# ───────────────────────────── cross-track gate ─────────────────────────────

class TestCrossTrackRearm:

    def test_releases_after_exactly_n_flat_days_and_rebases_peak(self):
        engine = _make_engine(cross_days=5)
        days = _days("2026-03-02", 8)
        eq = 0.82 * CAPITAL  # 410,000
        results = [_step(engine, d, eq) for d in days]
        # Days 1-4 blocked, day 5 released (exactly N flat trading days).
        assert [r["block"] for r in results[:4]] == ["dd"] * 4
        assert results[4]["block"] is None
        assert engine.dd_lock_releases == 1
        # Peak re-based to current equity: DD reads 0, no immediate re-trigger.
        assert engine._peak_equity_realized == pytest.approx(eq)
        assert results[4]["dd_r"] == pytest.approx(0.0)
        assert results[5]["block"] is None
        assert results[7]["block"] is None

    def test_new_losing_streak_retriggers_gate(self):
        engine = _make_engine(cross_days=5)
        # Isolate the soft gate: the kill switch floor is tested separately below.
        engine.prod_gate.kill_switch.max_dd_pct = 1.0
        days = _days("2026-03-02", 20)
        eq = 0.82 * CAPITAL
        for d in days[:6]:  # lock + release on day 5
            _step(engine, d, eq)
        assert engine.dd_lock_releases == 1
        # New losing streak: 18% below the re-based peak (410k) -> 336,200.
        r = _step(engine, days[6], 0.82 * eq)
        assert r["block"] == "dd"
        assert r["dd_r"] == pytest.approx(0.18)
        # Re-trigger day counts as flat day 1: N=5 means release on days[10].
        r2 = [_step(engine, d, 0.82 * eq) for d in days[7:10]]
        assert all(x["block"] == "dd" for x in r2)
        assert engine.dd_lock_releases == 1
        r3 = _step(engine, days[10], 0.82 * eq)
        assert r3["block"] is None
        assert engine.dd_lock_releases == 2

    def test_open_trade_resets_flat_counter_and_blocks_release(self):
        engine = _make_engine(cross_days=3)
        days = _days("2026-03-02", 12)
        eq = 0.82 * CAPITAL
        _step(engine, days[0], eq)
        _step(engine, days[1], eq)  # 2 flat days so far
        # A trade is open for several days: counter resets, no release, no re-base.
        engine.monthly_trade = MagicMock(total_pnl=-1000.0)
        for d in days[2:6]:
            _step(engine, d, eq, eq_mtm=eq - 1000.0)
        assert engine.dd_lock_releases == 0
        assert engine._peak_equity_realized == CAPITAL
        engine.monthly_trade = None
        # Needs a full N flat days again after the trade closes.
        assert _step(engine, days[6], eq)["block"] == "dd"
        assert _step(engine, days[7], eq)["block"] == "dd"
        assert _step(engine, days[8], eq)["block"] is None
        assert engine.dd_lock_releases == 1

    def test_no_release_without_lock(self):
        engine = _make_engine(cross_days=2)
        days = _days("2026-03-02", 6)
        # 5% DD: below the 15% cross threshold, no lock -> nothing to release.
        for d in days:
            _step(engine, d, 0.95 * CAPITAL)
        assert engine.dd_lock_releases == 0


# ───────────────────────────── kill switch ─────────────────────────────

class TestKillSwitchRearm:

    def test_releases_after_n_flat_days_with_cooldown_and_rebases(self):
        # Calendar-day cooldown of 2 days; release needs 3 flat trading days.
        engine = _make_engine(kill_days=3, kill_cooldown_days=2)
        days = _days("2026-03-02", 8)  # Mon..
        eq = 0.79 * CAPITAL  # 395,000 flat, 21% DD
        results = [_step(engine, d, eq) for d in days]
        assert results[0]["killed"] is True            # activation tick
        assert results[1]["killed"] is True            # flat day 1
        assert results[2]["killed"] is True            # flat day 2
        # Flat day 3 (Thu): N reached and cooldown (Wed) elapsed -> released.
        assert results[3]["killed"] is False
        assert results[3]["block"] is None
        assert engine.dd_lock_releases == 1
        assert engine._peak_equity == pytest.approx(eq)
        assert engine._peak_equity_realized == pytest.approx(eq)
        assert engine.prod_gate.kill_switch.state.is_active is False
        # No immediate re-trigger at the re-based peak.
        assert results[4]["killed"] is False
        assert results[4]["dd"] == pytest.approx(0.0)
        assert engine.prod_gate.kill_switch.state.total_activations == 1

    def test_cooldown_delays_release_past_n_flat_days(self):
        engine = _make_engine(kill_days=1, kill_cooldown_days=5)
        days = _days("2026-03-02", 9)
        eq = 0.79 * CAPITAL
        results = [_step(engine, d, eq) for d in days]
        # Activation Mon, cooldown until Mon+5 calendar days = Sat -> first
        # trading day on/after it is Mon of the next week.
        released = [i for i, r in enumerate(results) if not r["killed"]]
        assert released and days[released[0]] >= days[0] + timedelta(days=5)

    def test_new_losing_streak_reactivates_kill_switch(self):
        engine = _make_engine(kill_days=2, kill_cooldown_days=0)
        days = _days("2026-03-02", 10)
        eq = 0.79 * CAPITAL  # 395,000
        for d in days[:3]:
            _step(engine, d, eq)
        assert engine.dd_lock_releases == 1
        assert not engine.prod_gate.kill_switch.state.is_active
        # 21% below the re-based peak (395k) -> 312,050: kill switch fires again.
        r = _step(engine, days[3], 0.79 * eq)
        assert r["killed"] is True
        assert engine.prod_gate.kill_switch.state.total_activations == 2

    def test_release_for_rearm_is_noop_when_inactive(self):
        ks = DrawdownKillSwitch(max_dd_pct=0.20, cooldown_days=0)
        assert ks.release_for_rearm() is False

    def test_kill_release_also_clears_cross_tracker(self):
        engine = _make_engine(cross_days=0, kill_days=2, kill_cooldown_days=0)
        days = _days("2026-03-02", 6)
        eq = 0.79 * CAPITAL
        _step(engine, days[0], eq)  # kill fires
        engine._cross_dd_worst_while_blocked = 0.18  # tracker left over from before the kill
        _step(engine, days[1], eq)
        _step(engine, days[2], eq)  # released
        assert engine._cross_dd_worst_while_blocked == 0.0
        assert engine._peak_equity_realized == pytest.approx(eq)


class TestCrossReleaseKeepsKillFloor:

    def test_cross_release_does_not_move_kill_switch_floor(self):
        """Soft-gate release re-bases only the realized peak. The kill switch
        keeps measuring from the original MTM peak, so its 20% floor (400k)
        is not forgiven: a loss to 395k after the cross release still trips it."""
        engine = _make_engine(cross_days=5)
        days = _days("2026-03-02", 8)
        eq = 0.82 * CAPITAL  # 410k
        for d in days[:6]:
            _step(engine, d, eq)
        assert engine.dd_lock_releases == 1
        assert engine._peak_equity == CAPITAL  # MTM peak untouched
        r = _step(engine, days[6], 0.79 * CAPITAL)  # 395k, 21% from 500k
        assert r["killed"] is True
        assert engine.prod_gate.kill_switch.state.total_activations == 1
