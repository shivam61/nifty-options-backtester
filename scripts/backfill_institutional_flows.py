from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from src.extract.adapters import CDSLAdapter, FallbackThirdPartyAdapter
from src.normalize.schema import canonicalize
from src.normalize.tradewise_reconstruction import (
    DEFAULT_PROFILES,
    build_archive_month_index,
    expand_month_window,
    iter_month_starts,
    reconstruct_for_date_range,
)
from src.utils.checkpoints import CheckpointStore
from src.utils.config import PATHS
from src.utils.io_utils import write_dataframe_outputs


def _find_profile(profile_name: str):
    for profile in DEFAULT_PROFILES:
        if profile.name == profile_name:
            return profile
    raise ValueError(f"Unknown reconstruction profile: {profile_name}")


def _cache_path_for_record(record: dict[str, object]) -> Path:
    href = str(record["href"])
    year = int(record["year"])
    return PATHS.raw_root / "cdsl" / "equity_trade_zips" / str(year) / Path(href).name


def _load_or_fetch_zip(
    adapter: CDSLAdapter,
    checkpoints: CheckpointStore,
    month_key: date,
    record: dict[str, object],
    force: bool,
) -> Path:
    item_key = month_key.isoformat()
    zip_path = _cache_path_for_record(record)
    if zip_path.exists() and not force:
        checkpoints.upsert(adapter.source_name, f"tradewise_zip:{item_key}", "success", json.dumps({"path": str(zip_path)}))
        return zip_path

    raw_item = adapter.fetch_equity_month_zip(
        year=int(record["year"]),
        month_label=str(record.get("month_label") or ""),
        zip_href=str(record["href"]),
    )
    checkpoints.upsert(
        adapter.source_name,
        f"tradewise_zip:{item_key}",
        "success",
        json.dumps({"url": raw_item["url"], "path": str(zip_path)}),
    )
    return zip_path


def _build_official_reconstructed_frame(
    reconstructed: pd.DataFrame,
    zip_paths: list[Path],
    profile_name: str,
    month_window: int,
    effective_start_date: date,
    effective_end_date: date,
) -> pd.DataFrame:
    if reconstructed.empty:
        return canonicalize(pd.DataFrame())

    frame = reconstructed.rename(columns={"buy": "buy_value", "sell": "sell_value", "net": "net_value"}).copy()
    frame["participant_type"] = "FII/FPI"
    frame["market_segment"] = "capital_market"
    frame["sector"] = pd.NA
    frame["instrument"] = "equity"
    frame["series_kind"] = "reconstructed_official_tradewise"
    frame["source_name"] = "sebi_cdsl_tradewise"
    frame["source_url"] = ";".join(str(path) for path in zip_paths)
    frame["source_type"] = "official_tradewise_zip"
    frame["extraction_method"] = "streaming_xlsx_rule_engine"
    frame["is_official"] = True
    frame["is_provisional"] = False
    frame["is_final"] = True
    frame["confidence_score"] = 0.86
    frame["currency"] = "INR crore"
    frame["notes"] = (
        f"Official FPI/FII reconstruction from monthly trade-wise ZIPs using profile={profile_name}, "
        f"month_window={month_window}, date_basis=report_date, coverage={effective_start_date.isoformat()}:{effective_end_date.isoformat()}."
    )
    return canonicalize(frame)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", type=lambda s: date.fromisoformat(s), required=True)
    parser.add_argument("--end-date", type=lambda s: date.fromisoformat(s), required=True)
    parser.add_argument("--third-party-csv", type=str, default=None)
    parser.add_argument("--profile", default="strict_cash_new_eq_plus_eu")
    parser.add_argument("--month-window", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    checkpoints = CheckpointStore()
    cdsl = CDSLAdapter(checkpoint_store=checkpoints)
    profile = _find_profile(args.profile)

    requested_months = iter_month_starts(args.start_date, args.end_date)
    expanded_months = expand_month_window(requested_months, args.month_window)

    archive_records = cdsl.discover_equity_trade_archives()
    archive_index = build_archive_month_index(archive_records)
    available_months = sorted(archive_index)
    if not available_months:
        raise RuntimeError("No CDSL trade-wise monthly archives were discovered")

    min_available_month = available_months[0]
    max_available_month = available_months[-1]
    effective_start_date = max(args.start_date, min_available_month)
    effective_end_date = min(args.end_date, (pd.Period(max_available_month, freq="M").end_time.date()))
    if effective_start_date > effective_end_date:
        raise RuntimeError(
            f"Requested range {args.start_date.isoformat()}:{args.end_date.isoformat()} falls outside available official "
            f"trade-wise coverage {min_available_month.isoformat()}:{pd.Period(max_available_month, freq='M').end_time.date().isoformat()}"
        )

    requested_months = iter_month_starts(effective_start_date, effective_end_date)
    expanded_months = [
        month
        for month in expand_month_window(requested_months, args.month_window)
        if min_available_month <= month <= max_available_month
    ]

    missing_core_months = [month.isoformat() for month in requested_months if month not in archive_index]
    if missing_core_months:
        raise RuntimeError(f"Missing required monthly archive records for: {', '.join(missing_core_months)}")

    zip_paths: list[Path] = []
    for month_key in expanded_months:
        record = archive_index[month_key]
        zip_path = _load_or_fetch_zip(cdsl, checkpoints, month_key, record, force=args.force)
        zip_paths.append(zip_path)

    reconstructed = reconstruct_for_date_range(
        zip_paths=zip_paths,
        profile=profile,
        start_date=effective_start_date,
        end_date=effective_end_date,
        max_workers=args.max_workers,
    )
    frames: list[pd.DataFrame] = [
        _build_official_reconstructed_frame(
            reconstructed,
            zip_paths,
            profile.name,
            args.month_window,
            effective_start_date,
            effective_end_date,
        )
    ]

    if args.third_party_csv:
        third_party = FallbackThirdPartyAdapter(csv_path=args.third_party_csv)
        for item in third_party.fetch():
            frames.append(third_party.parse(item))

    combined = pd.concat(frames, ignore_index=True) if frames else canonicalize(pd.DataFrame())
    if not combined.empty:
        combined = combined.sort_values(["date", "participant_type", "source_name"]).reset_index(drop=True)

    write_dataframe_outputs(
        combined,
        PATHS.processed_root / "institutional_flows_daily.parquet",
        PATHS.processed_root / "institutional_flows_daily.csv",
    )
    print(
        json.dumps(
            {
                "rows": int(len(combined)),
                "effective_start_date": effective_start_date.isoformat(),
                "effective_end_date": effective_end_date.isoformat(),
                "months_used": len(expanded_months),
                "profile": profile.name,
                "max_workers": args.max_workers,
            }
        )
    )


if __name__ == "__main__":
    main()
