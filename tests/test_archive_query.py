"""Tests for data/archive_query.py. Synthetic archive in tmp_path (no network, no real archive),
except the one test that is skipped when the real archive is absent."""

from __future__ import annotations

import gzip
import os
from datetime import date

import pandas as pd
import pytest

from data import archive_query as aq
from data.nse_fo_archive import build_cache, default_archive_dir

HEADER = "date,expiry,strike,opt,open,high,low,close,settle,contracts,open_int,underlying"
STRIKES = [21800, 21900, 22000, 22100, 22200]
INDEX_SETTLE = 22000.0


def _write_day(ad, day: date, expiries, underlying, index_settle_on_expiry=True):
    """Write one daily csv.gz. Expiry-day rows carry the index settle (0 in 2019 files)."""
    lines = [HEADER]
    und = "" if underlying is None else f"{underlying:.2f}"
    spot = underlying if underlying is not None else 21950.0
    for exp in expiries:
        dte = (exp - day).days
        for k in STRIKES:
            for opt in ("CE", "PE"):
                intrinsic = max(0.0, spot - k) if opt == "CE" else max(0.0, k - spot)
                if dte == 0:
                    settle = INDEX_SETTLE if index_settle_on_expiry else 0.0
                else:
                    settle = round(intrinsic + 20.0 + 5.0 * dte, 2)
                contracts = 0 if (k == 21800 and opt == "CE") else 100
                oi = 1000 + k % 7
                lines.append(
                    f"{day:%Y-%m-%d},{exp:%Y-%m-%d},{k},{opt},{settle},{settle},{settle},{settle},"
                    f"{settle},{contracts},{oi},{und}"
                )
    path = os.path.join(ad, "daily", f"{day:%Y%m%d}.csv.gz")
    with gzip.open(path, "wt") as fh:
        fh.write("\n".join(lines) + "\n")


@pytest.fixture()
def archive(tmp_path):
    """Four synthetic days: one 2019 day (no underlying, 2019 expiry settle 0), three 2024 days."""
    ad = str(tmp_path / "nse_fo")
    os.makedirs(os.path.join(ad, "daily"))
    _write_day(ad, date(2019, 2, 11), [date(2019, 2, 14)], None, index_settle_on_expiry=False)
    _write_day(ad, date(2024, 7, 8), [date(2024, 7, 11), date(2024, 7, 18)], 22050.0)
    _write_day(ad, date(2024, 7, 9), [date(2024, 7, 11), date(2024, 7, 18)], 22010.0)
    _write_day(ad, date(2024, 7, 11), [date(2024, 7, 11), date(2024, 7, 18)], 22000.0)
    build_cache(ad)
    return ad


def _snapshot(root):
    out = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            st = os.stat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns)
    return out


def test_connect_creates_views(archive):
    con = aq.connect(archive)
    try:
        n = con.execute("SELECT count(*) FROM fo").fetchone()[0]
        assert n == 70  # 10 rows per (day, expiry) x 7 (day, expiry) pairs
        cols = {r[0] for r in con.execute("DESCRIBE fo_with_dte").fetchall()}
        assert {"dte", "moneyness_pct", "moneyness_band"} <= cols
        dte = con.execute(
            "SELECT dte FROM fo_with_dte WHERE date = DATE '2024-07-08' AND expiry = DATE '2024-07-11' LIMIT 1"
        ).fetchone()[0]
        assert dte == 3
        # underlying empty before 2024-07-08 -> moneyness NULL there
        nulls = con.execute("SELECT count(*) FROM fo_with_dte WHERE date < DATE '2024-01-01' AND moneyness_band IS NOT NULL").fetchone()[0]
        assert nulls == 0
    finally:
        con.close()


def test_row_cap_enforced(archive):
    with pytest.warns(UserWarning, match="truncated"):
        df = aq.query("SELECT * FROM fo", limit=5, archive_dir=archive)
    assert len(df) == 5
    assert df.attrs["truncated"] is True


def test_default_limit_returns_all_when_small(archive):
    df = aq.query("SELECT * FROM fo", archive_dir=archive)
    assert len(df) == 70
    assert df.attrs["truncated"] is False


def test_limit_above_5000_rejected(archive):
    with pytest.raises(ValueError, match="5000"):
        aq.query("SELECT * FROM fo", limit=5001, archive_dir=archive)
    with pytest.raises(ValueError):
        aq.query("SELECT * FROM fo", limit=0, archive_dir=archive)


def test_only_single_select_allowed(archive):
    with pytest.raises(ValueError):
        aq.query("COPY (SELECT 1) TO 'x.csv'", archive_dir=archive)
    with pytest.raises(ValueError):
        aq.query("SELECT 1; SELECT 2", archive_dir=archive)
    df = aq.query("SELECT 1 AS one;", archive_dir=archive)
    assert int(df["one"].iloc[0]) == 1


def test_read_only_archive_dir(archive):
    before = _snapshot(archive)
    aq.coverage(archive)
    for name in aq.EXAMPLES:
        aq.run_example(name, archive_dir=archive)
    aq.query("SELECT count(*) AS n FROM fo_with_dte", archive_dir=archive)
    assert _snapshot(archive) == before


@pytest.mark.parametrize("name", sorted(aq.EXAMPLES))
def test_each_example_runs_on_synthetic(archive, name):
    df = aq.run_example(name, archive_dir=archive)
    assert isinstance(df, pd.DataFrame)
    assert 0 < len(df) <= aq.MAX_LIMIT


def test_coverage_summary(archive):
    per_year, summary = aq.coverage(archive)
    assert summary["total_rows"] == 70
    assert summary["daily_files"] == 4
    assert summary["first_date"] == "2019-02-11"
    assert summary["last_date"] == "2024-07-11"
    assert list(per_year["year"]) == [2019, 2024]
    span = pd.bdate_range("2019-02-11", "2024-07-11")
    assert summary["weekdays_without_file"] == len(span) - 4


def test_stale_cache_message(archive):
    _write_day(archive, date(2024, 7, 12), [date(2024, 7, 18)], 22020.0)
    with pytest.raises(aq.ArchiveCacheError, match="stale") as exc:
        aq.connect(archive)
    assert "build_cache" in str(exc.value)


def test_missing_cache_message(archive):
    os.remove(os.path.join(archive, "_cache", "nifty_fo_all.parquet"))
    with pytest.raises(aq.ArchiveCacheError, match="missing") as exc:
        aq.connect(archive)
    assert "build_cache" in str(exc.value)


def test_cli_examples_and_query(archive, capsys):
    assert aq.main(["--examples"]) == 0
    assert "coverage_per_year" in capsys.readouterr().out
    assert aq.main(["SELECT count(*) AS n FROM fo", "--archive-dir", archive]) == 0
    assert "70" in capsys.readouterr().out
    assert aq.main(["SELECT * FROM fo", "--limit", "9999", "--archive-dir", archive]) == 2


_REAL_DIR = default_archive_dir()


@pytest.mark.skipif(not os.path.isdir(os.path.join(_REAL_DIR, "daily")), reason="real NSE F&O archive not present")
def test_real_archive_row_count():
    per_year, summary = aq.coverage()
    assert summary["total_rows"] > 2_000_000
    assert summary["first_date"] == "2019-02-11"
