from __future__ import annotations

import pandas as pd

from src.utils.config import PATHS
from src.validate.qa import build_quality_report


def main() -> None:
    input_path = PATHS.processed_root / "institutional_flows_daily.parquet"
    if not input_path.exists():
        raise FileNotFoundError(f"Missing {input_path}")

    df = pd.read_parquet(input_path)
    report = build_quality_report(df)
    lines = [
        "# Data Quality Report",
        "",
        "## Summary",
        report.summary.to_markdown(index=False) if not report.summary.empty else "No data.",
        "",
        "## Coverage By Year",
        report.coverage_by_year.to_markdown(index=False) if not report.coverage_by_year.empty else "No data.",
        "",
        "## Duplicate Rows",
        report.duplicates.to_markdown(index=False) if not report.duplicates.empty else "No duplicates detected.",
        "",
        "## Missing Dates",
        report.missing_dates.head(100).to_markdown(index=False) if not report.missing_dates.empty else "No business-day gaps detected.",
        "",
        "## Missing Months",
        report.missing_months.to_markdown(index=False) if not report.missing_months.empty else "No full-month gaps detected.",
        "",
        "## Net Mismatches",
        report.net_mismatches.to_markdown(index=False) if not report.net_mismatches.empty else "No net mismatches detected.",
        "",
        "## Suspicious Spikes",
        report.suspicious_spikes.to_markdown(index=False) if not report.suspicious_spikes.empty else "No suspicious spikes detected.",
        "",
    ]
    (PATHS.reports_root / "data_quality_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
