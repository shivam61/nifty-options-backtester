from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from src.enrich.sector_proxy import build_daily_sector_proxy
from src.extract.adapters import CDSLAdapter
from src.utils.config import PATHS
from src.utils.io_utils import write_dataframe_outputs


def main() -> None:
    adapter = CDSLAdapter()
    adapter.http.timeout_seconds = 5.0
    adapter.http.min_interval_seconds = 0.1
    sector_frames: list[pd.DataFrame] = []
    errors: list[str] = []
    start_date = date(2016, 4, 15)
    end_date = date(2025, 3, 31)

    for url in adapter.discover_sector_page_urls():
        date_match = re.search(r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})", url.replace("%20", " "))
        if date_match:
            parsed_date = pd.to_datetime(date_match.group(1), errors="coerce")
            if pd.notna(parsed_date):
                anchor_date = parsed_date.date()
                if anchor_date < start_date or anchor_date > end_date:
                    continue
        cache_path = PATHS.raw_root / "cdsl" / "sector_pages" / (Path(url).name or "sector.html")
        try:
            raw_item = adapter.fetch_sector_page(url)
        except Exception as exc:
            if not cache_path.exists():
                errors.append(f"{url} :: {type(exc).__name__}")
                continue
            raw_item = {"url": url, "payload": cache_path.read_text(encoding="utf-8")}
        try:
            sector_frames.append(adapter.parse_sector_page(raw_item))
        except Exception as exc:
            errors.append(f"{url} :: parse::{type(exc).__name__}")

    frame = pd.concat(sector_frames, ignore_index=True) if sector_frames else pd.DataFrame()
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["date", "sector", "series_kind", "source_url"]).reset_index(drop=True)
    proxy = build_daily_sector_proxy(frame)
    if proxy.empty:
        proxy = pd.DataFrame(columns=frame.columns)
    write_dataframe_outputs(
        proxy,
        PATHS.processed_root / "institutional_flows_sector_proxy_daily.parquet",
        PATHS.processed_root / "institutional_flows_sector_proxy_daily.csv",
    )
    report_lines = [
        "# Sector Proxy Build Report",
        "",
        f"- Fortnightly pages parsed: {len(sector_frames)}",
        f"- Fortnightly rows parsed: {len(frame)}",
        f"- Daily proxy rows generated: {len(proxy)}",
        "",
        "## Errors",
        "\n".join(f"- {line}" for line in errors) if errors else "No fetch/parse errors recorded.",
    ]
    (PATHS.reports_root / "sector_proxy_build_report.md").write_text("\n".join(report_lines), encoding="utf-8")


if __name__ == "__main__":
    main()
