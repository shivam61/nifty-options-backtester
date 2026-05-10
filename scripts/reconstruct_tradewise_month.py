from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.normalize.tradewise_reconstruction import DEFAULT_PROFILES, reconstruct_for_date_range
from src.utils.io_utils import write_dataframe_outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip-path", required=True)
    parser.add_argument("--profile", default="strict_cash_new_eq_plus_eu")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    profile = next(profile for profile in DEFAULT_PROFILES if profile.name == args.profile)
    zip_path = Path(args.zip_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = reconstruct_for_date_range(
        zip_paths=[zip_path],
        profile=profile,
        start_date=args.start_date,
        end_date=args.end_date,
        max_workers=1,
    )
    if not df.empty:
        df = df.sort_values("date").reset_index(drop=True)
    stem = zip_path.stem.replace(" ", "_")
    write_dataframe_outputs(
        df,
        output_dir / f"{stem}.parquet",
        output_dir / f"{stem}.csv",
    )
    print(f"{stem}:{len(df)}")


if __name__ == "__main__":
    main()
