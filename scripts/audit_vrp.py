#!/usr/bin/env python3
"""Variance-risk-premium audit of NIFTY index options on the local NSE F&O daily archive.

For each expiry cycle, observed at the fill session (the session after a signal day, the same
cadence as backtester/chain_engine.py) the audit compares what the option market priced with
what the index then did:

  weekly  : fill = session after each listed weekly expiry E; target = nearest listed expiry with
            calendar DTE in [min_dte_entry, max_dte_entry] (engine rule, WeeklyBacktestConfig)
  monthly : monthly expiry = last listed expiry of each calendar month. Two entry cadences:
            "dte21"        entry on the session whose DTE to the next monthly is closest to 21
                           (within [18, 24]); one cycle per monthly expiry
            "after_expiry" entry on the session after the prior monthly expiry (literal cadence,
                           DTE to the next monthly is then ~27-31; no DTE window applied)

Per cycle, at the fill session F (spot = repo NIFTY close, VIX = repo India VIX close):
  ATM straddle   K = listed strike nearest spot; straddle = CE price + PE price (archive settle,
                 close fallback where settle is 0; a leg with contracts == 0 and open_int == 0 skips
                 the cycle)
  implied move   straddle / spot
  realised move  |S_T - spot| / spot, S_T = archive expiry index settlement (repo NIFTY close
                 where the archive has none)
  ratio          realised / implied
  straddle P&L   hold-to-expiry short straddle, gross per unit: straddle - |S_T - K|
  OTM            short put and short call at 0.9 SD (the engine's strike rule, PCS put_sd 0.9;
                 snapped to listed strikes with a usable price):
                 premium - max(0, K_p - S_T) and premium - max(0, S_T - K_c), gross per unit

Dev-window guard: the archive is cut at --end when it is loaded (rows after --end are never
indexed). --end later than 2023-12-31 is refused unless --allow-holdout is passed.

Example:
    python scripts/audit_vrp.py --out ~/whatif_work/step0/vrp
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEV_START = date(2019, 2, 11)
DEV_END = date(2023, 12, 31)
DEFAULT_MARKET_START = date(2009, 1, 1)
LOT_SIZE = 65
N_BOOT = 10_000
SEED_CYCLE = 20261022
SEED_YEAR = 20261023
VIX_EDGES = [0.0, 13.0, 16.0, 20.0, 25.0, float("inf")]
VIX_LABELS = ["<13", "13-16", "16-20", "20-25", "25+"]
MIN_DTE, MAX_DTE = 3, 8          # WeeklyBacktestConfig.min_dte_entry / max_dte_entry
MONTH_DTE = (18, 24)
MONTH_DTE_TARGET = 21


class HoldoutRefused(SystemExit):
    pass


def check_window(end: date, allow_holdout: bool) -> None:
    """Refuse any end date after the development window unless explicitly allowed."""
    if end > DEV_END and not allow_holdout:
        raise HoldoutRefused(
            f"refusing --end {end}: later than the development window end {DEV_END}; "
            "pass --allow-holdout only for the pre-registered holdout step")


def bucket(vix: float) -> str:
    return pd.cut(pd.Series([vix]), VIX_EDGES, labels=VIX_LABELS, right=False).astype(str).iloc[0]


def _spot(market: pd.DataFrame, d: date) -> Optional[float]:
    ts = pd.Timestamp(d)
    if ts not in market.index:
        return None
    v = market.loc[ts, "nifty_close"]
    return float(v) if np.isfinite(v) else None


def _vix(market: pd.DataFrame, d: date) -> float:
    ts = pd.Timestamp(d)
    if ts not in market.index:
        return float("nan")
    return float(market.loc[ts, "vix"]) if "vix" in market.columns else float("nan")


def _liquid(row: Optional[dict]) -> bool:
    return row is not None and row["px_src"] >= 0 and np.isfinite(row["px"]) and not (
        row["contracts"] == 0 and row["open_int"] == 0)


def _nearest(strikes: np.ndarray, target: float) -> Optional[float]:
    if strikes.size == 0:
        return None
    dist = np.abs(strikes - target)
    return float(strikes[np.flatnonzero(dist == dist.min())[0]])  # ties: lower strike


def realised_settle(arch, market: pd.DataFrame, expiry: date) -> float:
    idx = arch.expiry_index_value(expiry)
    if np.isfinite(idx):
        return float(idx)
    s = _spot(market, expiry)
    return float("nan") if s is None else s


def _sd_strikes(spot: float, vix: float, dte: int, sd: float = 0.9) -> tuple[float, float]:
    """0.9 SD put and call strikes, the engine's strike rule (strategies.weekly_strategies
    generate_legs: period_vol = VIX/100 / sqrt(252) * sqrt(DTE), strikes rounded to 50)."""
    period_vol = vix / 100.0 / (252 ** 0.5) * (dte ** 0.5)
    sp = round((spot - spot * period_vol * sd) / 50) * 50
    sc = round((spot + spot * period_vol * sd) / 50) * 50
    return float(sp), float(sc)


def measure_cycle(arch, market, cadence: str, fill: date, expiry: date, spot: float, vix: float) -> Optional[dict]:
    """One cycle at fill session `fill` against `expiry`. None if untradeable or not settled."""
    dte = (expiry - fill).days
    if not arch.chain(fill, expiry).shape[0]:
        return None
    strikes_ce = arch.listed_strikes(fill, expiry, "CE")
    strikes_pe = arch.listed_strikes(fill, expiry, "PE")
    k = _nearest(np.intersect1d(strikes_ce, strikes_pe), spot)
    if k is None:
        return None
    ce = arch.row(fill, expiry, k, "CE")
    pe = arch.row(fill, expiry, k, "PE")
    if not (_liquid(ce) and _liquid(pe)):
        return None
    straddle = float(ce["px"]) + float(pe["px"])
    st = realised_settle(arch, market, expiry)
    if not np.isfinite(st):
        return None
    implied = straddle / spot
    realised = abs(st - spot) / spot
    rec = {
        "cadence": cadence, "fill_date": str(fill), "expiry": str(expiry), "dte": dte,
        "year": fill.year, "vix": vix, "vix_bucket": bucket(vix), "spot": spot, "atm_k": k,
        "straddle": straddle, "implied_move": implied, "settle_T": st, "realised_move": realised,
        "ratio": realised / implied if implied > 0 else float("nan"),
        "implied_minus_realised": implied - realised,
        "implied_gt_realised": bool(implied > realised),
        "straddle_pnl_unit": straddle - abs(st - k),
    }
    rec["straddle_pnl_pct"] = rec["straddle_pnl_unit"] / spot * 100
    # OTM: 0.9 SD put and call (engine strike rule), snapped to listed strikes with a usable price
    tp, tc = _sd_strikes(spot, vix, dte, 0.9)
    kp = _nearest(strikes_pe, tp)
    kc = _nearest(strikes_ce, tc)
    pr = arch.row(fill, expiry, kp, "PE") if kp is not None else None
    cr = arch.row(fill, expiry, kc, "CE") if kc is not None else None
    if _liquid(pr) and _liquid(cr):
        pp, pc = float(pr["px"]), float(cr["px"])
        rec.update({
            "put_k": kp, "put_prem": pp, "put_pnl_unit": pp - max(0.0, kp - st),
            "call_k": kc, "call_prem": pc, "call_pnl_unit": pc - max(0.0, st - kc),
        })
        rec["strangle_pnl_unit"] = rec["put_pnl_unit"] + rec["call_pnl_unit"]
    return rec


def weekly_cycles(arch, market, start: date, end: date) -> tuple[list[dict], Counter]:
    skips: Counter = Counter()
    out = []
    days = arch.trading_days()
    pos = {d: i for i, d in enumerate(days)}
    for e in arch.trading_days():
        if e < start or e > end or not arch.expires_on(e):
            continue
        i = pos[e] + 1
        if i >= len(days) or days[i] > end:
            skips["no_fill_session"] += 1
            continue
        fill = days[i]
        spot, vix = _spot(market, fill), _vix(market, fill)
        if spot is None or not np.isfinite(vix):
            skips["no_spot_or_vix"] += 1
            continue
        cands = [x for x in arch.weekly_expiries(fill) if MIN_DTE <= (x - fill).days <= MAX_DTE]
        if not cands:
            skips["no_expiry_in_dte_window"] += 1
            continue
        target = min(cands)
        rec = measure_cycle(arch, market, "weekly", fill, target, spot, vix)
        if rec is None:
            skips["untradeable_or_unsettled"] += 1
            continue
        out.append(rec)
    return out, skips


def monthly_expiries(arch, end: date) -> list[date]:
    listed = [d for d in arch.trading_days() if d <= end and arch.expires_on(d)]
    last: dict[tuple[int, int], date] = {}
    for d in listed:
        last[(d.year, d.month)] = d  # ascending, so the last one per month wins
    return sorted(last.values())


def monthly_cycles(arch, market, start: date, end: date, cadence: str) -> tuple[list[dict], Counter]:
    skips: Counter = Counter()
    out = []
    days = arch.trading_days()
    months = monthly_expiries(arch, end)
    for prev, nxt in zip(months[:-1], months[1:]):
        if nxt < start or nxt > end:
            continue
        if cadence == "after_expiry":
            i = days.index(prev) + 1 if prev in days else None
            if i is None or i >= len(days):
                skips["no_fill_session"] += 1
                continue
            fill = days[i]
        elif cadence == "dte21":
            window = [d for d in days if prev < d <= nxt and MONTH_DTE[0] <= (nxt - d).days <= MONTH_DTE[1]]
            if not window:
                skips["no_entry_in_dte_window"] += 1
                continue
            fill = min(window, key=lambda d: (abs((nxt - d).days - MONTH_DTE_TARGET), d))
        else:
            raise ValueError(cadence)
        if fill > end:
            skips["fill_after_end"] += 1
            continue
        spot, vix = _spot(market, fill), _vix(market, fill)
        if spot is None or not np.isfinite(vix):
            skips["no_spot_or_vix"] += 1
            continue
        rec = measure_cycle(arch, market, f"monthly_{cadence}", fill, nxt, spot, vix)
        if rec is None:
            skips["untradeable_or_unsettled"] += 1
            continue
        out.append(rec)
    return out, skips


def _boot_mean_ci(x: np.ndarray, seed: int) -> tuple[float, float]:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(N_BOOT, len(x)))
    lo, hi = np.percentile(x[idx].mean(axis=1), [2.5, 97.5])
    return float(lo), float(hi)


def _boot_year_ci(x: np.ndarray, years: np.ndarray, seed: int) -> tuple[float, float]:
    m = np.isfinite(x)
    x, years = x[m], years[m]
    uy = np.unique(years)
    if len(uy) < 2:
        return (float("nan"), float("nan"))
    sums = np.array([x[years == y].sum() for y in uy])
    cnts = np.array([(years == y).sum() for y in uy], float)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(uy), size=(N_BOOT, len(uy)))
    lo, hi = np.percentile(sums[picks].sum(axis=1) / cnts[picks].sum(axis=1), [2.5, 97.5])
    return float(lo), float(hi)


def summarise(df: pd.DataFrame, cols: list[str]) -> dict:
    """Means/medians and bootstrap CIs (cycle and year-cluster) of the given per-cycle columns."""
    out = {"n": int(len(df))}
    if df.empty:
        return out
    yrs = df["year"].to_numpy()
    for c in cols:
        x = df[c].to_numpy(float)
        lo_c, hi_c = _boot_mean_ci(x, SEED_CYCLE)
        lo_y, hi_y = _boot_year_ci(x, yrs, SEED_YEAR)
        out[c] = {"mean": float(np.nanmean(x)), "median": float(np.nanmedian(x)),
                  "ci_cycle": [lo_c, hi_c], "ci_year": [lo_y, hi_y], "n": int(np.isfinite(x).sum())}
    return out


def build_report(cycles: pd.DataFrame) -> dict:
    cols_pct = ["implied_move", "realised_move", "implied_minus_realised", "ratio"]
    cols_pnl = ["straddle_pnl_unit", "straddle_pnl_pct"]
    cols_otm = ["put_pnl_unit", "call_pnl_unit", "strangle_pnl_unit"]
    rep: dict = {}
    for cad, g in cycles.groupby("cadence"):
        block = {"overall": summarise(g, cols_pct + cols_pnl + cols_otm)}
        block["share_implied_gt_realised"] = float(g["implied_gt_realised"].mean()) if len(g) else None
        block["share_ratio_below_1"] = float((g["ratio"] < 1).mean()) if len(g) else None
        block["by_vix"] = {b: summarise(gb, cols_pct + cols_pnl + cols_otm)
                           | {"share_implied_gt_realised": float(gb["implied_gt_realised"].mean())}
                           for b, gb in g.groupby("vix_bucket", sort=False)}
        block["by_year"] = {int(y): summarise(gy, cols_pct + cols_pnl + cols_otm)
                            | {"share_implied_gt_realised": float(gy["implied_gt_realised"].mean())}
                            for y, gy in g.groupby("year")}
        rep[cad] = block
    return rep


def run_audit(arch, market: pd.DataFrame, start: date, end: date, cadences=("weekly", "dte21", "after_expiry")):
    market = market.copy()
    market.index = pd.to_datetime(market.index).normalize()
    market = market[market.index <= pd.Timestamp(end)]
    rows, skips = [], {}
    for cad in cadences:
        if cad == "weekly":
            r, s = weekly_cycles(arch, market, start, end)
        else:
            r, s = monthly_cycles(arch, market, start, end, cad)
        rows += r
        skips[cad] = dict(s)
    df = pd.DataFrame(rows)
    if not df.empty:
        assert df["expiry"].max() <= str(end) and df["fill_date"].max() <= str(end)
    return df, skips


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=lambda s: date.fromisoformat(s), default=DEV_START)
    ap.add_argument("--end", type=lambda s: date.fromisoformat(s), default=DEV_END)
    ap.add_argument("--allow-holdout", action="store_true",
                    help="permit --end after 2023-12-31 (only for the pre-registered holdout step)")
    ap.add_argument("--market-start", type=lambda s: date.fromisoformat(s), default=DEFAULT_MARKET_START)
    ap.add_argument("--archive-dir", type=str, default=None)
    ap.add_argument("--out", type=Path, required=True, help="output directory (cycles.csv, report.json)")
    a = ap.parse_args(argv)
    check_window(a.end, a.allow_holdout)
    if a.start > a.end:
        ap.error("--start must not be after --end")

    from scripts.run_chain_backtest import load_market
    from data.nse_fo_archive import NseFoArchive

    market = load_market(a.end, a.market_start)
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}
    arch = NseFoArchive(archive_dir=a.archive_dir, index_fallback=fallback, max_date=a.end)
    cycles, skips = run_audit(arch, market, a.start, a.end)
    a.out.mkdir(parents=True, exist_ok=True)
    cycles.to_csv(a.out / "cycles.csv", index=False)
    rep = build_report(cycles) if not cycles.empty else {}
    json.dump({"start": str(a.start), "end": str(a.end), "skips": skips, "report": rep},
              open(a.out / "report.json", "w"), indent=1, default=float)
    for cad, block in rep.items():
        o = block["overall"]
        print(f"{cad}: n={o['n']} implied={o['implied_move']['mean']*100:.3f}% "
              f"realised={o['realised_move']['mean']*100:.3f}% share(implied>realised)="
              f"{block['share_implied_gt_realised']:.3f} straddle_pnl/unit={o['straddle_pnl_unit']['mean']:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
