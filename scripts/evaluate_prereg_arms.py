#!/usr/bin/env python3
"""Apply the pre-registered pass rule to chain-backtest arms (development window only).

Input: one directory per arm (and one for the baseline), each holding the trades_x<mult>.json
files written by scripts/run_chain_backtest.py. Run every arm with the same --start/--end and
slippage multipliers, including the pass slippage (default 1.5).

Per arm, at the pass slippage:
    beats_baseline     arm expectancy per lot > baseline expectancy per lot
    positive           expectancy > 0
    year_ci_lo_gt_0    year-cluster 95% bootstrap CI lower bound > 0
    year_consistency   positive years >= ceil(0.8 x years present)   ("4 of 5")
Confirmatory pass (family-controlled) additionally needs:
    holm_p < alpha     Holm-adjusted one-sided circular block-bootstrap p-value (H0: mean <= 0)
    cost_gate          if --measured-multiplier is given: measured real/model slippage <= arm's
                       break-even multiplier (linear interpolation of expectancy vs multiplier)
An arm that only trims drawdown while expectancy stays <= 0 fails `positive`.

Guard: trades with entry_date after --window-end (default 2023-12-31, the development window)
are dropped and counted. Pass --allow-holdout to include them; that is the single holdout look
and must be justified in the pre-registration, not decided from these results.

Example:
    python scripts/evaluate_prereg_arms.py --baseline out/base \
        --arm P2_H1=out/h1 --arm P2_H2=out/h2 --out out/prereg_eval.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_chain_trades as act  # noqa: E402

DEV_END = "2023-12-31"
PASS_SLIPPAGE = 1.5
ALPHA = 0.05
YEAR_SHARE = 0.8
BLOCK_LEN = 8
N_BOOT = 10_000
SEED_BLOCK = 20261022
_TRADES_RE = re.compile(r"^trades_x([0-9]+(?:\.[0-9]+)?)\.json$")


def load_arm(path: Path, window_end: Optional[str]) -> tuple[dict[float, pd.DataFrame], int]:
    """{slippage multiplier: trades in window}, and the number of trades dropped after window_end."""
    out: dict[float, pd.DataFrame] = {}
    dropped = 0
    for f in sorted(Path(path).glob("trades_x*.json")):
        m = _TRADES_RE.match(f.name)
        if not m:
            continue
        df = pd.DataFrame(json.load(open(f))["trades"])
        if df.empty:
            out[float(m.group(1))] = df
            continue
        df["ppl"] = df["pnl_per_lot"].astype(float)
        df["entry_date"] = df["entry_date"].astype(str).str[:10]
        df["year"] = df["entry_date"].str[:4].astype(int)
        if window_end:
            keep = df["entry_date"] <= window_end
            dropped = max(dropped, int((~keep).sum()))  # same trades recur in every slippage file
            df = df[keep]
        out[float(m.group(1))] = df.sort_values("entry_date", kind="mergesort").reset_index(drop=True)
    if not out:
        raise SystemExit(f"no trades_x<mult>.json files in {path}")
    return out, dropped


def block_bootstrap(x: np.ndarray, block: int = BLOCK_LEN, n_boot: int = N_BOOT,
                    seed: int = SEED_BLOCK) -> tuple[float, float, float]:
    """Circular block bootstrap of the mean: (ci_lo, ci_hi, one-sided p for mean <= 0)."""
    n = len(x)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    b = min(block, n)
    n_blocks = math.ceil(n / b)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_boot, n_blocks))
    idx = ((starts[:, :, None] + np.arange(b)[None, None, :]) % n).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    p = (int((means <= 0).sum()) + 1) / (n_boot + 1)
    return float(lo), float(hi), float(p)


def break_even(exp_by_mult: dict[float, float]) -> tuple[Optional[float], str]:
    """Slippage multiplier where expectancy crosses zero, by linear interpolation."""
    pts = sorted(exp_by_mult.items())
    if len(pts) < 2:
        return None, "needs_two_multipliers"
    if all(e > 0 for _, e in pts):
        return None, "above_range"
    if all(e <= 0 for _, e in pts):
        return None, "below_range"
    for (m0, e0), (m1, e1) in zip(pts, pts[1:]):
        if e0 > 0 >= e1:
            return float(m0 + (m1 - m0) * e0 / (e0 - e1)), "interpolated"
    return None, "non_monotone"


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj: dict[str, float] = {}
    running = 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adj[k] = running
    return adj


def evaluate(baseline: dict[float, pd.DataFrame], arms: dict[str, dict[float, pd.DataFrame]],
             pass_slippage: float = PASS_SLIPPAGE, alpha: float = ALPHA,
             measured_multiplier: Optional[float] = None) -> dict:
    if pass_slippage not in baseline:
        raise SystemExit(f"baseline has no run at slippage {pass_slippage:g}x (have {sorted(baseline)})")
    base_exp = float(baseline[pass_slippage]["ppl"].mean())
    rows: dict[str, dict] = {}
    for name, runs in arms.items():
        if pass_slippage not in runs:
            raise SystemExit(f"arm {name} has no run at slippage {pass_slippage:g}x (have {sorted(runs)})")
        df = runs[pass_slippage]
        x = df["ppl"].to_numpy(float)
        years = df["year"].to_numpy()
        exp = float(x.mean()) if len(x) else float("nan")
        y_lo, y_hi = act.boot_year_ci(x, years, act.SEED_YEAR)
        b_lo, b_hi, p = block_bootstrap(x)
        year_means = df.groupby("year")["ppl"].mean() if len(df) else pd.Series(dtype=float)
        n_years = int(len(year_means))
        pos_years = int((year_means > 0).sum())
        need_years = math.ceil(YEAR_SHARE * n_years)
        exp_by_mult = {m: float(r["ppl"].mean()) for m, r in runs.items() if len(r)}
        be, be_status = break_even(exp_by_mult)
        checks = {
            "beats_baseline": bool(exp > base_exp),
            "positive": bool(exp > 0),
            "year_ci_lo_gt_0": bool(y_lo > 0),
            "year_consistency": bool(n_years > 0 and pos_years >= need_years),
        }
        rows[name] = {
            "n": int(len(x)), "exp_per_lot": round(exp, 1), "baseline_exp_per_lot": round(base_exp, 1),
            "exp_by_multiplier": {f"{m:g}": round(e, 1) for m, e in sorted(exp_by_mult.items())},
            "ci95_year": [round(y_lo, 1), round(y_hi, 1)],
            "ci95_block": [round(b_lo, 1), round(b_hi, 1)],
            "p_one_sided": p, "years": n_years, "positive_years": pos_years, "years_needed": need_years,
            "break_even_multiplier": None if be is None else round(be, 2), "break_even_status": be_status,
            "checks": checks, "rule_pass": all(checks.values()),
        }
    adj = holm({k: v["p_one_sided"] for k, v in rows.items()}) if rows else {}
    for k, row in rows.items():
        row["holm_p"] = adj[k]
        row["holm_ok"] = bool(adj[k] < alpha)
        if measured_multiplier is None:
            row["cost_gate"] = "not_evaluated"
            gate_ok = True
        else:
            be, st = row["break_even_multiplier"], row["break_even_status"]
            gate_ok = bool(st == "above_range" or (be is not None and measured_multiplier <= be))
            row["cost_gate"] = "pass" if gate_ok else "fail"
        row["confirmatory_pass"] = bool(row["rule_pass"] and row["holm_ok"] and gate_ok)
    return {"pass_slippage": pass_slippage, "alpha": alpha, "family_size": len(rows),
            "measured_multiplier": measured_multiplier, "arms": rows}


def format_report(res: dict, window_end: Optional[str], dropped: dict[str, int]) -> str:
    L = [f"pre-registered evaluation  pass slippage {res['pass_slippage']:g}x  alpha {res['alpha']}  "
         f"family size {res['family_size']}  window end {window_end or 'NONE (HOLDOUT INCLUDED)'}"]
    if window_end is None:
        L.append("WARNING: holdout trades are included. This is the single holdout look.")
    for name, n in dropped.items():
        if n:
            L.append(f"NOTE: {name}: dropped {n} trades with entry_date after {window_end}")
    for k, r in res["arms"].items():
        L.append("")
        L.append(f"{k}: n={r['n']}  exp/lot={r['exp_per_lot']} (baseline {r['baseline_exp_per_lot']})  "
                 f"year CI {r['ci95_year']}  block CI {r['ci95_block']}")
        L.append(f"   years positive {r['positive_years']}/{r['years']} (need {r['years_needed']})  "
                 f"holm p={r['holm_p']:.4f}  break-even {r['break_even_multiplier']} ({r['break_even_status']})  "
                 f"cost gate {r['cost_gate']}")
        L.append("   checks: " + ", ".join(f"{c}={'Y' if v else 'N'}" for c, v in r["checks"].items()))
        L.append(f"   RULE PASS: {'YES' if r['rule_pass'] else 'NO'}   "
                 f"CONFIRMATORY PASS: {'YES' if r['confirmatory_pass'] else 'NO'}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--arm", action="append", default=[], metavar="NAME=DIR",
                    help="repeatable; one registered hypothesis per arm")
    ap.add_argument("--window-end", default=DEV_END, help="drop entries after this date (default %(default)s)")
    ap.add_argument("--allow-holdout", action="store_true", help="include all dates (the single holdout look)")
    ap.add_argument("--pass-slippage", type=float, default=PASS_SLIPPAGE)
    ap.add_argument("--alpha", type=float, default=ALPHA)
    ap.add_argument("--measured-multiplier", type=float, default=None,
                    help="real/model slippage from scripts/summarize_quote_log.py; enables the cost gate")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if not a.arm:
        ap.error("give at least one --arm NAME=DIR")
    window_end = None if a.allow_holdout else a.window_end

    base, base_dropped = load_arm(a.baseline, window_end)
    arms, dropped = {}, {"baseline": base_dropped}
    for spec in a.arm:
        if "=" not in spec:
            ap.error(f"--arm needs NAME=DIR, got {spec!r}")
        name, d = spec.split("=", 1)
        if name in arms:
            ap.error(f"duplicate arm name {name!r}")
        arms[name], dropped[name] = load_arm(Path(d), window_end)

    res = evaluate(base, arms, a.pass_slippage, a.alpha, a.measured_multiplier)
    res["window_end"] = window_end
    res["dropped_after_window"] = dropped
    print(format_report(res, window_end, dropped))
    if a.out:
        a.out.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
