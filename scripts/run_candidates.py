#!/usr/bin/env python3
"""Pre-registered candidate families A and B on the real-price chain engine (docs/preregistration_candidates.md).

Runs one or all cells of one family over one phase window and writes, per cell:
    <out>/trades_<cell>.json   {"variant", "n", "trades": [...]}  normalised strategy_eval columns
    <out>/skips_<cell>.csv     reason,count (signals that did not open a trade)

Phases (Section 7): train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024-01-01 onward.
The holdout runs only with --allow-holdout, and its end is the last archive trading day at the time of the
look. This script writes trade and skip tables only. The holdout ledger row (logs/holdout_ledger.json) and
the registry row (logs/eval_registry.json) are written by strategy_eval, not by this script.

Market inputs come from the repo cache only (scripts/run_chain_backtest.load_market, MARKET_DATA_CACHE_ONLY=1).
Archive: --archive-dir, default $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive. Read-only input.

Example:
    python scripts/run_candidates.py --family A --cell all --phase train --lots 10 --slippage 1.5 \
        --out /tmp/cand_train

Expectancy printed per cell is per lot at the stated lot count (Section 8, item 5).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from backtester.candidates import FAMILY_CELLS, PHASE_WINDOWS, get_cell, harness_record  # noqa: E402
from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

DEFAULT_MARKET_START = date(2009, 1, 1)


def load_market(end: date, market_start: date = DEFAULT_MARKET_START) -> pd.DataFrame:
    """NIFTY close, India VIX and 5-day returns from the repo cache (scripts/run_chain_backtest.load_market)."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import run_chain_backtest as rcb  # noqa: E402  (imported lazily: it switches the cache-only env var)

    return rcb.load_market(end, market_start)


def _expectancy_per_lot(trades: list[dict]) -> float | None:
    per_lot = [float(t["pnl_net_rs"]) / int(t["lots"]) for t in trades]
    return round(sum(per_lot) / len(per_lot), 1) if per_lot else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", choices=["A", "B"], required=True,
                    help="A = put credit spread (VIX 16-25); B = long strangle (VIX < 13)")
    ap.add_argument("--cell", default="all",
                    help="a cell id of the family, or 'all' (default %(default)s)")
    ap.add_argument("--phase", choices=["train", "test", "holdout"], required=True)
    ap.add_argument("--allow-holdout", action="store_true",
                    help="required for --phase holdout (the single pre-registered look)")
    ap.add_argument("--lots", type=int, default=10, help="lots per trade; verdicts use 10 (default %(default)s)")
    ap.add_argument("--slippage", type=float, default=1.5,
                    help="slippage multiplier (verdict cost 1.5; default %(default)s)")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--archive-dir", type=str, default=None,
                    help="NSE F&O daily archive directory (default: $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive)")
    a = ap.parse_args(argv)

    if a.phase == "holdout" and not a.allow_holdout:
        ap.error("--phase holdout requires --allow-holdout (single pre-registered look)")
    if a.cell != "all" and a.cell not in {c.cell_id for c in FAMILY_CELLS[a.family]}:
        ap.error(f"cell {a.cell!r} is not a cell of family {a.family}")
    cells = list(FAMILY_CELLS[a.family]) if a.cell == "all" else [get_cell(a.cell)]

    start, end = PHASE_WINDOWS[a.phase]
    if end is None:  # holdout: end = last settlement date in the archive at the time of the look
        end = NseFoArchive(archive_dir=a.archive_dir).trading_days()[-1]
        print(f"holdout end (last archive trading day, recorded at the look): {end}")

    market = load_market(end, DEFAULT_MARKET_START)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=end)

    a.out.mkdir(parents=True, exist_ok=True)
    print(f"family {a.family} phase {a.phase} window {start}..{end} lots={a.lots} slippage={a.slippage}")
    for cell in cells:
        cfg = ChainConfig(slippage_multiplier=a.slippage, lots=a.lots, start=start, end=end,
                          candidate=cell, cash_settlement=True, legacy_costs=False)
        bt = ChainBacktest(arch, market, cfg)
        trades = [harness_record(t) for t in bt.run()]
        json.dump({"variant": f"candidate_{cell.cell_id}_{a.phase}", "family": a.family, "phase": a.phase,
                   "start": str(start), "end": str(end), "lots": a.lots,
                   "slippage_multiplier": a.slippage, "n": len(trades), "trades": trades},
                  open(a.out / f"trades_{cell.cell_id}.json", "w"), indent=1, default=str)
        pd.DataFrame(sorted(bt.skips.items()), columns=["reason", "count"]).to_csv(
            a.out / f"skips_{cell.cell_id}.csv", index=False)
        skips = dict(sorted(bt.skips.items()))
        print(f"{cell.cell_id}: trades={len(trades)} signal_days={bt.signal_days} "
              f"exp_per_lot(lots={a.lots})={_expectancy_per_lot(trades)} skips={skips}")
    print("ledger rows: written by strategy_eval (holdout_ledger / eval_registry), not by this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
