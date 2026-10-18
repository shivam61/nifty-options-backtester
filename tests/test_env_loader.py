"""
Tests for utils/env_loader.load_env.

Uses tmp_path files with FAKE values only. Never reads the real .env or
.env.local. Every variable touched is set through monkeypatch so the process
environment is restored after each test.
"""

from utils.env_loader import load_env

KEYS = [
    "TEST_ENV_ONLY_IN_DOTENV",
    "TEST_ENV_ONLY_IN_LOCAL",
    "TEST_ENV_IN_BOTH_FILES",
    "TEST_ENV_PROCESS_VS_DOTENV",
    "TEST_ENV_PROCESS_VS_LOCAL",
]


def _reset(monkeypatch):
    # setenv then delenv records the original (absent) state so monkeypatch
    # removes anything load_dotenv writes during the test.
    for key in KEYS:
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)


def test_dotenv_and_local_both_loaded(tmp_path, monkeypatch):
    _reset(monkeypatch)
    (tmp_path / ".env").write_text("TEST_ENV_ONLY_IN_DOTENV=fake-dotenv-value\n")
    (tmp_path / ".env.local").write_text("TEST_ENV_ONLY_IN_LOCAL=fake-local-value\n")

    load_env(tmp_path)

    import os
    assert os.environ["TEST_ENV_ONLY_IN_DOTENV"] == "fake-dotenv-value"
    assert os.environ["TEST_ENV_ONLY_IN_LOCAL"] == "fake-local-value"


def test_dotenv_wins_over_local_when_both_define_key(tmp_path, monkeypatch):
    _reset(monkeypatch)
    (tmp_path / ".env").write_text("TEST_ENV_IN_BOTH_FILES=from-dotenv\n")
    (tmp_path / ".env.local").write_text("TEST_ENV_IN_BOTH_FILES=from-local\n")

    load_env(tmp_path)

    import os
    assert os.environ["TEST_ENV_IN_BOTH_FILES"] == "from-dotenv"


def test_dotenv_overrides_process_env_as_before(tmp_path, monkeypatch):
    """Historical .env behaviour: override=True, so the file beats the process env."""
    _reset(monkeypatch)
    monkeypatch.setenv("TEST_ENV_PROCESS_VS_DOTENV", "from-process")
    (tmp_path / ".env").write_text("TEST_ENV_PROCESS_VS_DOTENV=from-dotenv\n")

    load_env(tmp_path)

    import os
    assert os.environ["TEST_ENV_PROCESS_VS_DOTENV"] == "from-dotenv"


def test_local_only_fills_missing_not_process_env(tmp_path, monkeypatch):
    """.env.local uses override=False: it fills gaps, it does not replace the process env."""
    _reset(monkeypatch)
    monkeypatch.setenv("TEST_ENV_PROCESS_VS_LOCAL", "from-process")
    (tmp_path / ".env.local").write_text("TEST_ENV_PROCESS_VS_LOCAL=from-local\n")

    load_env(tmp_path)

    import os
    assert os.environ["TEST_ENV_PROCESS_VS_LOCAL"] == "from-process"


def test_missing_files_are_tolerated(tmp_path, monkeypatch):
    _reset(monkeypatch)
    # Empty directory: neither file exists.
    load_env(tmp_path)
    load_env(tmp_path / "does-not-exist")

    import os
    assert "TEST_ENV_ONLY_IN_DOTENV" not in os.environ


def test_only_local_present_is_loaded(tmp_path, monkeypatch):
    _reset(monkeypatch)
    (tmp_path / ".env.local").write_text("TEST_ENV_ONLY_IN_LOCAL=fake-local-only\n")

    load_env(tmp_path)

    import os
    assert os.environ["TEST_ENV_ONLY_IN_LOCAL"] == "fake-local-only"
