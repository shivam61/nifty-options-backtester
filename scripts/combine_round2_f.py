#!/usr/bin/env python3
"""Family F (docs/preregistration_round2.md Section 3b): equal-capital combination of two round-2 cells.

Rule (no weights, no other cells): each trade of each leg is kept, with lots and every Rs column scaled by 0.5,
and the two lists are concatenated and sorted by entry date. Per-lot values are unchanged, so the paired
per-lot verdict of F is the equal-weight mix of the two legs' trades. Duplicate entry dates are allowed:
strategy_eval pairs the baseline on the per-date mean.

Capital mode (Tier 2): the two legs are run at Rs 25L each (run_round2.py --capital-mode). The F curve is
0.5 x equity_leg1 + 0.5 x equity_leg2, which is the 50/50 combination of the two Rs 25L curves, starting at Rs 25L.
This implies a daily 50/50 rebalance between the legs. Each leg keeps its own kill switch.

Usage:
    python scripts/combine_round2_f.py trades A.json B.json --out F_trades.json
    python scripts/combine_round2_f.py curves A_curve.csv B_curve.csv --out F_curve.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

RS_COLS = ("credit_rs", "max_loss_rs", "pnl_gross_rs", "cost_rs", "pnl_net_rs", "slippage_rs", "hedge_cost_rs")
WEIGHT = 0.5


def combine_trades(a: dict, b: dict) -> dict:
    trades = []
    for leg in (a, b):
        for t in leg["trades"]:
            r = dict(t)
            r["lots"] = t["lots"] * WEIGHT
            for c in RS_COLS:
                if c in r and r[c] is not None:
                    r[c] = r[c] * WEIGHT
            r["family"] = "F"
            trades.append(r)
    trades.sort(key=lambda r: (str(r["entry_date"]), str(r["strategy"])))
    return {"variant": "round2_F_test", "family": "F", "phase": a.get("phase"), "start": a.get("start"),
            "end": a.get("end"), "lots": a.get("lots"), "slippage_multiplier": a.get("slippage_multiplier"),
            "legs": [a.get("variant"), b.get("variant")], "weight_per_leg": WEIGHT,
            "n": len(trades), "trades": trades}


def combine_curves(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    m = a[["date", "equity"]].merge(b[["date", "equity"]], on="date", suffixes=("_a", "_b"), how="outer").sort_values("date")
    m = m.ffill().dropna()
    m["equity"] = WEIGHT * m["equity_a"] + WEIGHT * m["equity_b"]
    return m[["date", "equity"]].reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["trades", "curves"])
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    x = ap.parse_args(argv)
    if x.kind == "trades":
        out = combine_trades(json.loads(x.a.read_text(encoding="utf-8")), json.loads(x.b.read_text(encoding="utf-8")))
        x.out.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print(f"F trades: n={out['n']} (legs {out['legs']}) -> {x.out}")
    else:
        out = combine_curves(pd.read_csv(x.a), pd.read_csv(x.b))
        out.to_csv(x.out, index=False)
        print(f"F curve: {len(out)} sessions, final equity {out['equity'].iloc[-1]:.0f} -> {x.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
