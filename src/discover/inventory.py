from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from src.extract.adapters import (
    CDSLAdapter,
    FYERSAdapter,
    FallbackThirdPartyAdapter,
    NSECurrentAdapter,
    NSDLAdapter,
)


def build_source_inventory() -> pd.DataFrame:
    adapters = [
        CDSLAdapter(),
        NSECurrentAdapter(),
        NSDLAdapter(),
        FYERSAdapter(),
        FallbackThirdPartyAdapter(),
    ]
    return pd.DataFrame([asdict(adapter.discover()) for adapter in adapters])
