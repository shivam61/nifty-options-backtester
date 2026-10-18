"""
Single loader for the project's dotenv files.

Precedence (keeps the historical ``.env`` override behaviour):
  1. ``.env`` is loaded with override=True (its values win over the process env,
     as the code always did).
  2. ``.env.local`` is loaded with override=False: it only fills variables that
     are still missing after step 1.

Missing files are skipped silently. Secret values are never printed here.
"""

from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env(base_dir: Optional[Path] = None) -> None:
    """Load ``<base_dir>/.env`` then ``<base_dir>/.env.local`` (default: project root)."""
    base = Path(base_dir) if base_dir is not None else PROJECT_ROOT
    env_file = base / ".env"
    local_file = base / ".env.local"
    if env_file.is_file():
        load_dotenv(env_file, override=True)
    if local_file.is_file():
        load_dotenv(local_file, override=False)
