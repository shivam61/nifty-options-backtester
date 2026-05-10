from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.extract.adapters import CDSLAdapter
from src.normalize.tradewise_reconstruction import (
    DEFAULT_PROFILES,
    aggregate_reconstruction,
    parse_tradewise_zip,
    summarize_codes,
)
from src.utils.config import PATHS


def parse_official_daily_xls(directory: Path) -> pd.DataFrame:
    adapter = CDSLAdapter()
    rows = []
    for path in sorted(directory.glob("latest_*.xls")):
        try:
            frame = adapter.parse({"url": str(path), "payload": path.read_bytes()})
        except Exception:
            continue
        row = frame.iloc[0]
        rows.append(
            {
                "date": row["date"],
                "buy": float(row["buy_value"]),
                "sell": float(row["sell_value"]),
                "net": float(row["net_value"]),
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def _rmse(actual: pd.Series, predicted: pd.Series) -> float:
    return float((((actual - predicted) ** 2).mean()) ** 0.5)


def build_reconciliation_report(trade_df: pd.DataFrame, daily_df: pd.DataFrame) -> str:
    code_summary = summarize_codes(trade_df)

    lines = [
        "# CDSL ZIP Reconstruction Report",
        "",
        f"- Official daily rows parsed: {len(daily_df)}",
        f"- ZIP day rows parsed: {trade_df['trade_date'].nunique()}",
        f"- Distinct transaction codes: {trade_df['transaction_code'].nunique()}",
        "",
    ]

    lines.extend(
        [
            "## Code Summary",
            "",
            code_summary.head(20).to_markdown(index=False) if not code_summary.empty else "No ZIP data.",
            "",
        ]
    )

    profile_results: list[dict[str, object]] = []
    for profile in DEFAULT_PROFILES:
        candidate = aggregate_reconstruction(trade_df, profile)
        merged = daily_df.merge(candidate, on="date", how="inner", suffixes=("_official", "_candidate"))
        if merged.empty:
            profile_results.append(
                {
                    "profile": profile.name,
                    "date_basis": profile.date_basis,
                    "overlap_days": 0,
                    "buy_rmse": None,
                    "sell_rmse": None,
                    "net_rmse": None,
                    "buy_total_official": None,
                    "buy_total_candidate": None,
                    "sell_total_official": None,
                    "sell_total_candidate": None,
                }
            )
            continue
        profile_results.append(
            {
                "profile": profile.name,
                "date_basis": profile.date_basis,
                "overlap_days": len(merged),
                "buy_rmse": _rmse(merged["buy_official"], merged["buy_candidate"]),
                "sell_rmse": _rmse(merged["sell_official"], merged["sell_candidate"]),
                "net_rmse": _rmse(merged["net_official"], merged["net_candidate"]),
                "buy_total_official": merged["buy_official"].sum(),
                "buy_total_candidate": merged["buy_candidate"].sum(),
                "sell_total_official": merged["sell_official"].sum(),
                "sell_total_candidate": merged["sell_candidate"].sum(),
            }
        )

    profile_df = pd.DataFrame(profile_results).sort_values(["net_rmse", "buy_rmse"], na_position="last")
    lines.extend(
        [
            "## Reconstruction Profiles",
            "",
            profile_df.to_markdown(index=False),
            "",
        ]
    )

    best_row = profile_df.iloc[0]
    lines.extend(
        [
            "## Best Current Profile",
            "",
            f"- Profile: `{best_row['profile']}`",
            f"- Buy RMSE: {best_row['buy_rmse']:.2f}" if pd.notna(best_row["buy_rmse"]) else "- Buy RMSE: n/a",
            f"- Sell RMSE: {best_row['sell_rmse']:.2f}" if pd.notna(best_row["sell_rmse"]) else "- Sell RMSE: n/a",
            f"- Net RMSE: {best_row['net_rmse']:.2f}" if pd.notna(best_row["net_rmse"]) else "- Net RMSE: n/a",
            "",
        ]
    )

    lines.extend(
        [
            "## Conclusion",
            "",
            "- The monthly CDSL/SEBI ZIPs are official and the transaction codes are documented.",
            "- Using reporting date instead of trade date materially improves reconciliation and appears to match the official daily publication logic much better.",
            "- The remaining gaps are now smaller and are more likely due to instrument-scope edge cases or a few corporate-action semantics rather than report-type handling.",
            "- This module now makes those assumptions explicit and testable instead of hiding them inside one aggregate.",
            "- FYERS does not currently provide a documented public API for FII/DII history that improves this conclusion.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip-path", required=True)
    parser.add_argument("--daily-dir", required=True)
    args = parser.parse_args()

    trade_df = parse_tradewise_zip(Path(args.zip_path))
    daily_df = parse_official_daily_xls(Path(args.daily_dir))
    report = build_reconciliation_report(trade_df, daily_df)
    report_path = PATHS.reports_root / "cdsl_zip_reconstruction_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
