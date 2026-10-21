"""Date-aware NSE index-option charge schedule for the chain engine (new cost model).

Every rate is a (effective_from, percent) step: the rate in force on day d is the last entry with
effective_from <= d. Percentages are of the stated base (turnover = price x quantity).

Sources (verified by WebFetch / WebSearch on the build date unless marked):
  STT on sale of options (on premium, sell side)
    0.05%   until 2023-03-31   Zerodha marketintel bulletin 347967 (1 Apr 2023 revision, "before" column)
            https://zerodha.com/marketintel/bulletin/347967/revision-in-transaction-charges-and-stt-from-1st-april-2023
    0.0625% 2023-04-01..2024-09-30  same bulletin ("from" column); Geojit STT table
            https://support.geojit.com/support/solutions/articles/89000007948-what-are-the-applicable-securities-transaction-tax-stt-rates-
    0.1%    from 2024-10-01 (Budget 2024)  Zerodha marketintel bulletin 391488
            https://zerodha.com/marketintel/bulletin/391488/revision-in-transactions-charges-from-1st-october-2024
  STT on exercise of options (bought and exercised, on intrinsic value)
    0.125%  all dates in the dev window (Geojit table: 0.125% before and after 1 Oct 2024)
            https://support.geojit.com/support/solutions/articles/89000007948-what-are-the-applicable-securities-transaction-tax-stt-rates-
            Pre-2023 history of this rate was NOT separately verified; see docs/COSTS_NSE_OPTIONS.md.
  NSE exchange transaction charge, options (on premium, both sides)
    0.053%  until 2023-03-31   Zerodha bulletin 347967 (before column)
    0.05%   2023-04-01..2024-03-31  Zerodha bulletin 347967 (from column); Zerodha bulletin 373933
    0.0495% 2024-04-01..2024-09-30  Zerodha bulletin 373933 (revision from 1 Apr 2024)
            https://zerodha.com/marketintel/bulletin/373933/revision-in-nse-transaction-charges-from-april-1-2024
    0.03503% from 2024-10-01  Zerodha bulletin 391488; HDFC Securities 1 Oct 2024 notice
            https://www.hdfcsec.com/blog/details/revised-exchange-transaction-charges-w-e-f-1st-october-2024
    The 2019-2022 value (0.053%) is the value Zerodha lists as "before 1 Apr 2023"; no separate
    source for 2019-2022 was retrieved.
  Rates after 2024-10-01 are NOT used for any dev-window result. Newer Zerodha charge pages show
  different 2026 values (STT sell 0.15%, exchange 0.03553%); not verified, not in this table.
  SEBI turnover fee  0.0001% (Rs10 per crore), all dates. https://zerodha.com/charges/
  Stamp duty         0.003% (Rs300 per crore) on the buy side from 2020-07-01 (uniform).
            https://zerodha.com/marketintel/bulletin/259741/uniform-stamp-duty-applicable-from-july-1-2020
            Pre-2020-07-01 state-level rates were not retrieved; the 0.003% value is applied as a proxy.
  Brokerage          Rs20 flat per executed order.  https://zerodha.com/charges/
  GST                18% on (brokerage + exchange transaction charge + SEBI fee). NOT on STT or stamp.
                     https://zerodha.com/charges/
"""

from __future__ import annotations

from datetime import date

Step = tuple  # (effective_from: date, percent: float)

STT_SELL_PCT: tuple[Step, ...] = (
    (date(2019, 1, 1), 0.05),
    (date(2023, 4, 1), 0.0625),
    (date(2024, 10, 1), 0.1),
)
STT_EXERCISE_PCT: tuple[Step, ...] = (
    (date(2019, 1, 1), 0.125),
)
EXCHANGE_TXN_PCT: tuple[Step, ...] = (
    (date(2019, 1, 1), 0.053),
    (date(2023, 4, 1), 0.05),
    (date(2024, 4, 1), 0.0495),
    (date(2024, 10, 1), 0.03503),
)
SEBI_PCT: tuple[Step, ...] = ((date(2019, 1, 1), 0.0001),)
STAMP_BUY_PCT: tuple[Step, ...] = ((date(2019, 1, 1), 0.003),)
BROKERAGE_PER_ORDER = 20.0
GST_PCT = 18.0


def rate_on(table: tuple[Step, ...], d: date) -> float:
    """Percent in force on day d. Days before the first step are an error, not a silent default."""
    if d < table[0][0]:
        raise ValueError(f"no rate on {d} (table starts {table[0][0]})")
    val = None
    for eff, pct in table:
        if eff <= d:
            val = pct
    return val
