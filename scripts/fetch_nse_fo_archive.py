#!/usr/bin/env python3
"""Download NSE F&O daily bhavcopy (NIFTY index options) into the local NSE F&O archive.

Output matches what data/nse_fo_archive.py reads:
    <archive>/daily/YYYYMMDD.csv.gz
    columns: date,expiry,strike,opt,open,high,low,close,settle,contracts,open_int,underlying

Sources (NSE public archive):
    legacy  https://archives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip
    UDiFF   https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
Primary format is chosen by date (UDiFF from 2024-07-08); the other is tried on 404.
The legacy format has no underlying column, so underlying is written empty for 2019..2024-07-05 rows.

Resumable: existing non-empty daily files are skipped. Each file is written to .part,
read back and validated, then renamed atomically.
Weekends and exchange holidays (data/nse_holidays.json, segment_closed=true) are skipped
without a request. A 404 on any other weekday is logged and treated as not published (holiday).

Stdlib only. Usage examples:
    python scripts/fetch_nse_fo_archive.py --dry-run
    python scripts/fetch_nse_fo_archive.py --archive-dir <dir> --limit 5
    nohup python scripts/fetch_nse_fo_archive.py > logs/fetch_fo_nohup.out 2>&1 &
"""

from __future__ import annotations

import argparse
import csv
import gzip
import http.cookiejar
import io
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO, "logs")
HOLIDAY_FILE = os.path.join(REPO, "data", "nse_holidays.json")

DEFAULT_START = date(2019, 2, 11)
UDIFF_CUTOVER = date(2024, 7, 8)
MIN_INTERVAL_S = 1.5
RETRIES = 5
BACKOFF_S = (2, 4, 8, 16, 32)
MAX_CONSECUTIVE_FAILURES = 10
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

OUT_COLUMNS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close",
               "settle", "contracts", "open_int", "underlying"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
LEGACY_REQUIRED = ["INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH",
                   "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS", "OPEN_INT", "TIMESTAMP"]
UDIFF_REQUIRED = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "OpnPric",
                  "HghPric", "LwPric", "ClsPric", "SttlmPric", "TtlTradgVol", "OpnIntrst",
                  "UndrlygPric"]

log = logging.getLogger("fetch_fo")


class FetchError(Exception):
    pass


def legacy_url(d: date) -> str:
    mon = MONTHS[d.month - 1]
    return (f"https://archives.nseindia.com/content/historical/DERIVATIVES/"
            f"{d.year}/{mon}/fo{d.day:02d}{mon}{d.year}bhav.csv.zip")


def udiff_url(d: date) -> str:
    return f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"


def load_holidays(path: str) -> dict:
    """Segment-closed exchange holidays from data/nse_holidays.json: {date: name}."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        log.warning("holiday file not found: %s (relying on 404 detection only)", path)
        return {}
    return {date.fromisoformat(h["date"]): h.get("name", "")
            for h in data.get("holidays", []) if h.get("segment_closed")}


def _num(s: str) -> str:
    s = (s or "").strip()
    if s in ("", "-"):
        return ""
    return repr(float(s))


def _int(s: str) -> str:
    s = (s or "").strip()
    if s in ("", "-"):
        return "0"
    return str(int(float(s)))


def _legacy_date(s: str) -> date:
    """'11-FEB-2019' or '28-Feb-2019'."""
    d, m, y = s.strip().split("-")
    return date(int(y), MONTHS.index(m.strip().upper()[:3]) + 1, int(d))


def parse_bhavcopy(raw: bytes, day: date, fmt: str) -> list:
    """NIFTY CE/PE rows in archive layout. Raises ValueError on schema or date mismatch."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"zip has {len(members)} csv members, expected 1")
        text = z.read(members[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = LEGACY_REQUIRED if fmt == "legacy" else UDIFF_REQUIRED
    missing = [c for c in required if c not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"{fmt} bhavcopy missing columns {missing}")
    out = []
    for r in reader:
        if fmt == "legacy":
            if r["INSTRUMENT"].strip() != "OPTIDX" or r["SYMBOL"].strip() != "NIFTY":
                continue
            opt = r["OPTION_TYP"].strip().upper()
            if opt not in ("CE", "PE"):
                continue
            if _legacy_date(r["TIMESTAMP"]) != day:
                raise ValueError(f"TIMESTAMP {r['TIMESTAMP']} does not match requested {day}")
            expiry = _legacy_date(r["EXPIRY_DT"])
            o, h, lo, c = r["OPEN"], r["HIGH"], r["LOW"], r["CLOSE"]
            settle, contracts, oi, und = r["SETTLE_PR"], r["CONTRACTS"], r["OPEN_INT"], ""
            strike = r["STRIKE_PR"]
        else:
            if r["FinInstrmTp"].strip() != "IDO" or r["TckrSymb"].strip() != "NIFTY":
                continue
            opt = r["OptnTp"].strip().upper()
            if opt not in ("CE", "PE"):
                continue
            if date.fromisoformat(r["TradDt"].strip()) != day:
                raise ValueError(f"TradDt {r['TradDt']} does not match requested {day}")
            expiry = date.fromisoformat(r["XpryDt"].strip())
            o, h, lo, c = r["OpnPric"], r["HghPric"], r["LwPric"], r["ClsPric"]
            settle, contracts, oi, und = r["SttlmPric"], r["TtlTradgVol"], r["OpnIntrst"], r["UndrlygPric"]
            strike = r["StrkPric"]
        out.append([day.isoformat(), expiry.isoformat(), _num(strike), opt, _num(o), _num(h),
                    _num(lo), _num(c), _num(settle), _int(contracts), _int(oi), _num(und)])
    return out


def validate_rows(rows: list, day: date) -> None:
    if not rows:
        raise ValueError("no NIFTY CE/PE rows")
    opts = {r[3] for r in rows}
    if opts != {"CE", "PE"}:
        raise ValueError(f"expected both CE and PE rows, got {sorted(opts)}")
    early = [r for r in rows if date.fromisoformat(r[1]) < day]
    if early:
        raise ValueError(f"{len(early)} rows with expiry before trade date")


def write_day(path: str, rows: list) -> None:
    """Write gzip CSV to .part, read it back to validate, then rename atomically."""
    part = path + ".part"
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(OUT_COLUMNS)
    w.writerows(rows)
    try:
        with gzip.open(part, "wt", encoding="utf-8", newline="") as fh:
            fh.write(buf.getvalue())
        with gzip.open(part, "rt", encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            n = sum(1 for _ in rd)
        if header != OUT_COLUMNS or n != len(rows):
            raise ValueError(f"readback mismatch: header ok={header == OUT_COLUMNS}, rows {n}/{len(rows)}")
        os.replace(part, path)
    except Exception:
        if os.path.exists(part):
            os.remove(part)
        raise


class Fetcher:
    def __init__(self) -> None:
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._cj))
        self._last = 0.0

    def _pace(self) -> None:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _open(self, url: str, accept: str) -> bytes:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
        })
        self._pace()
        with self._opener.open(req, timeout=60) as r:
            return r.read()

    def warm_up(self) -> None:
        """Pick up NSE session cookies from the homepage. Best effort."""
        try:
            self._open("https://www.nseindia.com/", "text/html")
            log.info("session cookie warm-up ok (%d cookies)", len(self._cj))
        except Exception as exc:  # noqa: BLE001
            log.warning("session warm-up failed (%s); continuing without cookies", exc)

    def get(self, url: str):
        """Bytes, or None on 404. Retries 429/5xx and network errors with backoff."""
        reason = "unknown"
        for attempt in range(RETRIES + 1):
            try:
                return self._open(url, "*/*")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code != 429 and exc.code < 500:
                    raise FetchError(f"HTTP {exc.code} for {url}")
                reason = f"HTTP {exc.code}"
            except (urllib.error.URLError, OSError) as exc:
                reason = str(exc)
            if attempt < RETRIES:
                delay = BACKOFF_S[attempt]
                log.warning("retry %d/%d in %ds after %s: %s", attempt + 1, RETRIES, delay, reason, url)
                time.sleep(delay)
        raise FetchError(f"gave up after {RETRIES} retries ({reason}): {url}")


def fetch_day(fetcher: Fetcher, day: date):
    """(url, fmt, raw_bytes) from the first format that answers, or (None, None, None) on 404 for both."""
    primary = "udiff" if day >= UDIFF_CUTOVER else "legacy"
    other = "legacy" if primary == "udiff" else "udiff"
    for fmt in (primary, other):
        url = udiff_url(day) if fmt == "udiff" else legacy_url(day)
        raw = fetcher.get(url)
        if raw is not None:
            return url, fmt, raw
    return None, None, None


def planned_url(day: date) -> str:
    return udiff_url(day) if day >= UDIFF_CUTOVER else legacy_url(day)


def days_between(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def setup_logging(logpath: str) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(logpath, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.addHandler(fh)
    log.addHandler(sh)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Download NSE F&O daily bhavcopy (NIFTY options) archive.")
    ap.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START, help="YYYY-MM-DD")
    ap.add_argument("--end", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--archive-dir", default=None,
                    help="default: env NSE_FO_ARCHIVE_DIR, else ~/nse_fo_archive")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only, no network")
    ap.add_argument("--limit", type=int, default=None, help="stop after N days needing download")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.end < args.start:
        print("error: --end before --start", file=sys.stderr)
        return 2
    archive = os.path.expanduser(args.archive_dir or os.environ.get("NSE_FO_ARCHIVE_DIR") or "~/nse_fo_archive")
    daily = os.path.join(archive, "daily")
    os.makedirs(LOG_DIR, exist_ok=True)
    logpath = os.path.join(LOG_DIR, f"fetch_fo_{datetime.now():%Y%m%d_%H%M%S}.log")
    setup_logging(logpath)
    log.info("archive=%s start=%s end=%s dry_run=%s limit=%s",
             archive, args.start, args.end, args.dry_run, args.limit)
    log.info("log file: %s", logpath)

    holidays = load_holidays(HOLIDAY_FILE)
    if not args.dry_run:
        os.makedirs(daily, exist_ok=True)
    fetcher = None if args.dry_run else Fetcher()
    if fetcher:
        fetcher.warm_up()

    stats = Counter()
    attempted = 0
    consecutive_fail = 0
    for day in days_between(args.start, args.end):
        if day.weekday() >= 5:
            stats["weekend"] += 1
            continue
        if day in holidays:
            log.info("SKIP holiday %s (%s)", day, holidays[day])
            stats["holiday_list"] += 1
            continue
        path = os.path.join(daily, f"{day:%Y%m%d}.csv.gz")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            stats["existing"] += 1
            continue
        if args.limit is not None and attempted >= args.limit:
            break
        attempted += 1
        if args.dry_run:
            log.info("PLAN %s -> %s", day, planned_url(day))
            stats["planned"] += 1
            continue
        try:
            url, fmt, raw = fetch_day(fetcher, day)
        except FetchError as exc:
            stats["failed"] += 1
            consecutive_fail += 1
            log.error("FAIL %s: %s", day, exc)
            if consecutive_fail >= MAX_CONSECUTIVE_FAILURES:
                log.error("aborting after %d consecutive failures", consecutive_fail)
                break
            continue
        if raw is None:
            stats["not_published"] += 1
            consecutive_fail = 0
            log.warning("NOT PUBLISHED %s: 404 on both formats, weekday not in holiday list; treated as holiday", day)
            continue
        try:
            rows = parse_bhavcopy(raw, day, fmt)
            validate_rows(rows, day)
            write_day(path, rows)
        except (ValueError, KeyError, zipfile.BadZipFile, OSError, EOFError) as exc:
            stats["failed"] += 1
            consecutive_fail += 1
            log.error("INVALID %s from %s: %s: %s", day, url, type(exc).__name__, exc)
            if consecutive_fail >= MAX_CONSECUTIVE_FAILURES:
                log.error("aborting after %d consecutive failures", consecutive_fail)
                break
            continue
        consecutive_fail = 0
        stats["downloaded"] += 1
        stats["rows"] += len(rows)
        log.info("OK %s (%s) rows=%d bytes=%d", day, fmt, len(rows), os.path.getsize(path))

    log.info("SUMMARY %s", dict(stats))
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
