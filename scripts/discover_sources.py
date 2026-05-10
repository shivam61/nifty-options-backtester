from __future__ import annotations

from pathlib import Path

from src.discover.inventory import build_source_inventory
from src.utils.config import PATHS


def main() -> None:
    inventory = build_source_inventory()
    PATHS.reports_root.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(PATHS.reports_root / "source_inventory.csv", index=False)

    lines = [
        "# Source Inventory",
        "",
        "Recommended acquisition order:",
        "1. CDSL daily/archive for final FPI/FII daily cash flows.",
        "2. NSE current APIs for current-day DII and provisional combined FII/FPI.",
        "3. NSDL latest page as a same-day validator for final FPI/FII.",
        "4. CDSL fortnightly sector-wise pages for direct sector data and a derived daily proxy.",
        "5. FYERS and third-party adapters remain optional and non-primary.",
        "",
    ]
    for record in inventory.to_dict(orient="records"):
        lines.extend(
            [
                f"## {record['source_name']}",
                "",
                f"- Trust tier: {record['trust_tier']}",
                f"- History coverage: {record['history_coverage']}",
                f"- Granularity: {record['granularity']}",
                f"- Participant coverage: {', '.join(record['participant_coverage'])}",
                f"- Sector data: {record['sector_data']}",
                f"- Implementation difficulty: {record['implementation_difficulty']}",
                f"- Fragility risk: {record['fragility_risk']}",
                f"- URLs: {', '.join(record['urls']) if record['urls'] else 'n/a'}",
                "- Limitations:",
            ]
        )
        lines.extend([f"  - {item}" for item in record["limitations"]])
        lines.append("")

    (PATHS.reports_root / "source_inventory.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
