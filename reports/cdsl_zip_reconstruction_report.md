# CDSL ZIP Reconstruction Report

- Official daily rows parsed: 23
- ZIP day rows parsed: 25
- Distinct transaction codes: 14

## Code Summary

|   transaction_code | transaction_label                   | transaction_action   |   rows |   value_crore |
|-------------------:|:------------------------------------|:---------------------|-------:|--------------:|
|                 04 | sale_secondary_market               | sell                 | 236836 |  338538       |
|                 01 | purchase_secondary_market           | buy                  | 196471 |  262488       |
|                 07 | bonus_entitlement                   | neutral              |   2772 |       2.4164  |
|                 15 | call_money_or_forfeiture_adjustment | neutral              |   1806 |       0       |
|                 02 | purchase_primary_market             | buy                  |    810 |    3444.13    |
|                 03 | preferential_allotment              | buy                  |     34 |     870.694   |
|                 05 | rights_issue_purchase               | buy                  |     16 |      87.0444  |
|                 08 | stock_split_or_consolidation        | neutral              |     13 |      24.0775  |
|                 12 | redemption_or_extinguishment        | sell                 |     13 |      12.3665  |
|                 16 | other_corporate_action              | neutral              |     10 |       0       |
|                 14 | open_offer_or_delisting_acceptance  | sell                 |      9 |      17.1286  |
|                 13 | amalgamation_or_scheme_allotment    | buy                  |      8 |      41.9174  |
|                 10 | buyback_acceptance                  | sell                 |      5 |       6.02468 |
|                 11 | merger_demerger_scheme              | neutral              |      1 |      11.4674  |

## Reconstruction Profiles

| profile                         | date_basis   |   overlap_days |   buy_rmse |   sell_rmse |   net_rmse |   buy_total_official |   buy_total_candidate |   sell_total_official |   sell_total_candidate |
|:--------------------------------|:-------------|---------------:|-----------:|------------:|-----------:|---------------------:|----------------------:|----------------------:|-----------------------:|
| strict_cash_new_only            | report_date  |             22 |    574.823 |     233.443 |    599.543 |               251531 |                248730 |                324207 |                 322793 |
| cash_new_and_amend              | report_date  |             22 |    574.823 |     233.443 |    599.543 |               251531 |                248730 |                324207 |                 322793 |
| cash_signed_with_delete         | report_date  |             22 |    574.823 |     233.443 |    599.543 |               251531 |                248730 |                324207 |                 322793 |
| cash_plus_scheme_buy_sell       | report_date  |             22 |    574.823 |     233.443 |    599.543 |               251531 |                248730 |                324207 |                 322793 |
| strict_cash_new_only_trade_date | trade_date   |             23 |   3778.59  |    4091.79  |   2553.6   |               256811 |                264085 |                334837 |                 338350 |

## Best Current Profile

- Profile: `strict_cash_new_only`
- Buy RMSE: 574.82
- Sell RMSE: 233.44
- Net RMSE: 599.54

## Conclusion

- The monthly CDSL/SEBI ZIPs are official and the transaction codes are documented.
- Using reporting date instead of trade date materially improves reconciliation and appears to match the official daily publication logic much better.
- The remaining gaps are now smaller and are more likely due to instrument-scope edge cases or a few corporate-action semantics rather than report-type handling.
- This module now makes those assumptions explicit and testable instead of hiding them inside one aggregate.
- FYERS does not currently provide a documented public API for FII/DII history that improves this conclusion.
