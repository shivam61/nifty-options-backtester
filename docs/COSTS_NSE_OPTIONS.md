# NSE index-option costs and expiry settlement (chain backtest)

Code: `backtester/nse_option_rates.py` (rate table, with source URLs), `backtester/chain_engine.py`
(`_order_fees`, `_exercise_stt`, `_close`). Switches: `ChainConfig.cash_settlement` (default True),
`ChainConfig.legacy_costs` (default False); CLI `--legacy-settlement --legacy-costs`.

## Settlement

- A leg still open on its expiry day is cash-settled at intrinsic value vs the archive index
  settlement price (`px` on expiry-day rows, not floored at the 0.05 tick: an OTM leg settles at 0).
- No exit order: no exit slippage, no exit brokerage, exchange, SEBI, stamp or GST on the exit.
- STT on exercise: 0.125% of intrinsic value on bought (long) legs that finish in the money. Zerodha
  charges page: "STT on exercise ... 0.15% of the intrinsic value on options that are bought and
  exercised" (applies to bought options only; that page's 0.15% is a post-2024 value, see below).
  Short legs assigned at expiry are not charged STT on exercise per that page.
- Brokerage on expiry: the brief specifies none. Zerodha's charges page says "Brokerage is also
  charged on expired, exercised, and assigned options contracts" (Rs20 flat). This is NOT modelled
  here: at Rs20 per leg it is a known gap (up to Rs40-80 per trade). Flagged, not decided.
- Early exits (before expiry): normal exit slippage and an exit order with fees.

## Rate table (`backtester/nse_option_rates.py`)

| Charge | Base | Rate | Effective | Source |
|---|---|---|---|---|
| STT on sale of options | sell premium | 0.05% | to 2023-03-31 | Zerodha bulletin 347967 (1 Apr 2023 revision) https://zerodha.com/marketintel/bulletin/347967/revision-in-transaction-charges-and-stt-from-1st-april-2023 |
| | | 0.0625% | 2023-04-01 .. 2024-09-30 | same bulletin; Geojit https://support.geojit.com/support/solutions/articles/89000007948-what-are-the-applicable-securities-transaction-tax-stt-rates- |
| | | 0.1% | from 2024-10-01 | Zerodha bulletin 391488 https://zerodha.com/marketintel/bulletin/391488/revision-in-transactions-charges-from-1st-october-2024 |
| STT on exercise | intrinsic, bought legs | 0.125% | all dev-window dates | Geojit table (0.125% before and after 1 Oct 2024). Pre-2023 history not separately verified. |
| NSE exchange txn charge, options | premium, both sides | 0.053% | to 2023-03-31 | Zerodha bulletin 347967 ("before" column) |
| | | 0.05% | 2023-04-01 .. 2024-03-31 | Zerodha bulletin 347967 |
| | | 0.0495% | 2024-04-01 .. 2024-09-30 | Zerodha bulletin 373933 https://zerodha.com/marketintel/bulletin/373933/revision-in-nse-transaction-charges-from-april-1-2024 |
| | | 0.03503% | from 2024-10-01 | Zerodha bulletin 391488; HDFC Securities notice https://www.hdfcsec.com/blog/details/revised-exchange-transaction-charges-w-e-f-1st-october-2024 |
| SEBI turnover fee | turnover | 0.0001% (Rs10/crore) | all dates | https://zerodha.com/charges/ |
| Stamp duty | buy-side turnover | 0.003% (Rs300/crore) | from 2020-07-01 | Zerodha bulletin 259741 https://zerodha.com/marketintel/bulletin/259741/uniform-stamp-duty-applicable-from-july-1-2020 |
| Brokerage | per executed order | Rs20 flat | all dates | https://zerodha.com/charges/ |
| GST | (brokerage + exchange + SEBI) | 18% | all dates | https://zerodha.com/charges/ (not on STT or stamp) |

Verification status and gaps:
- Pre-2020-07-01 stamp duty was state-specific; the uniform 0.003% is applied as a proxy (tiny effect).
- Exchange rate for 2019-2022 is 0.053% per the Zerodha "before 1 Apr 2023" column; no separate
  2019-2022 source retrieved.
- Values after 2024-10-01 are not used for any dev-window result. The Zerodha charges page as read
  now shows STT sell 0.15%, exchange 0.03553% and exercise 0.15%, which differ from the table; those
  2025-2026 changes were not verified and are not in the table.
- The brief's assumption "STT sell 0.0625% until 2024-09-30" is wrong before 2023-04-01: it was 0.05%.
- Brief's "exchange 0.053% until 2024-09-30" is wrong: it fell to 0.05% (2023-04-01) and 0.0495%
  (2024-04-01) before the 0.03503% cut on 2024-10-01.

## Fee formula (new model, per trade)

Entry (fill date F): sold = short legs x fill x qty, bought = long legs x fill x qty, turnover = sold + bought.
- STT = sold x STT_sell(F); exchange = turnover x exch(F); SEBI = turnover x 0.0001%;
  stamp = bought x 0.003%; brokerage = Rs20 x legs; GST = 18% x (brokerage + exchange + SEBI).
Early exit (date X): same formula on the exit orders (short legs bought back, long legs sold), with
brokerage per leg. Settlement at expiry: STT on exercise only.

Legacy (`legacy_costs=True`): CostModel round trip on net credit: notional = |credit| x qty;
STT, exchange, SEBI, stamp on notional; brokerage 2 orders per leg; GST on brokerage only.
