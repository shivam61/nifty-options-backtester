from __future__ import annotations

import argparse
from pathlib import Path

from src.normalize.tradewise_reconstruction import DEFAULT_PROFILES, reconstruct_for_date_range
from src.utils.config import PATHS
from src.utils.io_utils import write_dataframe_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", action="append", dest="zip_paths", required=True)
    parser.add_argument("--profile", default="strict_cash_new_eq_plus_eu")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    args = parser.parse_args()

    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == args.profile)
    df = reconstruct_for_date_range(
        [Path(path) for path in args.zip_paths],
        profile,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    if not df.empty:
        df["participant_type"] = "FII/FPI"
        df["market_segment"] = "capital_market"
        df["sector"] = None
        df["instrument"] = "equity"
        df["series_kind"] = "reconstructed_official_tradewise"
        df["source_name"] = "sebi_cdsl_tradewise"
        df["source_url"] = ";".join(args.zip_paths)
        df["source_type"] = "official_tradewise_zip"
        df["extraction_method"] = "streaming_xlsx_rule_engine"
        df["is_official"] = True
        df["is_provisional"] = False
        df["is_final"] = True
        df["confidence_score"] = 0.86
        df["currency"] = "INR crore"
        df["notes"] = (
            f"Reconstructed from official trade-wise ZIPs using profile={profile.name}, "
            f"date_basis={profile.date_basis}, instrument_scope={profile.include_instrument_prefixes}"
        )
    write_dataframe_outputs(
        df,
        PATHS.processed_root / "institutional_flows_tradewise_reconstructed.parquet",
        PATHS.processed_root / "institutional_flows_tradewise_reconstructed.csv",
    )
    print(len(df))


if __name__ == "__main__":
    main()
