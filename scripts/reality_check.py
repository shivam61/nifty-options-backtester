#!/usr/bin/env python3
"""Search-level multiple-testing check over the DESCRIPTIVE screens in logs/explore/ (no new backtests, no 2024+ data,
no registry writes). Every screened cell is a "look"; this asks how much of the best-looking cell survives the search.

Cells. Four screens: skip_monthly (sm), event_skip (ev), vix_trend (vt), short_dte (sd). Each has baseline cell(s)
(per structure and slippage) and variant cells. A variant's benchmark is the baseline of ITS OWN screen with the same
structure and slippage (sd: BASE_k10 at the same slippage). Baselines are looks for the Holm step (vs 0) but are not
variants in the Reality Check (their excess over themselves is 0).

Alignment. Per-lot net P&L is booked on the signal date and placed on a daily calendar axis (first to last signal date
over all cells); days without a trade carry 0 (a skipped trade is "no P&L", so a skip-variant's excess over its
benchmark on a skipped day is minus the benchmark P&L). This is a documented choice, not the only one.

Tests.
  1. Per cell: mean Rs/lot per trade, t-stat per trade, one-sided p (H0: mean <= 0, Student t), Holm-adjusted across
     all cells (Holm step-down; monotone).
  2. White Reality Check and Hansen SPA over the variants' daily excess series d_k = x_k - benchmark_k, stationary
     bootstrap (mean block --block days, default 21 ~ one month, which also covers multi-day overlapping trades).
     RC: V = max_k sqrt(n) mean(d_k), null centred at mean(d_k). SPA: studentised, re-centred (Hansen SPA_c: only
     clearly poor cells keep their negative mean, so they cannot inflate the null). p = share of bootstrap stats >= observed.
  3. Deflated-Sharpe-style haircut (Bailey / Lopez de Prado) for N looks: per-trade Sharpe, SR0 = expected max SR of
     N null looks from the cross-cell SR variance; DSR = prob the cell's true SR exceeds SR0.

Caveats are printed into the JSON: cells are highly correlated (same trades), so effective N < N; trades overlap in
time; only four ideas were screened (the search space is larger than what was logged).

    .venv/Scripts/python.exe scripts/reality_check.py
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPLORE = REPO_ROOT / "logs" / "explore"
OUT = EXPLORE / "reality_check"
SEED = 20261121


# ----------------------------- statistics (pure, testable) -----------------------------
def trade_stats(x) -> dict:
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return {"n": n, "mean": float(x.mean()) if n else 0.0, "t": 0.0, "p_raw": 1.0}
    sd = x.std(ddof=1)
    t = x.mean() / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n": n, "mean": float(x.mean()), "sd": float(sd), "t": float(t),
            "p_raw": float(stats.t.sf(t, n - 1))}


def holm(p) -> np.ndarray:
    """Holm step-down adjusted p-values (monotone, capped at 1)."""
    p = np.asarray(p, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * p[i])
        adj[i] = min(1.0, run)
    return adj


def stationary_indices(n: int, n_boot: int, mean_block: float, rng) -> np.ndarray:
    """(n_boot, n) stationary-bootstrap indices (Politis-Romano), geometric block length."""
    q = 1.0 / mean_block
    idx = np.empty((n_boot, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, n_boot)
    jump = rng.random((n_boot, n)) < q
    new = rng.integers(0, n, (n_boot, n))
    for t in range(1, n):
        idx[:, t] = np.where(jump[:, t], new[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def reality_check(D: np.ndarray, n_boot: int = 5000, mean_block: float = 21.0, seed: int = SEED) -> dict:
    """D: (n_days, K) excess series. Returns White RC and Hansen SPA p-values for the best cell + per-cell mean."""
    D = np.asarray(D, float)
    n, K = D.shape
    rng = np.random.default_rng(seed)
    dbar = D.mean(0)
    idx = stationary_indices(n, n_boot, mean_block, rng)
    boot = np.empty((n_boot, K))
    chunk = 250
    for s in range(0, n_boot, chunk):
        boot[s:s + chunk] = D[idx[s:s + chunk]].mean(1)
    dev = boot - dbar                                  # bootstrap deviations of the mean
    omega = np.sqrt(n) * dev.std(0, ddof=1)            # long-run sd estimate of sqrt(n)*mean
    omega = np.where(omega > 0, omega, np.inf)
    # White RC (non-studentised, centred at dbar)
    v_obs = float(np.sqrt(n) * dbar.max())
    v_star = np.sqrt(n) * dev.max(1)
    p_rc = float((1 + (v_star >= v_obs).sum()) / (n_boot + 1))
    # Hansen SPA (studentised, g-centred)
    t_cell = np.sqrt(n) * dbar / omega
    t_obs = float(max(0.0, t_cell.max()))
    thresh = -np.sqrt(omega ** 2 / n * 2.0 * math.log(math.log(max(n, 3))))
    g = np.where(dbar <= thresh, dbar, 0.0)  # SPA_c: only clearly-poor cells keep their negative mean
    ts = np.sqrt(n) * (boot - dbar + g) / omega
    t_star = np.maximum(0.0, ts.max(1))
    p_spa = float((1 + (t_star >= t_obs).sum()) / (n_boot + 1))
    return {"n_days": n, "K": K, "best_idx": int(np.argmax(t_cell)), "best_idx_by_mean": int(np.argmax(dbar)),
            "dbar": dbar, "t_cell": t_cell, "V_obs": v_obs, "p_rc": p_rc, "T_obs": t_obs, "p_spa": p_spa}


def deflated_sharpe(x, n_looks: int, sr_var: float) -> dict:
    """Per-trade Sharpe of x vs the expected max Sharpe of n_looks null looks (Bailey & Lopez de Prado 2014)."""
    x = np.asarray(x, float)
    n = len(x)
    sd = x.std(ddof=1)
    sr = x.mean() / sd if sd > 0 else 0.0
    emc = 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - emc) * stats.norm.ppf(1 - 1.0 / n_looks)
                               + emc * stats.norm.ppf(1 - 1.0 / (n_looks * math.e)))
    sk = float(stats.skew(x))
    ku = float(stats.kurtosis(x, fisher=False))
    denom = 1 - sk * sr + (ku - 1) / 4.0 * sr ** 2
    z = (sr - sr0) * math.sqrt(n - 1) / math.sqrt(denom) if denom > 0 else 0.0
    return {"sr": float(sr), "sr0": float(sr0), "haircut": float(sr - sr0), "dsr": float(stats.norm.cdf(z))}


# ----------------------------- loading -----------------------------
def _series(df: pd.DataFrame, date_col: str, val_col: str) -> pd.Series:
    s = pd.Series(df[val_col].to_numpy(float), index=pd.to_datetime(df[date_col]))
    return s.groupby(level=0).sum()


def load_cells(explore: Path = EXPLORE) -> list[dict]:
    cells = []

    def add(name, screen, bench, s):
        cells.append({"name": name, "screen": screen, "bench": bench, "pl": s})

    for struct in ("PCS", "IC"):
        for sl in ("1.0", "0.3"):
            lab = "1x" if sl == "1.0" else "0.3x"
            df = pd.read_csv(explore / "skip_monthly" / f"trades_{struct}_{sl}.csv")
            b = f"sm|{struct}|{lab}|base"
            add(b, "sm", None, _series(df, "signal_date", "pnl_per_lot"))
            add(f"sm|{struct}|{lab}|skip_monthly_target", "sm", b,
                _series(df[~df["excluded"].astype(bool)], "signal_date", "pnl_per_lot"))
            df = pd.read_csv(explore / "event_skip" / f"baseline_trades_{struct}_{lab}.csv")
            b = f"ev|{struct}|{lab}|base"
            add(b, "ev", None, _series(df, "signal_date", "pnl_lot"))
            add(f"ev|{struct}|{lab}|event_skip", "ev", b,
                _series(df[~df["event"].astype(bool)], "signal_date", "pnl_lot"))
            b = f"vt|{struct}|{lab}|baseline"
            for v in ("baseline", "falling_N1", "falling_N5", "rising_N1", "rising_N5"):
                tr = json.load(open(explore / "vix_trend" / f"trades_{struct}_{lab}_{v}.json"))
                s = _series(pd.DataFrame(tr), "signal_date", "pnl_per_lot")
                add(f"vt|{struct}|{lab}|{v}", "vt", None if v == "baseline" else b, s)
    for cell in ("BASE_k10", "SD_k10", "SD_k13"):
        for sl in ("1", "0.3"):
            d = json.load(open(explore / "short_dte" / f"trades_{cell}_s{sl}.json"))
            df = pd.DataFrame(d["trades"])
            df["pl"] = df["pnl_net_rs"] / df["lots"]
            lab = "1x" if sl == "1" else "0.3x"
            add(f"sd|{cell}|{lab}", "sd", None if cell == "BASE_k10" else f"sd|BASE_k10|{lab}",
                _series(df, "signal_date", "pl"))
    return cells


def align(cells: list[dict]) -> pd.DataFrame:
    lo = min(c["pl"].index.min() for c in cells)
    hi = max(c["pl"].index.max() for c in cells)
    ix = pd.date_range(lo, hi, freq="D")
    return pd.DataFrame({c["name"]: c["pl"].reindex(ix).fillna(0.0) for c in cells})


# ----------------------------- main -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-boot", type=int, default=5000)
    ap.add_argument("--block", type=float, default=21.0)
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()

    cells = load_cells()
    X = align(cells)
    N = len(cells)
    rows = []
    for c in cells:
        st = trade_stats(c["pl"].to_numpy())
        rows.append({"cell": c["name"], "screen": c["screen"], "bench": c["bench"], **st})
    df = pd.DataFrame(rows)
    df["p_holm"] = holm(df["p_raw"].to_numpy())
    srs = (df["mean"] / df["sd"]).to_numpy()
    sr_var = float(np.var(srs, ddof=1))
    dsr = [deflated_sharpe(c["pl"].to_numpy(), N, sr_var) for c in cells]
    df["sr"] = [d["sr"] for d in dsr]
    df["sr0"] = [d["sr0"] for d in dsr]
    df["sr_haircut"] = [d["haircut"] for d in dsr]
    df["dsr"] = [d["dsr"] for d in dsr]

    var = [c for c in cells if c["bench"]]
    D = np.column_stack([X[c["name"]].to_numpy() - X[c["bench"]].to_numpy() for c in var])
    rc = reality_check(D, a.n_boot, a.block, a.seed)
    vdf = pd.DataFrame({"cell": [c["name"] for c in var], "bench": [c["bench"] for c in var],
                        "excess_mean_rs_per_day": rc["dbar"], "excess_t_studentised": rc["t_cell"]})
    vdf["excess_per_trade_rs"] = [
        float(D[:, i].sum() / max(len(var[i]["pl"]), 1)) for i in range(len(var))]
    df = df.merge(vdf[["cell", "excess_per_trade_rs", "excess_t_studentised"]], on="cell", how="left")
    df = df.sort_values("p_raw").reset_index(drop=True)

    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "cells.csv", index=False)
    best = var[rc["best_idx"]]["name"]
    summary = {
        "n_cells_total": N, "n_variants": len(var), "n_days": rc["n_days"], "n_boot": a.n_boot,
        "mean_block_days": a.block, "seed": a.seed,
        "best_variant_by_studentised_excess": best,
        "best_variant_by_mean_excess": var[rc["best_idx_by_mean"]]["name"],
        "white_rc_p": rc["p_rc"], "hansen_spa_p": rc["p_spa"],
        "min_holm_p_all_cells": float(df["p_holm"].min()),
        "sr_cross_cell_var": sr_var,
        "caveats": [
            "Cells share trades and dates: highly correlated, so effective N is below N (Holm and DSR are conservative).",
            "Trades overlap in time; block bootstrap on a daily axis (zeros on non-trade days) only partly handles this.",
            "Only 4 ideas were logged; the true search (ideas tried and dropped, parameter choices made earlier) is larger.",
            "Skipped-trade variants are scored as 0 P&L on skipped days; excess vs benchmark is full-sample.",
            "Dev window 2019-2023 only; holdout unread. Descriptive screen, no edge claim.",
        ],
    }
    json.dump({"summary": summary, "cells": json.loads(df.to_json(orient="records"))},
              open(OUT / "reality_check.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
    print(df.head(10)[["cell", "n", "mean", "t", "p_raw", "p_holm", "dsr"]].to_string(index=False))


if __name__ == "__main__":
    main()
