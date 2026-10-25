"""Independent MODEL-BASED study of a short ATM weekly straddle with a daily futures delta hedge.

Development window only (2019-02-11..2023-12-31); 2024+ is never used. Black-Scholes at sigma = k x India
VIX, hedged at each close with spot as the futures proxy, whole-lot hedges, explicit costs. It does NOT use
the NSE archive, so it is not real-price evidence. k is calibrated so the mean straddle premium equals the
real-price audit's mean implied move (1.644%, BACKTEST_CHANGELOG 2026-10-21); the realised move then comes
out of the data and is compared with the audit's 1.588%. Placebos: hedge sign flipped, in-sample drift removed.

Run:  python scripts/dh_straddle_model_study.py --out <outdir>     (needs data/.cache; about 1 minute)
"""
import argparse
import importlib.util
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from config import WeeklyBacktestConfig  # noqa: E402
from data.expiry_calendar import get_weekly_expiry_in_range  # noqa: E402
import analyze_chain_trades as act  # noqa: E402
import evaluate_prereg_arms as ev  # noqa: E402

spec = importlib.util.spec_from_file_location("rcb", REPO / "scripts" / "run_chain_backtest.py")
rcb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rcb)

DEV_START, DEV_END = date(2019, 2, 11), date(2023, 12, 31)
LOT, R = 65, 0.065
N_ = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
CM = WeeklyBacktestConfig().cost_model


def straddle(S, K, T, sig):
    d1 = (math.log(S / K) + (R + 0.5 * sig * sig) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    disc = math.exp(-R * T)
    call = S * N_(d1) - K * disc * N_(d2)
    put = K * disc * N_(-d2) - S * N_(-d1)
    return call + put, N_(d1) + (N_(d1) - 1.0)  # price, straddle delta (call + put)


def load_cycles():
    m = rcb.load_market(DEV_END, date(2018, 1, 1))
    m = m[(m.index >= pd.Timestamp("2018-01-01")) & (m.index <= pd.Timestamp(DEV_END))]
    idx = list(m.index)
    pos = {d: i for i, d in enumerate(idx)}
    cycles, i = [], next(j for j, d in enumerate(idx) if d.date() >= DEV_START)
    while i < len(idx):
        f = idx[i]
        res = get_weekly_expiry_in_range(f.date(), 3, 8)
        if not res:
            i += 1
            continue
        T, dte = res
        Tt = pd.Timestamp(T)
        if Tt > idx[-1] or Tt not in pos:
            break
        path = idx[i:pos[Tt] + 1]
        cycles.append({"fill": f, "expiry": Tt, "dte": dte, "path": path})
        i = pos[Tt] + 1
    return m, cycles


def fut_cost_units(qty_change_units, S, half_spread):
    """Rs for trading |qty| units of futures: half-spread, brokerage+GST, exchange fee, STT on sells (avg half)."""
    q = abs(qty_change_units)
    if q == 0:
        return 0.0
    value = q * S
    n_orders = 1
    brokerage = 20.0 * 1.18 * n_orders
    exch = value * 0.0000173 * 1.18
    stt = value * 0.000125 * 0.5          # sell side only, about half of the turnover
    return q * half_spread + brokerage + exch + stt


def opt_fees_rs(prem_unit, units, n_legs=2):
    sold = prem_unit * units
    return 20.0 * 1.18 * n_legs + sold * (0.000625 + 0.000503 * 1.18)


def simulate(m, cycles, k=1.0, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5, hedge_vol_mult=1.0):
    rows = []
    for c in cycles:
        path = c["path"]
        S0, v0 = float(m.loc[path[0], "nifty_close"]), float(m.loc[path[0], "vix"])
        if not np.isfinite(v0) or v0 <= 0:
            continue
        sig = k * v0 / 100.0
        Kx = round(S0 / 50.0) * 50.0
        Tn = path[-1]
        T0 = (Tn - path[0]).days / 365.0
        P0, _ = straddle(S0, Kx, T0, sig)
        slip = CM.slippage_per_unit(v0, 1.0) * slip_mult * 2           # two legs, sold
        units = n_lots * LOT
        pnl_prem = (P0 - slip) * units
        costs = opt_fees_rs(P0 - slip, units)
        fut_pnl, q_prev = 0.0, 0.0
        sig_h = sig * hedge_vol_mult
        for j, d in enumerate(path[:-1]):
            S = float(m.loc[d, "nifty_close"])
            if j > 0:
                fut_pnl += q_prev * (S - float(m.loc[path[j - 1], "nifty_close"]))
            if hedge == "daily":
                Tj = (Tn - d).days / 365.0
                _, dl = straddle(S, Kx, Tj, sig_h)
                q = round(n_lots * dl) * LOT       # short straddle delta is -dl, so hedge long +dl (whole lots)
            else:
                q = 0.0
            costs += fut_cost_units(q - q_prev, S, fut_hs)
            q_prev = q
        ST = float(m.loc[Tn, "nifty_close"])
        fut_pnl += q_prev * (ST - float(m.loc[path[-2], "nifty_close"])) if len(path) > 1 else 0.0
        costs += fut_cost_units(q_prev, ST, fut_hs)                        # flatten at expiry
        payoff = -(max(ST - Kx, 0.0) + max(Kx - ST, 0.0)) * units
        gross = pnl_prem + payoff + fut_pnl
        net = gross - costs
        rows.append({"fill": path[0], "year": path[0].year, "dte": c["dte"], "vix": v0, "S0": S0,
                     "premium_pct": P0 / S0 * 100, "move_pct": abs(ST / S0 - 1) * 100,
                     "net_per_lot": net / n_lots, "gross_per_lot": gross / n_lots,
                     "opt_per_lot": (pnl_prem + payoff) / n_lots, "fut_per_lot": fut_pnl / n_lots,
                     "cost_per_lot": costs / n_lots})
    return pd.DataFrame(rows)


def stats(df, col="net_per_lot"):
    x = df[col].to_numpy(float)
    yl, yh = act.boot_year_ci(x, df["year"].to_numpy(), act.SEED_YEAR)
    bl, bh, p = ev.block_bootstrap(x)
    ym = df.groupby("year")[col].mean()
    dd = np.cumsum(x)
    dd = float((dd - np.maximum.accumulate(np.maximum(dd, 0))).min())
    return {"n": len(x), "mean": round(x.mean(), 1), "sd": round(x.std(ddof=1), 1),
            "median": round(float(np.median(x)), 1), "win%": round((x > 0).mean() * 100, 1),
            "year_ci": [round(yl, 1), round(yh, 1)], "block_ci": [round(bl, 1), round(bh, 1)],
            "p_block_le0": round(p, 4), "pos_years": f"{int((ym > 0).sum())}/{len(ym)}",
            "by_year": {int(y): round(v, 0) for y, v in ym.items()},
            "worst": round(x.min(), 0), "p5": round(float(np.percentile(x, 5)), 0),
            "max_dd": round(dd, 0), "sharpe_wk": round(x.mean() / x.std(ddof=1) * math.sqrt(52), 2)}


def placebo(m, cycles, kcal):
    src = open(__file__).read().replace("q = round(n_lots * dl) * LOT", "q = -round(n_lots * dl) * LOT")
    ns = {"__file__": __file__, "__name__": "placebo_ns"}
    exec(compile(src.split('\nif __name__ == "__main__":')[0], "placebo", "exec"), ns)
    flip = ns["simulate"](m, cycles, k=kcal, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5)
    mu = float(np.log(m["nifty_close"]).diff().mean())
    m2 = m.copy()
    m2["nifty_close"] = m2["nifty_close"] * np.exp(-mu * np.arange(len(m2)))
    dd = simulate(m2, cycles, k=kcal, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5)
    r = m["nifty_close"].pct_change().dropna()
    return {"anti_hedge_fut_mean": round(flip.fut_per_lot.mean(), 1),
            "de_drifted": {"net": round(dd.net_per_lot.mean(), 1), "fut": round(dd.fut_per_lot.mean(), 1),
                           "opt": round(dd.opt_per_lot.mean(), 1)},
            "daily_mean_pct": round(r.mean() * 100, 4), "daily_lag1_autocorr": round(r.autocorr(1), 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    out = {}
    m, cycles = load_cycles()
    out["cycles"] = len(cycles)
    out["last_expiry_used"] = str(max(c["expiry"] for c in cycles).date())
    b = simulate(m, cycles, k=1.0, hedge="none", slip_mult=0.0, fut_hs=0.0)
    out["k1"] = {"premium_pct": round(b.premium_pct.mean(), 3), "move_pct": round(b.move_pct.mean(), 3),
                 "dte": round(b.dte.mean(), 2), "vix": round(b.vix.mean(), 2)}
    # calibrate k so the mean straddle premium equals the real-price audit's mean implied move (1.644%)
    lo, hi = 0.5, 1.5
    for _ in range(40):
        mid = (lo + hi) / 2
        pm = simulate(m, cycles, k=mid, hedge="none", slip_mult=0.0, fut_hs=0.0).premium_pct.mean()
        lo, hi = (mid, hi) if pm < 1.644 else (lo, mid)
    kcal = round((lo + hi) / 2, 3)
    out["k_cal"] = kcal
    out["realised_move_pct_mean"] = round(b.move_pct.mean(), 3)
    out["audit_reported"] = {"implied_move_pct": 1.644, "realised_move_pct": 1.588}

    grid = {}
    def run(tag, **kw):
        df = simulate(m, cycles, **kw)
        grid[tag] = {"net": stats(df), "gross_mean": round(df.gross_per_lot.mean(), 1),
                     "opt_mean": round(df.opt_per_lot.mean(), 1), "fut_mean": round(df.fut_per_lot.mean(), 1),
                     "cost_mean": round(df.cost_per_lot.mean(), 1)}
        return df
    # primary pre-set spec: calibrated k, daily hedge, 10 lots, 1.0x slippage, 0.5 pt futures half-spread
    prim = run("hedged_k_cal_10lots_1.0x", k=kcal, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5)
    run("unhedged_k_cal_1.0x", k=kcal, hedge="none", n_lots=10, slip_mult=1.0)
    for sm in (0.0, 1.5, 2.0):
        run(f"hedged_k_cal_10lots_{sm}x", k=kcal, hedge="daily", n_lots=10, slip_mult=sm, fut_hs=0.5)
    for n in (1, 3, 30):
        run(f"hedged_k_cal_{n}lots_1.0x", k=kcal, hedge="daily", n_lots=n, slip_mult=1.0, fut_hs=0.5)
    for kk in (0.90, 0.95, 1.00, 1.05, 1.10):
        run(f"hedged_k{kk}_10lots_1.0x", k=kk, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5)
    for fh in (0.0, 0.25, 1.0, 2.0):
        run(f"hedged_k_cal_10lots_fut{fh}", k=kcal, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=fh)
    for hv in (0.9, 1.1):
        run(f"hedged_k_cal_10lots_hedgevol{hv}", k=kcal, hedge="daily", n_lots=10, slip_mult=1.0, fut_hs=0.5, hedge_vol_mult=hv)
    out["grid"] = grid
    # worst weeks and VIX-bucket cut for the primary spec
    w = prim.sort_values("net_per_lot").head(6)[["fill", "vix", "move_pct", "net_per_lot", "opt_per_lot", "fut_per_lot"]]
    out["worst6"] = [{"fill": str(r.fill.date()), "vix": round(r.vix, 1), "move%": round(r.move_pct, 2),
                      "net": round(r.net_per_lot), "opt": round(r.opt_per_lot), "fut": round(r.fut_per_lot)} for r in w.itertuples()]
    prim["vb"] = pd.cut(prim.vix, [0, 13, 16, 20, 25, 99], right=False).astype(str)
    out["by_vix"] = {b: {"n": int(len(g)), "mean": round(g.net_per_lot.mean(), 0), "sd": round(g.net_per_lot.std(), 0)}
                     for b, g in prim.groupby("vb")}
    out["split"] = {"train_2019_2021": stats(prim[prim.year <= 2021])["mean"], "test_2022_2023": stats(prim[prim.year >= 2022])["mean"]}
    out["placebo"] = placebo(m, cycles, kcal)
    json.dump(out, open(args.out / "dh_results.json", "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "grid"}, indent=1, default=str))
    for tag, g in grid.items():
        n = g["net"]
        print(f"{tag:<34} net {n['mean']:>8} sd {n['sd']:>7} yrCI {n['year_ci']} blkCI {n['block_ci']} yrs+ {n['pos_years']} "
              f"| gross {g['gross_mean']:>7} opt {g['opt_mean']:>7} fut {g['fut_mean']:>7} cost {g['cost_mean']:>6}")
