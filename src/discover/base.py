from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from src.utils.http import HttpClient
from src.utils.logging_utils import get_logger


@dataclass
class SourceMetadata:
    source_name: str
    trust_tier: str
    history_coverage: str
    granularity: str
    fields_available: list[str]
    participant_coverage: list[str]
    sector_data: str
    implementation_difficulty: str
    fragility_risk: str
    limitations: list[str]
    urls: list[str]


class SourceAdapter(ABC):
    source_name = "base"

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self.http = http_client or HttpClient()
        self.logger = get_logger(self.source_name)

    @abstractmethod
    def discover(self) -> SourceMetadata:
        raise NotImplementedError

    def fetch(self, start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def parse(self, raw_item: dict[str, Any]) -> pd.DataFrame:
        raise NotImplementedError

    def normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame

    def validate(self, frame: pd.DataFrame) -> list[str]:
        return []
