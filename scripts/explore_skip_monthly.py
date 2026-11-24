#!/usr/bin/env python3
"""DESCRIPTIVE screen (NOT a verdict, no registry writes, dev window only): skip weekly entries whose target
expiry is the monthly expiry, or whose holding period [fill, expiry) contains a monthly expiry.

Done POST-HOC: candidate_entry_filter sees only the signal-day market row and the target expiry is chosen at fill,
so the filter cannot be expressed there without editing backtester/. Each baseline trade is tagged with its
expiry and monthly flags; the variant drops the tagged trades. Caveat: a real filter would free max_concurrent
slots and could change later entries (small effect: weekly holds end by the next expiry day).

    python scripts/explore_skip_monthly.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run_round3 as r3  # noqa: E402
from random_entry_null import mean_zero_bootstrap  # noqa: E402
from backtester.candidates import PCS, IRON_CONDOR, CandidateSpec  # noqa: E402
from backtester.chain_engine import ChainBacktest  # noqa: E402
from data.nse_fo_archive import NseFoArchive  # noqa: E402

START, END = date(2019, 2, 11), date(2023, 12, 31)   # dev window only; holdout never read
LOTS = 10
SLIPS = (1.0, 0.3)
OUT = REPO_ROOT / "logs" / "explore" / "skip_monthly"

SPECS = {
    "PCS": CandidateSpec("X_PCS", "X", PCS, 1.0, 300.0, "weekly", 13.0, 25.0),
    "IC": CandidateSpec("X_IC", "X", IRON_CONDOR, 1.0, 400.0, "weekly", 13.0, 25.0),
}


def summ(pl):
    pl = np.asarray(pl, float)
    if pl.size == 0:
        return {"n": 0, "rs_per_lot": None, "win": None}
    return {"n": int(pl.size), "rs_per_lot": float(pl.mean()), "win": float((pl > 0).mean())}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    market = r3.load_market(END)
    fb = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(index_fallback=fb, max_date=END)
    all_exp = sorted({e for v in arch._expiries_by_day.values() for e in v})
    last = {}
    for e in all_exp:
        last[(e.year, e.month)] = max(last.get((e.year, e.month), e), e)
    monthly = set(last.values())

    results, csv_rows = [], []
    for name, spec in SPECS.items():
        for slip in SLIPS:
            cfg = r3.build_config(spec, START, END, lots=LOTS, slippage=slip, capital_mode=False)
            trades = ChainBacktest(arch, market, cfg).run()
            df = pd.DataFrame(trades)
            df["pl"] = df["pnl"] / df["lots"]
            df["entry_date"] = pd.to_datetime(df["entry_date"])
            df["exp"] = pd.to_datetime(df["expiry"]).dt.date
            df["fill"] = df["entry_date"].dt.date
            df["target_monthly"] = df["exp"].isin(monthly)
            df["crosses_monthly"] = [any(f <= m < e for m in monthly) for f, e in zip(df["fill"], df["exp"])]
            df["excluded"] = df["target_monthly"] | df["crosses_monthly"]
            df["year"] = df["entry_date"].dt.year
            kept, exc = df[~df["excluded"]], df[df["excluded"]]
            cell = {
                "struct": name, "slippage": slip, "lots": LOTS,
                "baseline": summ(df["pl"]), "variant_kept": summ(kept["pl"]), "excluded": summ(exc["pl"]),
                "n_target_monthly": int(df["target_monthly"].sum()),
                "n_crosses_only": int((df["crosses_monthly"] & ~df["target_monthly"]).sum()),
                "by_year": {},
            }
            for y, g in df.groupby("year"):
                k = g[~g["excluded"]]
                cell["by_year"][int(y)] = {"base": summ(g["pl"]), "variant": summ(k["pl"]),
                                           "excluded": summ(g.loc[g["excluded"], "pl"])}
            if len(kept) >= 2:
                b = mean_zero_bootstrap(kept["pl"].to_numpy())
                cell["variant_boot_p_one_sided"] = b["p_one_sided"]
            if len(df) >= 2:
                cell["baseline_boot_p_one_sided"] = mean_zero_bootstrap(df["pl"].to_numpy())["p_one_sided"]
            results.append(cell)
            for y, v in cell["by_year"].items():
                for arm in ("base", "variant", "excluded"):
                    csv_rows.append({"struct": name, "slippage": slip, "year": y, "arm": arm, **v[arm]})
            df.drop(columns=["legs"], errors="ignore").to_csv(OUT / f"trades_{name}_{slip}.csv", index=False)
            print(json.dumps({k: v for k, v in cell.items() if k != "by_year"}, default=str), flush=True)
    json.dump(results, open(OUT / "summary.json", "w"), indent=1, default=str)
    pd.DataFrame(csv_rows).to_csv(OUT / "by_year.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
