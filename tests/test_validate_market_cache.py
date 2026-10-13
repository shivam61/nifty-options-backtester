"""
Offline tests for scripts/validate_market_cache.py.

All data is synthetic and written under pytest's tmp_path. Nothing touches
data/.cache, the network, or the data layer (--dataset is not exercised here).
"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts import validate_market_cache as v  # noqa: E402


ASOF = date(2026, 10, 9)


def _write_close(path: Path, close: np.ndarray, start="2020-01-01") -> None:
    idx = pd.bdate_range(start=start, periods=len(close))
    pd.DataFrame({"Close": close, "Open": close, "High": close, "Low": close,
                  "Volume": 0.0}, index=idx).to_parquet(path)


def _series(seed: int, base: float, n: int = 300) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return base * np.exp(rng.normal(0, 0.01, n))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_classify_india_vix_and_us_vix_overlap():
    stats = {"median": 18.0, "min": 10.0, "max": 60.0}
    cands = v.classify(stats)
    assert "india_vix" in cands
    assert "us_vix" in cands
    assert len(cands) > 1  # ambiguous by design


def test_classify_nifty_only_for_nifty_level():
    stats = {"median": 22000.0, "min": 8000.0, "max": 26000.0}
    cands = v.classify(stats)
    assert "nifty" in cands
    assert "sp500" not in cands  # Nifty-like values are excluded from S&P


def test_classify_sp500_when_history_reaches_low_levels():
    stats = {"median": 3000.0, "min": 700.0, "max": 6000.0}
    assert "sp500" in v.classify(stats)
    assert "nifty" not in v.classify(stats)


def test_classify_us10y_and_unclassifiable():
    assert v.classify({"median": 4.0, "min": 0.5, "max": 6.0}) == ["us_10y"]
    assert v.classify({"median": 0.01, "min": 0.0, "max": 0.02}) == []


def test_scan_file_reports_candidates_and_stats(tmp_path):
    p = tmp_path / "crude.parquet"
    _write_close(p, _series(1, 75.0))
    rec, close = v.scan_file(p)
    assert rec["error"] is None
    assert rec["rows"] == 300
    assert "brent" in rec["candidates"] and "wti" in rec["candidates"]
    assert close is not None and len(close) == 300
    assert rec["close_hash"]


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def test_byte_identical_close_detected(tmp_path):
    base = _series(2, 75.0)
    _write_close(tmp_path / "a.parquet", base)
    _write_close(tmp_path / "b.parquet", base.copy())
    _write_close(tmp_path / "c.parquet", _series(3, 40.0))
    recs, closes = v.scan_cache(tmp_path)
    identical, near = v.duplicate_groups(recs, closes)
    assert identical == [["a.parquet", "b.parquet"]]
    assert ["a.parquet", "b.parquet"] in near


def test_near_duplicate_above_95pct_grouped(tmp_path):
    base = _series(4, 100.0, n=200)
    tweaked = base.copy()
    tweaked[:5] *= 1.5  # 5 of 200 rows differ -> 97.5% overlap
    _write_close(tmp_path / "x.parquet", base)
    _write_close(tmp_path / "y.parquet", tweaked)
    recs, closes = v.scan_cache(tmp_path)
    identical, near = v.duplicate_groups(recs, closes)
    assert identical == []
    assert near == [["x.parquet", "y.parquet"]]


def test_below_threshold_not_grouped(tmp_path):
    base = _series(5, 100.0, n=200)
    other = base.copy()
    other[:40] *= 1.5  # 80% overlap -> not a duplicate
    _write_close(tmp_path / "x.parquet", base)
    _write_close(tmp_path / "y.parquet", other)
    recs, closes = v.scan_cache(tmp_path)
    assert v.duplicate_groups(recs, closes) == ([], [])


def test_identical_groups_fail_file_checks(tmp_path):
    base = _series(6, 75.0)
    _write_close(tmp_path / "a.parquet", base)
    _write_close(tmp_path / "b.parquet", base.copy())
    recs, closes = v.scan_cache(tmp_path)
    identical, _ = v.duplicate_groups(recs, closes)
    checks = dict((name, ok) for name, ok, _ in v.file_checks(recs, identical))
    assert checks["no byte-identical Close series"] is False
    no_dups = dict((name, ok) for name, ok, _ in v.file_checks(recs, []))
    assert no_dups["no byte-identical Close series"] is True


def test_scan_cache_errors_on_missing_or_empty_dir(tmp_path):
    with pytest.raises(RuntimeError):
        v.scan_cache(tmp_path / "nope")
    with pytest.raises(RuntimeError):
        v.scan_cache(tmp_path)


# ---------------------------------------------------------------------------
# Identity matrix and dataset checks
# ---------------------------------------------------------------------------

def _clean_raw() -> dict[str, pd.Series]:
    return v.synthetic_raw(ASOF)


def test_identity_matrix_flags_copied_column():
    raw = _clean_raw()
    raw["crude"] = raw["us_vix"].copy()
    df = pd.DataFrame(raw)
    pairs = v.identity_pairs(df, list(v.DATASET_RANGES))
    top = pairs[0]
    assert {top[0], top[1]} == {"crude", "us_vix"}
    assert top[2] == pytest.approx(1.0)
    assert v.pair_frac(df, "usdinr", "dxy") < 0.5


def test_clean_dataset_passes_all_checks():
    checks = v.evaluate_dataset(pd.DataFrame(_clean_raw()), ASOF)
    failed = [name for name, ok, _ in checks if not ok]
    assert failed == []
    assert v.exit_code(checks) == 0


def test_corrupted_dataset_fails_named_checks():
    raw = v.corrupt_raw(_clean_raw())
    checks = v.evaluate_dataset(pd.DataFrame(raw), ASOF)
    failed = {name for name, ok, _ in checks if not ok}
    assert "crude != us_vix" in failed
    assert "usdinr != dxy" in failed
    assert "no identical column pairs >50%" in failed
    assert "nifty_bank 20k-65k after 2023" in failed
    assert v.exit_code(checks) == 1


def test_stale_dataset_fails_freshness():
    df = pd.DataFrame(_clean_raw())
    checks = v.evaluate_dataset(df, date(2026, 11, 30), max_stale_days=5)
    fresh = [ok for name, ok, _ in checks if name == "last date fresh"]
    assert fresh == [False]


def test_missing_column_fails_median_check():
    raw = _clean_raw()
    del raw["europe"]
    checks = v.evaluate_dataset(pd.DataFrame(raw), ASOF)
    assert ("median in range: europe", False, "column missing") in checks


# ---------------------------------------------------------------------------
# Exit codes and CLI
# ---------------------------------------------------------------------------

def test_selftest_exits_zero():
    assert v.main(["--selftest"]) == 0


def test_usage_error_exits_two(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        v.main(["--no-such-flag"])
    assert exc.value.code == 2
    assert v.main(["--cache-dir", str(tmp_path / "missing")]) == 2


def test_bad_asof_is_argparse_usage_error():
    with pytest.raises(SystemExit) as exc:
        v.main(["--asof", "13-10-2026"])
    assert exc.value.code == 2


def test_cli_scan_writes_report_to_out(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    raw = _clean_raw()
    for k, s in raw.items():
        frame = pd.DataFrame({"Close": s.to_numpy()}, index=s.index)
        frame.to_parquet(cache / f"{k}.parquet")
    out = tmp_path / "report.txt"
    rc = v.main(["--cache-dir", str(cache), "--out", str(out), "--asof", ASOF.isoformat()])
    assert rc in (0, 1)  # file-scan checks only; coverage may be partial
    text = out.read_text(encoding="utf-8")
    assert "== FILE SCAN ==" in text
    assert "every ticker has a matching file" in text
    assert "OVERALL:" in text


def test_exit_code_helper():
    assert v.exit_code([("a", True, ""), ("b", True, "")]) == 0
    assert v.exit_code([("a", True, ""), ("b", False, "")]) == 1
