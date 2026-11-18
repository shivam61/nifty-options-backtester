#!/usr/bin/env python3
"""Retroactive registration of the six round-2 TRAIN cells in the strategy_eval registry (audit fix 5).

The round-2 train look ran (docs/preregistration_round2.md, Section 14) without a registry cut being written, so the
six train cuts were missing from logs/eval_registry.json. This script records them through the harness's own API
(strategy_eval.TestRegistry.add) as kind 'train', one cut per cell, named 'ROUND2_train|<cell>'.

What is recorded, per cell, from logs/round2/train_x1/trades_<cell>.json (1.0x slippage, lots=10):
    p_value   one-sided p of the non-overlapping t-test on per-lot net P&L (strategy_eval.stats.nonoverlap_ttest),
              the same statistic the verdict's C5 uses
    detail    window, lots, slippage, n, per-lot expectancy, and the words 'RETROACTIVE REGISTRATION'

This registration is retroactive: the cut is written after the look, not when it ran. The detail says so. Only the
six train cuts are written here. The extra test-window looks that were never registered are recorded as notes in
logs/round2/EXTRA_LOOKS.md, not as cuts. Re-running is a no-op for an identical cut and refuses a changed p.

Usage (the registry path is an argument, so it can be pointed at a scratch file):
    python scripts/register_round2_train.py --registry logs/eval_registry.json
    python scripts/register_round2_train.py --trades-dir logs/round2/train_x1 --registry <scratch.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

from strategy_eval import TestRegistry, load_trades  # noqa: E402
from strategy_eval.stats import nonoverlap_ttest  # noqa: E402
from strategy_eval.stress import per_lot  # noqa: E402

ROUND2_TRAIN_CELLS = ("C1", "C2", "D1", "D2", "E1", "E2")
NAME_PREFIX = "ROUND2_train|"
TRAIN_START = "2019-02-11"
TRAIN_END = "2021-12-31"
TRAIN_LOTS = 10
TRAIN_SLIPPAGE = 1.0
DEFAULT_TRADES_DIR = REPO_ROOT / "logs" / "round2" / "train_x1"
DEFAULT_REGISTRY = REPO_ROOT / "logs" / "eval_registry.json"
RETRO_NOTE = "RETROACTIVE REGISTRATION (recorded 2026-11-18 after the train look; not written at run time)"


def cut_name(cell: str) -> str:
    return f"{NAME_PREFIX}{cell}"


def cell_cut(trades_dir: Path, cell: str) -> dict:
    """Validate one round-2 train trade file and return {name, p_value, detail, n, expectancy}. Raises ValueError."""
    path = Path(trades_dir) / f"trades_{cell}.json"
    if not path.exists():
        raise ValueError(f"missing round-2 train file: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("phase") != "train" or obj.get("start") != TRAIN_START or obj.get("end") != TRAIN_END:
        raise ValueError(f"{path}: not a train-window file (phase={obj.get('phase')}, "
                         f"{obj.get('start')}..{obj.get('end')})")
    if int(obj.get("lots", -1)) != TRAIN_LOTS or float(obj.get("slippage_multiplier", -1)) != TRAIN_SLIPPAGE:
        raise ValueError(f"{path}: expected lots={TRAIN_LOTS} at {TRAIN_SLIPPAGE:g}x, found lots={obj.get('lots')} "
                         f"slippage={obj.get('slippage_multiplier')}")
    df = load_trades(path, name=cut_name(cell))
    n = int(len(df))
    if n and (str(df["entry_date"].min()) < TRAIN_START or str(df["entry_date"].max()) > TRAIN_END):
        raise ValueError(f"{path}: entries outside the train window")
    pl = per_lot(df, "pnl_net_rs")
    expectancy = float(np.mean(pl)) if n else float("nan")
    p = nonoverlap_ttest(pl, df["entry_date"], df["exit_date"]).get("p_one_sided") if n >= 2 else None
    detail = (f"{cell} train {TRAIN_START}..{TRAIN_END} lots={TRAIN_LOTS} {TRAIN_SLIPPAGE:g}x n={n} "
              f"expectancy={expectancy:+.1f} Rs/lot. {RETRO_NOTE}")
    return {"name": cut_name(cell), "p_value": p, "detail": detail, "n": n, "expectancy": expectancy}


def register_round2_train(trades_dir: Path, registry_path: Path) -> list[dict]:
    """Register the six train cuts into registry_path (created if missing). Returns the rows written or confirmed.

    All six files are validated before the registry is opened, so a refusal writes nothing."""
    cuts = [cell_cut(trades_dir, c) for c in ROUND2_TRAIN_CELLS]
    reg = TestRegistry.open(registry_path)
    rows = []
    for c in cuts:
        rec = reg.add(c["name"], c["p_value"], kind="train", detail=c["detail"])
        rows.append({"name": c["name"], "p_value": rec["p_value"], "n": c["n"], "expectancy": c["expectancy"]})
    reg.save()
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades-dir", type=Path, default=DEFAULT_TRADES_DIR,
                    help="directory with trades_<cell>.json for the six train cells (default %(default)s)")
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                    help="registry JSON to write (default %(default)s)")
    a = ap.parse_args(argv)
    try:
        rows = register_round2_train(a.trades_dir, a.registry)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    for r in rows:
        p = "n/a" if r["p_value"] is None else f"{r['p_value']:.4f}"
        print(f"{r['name']}: n={r['n']} expectancy={r['expectancy']:+.1f} Rs/lot p_one_sided={p}")
    print(f"registry: {a.registry} ({len(rows)} train cuts, kind 'train', retroactive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
