#!/usr/bin/env python3
"""DESCRIPTIVE screen (not a pre-registered test): weekly credit spreads entered only when VIX is falling.

Grid, declared before looking: lookback N in {1, 5} sessions; falling = VIX_S < VIX_{S-N}; rising = complement
(VIX_S >= VIX_{S-N}). Bases: weekly PCS (k=1.0, W=300, VIX [13,25)) and weekly IC (k=1.0, W=400, VIX [13,25)).
lots=10, slippage 1.0x and 0.3x, gate off, hold to expiry, round-3 engine settings.
DEV window 2019-02-11..2023-12-31 only (market and archive are capped at the window end; no holdout data is read).
Filter uses VIX closes dated <= S only (S = signal-day close). The filter goes through ChainConfig.candidate_entry_filter
(no backtester edits). No registry writes. Outputs: logs/explore/vix_trend/.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run_candidates as _rc  # noqa: E402
from backtester.candidates import (  # noqa: E402
    IRON_CONDOR, MAX_LOSS_BASIS_FILL_PLUS_FEES, PCS, STRIKE_BASIS_SIGNAL_CLOSE, CandidateSpec,
)
from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

START, END = date(2019, 2, 11), date(2023, 12, 31)
LOTS = 10
SLIPS = (1.0, 0.3)
LOOKBACKS = (1, 5)
OUT = REPO_ROOT / "logs" / "explore" / "vix_trend"
_COMMON = dict(strike_basis=STRIKE_BASIS_SIGNAL_CLOSE, max_loss_basis=MAX_LOSS_BASIS_FILL_PLUS_FEES)
BASES = {
    "PCS": CandidateSpec("XPCS", "X", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, **_COMMON),
    "IC": CandidateSpec("XIC", "X", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0, **_COMMON),
}


def vix_trend_filter(vix: pd.Series, n: int, want_falling: bool):
    """True when the VIX trend matches. Reads only values dated <= S. None if fewer than n+1 closes or NaN."""
    def _f(row):
        s = vix.loc[:pd.Timestamp(row.name)]
        if len(s) < n + 1:
            return None
        a, b = float(s.iloc[-1]), float(s.iloc[-1 - n])
        if not (np.isfinite(a) and np.isfinite(b)):
            return None
        return (a < b) if want_falling else (a >= b)
    return _f


def run(spec, market, arch, slip, filt):
    cfg = ChainConfig(slippage_multiplier=slip, lots=LOTS, start=START, end=END, candidate=spec,
                      cash_settlement=True, legacy_costs=False, max_concurrent=1, signal_cadence="expiry_day",
                      skip_zero_contract_legs=True, expiry_brokerage=True, candidate_entry_filter=filt)
    bt = ChainBacktest(arch, market, cfg)
    return bt.run(), dict(bt.skips)


def summarise(trades):
    if not trades:
        return {"n": 0, "rs_lot": None, "win": None, "by_year": {}}
    pl = pd.Series([float(t["pnl"]) / int(t["lots"]) for t in trades])
    yr = pd.Series([pd.Timestamp(t["fill_date"]).year for t in trades])
    by = {int(y): {"n": int((yr == y).sum()), "rs_lot": round(float(pl[yr == y].mean()), 1)}
          for y in sorted(yr.unique())}
    return {"n": len(pl), "rs_lot": round(float(pl.mean()), 1), "win": round(float((pl > 0).mean()) * 100, 1),
            "by_year": by}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    market = _rc.load_market(END, _rc.DEFAULT_MARKET_START)
    market = market.loc[:pd.Timestamp(END)]
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=None, index_fallback=fallback, max_date=END)
    vix = market["vix"]
    results = {}
    for bname, spec in BASES.items():
        for slip in SLIPS:
            variants = [("baseline", None)]
            for n in LOOKBACKS:
                variants += [(f"falling_N{n}", vix_trend_filter(vix, n, True)),
                             (f"rising_N{n}", vix_trend_filter(vix, n, False))]
            for vname, filt in variants:
                trades, skips = run(spec, market, arch, slip, filt)
                key = f"{bname}|{slip:g}x|{vname}"
                s = summarise(trades)
                s["skips"] = skips
                results[key] = s
                json.dump(trades, open(OUT / f"trades_{bname}_{slip:g}x_{vname}.json", "w"), default=str)
                print(f"{key:<26} n={s['n']:>3} Rs/lot={s['rs_lot']} win={s['win']}%  "
                      + " ".join(f"{y}:{v['rs_lot']}(n{v['n']})" for y, v in s["by_year"].items()), flush=True)
    json.dump(results, open(OUT / "summary.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
