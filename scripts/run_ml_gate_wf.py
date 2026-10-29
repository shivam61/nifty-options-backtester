#!/usr/bin/env python3
"""Run the pre-registered ML-gate arms (E / X / EX) on real prices, one continuous window per arm.

Each arm is one run_chain_backtest.py invocation over 2022-01-01..2026-10-16 at lots=10 and
slippage 0.15 / 0.30 / 0.60; the gate picks the walk-forward fold by decision-date year.
Baseline B_t0 is produced by the same script without gates and is skipped when already present.

    nohup python scripts/run_ml_gate_wf.py --fold-root ~/edge_explore/ml_wf \
        --out-root ~/edge_explore/ml_wf/runs > logs/ml_gate_wf.log 2>&1 &
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
THRESHOLDS = ("0.55", "0.50", "0.60")
SLIPPAGE = ("0.15", "0.30", "0.60")


def arm_specs(fold_root: Path) -> dict[str, list[str]]:
    specs: dict[str, list[str]] = {"B_t0": []}
    for t in THRESHOLDS:
        specs[f"E_t{t}"] = ["--entry-gate-model", str(fold_root), "--entry-gate-threshold", t]
    specs["X_t0"] = ["--exit-gate-model", str(fold_root)]
    for t in THRESHOLDS:
        specs[f"EX_t{t}"] = ["--entry-gate-model", str(fold_root), "--entry-gate-threshold", t,
                             "--exit-gate-model", str(fold_root)]
    return specs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fold-root", type=Path, required=True)
    ap.add_argument("--out-root", type=Path, required=True)
    ap.add_argument("--arms", nargs="*", default=None, help="subset of arm names (default: all)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--start", default="2022-01-01")
    ap.add_argument("--end", default="2026-10-16")
    a = ap.parse_args(argv)

    specs = arm_specs(a.fold_root.expanduser())
    names = a.arms or list(specs)
    unknown = [n for n in names if n not in specs]
    if unknown:
        ap.error(f"unknown arms {unknown}; choose from {list(specs)}")
    todo = []
    for n in names:
        out = a.out_root.expanduser() / n
        if (out / "summary.json").exists():
            print(f"skip {n}: {out}/summary.json exists", flush=True)
            continue
        todo.append((n, out))

    running: list[tuple[str, subprocess.Popen]] = []
    failed = []

    def reap(block: bool):
        for item in list(running):
            n, p = item
            rc = p.wait() if block else p.poll()
            if rc is None:
                continue
            running.remove(item)
            print(f"done {n} rc={rc}", flush=True)
            if rc != 0:
                failed.append(n)

    for n, out in todo:
        while len(running) >= a.jobs:
            reap(False)
            if len(running) >= a.jobs:
                running[0][1].wait()
        cmd = [sys.executable, str(REPO / "scripts" / "run_chain_backtest.py"),
               "--start", a.start, "--end", a.end, "--allow-holdout", "--lots", "10",
               "--slippage", *SLIPPAGE, "--out", str(out), *specs[n]]
        out.mkdir(parents=True, exist_ok=True)
        log = open(out / "run.log", "w")
        print("launch", n, flush=True)
        running.append((n, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=REPO)))
    while running:
        reap(True)
    if failed:
        print("FAILED:", failed, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
