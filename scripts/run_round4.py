#!/usr/bin/env python3
"""Round-4 cells G_M1, G_M2, G_M3, G_S1, G_T1, G_R1, G_W1: the round-3 cells plus a leak-free ML exit gate
(docs/preregistration_round4.md, Sections 2, 3 and 6). Structure follows scripts/run_round3.py.

Fixed for round 4: exit model logs/ml_cutoff_2021/exit_model.pkl (resolved from the repo root), trained through
2021-12-31. --exit-model cannot select another model; it exists only to be refused. Any path under data/.cache or
data/.cache_seed is refused, and so is a pickle whose period_metadata.train_end is missing or after 2021-12-31.
--no-gate turns the gate off (gate-off comparison); every --no-gate run is an EXTRA_LOOK.
Gate: ml_gate_adapters.make_exit_gate(path, load_gate_market(end)), default thresholds (prob >= 0.75, pnl < -15%).

Phases: train 2019-02-11..2021-12-31, test 2022-01-01..2023-12-31, holdout 2024-01-01 onward
(--phase holdout requires --allow-holdout).

Declared run: phase train, lots 10, slippage 0.3 (PASS_SLIPPAGE), not capital mode, gate on, no cut registered yet.
It registers cut 'ROUND4_train|<cell>' (kind train) in --registry at run time. Every other run (test, holdout,
slippage 1.0 sensitivity, capital mode, --no-gate, repeated train) is appended to --extra-looks BEFORE any trade is
generated. Output files as round 3 (trades_<cell>.json, skips_<cell>.csv, curve/summary in capital mode); the trades
JSON header also carries "gate" and "n_ml_exits".

Example (declared train run of every cell):
    python scripts/run_round4.py --phase train --cell all --out logs/round4/train
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

import run_candidates as _rc  # noqa: E402
import run_round3 as r3  # noqa: E402
from backtester.candidates import (  # noqa: E402
    PHASE_WINDOWS, ROUND4_CELL_IDS, get_round4_cell, harness_record,
)
from backtester.chain_engine import ML_EXIT_REASON, ChainBacktest  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402
from strategy_eval import TestRegistry, load_trades  # noqa: E402
from strategy_eval.stats import nonoverlap_ttest  # noqa: E402
from strategy_eval.stress import per_lot  # noqa: E402

DEFAULT_MARKET_START = _rc.DEFAULT_MARKET_START
PASS_SLIPPAGE = 0.3
TIER1_LOTS = r3.TIER1_LOTS
TIER2_LOTS = r3.TIER2_LOTS
TRAIN_CUT_PREFIX = "ROUND4_train|"
EXIT_MODEL_PATH = REPO_ROOT / "logs" / "ml_cutoff_2021" / "exit_model.pkl"
MAX_TRAIN_END = date(2021, 12, 31)
FORBIDDEN_MODEL_DIRS = (REPO_ROOT / "data" / ".cache", REPO_ROOT / "data" / ".cache_seed")
DEFAULT_REGISTRY = REPO_ROOT / "logs" / "eval_registry.json"
DEFAULT_EXTRA_LOOKS = REPO_ROOT / "logs" / "round4" / "EXTRA_LOOKS.md"
EXTRA_LOOKS_HEADER = (
    "# Round 4: runs that are not the single declared train run (logged before running)\n\n"
    "Written by scripts/run_round4.py. Each entry is appended before any trade is generated. These are looks at\n"
    "test or holdout P&L, sensitivity runs, capital-mode runs, gate-off runs or repeated train runs; they count in\n"
    "the bookkeeping.\n"
)


def cut_name(cell: str) -> str:
    return f"{TRAIN_CUT_PREFIX}{cell}"


def is_declared_train_run(*, phase: str, lots: int, slippage: float, capital_mode: bool, cut_exists: bool,
                          gate_on: bool = True) -> bool:
    """True only for the single declared train run of a cell: Tier 1, 0.3x, gate on, no earlier cut."""
    return (phase == "train" and lots == TIER1_LOTS and slippage == PASS_SLIPPAGE
            and not capital_mode and gate_on and not cut_exists)


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_exit_model(path) -> Path:
    """Refuse a leaky model path or a pickle trained after 2021-12-31 (or without period metadata); return the path."""
    p = Path(path)
    for root in FORBIDDEN_MODEL_DIRS:
        if _under(p, root):
            raise ValueError(f"refused: exit model {p} is under {root.relative_to(REPO_ROOT)} "
                             "(trained through 2026, leaks into test and holdout)")
    if not p.is_file():
        raise ValueError(f"refused: exit model {p} not found")
    import joblib
    state = joblib.load(p)
    md = state.get("period_metadata") if isinstance(state, dict) else None
    te = md.get("train_end") if isinstance(md, dict) else None
    if not te:
        raise ValueError(f"refused: exit model {p} has no period_metadata.train_end")
    if date.fromisoformat(str(te)[:10]) > MAX_TRAIN_END:
        raise ValueError(f"refused: exit model {p} train_end {te} is after {MAX_TRAIN_END}")
    return p


def build_gate(path, end: date):
    """Exit gate exactly as scripts/utilisation_sweep.py builds it."""
    import ml_gate_adapters as mga
    return mga.make_exit_gate(path, mga.load_gate_market(end))


def load_market(end: date, market_start: date = DEFAULT_MARKET_START) -> pd.DataFrame:
    return _rc.load_market(end, market_start)


def build_config(spec, start: date, end: date, *, lots, slippage: float, capital_mode: bool, exit_gate=None):
    cfg = r3.build_config(spec, start, end, lots=lots, slippage=slippage, capital_mode=capital_mode)
    return replace(cfg, exit_gate=exit_gate) if exit_gate is not None else cfg


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", default="all", choices=["all", *ROUND4_CELL_IDS])
    ap.add_argument("--phase", choices=["train", "test", "holdout"], required=True)
    ap.add_argument("--allow-holdout", action="store_true",
                    help="required for --phase holdout (the single pre-registered look)")
    ap.add_argument("--lots", type=int, default=None, help="10 for Tier 1 (default), 1 for --capital-mode")
    ap.add_argument("--slippage", type=float, default=PASS_SLIPPAGE,
                    help="slippage multiplier (pass bar 0.3; 1.0 is sensitivity; default %(default)s)")
    ap.add_argument("--capital-mode", action="store_true", help="Tier 2: Rs 25L equity sizing (requires --lots 1)")
    ap.add_argument("--no-gate", action="store_true", help="gate off (gate-off comparison); logged as an extra look")
    ap.add_argument("--exit-model", type=Path, default=None,
                    help="not selectable: only the fixed round-4 model is allowed; honoured only with --no-gate (ignored)")
    ap.add_argument("--out", type=Path, required=True, help="output directory")
    ap.add_argument("--archive-dir", type=str, default=None)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    ap.add_argument("--extra-looks", type=Path, default=DEFAULT_EXTRA_LOOKS)
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
    if a.exit_model is not None:
        for root in FORBIDDEN_MODEL_DIRS:
            if _under(a.exit_model, root):
                ap.error(f"--exit-model under {root.relative_to(REPO_ROOT)} is refused (leaky model)")
        if not a.no_gate and a.exit_model.resolve() != EXIT_MODEL_PATH.resolve():
            ap.error("--exit-model is fixed to logs/ml_cutoff_2021/exit_model.pkl; it can only differ with --no-gate")
    return a


def register_train_cut(cell: str, trades_file: Path, registry_path: Path, *, start: date, end: date,
                       lots: int, slippage: float) -> dict:
    """Write the 'ROUND4_train|<cell>' cut (kind train); same validation and p-value as round 3."""
    path = Path(trades_file)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("phase") != "train" or obj.get("start") != str(start) or obj.get("end") != str(end):
        raise ValueError(f"{path}: not a train-window file (phase={obj.get('phase')}, "
                         f"{obj.get('start')}..{obj.get('end')})")
    if int(obj.get("lots", -1)) != lots or float(obj.get("slippage_multiplier", -1)) != float(slippage):
        raise ValueError(f"{path}: expected lots={lots} at {slippage:g}x, found lots={obj.get('lots')} "
                         f"slippage={obj.get('slippage_multiplier')}")
    if obj.get("gate") is not True:
        raise ValueError(f"{path}: train cut requires a gate-on file (gate={obj.get('gate')})")
    trades = obj.get("trades", [])
    n = len(trades)
    expectancy = float(sum(float(t["pnl_net_rs"]) / int(t["lots"]) for t in trades) / n) if n else float("nan")
    p = None
    if n >= 2:
        df = load_trades(path, name=cut_name(cell))
        p = nonoverlap_ttest(per_lot(df, "pnl_net_rs"), df["entry_date"], df["exit_date"]).get("p_one_sided")
    detail = (f"{cell} train {start}..{end} lots={lots} {slippage:g}x gate=on n={n} "
              f"expectancy={expectancy:+.1f} Rs/lot. Registered at run time (single declared train run).")
    reg = TestRegistry.load(registry_path)
    rec = reg.add(cut_name(cell), p, kind="train", detail=detail)
    return {"name": cut_name(cell), "p_value": rec["p_value"], "n": n, "expectancy": expectancy}


def write_extra_look(path: Path, *, cells: list, phase: str, lots: int, slippage: float, capital_mode: bool,
                     gate_on: bool, window: str, command: str) -> None:
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
                f"- lots={lots} slippage={slippage:g}x capital_mode={capital_mode} gate={'on' if gate_on else 'off'}\n"
                "- reason: not the single declared train run (test or holdout phase, sensitivity slippage, "
                "capital mode, gate-off, or a repeated train run)\n"
                f"- command: {command}\n"
                "- written before any trade is generated for these cells\n")


def main(argv=None) -> int:
    a = parse_args(argv)
    cell_ids = list(ROUND4_CELL_IDS) if a.cell == "all" else [a.cell]
    cells = [get_round4_cell(c) for c in cell_ids]
    lots = a.lots if a.lots is not None else (TIER2_LOTS if a.capital_mode else TIER1_LOTS)
    start, end = PHASE_WINDOWS[a.phase]
    gate_on = not a.no_gate

    if gate_on:   # refuse a leaky model before anything is written
        try:
            validate_exit_model(EXIT_MODEL_PATH)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    existing = set()
    if a.phase == "train":
        existing = {c["name"] for c in TestRegistry.load(a.registry).to_dict()["cuts"]}
    declared = {c: is_declared_train_run(phase=a.phase, lots=lots, slippage=a.slippage, capital_mode=a.capital_mode,
                                         cut_exists=cut_name(c) in existing, gate_on=gate_on) for c in cell_ids}

    extra = [c for c in cell_ids if not declared[c]]
    if extra:
        window = f"{start}..{end}" if end is not None else f"{start}..(last archive day, resolved at the look)"
        command = " ".join(["scripts/run_round4.py", *(argv if argv is not None else sys.argv[1:])])
        write_extra_look(a.extra_looks, cells=extra, phase=a.phase, lots=lots, slippage=a.slippage,
                         capital_mode=a.capital_mode, gate_on=gate_on, window=window, command=command)
        print(f"EXTRA_LOOKS: {len(extra)} cell(s) logged in {a.extra_looks} before running")

    if end is None:
        end = NseFoArchive(archive_dir=a.archive_dir).trading_days()[-1]
        print(f"holdout end (last archive trading day, recorded at the look): {end}")

    exit_gate = build_gate(EXIT_MODEL_PATH, end) if gate_on else None
    market = load_market(end, DEFAULT_MARKET_START)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=end)

    a.out.mkdir(parents=True, exist_ok=True)
    print(f"round 4 phase {a.phase} window {start}..{end} lots={lots} slippage={a.slippage} "
          f"capital_mode={a.capital_mode} gate={'on' if gate_on else 'off'} cells={cell_ids}")
    skip_table = {}
    for spec in cells:
        cfg = build_config(spec, start, end, lots=lots, slippage=a.slippage, capital_mode=a.capital_mode,
                           exit_gate=exit_gate)
        bt = ChainBacktest(arch, market, cfg)
        raw = bt.run()
        n_ml = sum(1 for t in raw if t.get("exit_reason") == ML_EXIT_REASON)
        trades = [harness_record(t) for t in raw]
        json.dump({"variant": f"round4_{spec.cell_id}_{a.phase}", "family": spec.family, "phase": a.phase,
                   "start": str(start), "end": str(end), "lots": lots, "slippage_multiplier": a.slippage,
                   "gate": gate_on, "n_ml_exits": n_ml, "n": len(trades), "trades": trades},
                  open(a.out / f"trades_{spec.cell_id}.json", "w"), indent=1, default=str)
        pd.DataFrame(sorted(bt.skips.items()), columns=["reason", "count"]).to_csv(
            a.out / f"skips_{spec.cell_id}.csv", index=False)
        skip_table[spec.cell_id] = dict(bt.skips)
        print(f"{spec.cell_id}: trades={len(trades)} n_ml_exits={n_ml} signal_days={bt.signal_days} "
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
    print(r3.format_skip_table(skip_table))
    print("ledger rows: written by strategy_eval (holdout_ledger / eval_registry), not by this script")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
