#!/usr/bin/env python3
"""DESCRIPTIVE screen (NOT a verdict, no registry writes, holdout never read): short-DTE hedged weekly iron condor.

Dev window 2019-02-11..2023-12-31 only. lots=10, gate off, slippage 1.0x and 0.3x. IC, W=400, VIX [13, 25).
Cells (fixed grid, no tuning): SD_k10 and SD_k13 (k=1.0 / 1.3, DTE at fill in [1, 2]) and BASE_k10 (k=1.0, DTE [3, 8],
the normal weekly expiry-day cadence, same as round 3 W1 apart from k and VIX band).

How the short-DTE window is expressed WITHOUT editing backtester/:
  * backtester.candidates.pick_expiry reads the module constant WEEKLY_DTE_WINDOW at call time. This script sets
    that constant to (1, 2) for the SD cells and restores (3, 8) afterwards (monkeypatch, in-process only).
  * Cadence: signal_cadence='daily' (signal every session, fill next session). Fill-day DTE not in [1, 2] drops the
    pending signal ('no_expiry_in_dte_window'). Entry is therefore signal 2-3 sessions before expiry, fill 1-2
    calendar days before expiry. max_concurrent=1 so one trade per expiry cycle at most.
  * Actual DTE at fill is recomputed from the trade records (expiry - entry_date) and tabulated.
Other settings as round 3 (strike_basis signal_close, max_loss fill_plus_fees, expiry_brokerage, zero-contract skip).

    python scripts/explore_short_dte.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backtester.candidates as cand  # noqa: E402
import run_round3 as r3  # noqa: E402
from backtester.candidates import (  # noqa: E402
    IRON_CONDOR, MAX_LOSS_BASIS_FILL_PLUS_FEES, STRIKE_BASIS_SIGNAL_CLOSE, CandidateSpec, harness_record,
)
from backtester.chain_engine import ChainBacktest  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

DEV_START, DEV_END = date(2019, 2, 11), date(2023, 12, 31)
LOTS = 10
OUT = REPO_ROOT / "logs" / "explore" / "short_dte"
_C = dict(strike_basis=STRIKE_BASIS_SIGNAL_CLOSE, max_loss_basis=MAX_LOSS_BASIS_FILL_PLUS_FEES)
CELLS = [  # (spec, dte window, signal cadence)
    (CandidateSpec("SD_k10", "X", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0, **_C), (1, 2), "daily"),
    (CandidateSpec("SD_k13", "X", IRON_CONDOR, 1.3, 400.0, "weekly", 13.0, 25.0, **_C), (1, 2), "daily"),
    (CandidateSpec("BASE_k10", "X", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0, **_C), (3, 8), "expiry_day"),
]
SLIPPAGES = (1.0, 0.3)


def run_cell(arch, market, spec, window, cadence, slip):
    orig = cand.WEEKLY_DTE_WINDOW
    cand.WEEKLY_DTE_WINDOW = window
    try:
        cfg = r3.build_config(spec, DEV_START, DEV_END, lots=LOTS, slippage=slip, capital_mode=False)
        if cadence != cfg.signal_cadence:
            from dataclasses import replace
            cfg = replace(cfg, signal_cadence=cadence)
        bt = ChainBacktest(arch, market, cfg)
        recs = [harness_record(t) for t in bt.run()]
    finally:
        cand.WEEKLY_DTE_WINDOW = orig
    return recs, dict(bt.skips)


def summarise(recs):
    if not recs:
        return None
    df = pd.DataFrame(recs)
    df["lots"] = df["lots"].astype(float)
    df["net_lot"] = df["pnl_net_rs"] / df["lots"]
    df["credit_lot"] = df["credit_rs"] / df["lots"]
    df["cost_lot"] = df["cost_rs"] / df["lots"]
    df["slip_lot"] = df["slippage_rs"] / df["lots"]
    df["dte"] = (pd.to_datetime(df["expiry"]) - pd.to_datetime(df["entry_date"])).dt.days
    df["year"] = pd.to_datetime(df["entry_date"]).dt.year
    py = df.groupby("year")["net_lot"].agg(["count", "mean"])
    return {
        "n": len(df), "rs_lot": df["net_lot"].mean(), "win": (df["net_lot"] > 0).mean(),
        "worst": df["net_lot"].min(), "credit_lot": df["credit_lot"].mean(), "cost_lot": df["cost_lot"].mean(),
        "slip_lot": df["slip_lot"].mean(), "sd_lot": df["net_lot"].std(),
        "dte_at_fill": dict(sorted(Counter(df["dte"]).items())),
        "exit_reasons": dict(Counter(df["exit_reason"])),
        "per_year": {int(y): {"n": int(r["count"]), "rs_lot": round(float(r["mean"]), 1)} for y, r in py.iterrows()},
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    market = r3.load_market(DEV_END)
    fb = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(index_fallback=fb, max_date=DEV_END)
    results = []
    for spec, window, cadence in CELLS:
        for slip in SLIPPAGES:
            recs, skips = run_cell(arch, market, spec, window, cadence, slip)
            tag = f"{spec.cell_id}_s{slip:g}"
            json.dump({"cell": spec.cell_id, "dte_window": window, "cadence": cadence, "slippage": slip,
                       "lots": LOTS, "start": str(DEV_START), "end": str(DEV_END), "n": len(recs),
                       "skips": skips, "trades": recs},
                      open(OUT / f"trades_{tag}.json", "w"), indent=1, default=str)
            s = summarise(recs)
            results.append({"cell": spec.cell_id, "slippage": slip, "skips": skips, "summary": s})
            if s is None:
                print(f"{tag}: no trades skips={skips}")
                continue
            print(f"{tag}: n={s['n']} Rs/lot={s['rs_lot']:+.0f} win={s['win']:.0%} worst={s['worst']:+.0f} "
                  f"credit/lot={s['credit_lot']:.0f} fees/lot={s['cost_lot']:.0f} slip/lot={s['slip_lot']:.0f} "
                  f"sd={s['sd_lot']:.0f} DTE@fill={s['dte_at_fill']}")
            print(f"    per-year {s['per_year']}")
            print(f"    exits {s['exit_reasons']} skips {skips}")
    json.dump(results, open(OUT / "summary.json", "w"), indent=1, default=str)
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
