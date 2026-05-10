"""Frozen monthly strategy universe used by the regime selector."""

ACTIVE_MONTHLY_STRATEGIES = (
    "calendar_spread",
    "put_credit_spread",
    "put_credit_wide",
    "iron_condor",
    "broken_wing_butterfly",
)

ACTIVE_MONTHLY_STRATEGY_SET = set(ACTIVE_MONTHLY_STRATEGIES)

