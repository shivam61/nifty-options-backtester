#!/usr/bin/env python3
"""Descriptive utilisation sweep (NOT a verdict, no registry writes, holdout never read).

Runs the 7 frozen round-3 cells in capital mode on the dev window 2019-02-11..2023-12-31 at several
risk_cap_pct values (margin_cap_pct and max_lots raised so the risk cap binds). Per-lot edge is unchanged by
sizing; this shows how CAGR, MaxDD and Sharpe scale with utilisation. Kill switch is reported on and off.

    python scripts/utilisation_sweep.py --out logs/util_sweep
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import run_round3 as r3  # noqa: E402
from backtester.candidates import ROUND3_CELL_IDS, get_round3_cell  # noqa: E402
from backtester.chain_engine import ML_EXIT_REASON, ChainBacktest  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

DEV_START, DEV_END = date(2019, 2, 11), date(2023, 12, 31)
WINDOWS = {"dev": (DEV_START, DEV_END), "train": (date(2019, 2, 11), date(2021, 12, 31))}
LEAKY_MODEL = Path("data/.cache/exit_model.pkl")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--risk", type=float, nargs="+", default=[0.05, 0.10, 0.20, 0.40])
    ap.add_argument("--cells", nargs="+", default=list(ROUND3_CELL_IDS))
    ap.add_argument("--slippage", type=float, default=1.0)
    ap.add_argument("--exit-model", type=Path, default=None,
                    help="exit_model.pkl (or fold root): ML exit gate on top of the rules, default off")
    ap.add_argument("--window", choices=sorted(WINDOWS), default="dev")
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    start, end = WINDOWS[a.window]

    exit_gate = None
    if a.exit_model is not None:
        import ml_gate_adapters as mga
        if a.exit_model.resolve() == (REPO_ROOT / LEAKY_MODEL).resolve():
            bar = "!" * 78
            print(bar, "WARNING: LEAKY exit model data/.cache/exit_model.pkl is trained through 2026 "
                  "and overlaps the test window AND the holdout. Results are NOT out-of-sample.",
                  bar, sep="\n", flush=True)
        exit_gate = mga.make_exit_gate(a.exit_model, mga.load_gate_market(end))

    market = r3.load_market(end)
    fb = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(index_fallback=fb, max_date=end)
    rows = []
    for cid in a.cells:
        spec = get_round3_cell(cid)
        for risk in a.risk:
            for kill in (0.20, 0.99):
                cfg = r3.build_config(spec, start, end, lots=1, slippage=a.slippage, capital_mode=True)
                cfg = replace(cfg, risk_cap_pct=risk, margin_cap_pct=min(0.95, risk * 4), max_lots=500,
                              kill_dd_pct=kill, exit_gate=exit_gate)
                bt = ChainBacktest(arch, market, cfg)
                trades = bt.run()
                n = len(trades)
                s = bt.capital_summary(echo=False)
                row = {"cell": cid, "risk_cap": risk, "kill": kill, "n": n, "n_ml_exits": sum(1 for t in trades if t.get("exit_reason") == ML_EXIT_REASON),
                       "window": a.window, "cagr": s["cagr_pct"],
                       "maxdd": s["max_dd_pct"], "sharpe": s["sharpe_daily_ann"], "avg_lots": s["avg_lots"],
                       "final": s["final_equity"]}
                rows.append(row)
                print(row, flush=True)
    name = "sweep" + ("" if a.window == "dev" else f"_{a.window}") + (
        f"_{a.exit_model.parent.name}_{a.exit_model.stem}" if a.exit_model is not None else "") + ".json"
    json.dump(rows, open(a.out / name, "w"), indent=1, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
