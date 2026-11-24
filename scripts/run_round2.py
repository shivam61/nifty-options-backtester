#!/usr/bin/env python3
"""Round-2 hedged NIFTY option-selling cells C1, C2, D1, D2, E1, E2 (docs/preregistration_round2.md, Sections 3-6, 11.3).

Declared cells live in backtester.candidates.ROUND2_CELLS (frozen, Section 3 table). Family F (combination) is not
declared and not run here: it is built only after train (Section 3b).

Per cell, writes into --out:
    trades_<cell>.json   {"variant", "family", "phase", "n", "trades": [...]}  normalised strategy_eval columns
    skips_<cell>.csv     reason,count (signals that did not open a trade)
    curve_<cell>.csv, summary_<cell>.json   capital mode only (Tier 2 input for scripts/eval_strategy.py)

Tier 1 (per-lot verdict, Section 4): default --lots 10, no capital mode, --slippage 1.0 (pass bar).
Tier 2 (capital mode, Section 4): --capital-mode, which requires --lots 1 (sizing is per trade). Fixed:
Rs 25L capital, equity-based sizing, risk_cap_pct 0.05, margin_cap_pct 0.20, kill_dd_pct 0.20 absorbing,
max_lots engine default.
Always fixed for round 2: skip_zero_contract_legs=True (Section 2), max_concurrent=1, signal_cadence="expiry_day".

Phases (Section 6): train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024-01-01 onward.
--phase holdout requires --allow-holdout (the single pre-registered look; same guard as scripts/run_candidates.py).
This script writes trade and skip tables only. Ledger and registry rows are written by strategy_eval.

Market inputs come from the repo cache only (scripts/run_chain_backtest.load_market, MARKET_DATA_CACHE_ONLY=1).
Archive: --archive-dir, default $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive. Read-only input.

Example (train, Tier 1):
    python scripts/run_round2.py --phase train --cell all --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import run_candidates as _rc  # noqa: E402  (same loader and expectancy helper as the round-1 runner)
from backtester.candidates import (  # noqa: E402
    PHASE_WINDOWS, ROUND2_CELL_IDS, CandidateSpec, get_round2_cell, harness_record,
)
from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

DEFAULT_MARKET_START = _rc.DEFAULT_MARKET_START
TIER1_LOTS = 10
TIER2_LOTS = 1
TIER2_CAPITAL_RS = 2_500_000.0     # Rs 25 lakh (Section 4)
TIER2_RISK_CAP_PCT = 0.05          # proposed in Section 4, recorded as author-approved (Section 12)
TIER2_MARGIN_CAP_PCT = 0.20
TIER2_KILL_DD_PCT = 0.20


def load_market(end: date, market_start: date = DEFAULT_MARKET_START) -> pd.DataFrame:
    return _rc.load_market(end, market_start)


def build_config(spec: CandidateSpec, start: date, end: date, *, lots, slippage: float,
                 capital_mode: bool, capital_rs: float = TIER2_CAPITAL_RS) -> ChainConfig:
    """ChainConfig for one round-2 cell with the fixed round-2 settings (Sections 2 and 4)."""
    if lots is None:
        lots = TIER2_LOTS if capital_mode else TIER1_LOTS
    cfg = ChainConfig(slippage_multiplier=slippage, lots=lots, start=start, end=end, candidate=spec,
                      cash_settlement=True, legacy_costs=False, max_concurrent=1, signal_cadence="expiry_day",
                      skip_zero_contract_legs=True)
    if capital_mode:
        cfg = replace(cfg, capital_mode=True, capital_rs=capital_rs, risk_cap_pct=TIER2_RISK_CAP_PCT,
                      margin_cap_pct=TIER2_MARGIN_CAP_PCT, kill_dd_pct=TIER2_KILL_DD_PCT,
                      equity_based_sizing=True)
    return cfg


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", default="all", choices=["all", *ROUND2_CELL_IDS],
                    help="a round-2 cell, or 'all' (default %(default)s); F is not a cell")
    ap.add_argument("--phase", choices=["train", "test", "holdout"], required=True)
    ap.add_argument("--allow-holdout", action="store_true",
                    help="required for --phase holdout (the single pre-registered look)")
    ap.add_argument("--lots", type=int, default=None,
                    help="lots per trade: 10 for Tier 1 (default), 1 for --capital-mode")
    ap.add_argument("--slippage", type=float, default=1.0, help="slippage multiplier (pass bar 1.0; default %(default)s)")
    ap.add_argument("--capital-mode", action="store_true",
                    help="Tier 2: size each trade from Rs 25L equity (requires --lots 1)")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--archive-dir", type=str, default=None,
                    help="NSE F&O daily archive directory (default: $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive)")
    return ap


def parse_args(argv=None) -> argparse.Namespace:
    ap = _parser()
    a = ap.parse_args(argv)
    if a.phase == "holdout" and not a.allow_holdout:
        ap.error("--phase holdout requires --allow-holdout (single pre-registered look)")
    if a.allow_holdout and a.phase != "holdout":
        ap.error("--allow-holdout applies to --phase holdout only")
    if a.capital_mode and a.lots is not None and a.lots != TIER2_LOTS:
        ap.error("--capital-mode requires --lots 1 (sizing is applied per trade)")
    return a


def main(argv=None) -> int:
    a = parse_args(argv)
    cell_ids = list(ROUND2_CELL_IDS) if a.cell == "all" else [a.cell]
    cells = [get_round2_cell(c) for c in cell_ids]

    start, end = PHASE_WINDOWS[a.phase]
    if end is None:  # holdout: end = last settlement date in the archive at the time of the look
        end = NseFoArchive(archive_dir=a.archive_dir).trading_days()[-1]
        print(f"holdout end (last archive trading day, recorded at the look): {end}")

    market = load_market(end, DEFAULT_MARKET_START)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=end)

    a.out.mkdir(parents=True, exist_ok=True)
    lots = a.lots if a.lots is not None else (TIER2_LOTS if a.capital_mode else TIER1_LOTS)
    print(f"round 2 phase {a.phase} window {start}..{end} lots={lots} slippage={a.slippage} "
          f"capital_mode={a.capital_mode} cells={cell_ids} (F not run)")
    for spec in cells:
        cfg = build_config(spec, start, end, lots=lots, slippage=a.slippage, capital_mode=a.capital_mode)
        bt = ChainBacktest(arch, market, cfg)
        trades = [harness_record(t) for t in bt.run()]
        json.dump({"variant": f"round2_{spec.cell_id}_{a.phase}", "family": spec.family, "phase": a.phase,
                   "start": str(start), "end": str(end), "lots": lots,
                   "slippage_multiplier": a.slippage, "n": len(trades), "trades": trades},
                  open(a.out / f"trades_{spec.cell_id}.json", "w"), indent=1, default=str)
        pd.DataFrame(sorted(bt.skips.items()), columns=["reason", "count"]).to_csv(
            a.out / f"skips_{spec.cell_id}.csv", index=False)
        skips = dict(sorted(bt.skips.items()))
        print(f"{spec.cell_id}: trades={len(trades)} signal_days={bt.signal_days} "
              f"exp_per_lot(lots={lots})={_rc._expectancy_per_lot(trades)} skips={skips}")
        if a.capital_mode:
            pd.DataFrame([{"date": str(d), "equity": e, "margin_used": m} for d, e, m in bt.capital_curve]).to_csv(
                a.out / f"curve_{spec.cell_id}.csv", index=False)
            summary = bt.capital_summary(echo=False)
            json.dump(summary, open(a.out / f"summary_{spec.cell_id}.json", "w"), indent=1, default=str)
            print(f"  capital: final_equity={summary['final_equity']:.0f} CAGR={summary['cagr_pct']}% "
                  f"MaxDD={summary['max_dd_pct']}% Sharpe(daily)={summary['sharpe_daily_ann']} "
                  f"avg_lots={summary['avg_lots']}")
    print("ledger rows: written by strategy_eval (holdout_ledger / eval_registry), not by this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
