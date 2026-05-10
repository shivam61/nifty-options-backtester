from __future__ import annotations

import pandas as pd

from src.extract.adapters import CDSLAdapter, NSECurrentAdapter, NSDLAdapter
from src.utils.config import PATHS
from src.utils.io_utils import write_dataframe_outputs


def main() -> None:
    frames = []
    for adapter in [NSECurrentAdapter(), NSDLAdapter(), CDSLAdapter()]:
        for item in adapter.fetch():
            parser = getattr(adapter, "parse")
            frames.append(parser(item))
    combined = pd.concat(frames, ignore_index=True).sort_values(["date", "participant_type", "source_name"])
    write_dataframe_outputs(
        combined,
        PATHS.processed_root / "institutional_flows_daily.parquet",
        PATHS.processed_root / "institutional_flows_daily.csv",
    )


if __name__ == "__main__":
    main()
