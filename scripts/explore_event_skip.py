#!/usr/bin/env python3
"""DESCRIPTIVE screen (not a verdict, no registry writes, holdout never read): weekly IC / PCS skipping event weeks.

Dev window 2019-02-11..2023-12-31. Cells: IC (k=1.0, W=400, VIX [13,25)) and PCS (k=1.0, W=300, VIX [13,25)),
hold to expiry, lots=10, slippage 1.0x and 0.3x, ML gate off. Event-skip is applied through the existing
ChainConfig.candidate_entry_filter hook (no backtester edits). A trade's "week" = calendar days S+1..S+7 after the
signal day S (fill next session, weekly expiry ~7 days later). Baseline trades are also tagged post-hoc with the same
rule, giving kept vs excluded P&L from ONE run; the filtered run must reproduce the kept set (checked).

Event calendar: backtester/production_rules.py has only APPROXIMATE FOMC/RBI dates for 2019-2023, so dated lists are
hardcoded below from memory of public schedules (best effort, NOT verified against primary sources).
Results-season weeks are a crude proxy (10th..22nd of Jan/Apr/Jul/Oct), not actual company dates.

    python scripts/explore_event_skip.py
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import run_round3 as r3  # noqa: E402
from backtester.candidates import (  # noqa: E402
    IRON_CONDOR, PCS, _R3_COMMON, CandidateSpec, harness_record,
)
from backtester.chain_engine import ChainBacktest  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

START, END = date(2019, 2, 11), date(2023, 12, 31)
OUT = REPO_ROOT / "logs" / "explore" / "event_skip"
D = date

RBI = [D(2019, 2, 7), D(2019, 4, 4), D(2019, 6, 6), D(2019, 8, 7), D(2019, 10, 4), D(2019, 12, 5),
       D(2020, 2, 6), D(2020, 3, 27), D(2020, 5, 22), D(2020, 8, 6), D(2020, 10, 9), D(2020, 12, 4),
       D(2021, 2, 5), D(2021, 4, 7), D(2021, 6, 4), D(2021, 8, 6), D(2021, 10, 8), D(2021, 12, 8),
       D(2022, 2, 10), D(2022, 4, 8), D(2022, 5, 4), D(2022, 6, 8), D(2022, 8, 5), D(2022, 9, 30), D(2022, 12, 7),
       D(2023, 2, 8), D(2023, 4, 6), D(2023, 6, 8), D(2023, 8, 10), D(2023, 10, 6), D(2023, 12, 8)]
BUDGET = [D(2019, 2, 1), D(2019, 7, 5), D(2020, 2, 1), D(2021, 2, 1), D(2022, 2, 1), D(2023, 2, 1)]
# FOMC decision days (US date); India reacts next session, so the event day used is +1 calendar day.
FOMC_US = [D(2019, 1, 30), D(2019, 3, 20), D(2019, 5, 1), D(2019, 6, 19), D(2019, 7, 31), D(2019, 9, 18),
           D(2019, 10, 30), D(2019, 12, 11),
           D(2020, 1, 29), D(2020, 3, 3), D(2020, 3, 15), D(2020, 4, 29), D(2020, 6, 10), D(2020, 7, 29),
           D(2020, 9, 16), D(2020, 11, 5), D(2020, 12, 16),
           D(2021, 1, 27), D(2021, 3, 17), D(2021, 4, 28), D(2021, 6, 16), D(2021, 7, 28), D(2021, 9, 22),
           D(2021, 11, 3), D(2021, 12, 15),
           D(2022, 1, 26), D(2022, 3, 16), D(2022, 5, 4), D(2022, 6, 15), D(2022, 7, 27), D(2022, 9, 21),
           D(2022, 11, 2), D(2022, 12, 14),
           D(2023, 2, 1), D(2023, 3, 22), D(2023, 5, 3), D(2023, 6, 14), D(2023, 7, 26), D(2023, 9, 20),
           D(2023, 11, 1), D(2023, 12, 13)]
FOMC = [d + timedelta(days=1) for d in FOMC_US]
EVENT_DATES = {"rbi": RBI, "budget": BUDGET, "fomc": FOMC}


def event_types(signal_day: date) -> list:
    """Event types whose date falls in the trade week S+1..S+7."""
    lo, hi = signal_day + timedelta(days=1), signal_day + timedelta(days=7)
    out = [k for k, ds in EVENT_DATES.items() if any(lo <= d <= hi for d in ds)]
    for off in range(7):
        c = lo + timedelta(days=off)
        if c.month in (1, 4, 7, 10) and 10 <= c.day <= 22:
            out.append("results")
            break
    return out


def event_filter(row):
    return len(event_types(pd.Timestamp(row.name).date())) == 0


CELLS = {
    "IC": CandidateSpec("EV_IC", "W", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0, **_R3_COMMON),
    "PCS": CandidateSpec("EV_PCS", "W", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, **_R3_COMMON),
}


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "rs_per_lot": None, "win": None, "by_year": {}}
    pl = df["pnl_lot"]
    by = {str(y): {"n": int(len(g)), "rs_lot": round(float(g["pnl_lot"].mean()), 1)}
          for y, g in df.groupby("year")}
    return {"n": int(len(df)), "rs_per_lot": round(float(pl.mean()), 1), "win": round(float((pl > 0).mean()), 3),
            "by_year": by}


def to_df(trades: list) -> pd.DataFrame:
    recs = [harness_record(t) for t in trades]
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    df["pnl_lot"] = df["pnl_net_rs"] / df["lots"]
    df["year"] = pd.to_datetime(df["entry_date"]).dt.year
    df["types"] = df["signal_date"].map(lambda s: event_types(pd.Timestamp(s).date()))
    df["event"] = df["types"].map(bool)
    return df


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    market = r3.load_market(END)
    fb = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(index_fallback=fb, max_date=END)
    res = {}
    for name, spec in CELLS.items():
        for slip in (1.0, 0.3):
            key = f"{name}@{slip:g}x"
            cfg = r3.build_config(spec, START, END, lots=10, slippage=slip, capital_mode=False)
            base = to_df(ChainBacktest(arch, market, cfg).run())
            from dataclasses import replace
            filt = to_df(ChainBacktest(arch, market, replace(cfg, candidate_entry_filter=event_filter)).run())
            kept, excl = base[~base["event"]], base[base["event"]]
            same = (sorted(map(str, kept["signal_date"])) == sorted(map(str, filt["signal_date"])))
            by_type = {t: stats(excl[excl["types"].map(lambda x, t=t: t in x)]) for t in ("rbi", "budget", "fomc", "results")}
            res[key] = {"baseline": stats(base), "event_skip": stats(filt), "kept_posthoc": stats(kept),
                        "excluded": stats(excl), "excluded_by_type_overlapping": {k: {"n": v["n"], "rs_per_lot": v["rs_per_lot"]} for k, v in by_type.items()},
                        "filtered_run_equals_posthoc_kept": bool(same)}
            base.drop(columns=["legs"]).to_csv(OUT / f"baseline_trades_{name}_{slip:g}x.csv", index=False)
    json.dump(res, open(OUT / "event_skip_results.json", "w"), indent=1)
    print(f"{'cell':<9}{'set':<10}{'n':>5}{'Rs/lot':>9}{'win':>7}  per-year Rs/lot(n)")
    for key, r in res.items():
        for s in ("baseline", "event_skip", "excluded"):
            v = r[s]
            py = " ".join(f"{y}:{b['rs_lot']:+.0f}({b['n']})" for y, b in v["by_year"].items())
            print(f"{key:<9}{s:<10}{v['n']:>5}{str(v['rs_per_lot']):>9}{str(v['win']):>7}  {py}")
        print(f"   excluded by type (overlapping): {r['excluded_by_type_overlapping']}  filter==posthoc: "
              f"{r['filtered_run_equals_posthoc_kept']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
