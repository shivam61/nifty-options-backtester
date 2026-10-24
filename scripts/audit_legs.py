#!/usr/bin/env python3
"""Per-leg payoff audit of weekly NIFTY option selling, development window only (H1-H3 of
docs/preregistration_edge_search.md).

Cycles are the weekly cycles of scripts/audit_vrp.weekly_cycles, reused unchanged:
  fill   = the session after each listed weekly expiry E (the signal is E's close)
  target = the nearest listed expiry with calendar DTE in [3, 8] from the fill (Thursday weeklies in
           the dev window, so DTE is ~6 and the hold is one week)
  spot   = repo NIFTY close at the fill; VIX = repo India VIX close at the fill (same as audit_vrp)

For every cycle and every distance in SD_GRID (0.5 .. 2.0 SD, the engine's strike rule
audit_vrp._sd_strikes: period vol = VIX/100/sqrt(252)*sqrt(DTE), strikes rounded to 50, snapped to
a listed strike with a usable price by audit_vrp._nearest) the audit prices one short OTM put and one
short OTM call at the fill session. Per unit, gross of costs, hold to the expiry settle:
  put  payoff = premium - max(0, K_put - S_T)
  call payoff = premium - max(0, S_T - K_call)
where S_T is the expiry index settle (audit_vrp.realised_settle). All money in index points per unit
(one unit = one NIFTY index point of option premium); Rs/lot = points x LOT_SIZE (65).

Cuts. The tested family (36) is Holm-corrected together; each tests mean = 0 (or put-minus-call = 0):
  H1  put and call payoff at each SD level (7 + 7), put minus call at each SD level (7)
  H2  put, call and strangle (0.9 SD) by fill-session VIX bucket (5 x 3)
  Descriptive, not tested (3): the tail view. The mean after removing the worst 5% of weeks is
      positive by construction when computed in-sample, so it is reported with its CI but not tested.
  H3  power only: SE, minimum detectable effect at 80% power and 5% two-sided, and weeks needed for
      +8 points per unit. Not a test, not in the Holm family.

Inference: per cut, the mean with a year-cluster bootstrap CI and a moving-block bootstrap CI (4-week
circular blocks, chronological), and two-sided bootstrap p-values under the null of mean 0 from both
resampling schemes. Holm correction runs over all tested cuts, once per p-value family.

Development-window guard. The archive loader parses every daily file under the archive it is given
before it applies max_date, so this script never hands it the real archive. It builds a work
directory of symlinks to the daily files whose filename date is <= --end and points the loader at
that directory. Files after --end are never opened. The repo market cache (NIFTY, VIX) is loaded by
scripts/run_chain_backtest.load_market, which reads the cached full-history parquet and clips to
--end after loading; that is a known exception, see docs/analysis/audit_legs_dev.md.

Example:
    .venv/bin/python -I scripts/audit_legs.py --out /tmp/audit_legs
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import NormalDist
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.audit_vrp as audit  # noqa: E402  (reused helpers; the weekly cycle rule lives there)

DEV_START = audit.DEV_START
DEV_END = audit.DEV_END
LOT_SIZE = audit.LOT_SIZE
N_BOOT = audit.N_BOOT
SD_GRID = (0.5, 0.7, 0.9, 1.1, 1.3, 1.5, 2.0)
ENGINE_SD = 0.9                  # WeeklyPutCreditSpread / strangle rule used by audit_vrp
VIX_LABELS = audit.VIX_LABELS
BLOCK_LEN = 4                    # moving-block length in weeks
TAIL_Q = 0.05                    # worst 5% of weeks
ALPHA = 0.05
POWER = 0.80
TARGET_PTS = 8.0                 # pre-registered effect size for the weeks-needed statement
SEED_YEAR = 20261024
SEED_BLOCK = 20261025
DEFAULT_OUT = Path("/tmp/audit_legs")
DEFAULT_WORK = Path("/tmp/audit_legs/dev_archive")
Z = NormalDist()


class HoldoutRefused(SystemExit):
    pass


def _tag(sd: float) -> str:
    return f"{sd:.1f}"


def dev_archive_view(archive_dir: str, work_dir: Path, end: date) -> tuple[str, int]:
    """Symlink the daily files dated <= end into work_dir/daily and return (work_dir, n_linked).

    Only file names are listed; a file dated after end is never opened or linked. Stale links from a
    previous run with a different --end are removed first. The loader rebuilds its parquet in
    work_dir/_cache when the file count or total size changes."""
    src = Path(archive_dir) / "daily"
    dst = Path(work_dir) / "daily"
    dst.mkdir(parents=True, exist_ok=True)
    for old in dst.glob("*.csv.gz"):
        old.unlink()
    n = 0
    for f in sorted(src.glob("*.csv.gz")):
        stamp = f.name[:8]
        if not stamp.isdigit():
            continue
        d = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        if d > end:
            continue
        (dst / f.name).symlink_to(f.resolve())
        n += 1
    if n == 0:
        raise FileNotFoundError(f"no daily files on or before {end} under {src}")
    return str(work_dir), n


def leg_payoffs(arch, rec: dict, sd_levels=SD_GRID) -> tuple[dict, Counter]:
    """Put and call short-leg premium, strike and payoff at each SD level for one weekly cycle.

    Uses the cycle's fill date, expiry, spot, VIX and settle exactly as audit_vrp.measure_cycle does.
    A leg with no usable price or with contracts == 0 and open_int == 0 is recorded as NaN and counted."""
    fill, expiry = date.fromisoformat(rec["fill_date"]), date.fromisoformat(rec["expiry"])
    spot, vix, st, dte = rec["spot"], rec["vix"], rec["settle_T"], rec["dte"]
    strikes = {"put": arch.listed_strikes(fill, expiry, "PE"), "call": arch.listed_strikes(fill, expiry, "CE")}
    out: dict = {}
    skips: Counter = Counter()
    for sd in sd_levels:
        tg = _tag(sd)
        tp, tc = audit._sd_strikes(spot, vix, dte, sd)
        for side, target, opt in (("put", tp, "PE"), ("call", tc, "CE")):
            k = audit._nearest(strikes[side], target)
            row = arch.row(fill, expiry, k, opt) if k is not None else None
            if not audit._liquid(row):
                skips[f"{side}_{tg}_illiquid"] += 1
                out[f"{side}_k_{tg}"] = np.nan
                out[f"{side}_prem_{tg}"] = np.nan
                out[f"{side}_pnl_{tg}"] = np.nan
                continue
            prem = float(row["px"])
            intrinsic = max(0.0, k - st) if side == "put" else max(0.0, st - k)
            out[f"{side}_k_{tg}"] = float(k)
            out[f"{side}_prem_{tg}"] = prem
            out[f"{side}_pnl_{tg}"] = prem - intrinsic
    return out, skips


def weekly_leg_table(arch, market: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, dict]:
    """One row per weekly cycle (audit_vrp.weekly_cycles selection) with per-leg payoffs at every SD."""
    recs, cyc_skips = audit.weekly_cycles(arch, market, start, end)
    rows = []
    leg_skips: Counter = Counter()
    for rec in recs:
        legs, ls = leg_payoffs(arch, rec, SD_GRID)
        leg_skips.update(ls)
        row = dict(rec)
        row.update(legs)
        row["settle_src"] = "archive" if np.isfinite(arch.expiry_index_value(date.fromisoformat(rec["expiry"]))) \
            else "close_fallback"
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, {"cycle": dict(cyc_skips), "leg": dict(leg_skips)}
    df = df.sort_values("fill_date").reset_index(drop=True)
    for sd in SD_GRID:
        tg = _tag(sd)
        df[f"put_pnl_{tg}"] = df[f"put_pnl_{tg}"].astype(float)
        df[f"call_pnl_{tg}"] = df[f"call_pnl_{tg}"].astype(float)
        df[f"diff_pc_{tg}"] = df[f"put_pnl_{tg}"] - df[f"call_pnl_{tg}"]  # NaN unless both legs priced
    t = _tag(ENGINE_SD)
    df[f"strangle_pnl_{t}"] = df[f"put_pnl_{t}"] + df[f"call_pnl_{t}"]
    assert df["expiry"].max() <= str(end) and df["fill_date"].max() <= str(end)
    return df, {"cycle": dict(cyc_skips), "leg": dict(leg_skips)}


# ---------------------------------------------------------------- statistics

def holm(p: list[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in the input order."""
    m = len(p)
    order = np.argsort(p, kind="stable")
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj.tolist()


def _boot_block(x: np.ndarray, block: int, seed: int) -> tuple[float, float, float, float]:
    """Moving-block (circular, chronological) bootstrap: (ci_lo, ci_hi, p_two_sided, boot_se)."""
    n = len(x)
    if n < 2:
        return (float("nan"),) * 4
    rng = np.random.default_rng(seed)
    nb = -(-n // block)
    starts = rng.integers(0, n, size=(N_BOOT, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(N_BOOT, nb * block)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    xc = x - x.mean()
    p = float(np.mean(np.abs(xc[idx].mean(axis=1)) >= abs(x.mean())))
    return float(lo), float(hi), p, float(means.std(ddof=1))


def _year_p(x: np.ndarray, years: np.ndarray, seed: int) -> float:
    """Two-sided year-cluster bootstrap p-value for mean 0 (centred data, resampled years)."""
    uy = np.unique(years)
    if len(uy) < 2:
        return float("nan")
    xc = x - x.mean()
    sums = np.array([xc[years == y].sum() for y in uy])
    cnts = np.array([(years == y).sum() for y in uy], float)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(uy), size=(N_BOOT, len(uy)))
    stat = sums[picks].sum(axis=1) / cnts[picks].sum(axis=1)
    return float(np.mean(np.abs(stat) >= abs(x.mean())))


def _boot_ratio_year_ci(num: np.ndarray, den: np.ndarray, years: np.ndarray, seed: int) -> tuple[float, float]:
    uy = np.unique(years)
    if len(uy) < 2 or den.sum() == 0:
        return (float("nan"), float("nan"))
    sn = np.array([num[years == y].sum() for y in uy])
    sd_ = np.array([den[years == y].sum() for y in uy])
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(uy), size=(N_BOOT, len(uy)))
    r = sn[picks].sum(axis=1) / sd_[picks].sum(axis=1)
    lo, hi = np.percentile(r, [2.5, 97.5])
    return float(lo), float(hi)


def cut_stats(df: pd.DataFrame, col: str, family: str, name: str, mask: Optional[pd.Series] = None,
              tested: bool = True) -> dict:
    """Mean of one per-cycle column over a subset, with year-cluster and moving-block inference.

    tested=False marks a descriptive cut: it is reported with its CIs but is not in the Holm family."""
    sub = df if mask is None else df.loc[mask]
    sub = sub[np.isfinite(sub[col].to_numpy(float))]
    x = sub[col].to_numpy(float)
    years = sub["year"].to_numpy()
    row = {"family": family, "cut": name, "column": col, "n": int(len(x))}
    if len(x) < 2:
        row.update(mean=float("nan"), tested=False)
        return row
    lo_y, hi_y = audit._boot_year_ci(x, years, SEED_YEAR)
    lo_b, hi_b, p_b, se_b = _boot_block(x, BLOCK_LEN, SEED_BLOCK)
    yr = {int(y): float(x[years == y].mean()) for y in np.unique(years)}
    row.update({
        "mean": float(x.mean()), "median": float(np.median(x)), "sd": float(x.std(ddof=1)),
        "mean_rs_lot": float(x.mean() * LOT_SIZE),
        "ci_year": [lo_y, hi_y], "ci_block": [lo_b, hi_b], "se_block": se_b,
        "p_block": p_b, "p_year": _year_p(x, years, SEED_YEAR),
        "years_positive": int(sum(v > 0 for v in yr.values())), "years_n": len(yr), "year_means": yr,
        "tested": tested,
    })
    return row


def pooled_fraction(df: pd.DataFrame, pnl: str, prem: str) -> dict:
    """Pooled payoff over pooled premium (fraction of premium kept after expiry settle), with year CI."""
    m = np.isfinite(df[pnl].to_numpy(float)) & np.isfinite(df[prem].to_numpy(float))
    num = df[pnl].to_numpy(float)[m]
    den = df[prem].to_numpy(float)[m]
    yrs = df["year"].to_numpy()[m]
    lo, hi = _boot_ratio_year_ci(num, den, yrs, SEED_YEAR)
    return {"n": int(m.sum()), "premium_mean": float(den.mean()) if len(den) else float("nan"),
            "payoff_mean": float(num.mean()) if len(num) else float("nan"),
            "kept_fraction": float(num.sum() / den.sum()) if den.sum() else float("nan"),
            "ci_year": [lo, hi]}


def tail_view(df: pd.DataFrame, col: str) -> tuple[dict, pd.Series]:
    """Contribution of the worst TAIL_Q of weeks to the mean. Returns (summary, mask of the other weeks)."""
    x = df[col].to_numpy(float)
    ok = np.isfinite(x)
    n = int(ok.sum())
    k = int(math.ceil(TAIL_Q * n)) if n else 0
    order = np.argsort(np.where(ok, x, np.inf))
    worst = order[:k]
    keep = np.zeros(len(df), bool)
    keep[order[k:n]] = True
    keep &= ok
    summary = {
        "column": col, "n": n, "k_worst": k,
        "mean_all": float(x[ok].mean()) if n else float("nan"),
        "tail_mean": float(x[worst].mean()) if k else float("nan"),
        "tail_contribution_to_mean": float(x[worst].sum() / n) if n else float("nan"),
        "ex_tail_contribution_to_mean": float(x[keep].sum() / n) if n else float("nan"),
        "worst_week": str(df["fill_date"].iloc[worst[0]]) if k else None,
    }
    return summary, pd.Series(keep, index=df.index)


def power_block(df: pd.DataFrame, cols: dict[str, str]) -> list[dict]:
    """H3: standard error, minimum detectable effect at POWER, power at +TARGET_PTS, and weeks needed.

    Two-sided alpha ALPHA. The iid SE uses the per-week sd. The block SE is the moving-block bootstrap
    SE of the mean (BLOCK_LEN weeks), and its design effect scales the weeks needed."""
    za = Z.inv_cdf(1 - ALPHA / 2)
    zb = Z.inv_cdf(POWER)
    out = []
    for label, col in cols.items():
        x = df[col].to_numpy(float)
        x = x[np.isfinite(x)]
        n = len(x)
        sd = float(x.std(ddof=1))
        se = sd / math.sqrt(n)
        _, _, _, se_block = _boot_block(x, BLOCK_LEN, SEED_BLOCK)
        deff = (se_block / se) ** 2 if se > 0 else float("nan")
        mde = (za + zb) * se
        mde_block = (za + zb) * se_block
        pow_at_target = Z.cdf(TARGET_PTS / se - za) + Z.cdf(-TARGET_PTS / se - za)
        weeks_iid = math.ceil(((za + zb) * sd / TARGET_PTS) ** 2)
        mad_sd = 1.4826 * float(np.median(np.abs(x - np.median(x))))  # robust scale, descriptive only
        out.append({
            "series": label, "column": col, "n_weeks": n, "mean": float(x.mean()), "sd": sd,
            "mad_sd": mad_sd, "se_iid": se, "mde_iid_pts": mde, "se_block": se_block, "mde_block_pts": mde_block,
            "design_effect_block": deff, "power_at_target_obs_n": float(pow_at_target),
            "weeks_for_target_iid": weeks_iid,
            "weeks_for_target_block": int(math.ceil(weeks_iid * deff)) if np.isfinite(deff) else None,
        })
    return out


def build_cuts(df: pd.DataFrame) -> tuple[list[dict], dict]:
    """All tested cuts (H1, H2) with Holm-adjusted p-values, plus the tail summaries."""
    cuts: list[dict] = []
    for sd in SD_GRID:
        tg = _tag(sd)
        cuts.append(cut_stats(df, f"put_pnl_{tg}", "H1", f"put {tg} SD"))
        cuts.append(cut_stats(df, f"call_pnl_{tg}", "H1", f"call {tg} SD"))
    for sd in SD_GRID:
        tg = _tag(sd)
        cuts.append(cut_stats(df, f"diff_pc_{tg}", "H1", f"put minus call {tg} SD"))
    t = _tag(ENGINE_SD)
    for b in VIX_LABELS:
        mask = df["vix_bucket"] == b
        for side, col in (("put", f"put_pnl_{t}"), ("call", f"call_pnl_{t}"), ("strangle", f"strangle_pnl_{t}")):
            cuts.append(cut_stats(df, col, "H2", f"VIX {b} {side} {t} SD", mask))
    tails = {}
    for side, col in (("put", f"put_pnl_{t}"), ("call", f"call_pnl_{t}"), ("strangle", f"strangle_pnl_{t}")):
        summ, keep = tail_view(df, col)
        tails[side] = summ
        # Descriptive only: the worst weeks are removed in-sample, so a test of the remaining mean is
        # positive by construction and must not enter the Holm family.
        cuts.append(cut_stats(df, col, "H2", f"{side} {t} SD ex worst {int(TAIL_Q*100)}% of weeks", keep,
                              tested=False))
    tested = [c for c in cuts if c.get("tested")]
    pb = holm([c["p_block"] for c in tested])
    py = holm([c["p_year"] for c in tested])
    for c, a, b in zip(tested, pb, py):
        c["p_block_holm"] = a
        c["p_year_holm"] = b
    return cuts, tails


# ---------------------------------------------------------------- reporting

def _fmt(x, nd=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def render_tables(df: pd.DataFrame, cuts: list[dict], tails: dict, power: list[dict],
                  skips: dict, fractions: dict) -> str:
    L: list[str] = []
    n_tests = sum(1 for c in cuts if c.get("tested"))
    L.append(f"Weekly cycles: {len(df)} (fill {df['fill_date'].min()} .. {df['fill_date'].max()}); "
             f"years {sorted(df['year'].unique().tolist())}")
    L.append(f"Cycle skips: {skips['cycle']}")
    L.append(f"Leg skips (no usable price or contracts==0 and OI==0): {skips['leg']}")
    n_desc = sum(1 for c in cuts if not c.get("tested") and c.get("mean") == c.get("mean"))
    L.append(f"Tested cuts in Holm family: {n_tests}; descriptive cuts examined but not tested: {n_desc}")
    L.append("")
    L.append("### H1 per-leg payoff by SD level (pts/unit, gross, hold to expiry settle)")
    L.append("| cut | n | mean pts/unit (Rs/lot) | CI year | CI 4-wk block | p block | p block Holm | p year Holm | years>0 |")
    L.append("|---|---:|---:|---|---|---:|---:|---:|---:|")
    for c in cuts:
        if c["family"] != "H1" or not c.get("tested"):
            continue
        L.append(f"| {c['cut']} | {c['n']} | {c['mean']:.2f} ({c['mean_rs_lot']:.0f}) | "
                 f"[{_fmt(c['ci_year'][0])}, {_fmt(c['ci_year'][1])}] | "
                 f"[{_fmt(c['ci_block'][0])}, {_fmt(c['ci_block'][1])}] | {c['p_block']:.4f} | "
                 f"{c['p_block_holm']:.4f} | {c['p_year_holm']:.4f} | {c['years_positive']}/{c['years_n']} |")
    L.append("")
    L.append("### H1 premium collected and fraction kept (pooled payoff / pooled premium; year-cluster CI)")
    L.append("| SD | put prem pts | put kept | put kept CI | call prem pts | call kept | call kept CI |")
    L.append("|---|---:|---:|---|---:|---:|---|")
    for sd in SD_GRID:
        tg = _tag(sd)
        p, cl = fractions[f"put_{tg}"], fractions[f"call_{tg}"]
        L.append(f"| {tg} | {p['premium_mean']:.2f} | {_fmt(p['kept_fraction'], 3)} | "
                 f"[{_fmt(p['ci_year'][0], 3)}, {_fmt(p['ci_year'][1], 3)}] | {cl['premium_mean']:.2f} | "
                 f"{_fmt(cl['kept_fraction'], 3)} | [{_fmt(cl['ci_year'][0], 3)}, {_fmt(cl['ci_year'][1], 3)}] |")
    L.append("")
    L.append("### H2 by fill-session VIX bucket at the engine rule (0.9 SD), pts/unit")
    L.append("| cut | n | mean pts/unit (Rs/lot) | CI year | CI 4-wk block | p block Holm | years>0 |")
    L.append("|---|---:|---:|---|---|---:|---:|")
    for c in cuts:
        if c["family"] != "H2" or not c.get("tested") or "ex worst" in c["cut"]:
            continue
        L.append(f"| {c['cut']} | {c['n']} | {c['mean']:.2f} ({c['mean_rs_lot']:.0f}) | "
                 f"[{_fmt(c['ci_year'][0])}, {_fmt(c['ci_year'][1])}] | "
                 f"[{_fmt(c['ci_block'][0])}, {_fmt(c['ci_block'][1])}] | {c['p_block_holm']:.4f} | "
                 f"{c['years_positive']}/{c['years_n']} |")
    L.append("")
    L.append("### H2 tail view (0.9 SD; pts/unit)")
    L.append("Descriptive only (not tested): the ex-tail mean removes the worst weeks in-sample, so it is "
             "positive by construction; read the contributions, not its p-value.")
    L.append("")
    L.append("| side | mean all | worst-5% k | tail mean | tail contrib. to mean | ex-tail mean | ex-tail CI block | worst week |")
    L.append("|---|---:|---:|---:|---:|---:|---|---|")
    for side, s in tails.items():
        ex = next(c for c in cuts if c["family"] == "H2" and c["cut"].startswith(f"{side} 0.9 SD ex worst"))
        L.append(f"| {side} | {s['mean_all']:.2f} | {s['k_worst']} | {s['tail_mean']:.2f} | "
                 f"{s['tail_contribution_to_mean']:.2f} | {ex['mean']:.2f} | "
                 f"[{_fmt(ex['ci_block'][0])}, {_fmt(ex['ci_block'][1])}] | {s['worst_week']} |")
    L.append("")
    L.append("### H3 power (weekly series, pts/unit; alpha 0.05 two-sided, power 0.80; not a test)")
    L.append("| series | n | mean | sd | sd (MAD, robust) | SE iid | MDE iid | SE block | MDE block | power at +8 | weeks for +8 (iid) | weeks for +8 (block) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in power:
        L.append(f"| {p['series']} | {p['n_weeks']} | {p['mean']:.2f} | {p['sd']:.2f} | {p['mad_sd']:.2f} | "
                 f"{p['se_iid']:.2f} | {p['mde_iid_pts']:.2f} | {p['se_block']:.2f} | {p['mde_block_pts']:.2f} | "
                 f"{p['power_at_target_obs_n']:.2f} | {p['weeks_for_target_iid']} | {p['weeks_for_target_block']} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=lambda s: date.fromisoformat(s), default=DEV_START)
    ap.add_argument("--end", type=lambda s: date.fromisoformat(s), default=DEV_END)
    ap.add_argument("--market-start", type=lambda s: date.fromisoformat(s), default=audit.DEFAULT_MARKET_START)
    ap.add_argument("--archive-dir", type=str, default=None)
    ap.add_argument("--work-dir", type=Path, default=DEFAULT_WORK,
                    help="scratch dir for the dev-only archive view (symlinks + its parquet cache)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    # No holdout flag exists for this script: any --end after the dev window is refused.
    if a.end > DEV_END:
        raise HoldoutRefused(f"refusing --end {a.end}: audit_legs is development-window only "
                             f"(end <= {DEV_END}); there is no holdout option in this script")
    if a.start > a.end:
        ap.error("--start must not be after --end")

    from scripts.run_chain_backtest import load_market
    from data.nse_fo_archive import NseFoArchive, default_archive_dir

    market = load_market(a.end, a.market_start)
    market = market.copy()
    market.index = pd.to_datetime(market.index).normalize()
    market = market[market.index <= pd.Timestamp(a.end)]
    fallback = {d.date(): float(v) for d, v in market["nifty_close"].items()}

    view_dir, n_linked = dev_archive_view(a.archive_dir or default_archive_dir(), a.work_dir, a.end)
    arch = NseFoArchive(archive_dir=view_dir, index_fallback=fallback, max_date=a.end)

    df, skips = weekly_leg_table(arch, market, a.start, a.end)
    if df.empty:
        raise SystemExit("no weekly cycles measured")
    cuts, tails = build_cuts(df)
    t = _tag(ENGINE_SD)
    power = power_block(df, {"ATM straddle": "straddle_pnl_unit", f"short put {t} SD": f"put_pnl_{t}",
                             f"short call {t} SD": f"call_pnl_{t}", f"strangle {t} SD": f"strangle_pnl_{t}"})
    fractions = {}
    for sd in SD_GRID:
        tg = _tag(sd)
        fractions[f"put_{tg}"] = pooled_fraction(df, f"put_pnl_{tg}", f"put_prem_{tg}")
        fractions[f"call_{tg}"] = pooled_fraction(df, f"call_pnl_{tg}", f"call_prem_{tg}")

    a.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out / "cycles_legs.csv", index=False)
    pd.DataFrame(cuts).drop(columns=["year_means"], errors="ignore").to_csv(a.out / "cuts.csv", index=False)
    meta = {
        "start": str(a.start), "end": str(a.end), "dev_files_linked": n_linked,
        "n_cycles": int(len(df)), "n_tested_cuts": int(sum(c.get("tested", False) for c in cuts)),
        "block_len_weeks": BLOCK_LEN, "tail_q": TAIL_Q, "n_boot": N_BOOT,
        "skips": skips, "tails": tails, "power": power, "fractions": fractions,
        "cuts": cuts,
        "statistic_units": "index points per unit (1 unit = 1 NIFTY point of premium); Rs/lot = pts x 65",
    }
    json.dump(meta, open(a.out / "report.json", "w"), indent=1, default=float)
    tables = render_tables(df, cuts, tails, power, skips, fractions)
    (a.out / "tables.md").write_text(tables)
    print(tables)
    print(f"wrote {a.out}/cycles_legs.csv, cuts.csv, report.json, tables.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
