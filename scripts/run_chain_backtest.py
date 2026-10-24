#!/usr/bin/env python3
"""Real-price (archive settle) weekly chain backtest driver.

Runs backtester.chain_engine.ChainBacktest over the local NSE F&O daily archive for each
slippage multiplier and writes, per multiplier:
    <out>/trades_x<mult>.json   {"variant", "n", "trades": [...]}
    <out>/diag_x<mult>.json     signal/skip/diagnostic counters
    <out>/skips_x<mult>.csv     skip log
and <out>/summary.json with one row per multiplier.

Market inputs (never a network fetch):
    NIFTY 50 Close and India VIX Close come from data.market_data.MarketDataFetcher with
    MARKET_DATA_CACHE_ONLY=1 over [--market-start, --end]. The series are placed on the NIFTY
    trading calendar exactly as the original ad-hoc driver did (VIX reindexed, no forward fill).
    The 5-day return columns use the same definitions as data/market_data.py (pct_change(5)).
    Full history from --market-start is loaded so the 5-day returns on the first signal day are
    defined; signals are still only considered from --start.

Archive: NseFoArchive(--archive-dir), default $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive. Read-only
input; its parquet cache lives inside the archive directory.

Example:
    python scripts/run_chain_backtest.py --start 2019-02-11 --end 2023-12-31 \
        --slippage 1.0 1.5 2.0 --out /tmp/chain_out

--end later than 2023-12-31 (the 2024+ holdout) is refused unless --allow-holdout is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from strategies.weekly_strategies import WeeklyExitArms  # noqa: E402

DEFAULT_START = date(2019, 2, 11)
DEV_END = date(2023, 12, 31)
DEFAULT_END = DEV_END
DEFAULT_MARKET_START = date(2009, 1, 1)


def check_window(end: date, allow_holdout: bool) -> None:
    """The 2024+ holdout is opened once, for one pre-registered candidate."""
    if end > DEV_END and not allow_holdout:
        raise SystemExit(
            f"refusing --end {end}: later than the development window end {DEV_END}; "
            "pass --allow-holdout only for the pre-registered holdout step")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def load_market(end: date, market_start: date = DEFAULT_MARKET_START) -> pd.DataFrame:
    """NIFTY close + India VIX close on the NIFTY calendar, from the repo cache only."""
    os.environ["MARKET_DATA_CACHE_ONLY"] = "1"
    from data.market_data import MarketDataFetcher  # imported after the env switch

    fetch = MarketDataFetcher(market_start, end)
    nifty = fetch.nifty
    vix_raw = fetch.vix
    if nifty is None or nifty.empty or "Close" not in nifty.columns:
        raise SystemExit(f"no NIFTY rows in the repo cache for {market_start}..{end}; run refresh-data")
    if vix_raw is None or vix_raw.empty or "Close" not in vix_raw.columns:
        raise SystemExit(f"no India VIX rows in the repo cache for {market_start}..{end}; run refresh-data")

    n = nifty.copy()
    v = vix_raw.copy()
    for df in (n, v):
        df.index = pd.to_datetime(df.index).normalize()
        df.sort_index(inplace=True)
    close = n["Close"].astype(float)
    vix = v["Close"].astype(float).reindex(close.index)
    m = pd.DataFrame({"nifty_close": close, "vix": vix})
    m["nifty_return_5d"] = m["nifty_close"].pct_change(5)
    m["vix_change_5d"] = m["vix"].pct_change(5)
    return m


def run_one(arch, market: pd.DataFrame, start: date, end: date, mult: float, lots: int,
            overrides: dict | None = None):
    cfg = ChainConfig(slippage_multiplier=mult, lots=lots, start=start, end=end, **(overrides or {}))
    bt = ChainBacktest(arch, market, cfg)
    trades = bt.run()
    diag = {
        "mult": mult, "start": str(start), "end": str(end), "lots": lots,
        "arms": {"pcs_put_sd": cfg.pcs_put_sd, "breach_stop": cfg.exit_arms.breach_stop,
                 "ic_hold_to_expiry": cfg.exit_arms.ic_hold_to_expiry,
                 "hold_to_expiry": cfg.exit_arms.hold_to_expiry},
        "cfg": {"min_vix_floor": cfg.min_vix_floor, "capital_protection_per_lot": cfg.capital_protection_per_lot,
                "hold_to_expiry": cfg.exit_arms.hold_to_expiry},
        "signal_days": bt.signal_days, "signals_while_open": bt.signals_while_open,
        "trades": len(trades), "skips": dict(bt.skips), "diag": dict(bt.diag),
        "expiry_close_vs_intrinsic_max": max(bt.expiry_intrinsic_dev) if bt.expiry_intrinsic_dev else None,
        "expiry_close_vs_intrinsic_n": len(bt.expiry_intrinsic_dev),
        "expiry_close_vs_intrinsic_gt5": int(sum(1 for x in bt.expiry_intrinsic_dev if x > 5.0)),
        "expiry_index_vs_nifty_max": max(bt.index_vs_nifty) if bt.index_vs_nifty else None,
        "expiry_index_vs_nifty_n": len(bt.index_vs_nifty),
    }
    if not cfg.fully_legacy:  # legacy mode keeps the pre-change diag schema byte for byte
        diag["cfg"].update({"cash_settlement": cfg.cash_settlement, "legacy_costs": cfg.legacy_costs})
    return trades, diag, bt.skip_log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=_parse_date, default=DEFAULT_START,
                    help="first signal date considered (default %(default)s)")
    ap.add_argument("--end", type=_parse_date, default=DEFAULT_END,
                    help="last signal date considered; market data is pinned to this end (default %(default)s)")
    ap.add_argument("--allow-holdout", action="store_true",
                    help="permit --end after 2023-12-31 (pre-registered holdout step only)")
    ap.add_argument("--market-start", type=_parse_date, default=DEFAULT_MARKET_START,
                    help="start of market history loaded for 5-day returns (default %(default)s)")
    ap.add_argument("--slippage", type=float, nargs="+", default=[1.0],
                    help="slippage multipliers, one run each (default: 1.0)")
    ap.add_argument("--lots", type=int, default=1)
    # Structural / exit arms; defaults reproduce the baseline. Each can be run on its own.
    ap.add_argument("--pcs-put-sd", type=float, default=0.9,
                    help="arm A: PCS short-put distance in 1-SD units (default %(default)s = baseline)")
    ap.add_argument("--no-breach-stop", action="store_true",
                    help="arm B: disable the close-based short-strike breach stop (PCS and IC)")
    ap.add_argument("--ic-hold-to-expiry", action="store_true",
                    help="arm C: IC exits only on the credit-multiple stop and expiry settle")
    ap.add_argument("--no-early-exits", action="store_true",
                    help="family F1: PCS and IC held to expiry settle; every other exit disabled")
    ap.add_argument("--min-vix", type=float, default=None,
                    help="family F2: skip entry signals with India VIX below this value (default: no floor)")
    ap.add_argument("--legacy-settlement", action="store_true",
                    help="legacy: expiry is an exit order (exit slippage and exit fees) instead of cash "
                         "settlement at intrinsic value")
    ap.add_argument("--legacy-costs", action="store_true",
                    help="legacy: CostModel round-trip fee formula on the net credit (GST on brokerage only)")
    ap.add_argument("--fixed-capital-protection", action="store_true",
                    help="legacy: capital-protection stop uses a fixed Rs20,000 total at any lot count")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--archive-dir", type=str, default=None,
                    help="NSE F&O daily archive directory (default: $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive)")
    a = ap.parse_args(argv)
    check_window(a.end, a.allow_holdout)
    if a.start > a.end:
        ap.error("--start must not be after --end")
    if a.market_start > a.start:
        ap.error("--market-start must not be after --start")

    from data.nse_fo_archive import NseFoArchive

    a.out.mkdir(parents=True, exist_ok=True)
    market = load_market(a.end, a.market_start)
    # expiry-day index settlement fallback for archive days with no positive index settle (2019)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    # rows dated after --end are dropped at load time (never indexed)
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=a.end)

    summary = {"start": str(a.start), "end": str(a.end), "market_start": str(a.market_start),
               "market_rows": int(len(market)), "archive_rows": int(arch.n_rows), "runs": []}
    overrides = {
        "pcs_put_sd": a.pcs_put_sd,
        "exit_arms": WeeklyExitArms(breach_stop=not a.no_breach_stop,
                                    ic_hold_to_expiry=a.ic_hold_to_expiry,
                                    hold_to_expiry=a.no_early_exits),
        "min_vix_floor": a.min_vix,
        "capital_protection_per_lot": not a.fixed_capital_protection,
        "cash_settlement": not a.legacy_settlement,
        "legacy_costs": a.legacy_costs,
    }
    summary["arms"] = {"pcs_put_sd": a.pcs_put_sd, "breach_stop": not a.no_breach_stop,
                       "ic_hold_to_expiry": a.ic_hold_to_expiry, "hold_to_expiry": a.no_early_exits}
    summary["cfg"] = {"min_vix_floor": a.min_vix, "capital_protection_per_lot": not a.fixed_capital_protection}
    if not (a.legacy_settlement and a.legacy_costs):  # fully-legacy summary schema unchanged
        summary["cfg"].update({"cash_settlement": not a.legacy_settlement, "legacy_costs": a.legacy_costs})
    for mult in a.slippage:
        tag = f"x{mult:g}"
        trades, diag, skip_log = run_one(arch, market, a.start, a.end, mult, a.lots, overrides)
        json.dump({"variant": f"chain_{tag}", "n": len(trades), "trades": trades},
                  open(a.out / f"trades_{tag}.json", "w"), indent=1, default=str)
        json.dump(diag, open(a.out / f"diag_{tag}.json", "w"), indent=1, default=str)
        pd.DataFrame(skip_log).to_csv(a.out / f"skips_{tag}.csv", index=False)
        pnl = [float(t["pnl_per_lot"]) for t in trades]
        summary["runs"].append({
            "tag": tag, "slippage_multiplier": mult, "trades": len(trades),
            "total_pnl_per_lot": round(sum(pnl), 1),
            "exp_per_lot": round(sum(pnl) / len(pnl), 1) if pnl else None,
        })
        print(f"{tag}: trades={len(trades)} exp_per_lot={summary['runs'][-1]['exp_per_lot']}")
    json.dump(summary, open(a.out / "summary.json", "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
