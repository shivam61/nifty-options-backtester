"""
Loader for the local NSE F&O daily archive (NIFTY index options, end-of-day).

Archive layout (read-only, licence-restricted, treated as untrusted input):
    <archive>/daily/YYYYMMDD.csv.gz
    columns: date,expiry,strike,opt,open,high,low,close,settle,contracts,open_int,underlying

The concatenated table is cached as parquet INSIDE the archive directory (never in the repo):
    <archive>/_cache/nifty_fo_all.parquet
    <archive>/_cache/nifty_fo_all.manifest.json   (file count + total bytes; rebuild on change)

Archive directory: env NSE_FO_ARCHIVE_DIR, default ~/nse_fo_archive.

Parsing the daily files is done by this module. Run anything that parses the archive with
`python3 -I` so that no cwd or user-site module can shadow a stdlib/pandas import.

API
    arch = NseFoArchive()
    arch.trading_days()                      -> sorted list of dates that have a daily file
    arch.weekly_expiries(day)                -> listed expiries with 0 <= (expiry - day).days <= 14
    arch.chain(day, expiry)                  -> DataFrame of all rows for that day and expiry
    arch.price(day, expiry, strike, opt, field='settle') -> float (NaN if not listed)
    arch.row(day, expiry, strike, opt)       -> dict(settle, close, contracts, open_int) or None
    arch.underlying(day)                     -> float (NaN if no file)
"""

from __future__ import annotations

import glob
import gzip
import json
import os
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

WEEKLY_HORIZON_DAYS = 14
REQUIRED_COLUMNS = [
    "date", "expiry", "strike", "opt", "open", "high", "low", "close",
    "settle", "contracts", "open_int", "underlying",
]
NUMERIC_COLUMNS = ["strike", "open", "high", "low", "close", "settle", "contracts", "open_int", "underlying"]


def default_archive_dir() -> str:
    return os.path.expanduser(os.environ.get("NSE_FO_ARCHIVE_DIR", "~/nse_fo_archive"))


def _daily_files(archive_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(archive_dir, "daily", "*.csv.gz")))


def _read_daily(path: str) -> pd.DataFrame:
    with gzip.open(path, "rt") as fh:
        df = pd.read_csv(fh, dtype={"date": str, "expiry": str, "opt": str})
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{os.path.basename(path)} missing columns {missing}")
    return df[REQUIRED_COLUMNS]


def build_cache(archive_dir: Optional[str] = None, force: bool = False) -> str:
    """Concatenate all daily files into one parquet cached in the archive dir. Returns its path."""
    archive_dir = archive_dir or default_archive_dir()
    cache_dir = os.path.join(archive_dir, "_cache")
    pq_path = os.path.join(cache_dir, "nifty_fo_all.parquet")
    man_path = os.path.join(cache_dir, "nifty_fo_all.manifest.json")
    files = _daily_files(archive_dir)
    if not files:
        raise FileNotFoundError(f"no daily files under {archive_dir}/daily")
    total = sum(os.path.getsize(f) for f in files)
    manifest = {"n_files": len(files), "total_bytes": total}
    if not force and os.path.exists(pq_path) and os.path.exists(man_path):
        with open(man_path) as fh:
            if json.load(fh) == manifest:
                return pq_path

    frames = []
    bad = []
    for f in files:
        try:
            frames.append(_read_daily(f))
        except Exception as exc:  # untrusted input: record, skip, keep going
            bad.append((os.path.basename(f), type(exc).__name__))
    if bad:
        raise ValueError(f"unreadable daily files (refusing to build partial cache): {bad[:5]}")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
    df["expiry"] = pd.to_datetime(df["expiry"], format="%Y-%m-%d")
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["opt"] = df["opt"].astype(str).str.upper().str.strip()
    df = df[df["opt"].isin(["CE", "PE"])].reset_index(drop=True)
    df = df.drop_duplicates(subset=["date", "expiry", "strike", "opt"], keep="first")
    os.makedirs(cache_dir, exist_ok=True)
    df.to_parquet(pq_path, index=False)
    with open(man_path, "w") as fh:
        json.dump(manifest, fh)
    return pq_path


class NseFoArchive:
    """In-memory index over the cached archive. Read-only."""

    def __init__(self, archive_dir: Optional[str] = None, index_fallback: Optional[dict] = None,
                 max_date: Optional[date] = None):
        """index_fallback: {expiry_day: index settlement value} used on expiry days where the
        archive carries no positive index settle (2019 files). Supplied by the caller from the
        repo's Nifty close."""
        self.archive_dir = archive_dir or default_archive_dir()
        index_fallback = index_fallback or {}
        pq = build_cache(self.archive_dir)
        df = pd.read_parquet(pq)
        if max_date is not None:  # drop later rows right after load, before any indexing
            df = df[df["date"] <= pd.Timestamp(max_date)].reset_index(drop=True)
        df["d"] = df["date"].dt.date
        df["e"] = df["expiry"].dt.date
        self._days = sorted(df["d"].unique())
        self._day_set = set(self._days)
        self._groups: dict[tuple, dict] = {}
        self._underlying: dict[date, float] = {}
        for (d, e), g in df.groupby(["d", "e"], sort=False):
            strike = g["strike"].to_numpy(float)
            is_ce = (g["opt"].to_numpy() == "CE")
            settle = g["settle"].to_numpy(float)
            close = g["close"].to_numpy(float)
            if d == e:
                # Expiry day: the archive 'settle' column holds the INDEX settlement value, the
                # same number on every row (2020+; matches the Nifty close). In 2019 it is 0.
                # Option price = intrinsic vs that index value (NSE final settlement).
                pos = settle[settle > 0]
                if pos.size:
                    idx_val, src = float(pos[0]), 2
                elif d in index_fallback and np.isfinite(index_fallback[d]):
                    idx_val, src = float(index_fallback[d]), 3
                else:
                    idx_val, src = float("nan"), -1
                if src >= 0:
                    px = np.where(is_ce, np.maximum(0.0, idx_val - strike), np.maximum(0.0, strike - idx_val))
                else:
                    px = np.full(len(strike), np.nan)
                px_src = np.full(len(strike), src)
            else:
                # Ordinary day: settle is the option price; close only where settle is 0.
                px = np.where(settle > 0, settle, np.where(close > 0, close, np.nan))
                px_src = np.where(settle > 0, 0, np.where(close > 0, 1, -1))
            self._groups[(d, e)] = {
                "strike": strike,
                "is_ce": is_ce,
                "settle": settle,
                "close": close,
                "px": px,
                "px_src": px_src,
                "expiry_day": d == e,
                "contracts": g["contracts"].to_numpy(float),
                "open_int": g["open_int"].to_numpy(float),
                "frame": g.drop(columns=["d", "e"]).reset_index(drop=True),
            }
        und = df.groupby("d")["underlying"].first()
        self._underlying = {k: float(v) for k, v in und.items()}
        self._expiries_by_day: dict[date, list[date]] = {}
        for (d, e) in self._groups:
            self._expiries_by_day.setdefault(d, []).append(e)
        for d in self._expiries_by_day:
            self._expiries_by_day[d].sort()
        self.n_rows = int(len(df))

    # ---- calendar
    def trading_days(self) -> list[date]:
        return list(self._days)

    def has_day(self, day: date) -> bool:
        return day in self._day_set

    def expiry_index_value(self, day: date) -> float:
        """Index settlement value used for expiry-day intrinsic (NaN if none)."""
        grp = self._groups.get((day, day))
        if grp is None:
            return float("nan")
        pos = grp["settle"][grp["settle"] > 0]
        return float(pos[0]) if pos.size else float("nan")

    def expires_on(self, day: date) -> bool:
        """True if the archive lists a contract expiring on `day` (expiry-day file)."""
        return (day, day) in self._groups

    def next_day(self, day: date) -> Optional[date]:
        """Next archive trading day strictly after `day` (None if none)."""
        i = self._bisect_right(day)
        return self._days[i] if i < len(self._days) else None

    def _bisect_right(self, day: date) -> int:
        lo, hi = 0, len(self._days)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._days[mid] <= day:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ---- chain access
    def weekly_expiries(self, day: date) -> list[date]:
        """Listed expiries with 0 <= (expiry - day).days <= 14, ascending. Empty if day has no file."""
        out = []
        for e in self._expiries_by_day.get(day, []):
            dd = (e - day).days
            if 0 <= dd <= WEEKLY_HORIZON_DAYS:
                out.append(e)
        return out

    def chain(self, day: date, expiry: date) -> pd.DataFrame:
        grp = self._groups.get((day, expiry))
        if grp is None:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)
        return grp["frame"]

    def row(self, day: date, expiry: date, strike: float, opt: str) -> Optional[dict]:
        grp = self._groups.get((day, expiry))
        if grp is None:
            return None
        want_ce = opt.upper() in ("CE", "CALL")
        m = (np.abs(grp["strike"] - float(strike)) < 1e-6) & (grp["is_ce"] == want_ce)
        idx = np.flatnonzero(m)
        if idx.size == 0:
            return None
        i = int(idx[0])
        return {
            "strike": float(grp["strike"][i]),
            "settle": float(grp["settle"][i]),
            "close": float(grp["close"][i]),
            "px": float(grp["px"][i]),
            # 0 settle | 1 close fallback (ordinary day) | 2 expiry intrinsic vs archive index
            # settle | 3 expiry intrinsic vs fallback index | -1 no price
            "px_src": int(grp["px_src"][i]),
            "expiry_day": bool(grp["expiry_day"]),
            "contracts": int(grp["contracts"][i]),
            "open_int": int(grp["open_int"][i]),
        }

    def price(self, day: date, expiry: date, strike: float, opt: str, field: str = "settle") -> float:
        r = self.row(day, expiry, strike, opt)
        if r is None:
            return float("nan")
        return float(r[field])

    def underlying(self, day: date) -> float:
        return self._underlying.get(day, float("nan"))

    def listed_strikes(self, day: date, expiry: date, opt: str) -> np.ndarray:
        """Strikes with a usable price (settle, or close where settle is 0) for (day, expiry, opt)."""
        grp = self._groups.get((day, expiry))
        if grp is None:
            return np.array([])
        want_ce = opt.upper() in ("CE", "CALL")
        m = (grp["is_ce"] == want_ce) & (grp["px_src"] >= 0)
        return np.unique(grp["strike"][m])


def _smoke(archive_dir: Optional[str] = None) -> None:  # pragma: no cover - manual use
    a = NseFoArchive(archive_dir)
    days = a.trading_days()
    print("days", len(days), days[0], days[-1], "rows", a.n_rows)
