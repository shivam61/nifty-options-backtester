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
from dataclasses import replace
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
    # Capital mode (opt-in). Writes curve_<cell>.csv (date,equity,margin_used) and summary_<cell>.json for
    # scripts/eval_strategy.py --equity-curve (Tier 2). Requires --lots 1: sizing is per trade.
    ap.add_argument("--capital-mode", action="store_true",
                    help="size each trade from capital (requires --lots 1); writes the equity curve and summary")
    ap.add_argument("--capital-rs", type=float, default=2_500_000.0, help="capital base Rs (default %(default)s = 25L)")
    ap.add_argument("--risk-cap-pct", type=float, default=0.10, help="max loss per trade as a fraction of capital")
    ap.add_argument("--margin-cap-pct", type=float, default=0.20, help="margin per trade as a fraction of capital")
    ap.add_argument("--max-lots", type=int, default=30, help="lot cap per trade")
    ap.add_argument("--kill-dd-pct", type=float, default=0.20, help="kill-switch drawdown from peak equity")
    ap.add_argument("--equity-sizing", action="store_true",
                    help="size from current equity instead of --capital-rs (capital mode only)")
    ap.add_argument("--max-concurrent", type=int, default=1, help="positions open at once (default %(default)s)")
    a = ap.parse_args(argv)

    if a.phase == "holdout" and not a.allow_holdout:
        ap.error("--phase holdout requires --allow-holdout (single pre-registered look)")
    if a.capital_mode and a.lots != 1:
        ap.error("--capital-mode requires --lots 1 (sizing is applied per trade)")
    if a.equity_sizing and not a.capital_mode:
        ap.error("--equity-sizing requires --capital-mode")
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
                          candidate=cell, cash_settlement=True, legacy_costs=False,
                          max_concurrent=a.max_concurrent)
        if a.capital_mode:
            cfg = replace(cfg, capital_mode=True, capital_rs=a.capital_rs, risk_cap_pct=a.risk_cap_pct,
                          margin_cap_pct=a.margin_cap_pct, max_lots=a.max_lots, kill_dd_pct=a.kill_dd_pct,
                          equity_based_sizing=a.equity_sizing)
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
        if a.capital_mode:
            pd.DataFrame([{"date": str(d), "equity": e, "margin_used": m} for d, e, m in bt.capital_curve]).to_csv(
                a.out / f"curve_{cell.cell_id}.csv", index=False)
            summary = bt.capital_summary(echo=False)
            json.dump(summary, open(a.out / f"summary_{cell.cell_id}.json", "w"), indent=1, default=str)
            print(f"  capital: final_equity={summary['final_equity']:.0f} CAGR={summary['cagr_pct']}% "
                  f"MaxDD={summary['max_dd_pct']}% Sharpe(daily)={summary['sharpe_daily_ann']} "
                  f"avg_lots={summary['avg_lots']}")
    print("ledger rows: written by strategy_eval (holdout_ledger / eval_registry), not by this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
