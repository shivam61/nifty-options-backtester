#!/usr/bin/env python3
"""Round-3 monthly and filtered hedged NIFTY option-selling cells M1, M2, M3, S1, T1, R1, W1
(docs/preregistration_round3.md, Sections 3, 4 and 7).

Declared cells live in backtester.candidates.ROUND3_CELLS (frozen Section 3 table). The combiner (Section 3b) is not
declared and not run here.

Per cell, writes into --out:
    trades_<cell>.json   {"variant", "family", "phase", "n", "trades": [...]}  normalised strategy_eval columns
    skips_<cell>.csv     reason,count (signals that did not open a trade)
    curve_<cell>.csv, summary_<cell>.json   capital mode only (Tier 2 input for scripts/eval_strategy.py)
A skip-reason table for all cells is printed at the end.

Fixed for round 3: hold to expiry (cell definitions), strike_basis='signal_close', max_loss_basis='fill_plus_fees',
expiry_brokerage=True, skip_zero_contract_legs=True, max_concurrent=1, signal_cadence='expiry_day' (monthly cells set
monthly_signal on their CandidateSpec).

Tier 1 (per-lot verdict, Section 4): default --lots 10, no capital mode, --slippage 1.0 (pass bar).
Tier 2 (capital mode, Section 4): --capital-mode, which requires --lots 1. Rs 25L capital, equity-based sizing,
risk_cap_pct 0.05, margin_cap_pct 0.20, kill_dd_pct 0.20 absorbing.

Phases (Section 4): train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024-01-01 onward.
--phase holdout requires --allow-holdout (the single pre-registered look; same guard as round 2).

Train registration: a train run that is the single declared run of its cell (Tier 1, slippage 1.0, lots 10, not
capital mode, no cut registered yet) writes one cut 'ROUND3_train|<cell>' (kind train, one-sided non-overlapping t
p-value on per-lot net P&L) into --registry at run time. A changed p for a registered cell is refused.

EXTRA_LOOKS: any other run (test or holdout phase, sensitivity slippage, capital mode, repeated train run) appends an
entry to --extra-looks BEFORE any trade is generated. Test and holdout runs write trade and skip tables only; verdicts
and holdout ledger rows are written later by strategy_eval.

Market inputs come from the repo cache only (scripts/run_chain_backtest.load_market, MARKET_DATA_CACHE_ONLY=1).
Archive: --archive-dir, default $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive. Read-only input.

Example (train, Tier 1, declared run of every cell):
    python scripts/run_round3.py --phase train --cell all --out <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import pandas as pd  # noqa: E402

import run_candidates as _rc  # noqa: E402  (same loader and expectancy helper as the round-1 and round-2 runners)
from backtester.candidates import (  # noqa: E402
    CANDIDATE_SKIP_REASONS, PHASE_WINDOWS, ROUND3_CELL_IDS, CandidateSpec, get_round3_cell, harness_record,
)
from backtester.chain_engine import ChainBacktest, ChainConfig  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402
from strategy_eval import TestRegistry, load_trades  # noqa: E402
from strategy_eval.stats import nonoverlap_ttest  # noqa: E402
from strategy_eval.stress import per_lot  # noqa: E402

DEFAULT_MARKET_START = _rc.DEFAULT_MARKET_START
PASS_SLIPPAGE = 1.0
TIER1_LOTS = 10
TIER2_LOTS = 1
TIER2_CAPITAL_RS = 2_500_000.0     # Rs 25 lakh (Section 4)
TIER2_RISK_CAP_PCT = 0.05
TIER2_MARGIN_CAP_PCT = 0.20
TIER2_KILL_DD_PCT = 0.20
TRAIN_CUT_PREFIX = "ROUND3_train|"
DEFAULT_REGISTRY = REPO_ROOT / "logs" / "eval_registry.json"
DEFAULT_EXTRA_LOOKS = REPO_ROOT / "logs" / "round3" / "EXTRA_LOOKS.md"
EXTRA_LOOKS_HEADER = (
    "# Round 3: runs that are not the single declared train run (logged before running)\n\n"
    "Written by scripts/run_round3.py. Each entry is appended before any trade is generated. These are looks at\n"
    "test or holdout P&L, sensitivity runs, capital-mode runs or repeated train runs; they count in the bookkeeping.\n"
)


def cut_name(cell: str) -> str:
    return f"{TRAIN_CUT_PREFIX}{cell}"


def is_declared_train_run(*, phase: str, lots: int, slippage: float, capital_mode: bool, cut_exists: bool) -> bool:
    """True only for the single declared train run of a cell: Tier 1, pass slippage, no earlier cut."""
    return (phase == "train" and lots == TIER1_LOTS and slippage == PASS_SLIPPAGE
            and not capital_mode and not cut_exists)


def load_market(end: date, market_start: date = DEFAULT_MARKET_START) -> pd.DataFrame:
    return _rc.load_market(end, market_start)


def build_config(spec: CandidateSpec, start: date, end: date, *, lots, slippage: float,
                 capital_mode: bool, capital_rs: float = TIER2_CAPITAL_RS) -> ChainConfig:
    """ChainConfig for one round-3 cell with the fixed round-3 settings (Sections 2 and 4)."""
    if lots is None:
        lots = TIER2_LOTS if capital_mode else TIER1_LOTS
    cfg = ChainConfig(slippage_multiplier=slippage, lots=lots, start=start, end=end, candidate=spec,
                      cash_settlement=True, legacy_costs=False, max_concurrent=1, signal_cadence="expiry_day",
                      skip_zero_contract_legs=True, expiry_brokerage=True)
    if capital_mode:
        cfg = replace(cfg, capital_mode=True, capital_rs=capital_rs, risk_cap_pct=TIER2_RISK_CAP_PCT,
                      margin_cap_pct=TIER2_MARGIN_CAP_PCT, kill_dd_pct=TIER2_KILL_DD_PCT,
                      equity_based_sizing=True)
    return cfg


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", default="all", choices=["all", *ROUND3_CELL_IDS],
                    help="a round-3 cell, or 'all' (default %(default)s); the combiner is not a cell")
    ap.add_argument("--phase", choices=["train", "test", "holdout"], required=True)
    ap.add_argument("--allow-holdout", action="store_true",
                    help="required for --phase holdout (the single pre-registered look)")
    ap.add_argument("--lots", type=int, default=None,
                    help="lots per trade: 10 for Tier 1 (default), 1 for --capital-mode")
    ap.add_argument("--slippage", type=float, default=PASS_SLIPPAGE,
                    help="slippage multiplier (pass bar 1.0; default %(default)s)")
    ap.add_argument("--capital-mode", action="store_true",
                    help="Tier 2: size each trade from Rs 25L equity (requires --lots 1)")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--archive-dir", type=str, default=None,
                    help="NSE F&O daily archive directory (default: $NSE_FO_ARCHIVE_DIR or ~/nse_fo_archive)")
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                    help="registry JSON for train cuts (default %(default)s)")
    ap.add_argument("--extra-looks", type=Path, default=DEFAULT_EXTRA_LOOKS,
                    help="EXTRA_LOOKS log, appended before any non-declared run (default %(default)s)")
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


def register_train_cut(cell: str, trades_file: Path, registry_path: Path, *, start: date, end: date,
                       lots: int, slippage: float) -> dict:
    """Write the train cut for one cell into the registry through strategy_eval.TestRegistry.add (kind 'train').

    Validates the trades file first (train phase, window, lots, slippage); a refusal writes nothing. The p-value is the
    one-sided non-overlapping t-test on per-lot net P&L (the statistic C5 uses). A changed p for an already registered
    cut raises ValueError from TestRegistry.add before anything is written.
    """
    path = Path(trades_file)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("phase") != "train" or obj.get("start") != str(start) or obj.get("end") != str(end):
        raise ValueError(f"{path}: not a train-window file (phase={obj.get('phase')}, "
                         f"{obj.get('start')}..{obj.get('end')})")
    if int(obj.get("lots", -1)) != lots or float(obj.get("slippage_multiplier", -1)) != float(slippage):
        raise ValueError(f"{path}: expected lots={lots} at {slippage:g}x, found lots={obj.get('lots')} "
                         f"slippage={obj.get('slippage_multiplier')}")
    trades = obj.get("trades", [])
    n = len(trades)
    expectancy = float(sum(float(t["pnl_net_rs"]) / int(t["lots"]) for t in trades) / n) if n else float("nan")
    p = None
    if n >= 2:
        df = load_trades(path, name=cut_name(cell))
        p = nonoverlap_ttest(per_lot(df, "pnl_net_rs"), df["entry_date"], df["exit_date"]).get("p_one_sided")
    detail = (f"{cell} train {start}..{end} lots={lots} {slippage:g}x n={n} "
              f"expectancy={expectancy:+.1f} Rs/lot. Registered at run time (single declared train run).")
    reg = TestRegistry.load(registry_path)
    rec = reg.add(cut_name(cell), p, kind="train", detail=detail)
    return {"name": cut_name(cell), "p_value": rec["p_value"], "n": n, "expectancy": expectancy}


def write_extra_look(path: Path, *, cells: list, phase: str, lots: int, slippage: float, capital_mode: bool,
                     window: str, command: str) -> None:
    """Append one EXTRA_LOOKS entry. Called before any trade is generated for these cells."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    stamp = datetime.now().isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write(EXTRA_LOOKS_HEADER)
        f.write(f"\n## {stamp} phase={phase} cells={','.join(cells)}\n"
                f"- window: {window}\n"
                f"- lots={lots} slippage={slippage:g}x capital_mode={capital_mode}\n"
                "- reason: not the single declared train run (test or holdout phase, sensitivity slippage, "
                "capital mode, or a repeated train run)\n"
                f"- command: {command}\n"
                "- written before any trade is generated for these cells\n")


def format_skip_table(table: dict) -> str:
    """Skip-reason table: rows are reasons with a non-zero count in any cell, columns are cells."""
    cells = list(table)
    reasons = [r for r in CANDIDATE_SKIP_REASONS if any(table[c].get(r, 0) for c in cells)]
    reasons += sorted({r for c in cells for r in table[c] if r not in CANDIDATE_SKIP_REASONS and table[c][r]})
    if not reasons:
        return "skip reasons: none"
    lines = ["skip reasons (signals that did not open a trade)",
             f"{'reason':<22}" + "".join(f"{c:>8}" for c in cells)]
    for r in reasons:
        lines.append(f"{r:<22}" + "".join(f"{table[c].get(r, 0):>8}" for c in cells))
    return "\n".join(lines)


def main(argv=None) -> int:
    a = parse_args(argv)
    cell_ids = list(ROUND3_CELL_IDS) if a.cell == "all" else [a.cell]
    cells = [get_round3_cell(c) for c in cell_ids]
    lots = a.lots if a.lots is not None else (TIER2_LOTS if a.capital_mode else TIER1_LOTS)
    start, end = PHASE_WINDOWS[a.phase]

    existing = set()
    if a.phase == "train":
        existing = {c["name"] for c in TestRegistry.load(a.registry).to_dict()["cuts"]}
    declared = {c: is_declared_train_run(phase=a.phase, lots=lots, slippage=a.slippage, capital_mode=a.capital_mode,
                                         cut_exists=cut_name(c) in existing) for c in cell_ids}

    # EXTRA_LOOKS is written before any market or archive read, and before any trade is generated.
    extra = [c for c in cell_ids if not declared[c]]
    if extra:
        window = f"{start}..{end}" if end is not None else f"{start}..(last archive day, resolved at the look)"
        command = " ".join(["scripts/run_round3.py", *(argv if argv is not None else sys.argv[1:])])
        write_extra_look(a.extra_looks, cells=extra, phase=a.phase, lots=lots, slippage=a.slippage,
                         capital_mode=a.capital_mode, window=window, command=command)
        print(f"EXTRA_LOOKS: {len(extra)} cell(s) logged in {a.extra_looks} before running")

    if end is None:  # holdout: end = last settlement date in the archive at the time of the look
        end = NseFoArchive(archive_dir=a.archive_dir).trading_days()[-1]
        print(f"holdout end (last archive trading day, recorded at the look): {end}")

    market = load_market(end, DEFAULT_MARKET_START)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=end)

    a.out.mkdir(parents=True, exist_ok=True)
    print(f"round 3 phase {a.phase} window {start}..{end} lots={lots} slippage={a.slippage} "
          f"capital_mode={a.capital_mode} cells={cell_ids} (combiner not run)")
    skip_table = {}
    for spec in cells:
        cfg = build_config(spec, start, end, lots=lots, slippage=a.slippage, capital_mode=a.capital_mode)
        bt = ChainBacktest(arch, market, cfg)
        trades = [harness_record(t) for t in bt.run()]
        json.dump({"variant": f"round3_{spec.cell_id}_{a.phase}", "family": spec.family, "phase": a.phase,
                   "start": str(start), "end": str(end), "lots": lots,
                   "slippage_multiplier": a.slippage, "n": len(trades), "trades": trades},
                  open(a.out / f"trades_{spec.cell_id}.json", "w"), indent=1, default=str)
        pd.DataFrame(sorted(bt.skips.items()), columns=["reason", "count"]).to_csv(
            a.out / f"skips_{spec.cell_id}.csv", index=False)
        skip_table[spec.cell_id] = dict(bt.skips)
        print(f"{spec.cell_id}: trades={len(trades)} signal_days={bt.signal_days} "
              f"exp_per_lot(lots={lots})={_rc._expectancy_per_lot(trades)}")
        if a.capital_mode:
            pd.DataFrame([{"date": str(d), "equity": e, "margin_used": m} for d, e, m in bt.capital_curve]).to_csv(
                a.out / f"curve_{spec.cell_id}.csv", index=False)
            summary = bt.capital_summary(echo=False)
            json.dump(summary, open(a.out / f"summary_{spec.cell_id}.json", "w"), indent=1, default=str)
            print(f"  capital: final_equity={summary['final_equity']:.0f} CAGR={summary['cagr_pct']}% "
                  f"MaxDD={summary['max_dd_pct']}% Sharpe(daily)={summary['sharpe_daily_ann']} "
                  f"avg_lots={summary['avg_lots']}")
        if declared[spec.cell_id]:
            try:
                row = register_train_cut(spec.cell_id, a.out / f"trades_{spec.cell_id}.json", a.registry,
                                         start=start, end=end, lots=lots, slippage=a.slippage)
            except ValueError as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 2
            p = "n/a" if row["p_value"] is None else f"{row['p_value']:.4f}"
            print(f"  registered {row['name']} n={row['n']} p_one_sided={p} in {a.registry}")
    print(format_skip_table(skip_table))
    print("ledger rows: written by strategy_eval (holdout_ledger / eval_registry), not by this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
