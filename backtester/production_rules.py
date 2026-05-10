"""
Production safety rules for weekly/monthly options trading.

Philosophy: "Collect small premiums daily, but insure against rare disasters."

Hard rules enforced:
  1. NO NAKED SELLING — every short leg must have a matching long hedge
  2. HEDGE RATIO — spread width cannot exceed max_spread_width_pct of spot
  3. EVENT CALENDAR — no new entries within N days of known macro events
  4. PORTFOLIO DD KILL SWITCH — hard halt at 10-12% drawdown, force-closes weeklies
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from data.expiry_calendar import get_monthly_expiry


# ═══════════════════════════════════════════════════════════════════════════════
#  1. No-Naked-Selling Validator
# ═══════════════════════════════════════════════════════════════════════════════

class NakedPositionError(ValueError):
    """Raised when a trade contains an unhedged short leg."""
    pass


def validate_no_naked(legs, raise_on_fail: bool = True) -> tuple[bool, str]:
    """
    Verify every short leg has a matching long leg of the same option type.
    A spread must have: short PE + long PE, or short CE + long CE.
    """
    short_legs = [l for l in legs if l.is_short]
    long_legs = [l for l in legs if not l.is_short]

    if not short_legs:
        return True, "No short legs — no risk"

    if not long_legs:
        msg = f"NAKED: {len(short_legs)} short leg(s) with NO hedge"
        if raise_on_fail:
            raise NakedPositionError(msg)
        return False, msg

    for sl in short_legs:
        matching_longs = [l for l in long_legs if l.option_type == sl.option_type]
        if not matching_longs:
            msg = (f"NAKED: Short {sl.option_type} @ {sl.strike} has no "
                   f"matching long {sl.option_type}")
            if raise_on_fail:
                raise NakedPositionError(msg)
            return False, msg

    return True, "All short legs hedged"


def validate_hedge_ratio(
    legs, spot: float, max_spread_width_pct: float = 3.0,
    raise_on_fail: bool = False,
) -> tuple[bool, str]:
    """
    Check that no spread width exceeds max_spread_width_pct of spot.
    E.g., at spot=23000, max 3% = 690 points max spread width.
    Prevents absurdly wide hedges that are structurally naked-adjacent.
    """
    max_width_abs = spot * max_spread_width_pct / 100.0
    short_legs = [l for l in legs if l.is_short]
    long_legs = [l for l in legs if not l.is_short]

    for sl in short_legs:
        matching = [l for l in long_legs if l.option_type == sl.option_type]
        if not matching:
            continue
        closest = min(matching, key=lambda l: abs(l.strike - sl.strike))
        width = abs(sl.strike - closest.strike)
        if width > max_width_abs:
            msg = (f"WIDE HEDGE: {sl.option_type} spread width {width:.0f} > "
                   f"{max_width_abs:.0f} ({max_spread_width_pct}% of spot {spot:.0f})")
            if raise_on_fail:
                raise NakedPositionError(msg)
            return False, msg

    return True, "Hedge ratio OK"


# ═══════════════════════════════════════════════════════════════════════════════
#  2. India Market Event Calendar
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MarketEvent:
    date: date
    name: str
    severity: str       # "high", "critical"
    block_days_before: int = 1
    block_days_after: int = 0


def _rbi_policy_dates(year: int) -> list[date]:
    """
    RBI MPC meets ~6 times/year. Dates for 2024-2027 are known; for other
    years we approximate: Feb, Apr, Jun, Aug, Oct, Dec — first week.
    """
    known = {
        2024: [date(2024, 2, 8), date(2024, 4, 5), date(2024, 6, 7),
               date(2024, 8, 8), date(2024, 10, 9), date(2024, 12, 6)],
        2025: [date(2025, 2, 7), date(2025, 4, 9), date(2025, 6, 6),
               date(2025, 8, 8), date(2025, 10, 8), date(2025, 12, 5)],
        2026: [date(2026, 2, 6), date(2026, 4, 8), date(2026, 6, 5),
               date(2026, 8, 7), date(2026, 10, 7), date(2026, 12, 4)],
    }
    if year in known:
        return known[year]
    return [date(year, m, 7) for m in (2, 4, 6, 8, 10, 12)]


def _budget_dates(year: int) -> list[date]:
    """Union Budget — typically Feb 1 (Jul 1 for interim years)."""
    return [date(year, 2, 1)]


def _us_fed_dates(year: int) -> list[date]:
    """
    US Fed FOMC — 8 meetings/year. Approximate: late Jan, mid Mar, early May,
    mid Jun, late Jul, mid Sep, early Nov, mid Dec.
    IST impact is next-day gap for Indian markets.
    """
    approx = [
        (1, 29), (3, 19), (5, 7), (6, 18),
        (7, 30), (9, 17), (11, 5), (12, 17),
    ]
    dates = []
    for m, d in approx:
        try:
            dates.append(date(year, m, min(d, 28)))
        except ValueError:
            pass
    return dates


def _monthly_expiry_dates(year: int) -> list[date]:
    """Era-aware monthly expiry dates for the full year."""
    expiries = []
    for month in range(1, 13):
        expiries.append(get_monthly_expiry(year, month, ref_date=date(year, month, 15)))
    return expiries


def _election_dates() -> list[date]:
    """Major Indian elections (general, state) — manually maintained."""
    return [
        date(2024, 4, 19), date(2024, 5, 20), date(2024, 6, 4),  # 2024 general
    ]


def build_event_calendar(start_year: int, end_year: int) -> list[MarketEvent]:
    """
    Build a comprehensive India market event calendar.

    Each event carries a severity and a blocking window (days before/after)
    during which NO new weekly entries should be opened.
    """
    events: list[MarketEvent] = []

    for year in range(start_year, end_year + 1):
        for d in _rbi_policy_dates(year):
            events.append(MarketEvent(d, f"RBI MPC {d:%b %Y}", "high",
                                      block_days_before=1, block_days_after=0))

        for d in _budget_dates(year):
            events.append(MarketEvent(d, f"Union Budget {year}", "critical",
                                      block_days_before=2, block_days_after=1))

        for d in _us_fed_dates(year):
            events.append(MarketEvent(d, f"US FOMC {d:%b %Y}", "high",
                                      block_days_before=1, block_days_after=1))

        for d in _monthly_expiry_dates(year):
            events.append(MarketEvent(d, f"Monthly Expiry {d:%b %Y}", "high",
                                      block_days_before=1, block_days_after=0))

    for d in _election_dates():
        events.append(MarketEvent(d, f"Election {d:%Y}", "critical",
                                  block_days_before=3, block_days_after=1))

    events.sort(key=lambda e: e.date)
    return events


class EventCalendar:
    """
    Checks if a given date falls within the blocking window of any market event.
    Pre-computed for fast O(1) lookup during backtesting.
    """

    def __init__(self, start_year: int = 2009, end_year: int = 2027):
        self.events = build_event_calendar(start_year, end_year)
        self._blocked_dates: dict[date, MarketEvent] = {}
        for event in self.events:
            for offset in range(-event.block_days_before, event.block_days_after + 1):
                blocked = event.date + timedelta(days=offset)
                existing = self._blocked_dates.get(blocked)
                if existing is None or event.severity == "critical":
                    self._blocked_dates[blocked] = event

    def is_blocked(self, check_date: date) -> tuple[bool, Optional[MarketEvent]]:
        """Returns (blocked, event) if the date falls in any event window."""
        event = self._blocked_dates.get(check_date)
        if event is not None:
            return True, event
        return False, None

    def next_event(self, from_date: date) -> Optional[MarketEvent]:
        """Next upcoming event on or after from_date."""
        for e in self.events:
            if e.date >= from_date:
                return e
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Portfolio Drawdown Kill Switch
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KillSwitchState:
    """Tracks the DD kill switch state across the backtest."""
    is_active: bool = False
    activated_date: Optional[date] = None
    activated_dd_pct: float = 0.0
    cooldown_until: Optional[date] = None
    total_activations: int = 0
    weekly_force_closes: int = 0
    entries_blocked: int = 0


class DrawdownKillSwitch:
    """
    Hard circuit breaker that activates at max_dd_pct drawdown.

    When triggered:
      1. Force-close ALL weekly positions immediately (eat the loss at market)
      2. Block ALL new entries (monthly + weekly) for cooldown_days
      3. Re-enable only when DD recovers below recovery_dd_pct

    This is your insurance policy. Stop losses fail during gaps.
    This switch doesn't — it acts on portfolio equity, not position P&L.
    """

    def __init__(
        self,
        max_dd_pct: float = 0.10,       # 10% drawdown → kill
        recovery_dd_pct: float = 0.05,  # recovery below 5% → re-enable
        cooldown_days: int = 5,         # minimum cooldown even if DD recovers
    ):
        self.max_dd_pct = max_dd_pct
        self.recovery_dd_pct = recovery_dd_pct
        self.cooldown_days = cooldown_days
        self.state = KillSwitchState()

    def check(self, current_date: date, dd_pct: float) -> bool:
        """
        Check if the kill switch should be active.
        Returns True if all trading should halt.
        """
        if self.state.is_active:
            if self.state.cooldown_until and current_date < self.state.cooldown_until:
                self.state.entries_blocked += 1
                return True

            if dd_pct > self.recovery_dd_pct:
                self.state.entries_blocked += 1
                return True

            self.state.is_active = False
            self.state.activated_date = None
            self.state.cooldown_until = None
            return False

        if dd_pct >= self.max_dd_pct:
            self.state.is_active = True
            self.state.activated_date = current_date
            self.state.activated_dd_pct = dd_pct
            self.state.cooldown_until = current_date + timedelta(days=self.cooldown_days)
            self.state.total_activations += 1
            return True

        return False

    def should_force_close_weekly(self) -> bool:
        """True on the activation tick — close weekly positions immediately."""
        return (self.state.is_active and
                self.state.activated_date is not None and
                self.state.total_activations > 0 and
                self.state.cooldown_until is not None and
                self.state.cooldown_until == self.state.activated_date + timedelta(days=self.cooldown_days))


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Combined Production Gate (single entry point for all checks)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProductionRulesConfig:
    """All production safety parameters in one place."""
    max_spread_width_pct: float = 3.0
    dd_kill_pct: float = 0.10
    dd_recovery_pct: float = 0.05
    dd_cooldown_days: int = 5
    block_events: bool = True
    enforce_no_naked: bool = True
    enforce_hedge_ratio: bool = True


class ProductionGate:
    """
    Single entry point for all production safety checks.

    Usage in combined_engine:
        gate = ProductionGate(config)
        # In the daily loop:
        if gate.kill_switch.check(current_date, dd_pct):
            # force close weeklies, block all entries
        if gate.should_block_weekly_entry(current_date, legs, spot):
            # skip this entry
    """

    def __init__(self, config: ProductionRulesConfig = ProductionRulesConfig()):
        self.config = config
        self.kill_switch = DrawdownKillSwitch(
            max_dd_pct=config.dd_kill_pct,
            recovery_dd_pct=config.dd_recovery_pct,
            cooldown_days=config.dd_cooldown_days,
        )
        self.event_calendar = EventCalendar()
        self.event_blocks = 0
        self.naked_blocks = 0
        self.hedge_ratio_blocks = 0

    def should_block_weekly_entry(
        self, current_date: date, legs=None, spot: float = 0.0,
    ) -> tuple[bool, str]:
        """
        Run all pre-entry checks. Returns (blocked, reason).
        Called BEFORE the trade is created.
        """
        # Event calendar
        if self.config.block_events:
            blocked, event = self.event_calendar.is_blocked(current_date)
            if blocked:
                self.event_blocks += 1
                return True, f"event:{event.name}"

        if legs is not None:
            # No-naked-selling
            if self.config.enforce_no_naked:
                valid, msg = validate_no_naked(legs, raise_on_fail=False)
                if not valid:
                    self.naked_blocks += 1
                    return True, f"naked:{msg}"

            # Hedge ratio
            if self.config.enforce_hedge_ratio and spot > 0:
                valid, msg = validate_hedge_ratio(
                    legs, spot, self.config.max_spread_width_pct, raise_on_fail=False,
                )
                if not valid:
                    self.hedge_ratio_blocks += 1
                    return True, f"hedge_ratio:{msg}"

        return False, ""

    def should_block_monthly_entry(
        self, current_date: date, legs=None, spot: float = 0.0,
    ) -> tuple[bool, str]:
        """Monthly track: only event calendar + naked check (no DD kill for monthly)."""
        if self.config.block_events:
            blocked, event = self.event_calendar.is_blocked(current_date)
            if blocked and event and event.severity == "critical":
                self.event_blocks += 1
                return True, f"event:{event.name}"

        if legs is not None and self.config.enforce_no_naked:
            valid, msg = validate_no_naked(legs, raise_on_fail=False)
            if not valid:
                self.naked_blocks += 1
                return True, f"naked:{msg}"

        return False, ""

    def print_stats(self) -> None:
        ks = self.kill_switch.state
        print(f"\n  {'='*60}")
        print(f"  PRODUCTION SAFETY STATS")
        print(f"  {'='*60}")
        print(f"  DD Kill Switch activations:  {ks.total_activations}")
        print(f"  Weekly force-closes (kill):   {ks.weekly_force_closes}")
        print(f"  Entries blocked (kill):        {ks.entries_blocked}")
        print(f"  Event calendar blocks:         {self.event_blocks}")
        print(f"  Naked position blocks:         {self.naked_blocks}")
        print(f"  Hedge ratio blocks:            {self.hedge_ratio_blocks}")
