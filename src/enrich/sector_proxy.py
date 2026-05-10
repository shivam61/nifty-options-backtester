from __future__ import annotations

import pandas as pd


def build_daily_sector_proxy(fortnightly_sector_df: pd.DataFrame) -> pd.DataFrame:
    frame = fortnightly_sector_df.copy()
    if frame.empty:
        return frame

    frame["date"] = pd.to_datetime(frame["date"])
    proxy_rows = []
    for _, row in frame.iterrows():
        anchor_date = row["date"].date()
        start_date = anchor_date.replace(day=1) if anchor_date.day <= 15 else anchor_date.replace(day=16)
        business_days = pd.date_range(start_date, anchor_date, freq="B")
        if len(business_days) == 0:
            continue
        daily_net = float(row["net_value"]) / len(business_days) if pd.notna(row["net_value"]) else None
        for business_day in business_days:
            proxy_rows.append(
                {
                    **row.to_dict(),
                    "date": business_day.date(),
                    "net_value": daily_net,
                    "buy_value": pd.NA,
                    "sell_value": pd.NA,
                    "series_kind": "daily_sector_proxy_from_fortnightly",
                    "notes": (
                        "Proxy built by evenly distributing official fortnightly sector net investment "
                        "across business days within the reported half-month window."
                    ),
                    "confidence_score": 0.55,
                }
            )
    return pd.DataFrame(proxy_rows)
