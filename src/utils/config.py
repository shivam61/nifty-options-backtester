from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
RAW_ROOT = DATA_ROOT / "raw"
PROCESSED_ROOT = DATA_ROOT / "processed"
REPORTS_ROOT = PROJECT_ROOT / "reports"
LOGS_ROOT = PROJECT_ROOT / "logs"
CHECKPOINT_DB = PROJECT_ROOT / "data" / "institutional_flows_checkpoints.sqlite"


@dataclass(frozen=True)
class PipelinePaths:
    project_root: Path = PROJECT_ROOT
    data_root: Path = DATA_ROOT
    raw_root: Path = RAW_ROOT
    processed_root: Path = PROCESSED_ROOT
    reports_root: Path = REPORTS_ROOT
    logs_root: Path = LOGS_ROOT
    checkpoint_db: Path = CHECKPOINT_DB

    def ensure(self) -> "PipelinePaths":
        for path in [
            self.data_root,
            self.raw_root,
            self.processed_root,
            self.reports_root,
            self.logs_root,
            self.checkpoint_db.parent,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        return self


PATHS = PipelinePaths().ensure()
