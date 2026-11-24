"""Pass rule (docs/preregistration_edge_search.md, written 2026-10-24) and its guards.

Pass rule for a candidate. All five must hold at the verdict cost level (1.5x slippage, no
extra haircut), on the development window only:
  C1  beats the baseline at that cost level (paired on common entry dates: mean difference > 0)
  C2  per-lot expectancy > 0
  C3  year-cluster bootstrap 95% CI lower bound > 0
  C4  at least 4 of the 5 development years (2019-2023) have positive per-lot expectancy
  C5  one-sided t-test on the non-overlapping subsample has a Holm-adjusted p < 0.05, where the
      Holm family is every cut recorded in the TestRegistry (the verdict cut is added to it)
Assumption: the pre-registration lists the four criteria in its pass-rule table and names Holm
as the multiple-testing rule over the cuts examined. C5 turns that Holm rule into a pass item.

Verdict values:
  PASS                  all of C1..C5 pass, and every evaluated trade is priced with 'chain' or 'live'
  FAIL                  at least one criterion fails
  INSUFFICIENT_DATA     no failures, but at least one criterion cannot be evaluated (no baseline,
                        fewer than MIN_TRADES, fewer than 5 development years, no p-value)
  INDICATIVE_ONLY       any evaluated trade (candidate or baseline) is priced with 'bs'. This is a
                        hard cap: a model-priced result can never be PASS. The criteria are still
                        reported in full, with their own result in `criteria_verdict`.

Guards:
  Development window: entries from DEV_START (2019-02-11) to DEV_END (2023-12-31) only. Entries
  before DEV_START are always excluded. Entries after DEV_END are excluded unless allow_holdout=True
  (mirrors scripts/run_chain_backtest.py --allow-holdout). The 2024+ holdout is a one-time look for
  the one pre-registered candidate and must not be opened by default. Every allow_holdout=True call
  appends a row to the holdout ledger (logs/holdout_ledger.json) before any holdout trade is scored,
  and is counted as a registry cut.
Registry: every verdict cut is written to the registry file automatically (default
  logs/eval_registry.json). Pass a TestRegistry (in memory or with its own path) to override.
Block bootstrap: a monthly-block CI of expectancy is reported next to the year-cluster CI. It is not a
  pass criterion.

Windows (window=, docs/preregistration_candidates.md Section 10). Default 'dev' is the rule above, unchanged.
  'test'     entries 2022-01-01..2023-12-31; exit must fall inside the window (straddlers purged, as in
             strategy_eval.walkforward). C3' = monthly-block bootstrap 95% CI lower bound > 0 (same n_boot and
             seed as C3). C4' = both years 2022 and 2023 have positive per-lot expectancy (2 of 2). Needs
             allow_holdout=False; allow_holdout=True is refused.
  'holdout'  entries from 2024-01-01 only. Requires allow_holdout=True, which appends one ledger row before any
             holdout trade is scored. C3' as above. C4' = every calendar year present in the holdout is positive.
  C1, C2 and C5 are the same in every window. Window verdicts use criteria ids C3' and C4'. Their cut names
  carry the window, so a test cut and a dev cut of the same candidate are distinct.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from strategy_eval.holdout_ledger import append_holdout_look
from strategy_eval.metrics import core_metrics
from strategy_eval.stats import (
    DEFAULT_SEED, N_BOOT_DEFAULT, TestRegistry, monthly_block_bootstrap, nonoverlap_ttest, resolve_registry,
    year_cluster_bootstrap, year_consistency,
)
from strategy_eval.stress import per_lot, stress_trades

DEV_START = date(2019, 2, 11)
DEV_END = date(2023, 12, 31)
DEV_YEARS = (2019, 2020, 2021, 2022, 2023)
VERDICT_SLIPPAGE = 1.5
VERDICT_HAIRCUT = 0.0
MIN_TRADES = 30
MIN_POSITIVE_YEARS = 4
ALPHA = 0.05
PREREG_REF = "docs/preregistration_edge_search.md"
HOLDOUT_START = date(2024, 1, 1)
TEST_START = date(2022, 1, 1)
TEST_END = DEV_END
TEST_YEARS = (2022, 2023)
WINDOWS = ("dev", "test", "holdout")

PASS, FAIL, INSUFFICIENT, INDICATIVE = "PASS", "FAIL", "INSUFFICIENT_DATA", "INDICATIVE_ONLY"


def apply_windows(df: pd.DataFrame, allow_holdout: bool = False) -> tuple[pd.DataFrame, dict]:
    """Keep trades inside the development window (plus the holdout only when allowed). Returns counts."""
    entry = pd.to_datetime(df["entry_date"]).dt.date
    pre = entry < DEV_START
    late = entry > DEV_END
    late_excluded = late & (not allow_holdout)
    keep = ~(pre | late_excluded)
    info = {
        "rows_in": int(len(df)), "rows_kept": int(keep.sum()),
        "pre_dev_excluded": int(pre.sum()), "holdout_excluded": int(late_excluded.sum()),
        "allow_holdout": bool(allow_holdout), "dev_start": str(DEV_START), "dev_end": str(DEV_END),
    }
    return df.loc[keep].reset_index(drop=True), info


def select_window(df: pd.DataFrame, window: str = "dev", allow_holdout: bool = False) -> tuple[pd.DataFrame, dict]:
    """Rows of the verdict window. 'dev' is apply_windows, unchanged. 'test' and 'holdout' per the docstring."""
    if window == "dev":
        return apply_windows(df, allow_holdout)
    entry = pd.to_datetime(df["entry_date"])
    exit_ = pd.to_datetime(df["exit_date"])
    if window == "test":
        in_w = (entry >= pd.Timestamp(TEST_START)) & (entry <= pd.Timestamp(TEST_END))
        straddle = in_w & (exit_ > pd.Timestamp(TEST_END))
        keep = in_w & ~straddle
        extra = {"straddle_purged": int(straddle.sum()), "pre_window_excluded": int((entry < pd.Timestamp(TEST_START)).sum()),
                 "post_window_excluded": int((entry > pd.Timestamp(TEST_END)).sum())}
    elif window == "holdout":
        keep = entry >= pd.Timestamp(HOLDOUT_START)
        extra = {"pre_window_excluded": int((entry < pd.Timestamp(HOLDOUT_START)).sum())}
    else:
        raise ValueError(f"window must be one of {WINDOWS}, got {window!r}")
    info = {"window": window, "rows_in": int(len(df)), "rows_kept": int(keep.sum()), "allow_holdout": bool(allow_holdout),
            "dev_start": str(DEV_START), "dev_end": str(DEV_END), **extra}
    return df.loc[keep].reset_index(drop=True), info


def _crit(cid: str, name: str, status: str, value=None, threshold=None, detail: str = "") -> dict:
    return {"id": cid, "name": name, "status": status, "value": value, "threshold": threshold, "detail": detail}


def evaluate_pass_rule(candidate: pd.DataFrame, baseline: pd.DataFrame | None = None, *,
                       allow_holdout: bool = False, registry: TestRegistry | None = None,
                       name: str = "candidate", verdict_slippage: float = VERDICT_SLIPPAGE,
                       verdict_haircut: float = VERDICT_HAIRCUT, n_boot: int = N_BOOT_DEFAULT,
                       seed: int = DEFAULT_SEED, window: str = "dev") -> dict:
    """Apply the pre-registered pass rule. See the module docstring for criteria and guards."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}, got {window!r}")
    if window == "test" and allow_holdout:
        raise ValueError("window='test' is not the holdout; allow_holdout=True is refused for it")
    if window == "holdout" and not allow_holdout:
        raise ValueError("window='holdout' requires allow_holdout=True (one ledgered holdout look)")
    wsuffix = "" if window == "dev" else f"|{window}-window"
    registry = resolve_registry(registry)     # None -> logs/eval_registry.json (auto-registration)
    holdout_look = None
    if allow_holdout:
        # Ledger first, before any holdout trade is scored. Each call is one look.
        cand_late = pd.to_datetime(candidate["entry_date"]).dt.date > DEV_END
        window_row = {"dev_start": str(DEV_START), "dev_end": str(DEV_END), "holdout_from": str(HOLDOUT_START),
                  "candidate_holdout_trades": int(cand_late.sum()),
                  "baseline_holdout_trades": (int((pd.to_datetime(baseline["entry_date"]).dt.date > DEV_END).sum())
                                              if baseline is not None else None),
                  "verdict_slippage": verdict_slippage, "verdict_haircut": verdict_haircut}
        if window != "dev":
            window_row = {**window_row, "window": window}
        holdout_look = append_holdout_look(name, window_row)
        registry.add(f"{name}|holdout-look#{holdout_look['index']}", None, kind="holdout_look",
                     detail=f"holdout look {holdout_look['index']} at {holdout_look['timestamp']}")
    sources_all = set(candidate["pricing_source"].astype(str))
    if baseline is not None:
        sources_all |= set(baseline["pricing_source"].astype(str))
    bs_capped = "bs" in sources_all

    cand_w, cand_info = select_window(candidate, window, allow_holdout)
    base_w, base_info = (select_window(baseline, window, allow_holdout) if baseline is not None else (None, None))

    cs = stress_trades(cand_w, verdict_haircut, verdict_slippage) if len(cand_w) else cand_w
    pl = per_lot(cs) if len(cs) else np.array([])
    years = cs["entry_date"].dt.year.to_numpy() if len(cs) else np.array([], dtype=int)
    n = len(pl)
    enough = n >= MIN_TRADES
    cut_key = (f"{name}|verdict|slip{verdict_slippage:g}|hc{verdict_haircut:g}"
               f"|{'holdout-incl' if allow_holdout else 'dev'}{wsuffix}")
    wdesc = "" if window == "dev" else f" [{window} window]"

    criteria: list[dict] = []
    base_n = 0

    # C1: beats the baseline at the verdict cost level, paired on common entry dates.
    if baseline is None:
        criteria.append(_crit("C1", "beats baseline at verdict cost", INSUFFICIENT,
                              detail="no baseline supplied"))
    else:
        bs_st = stress_trades(base_w, verdict_haircut, verdict_slippage) if len(base_w) else base_w
        base_n = len(bs_st)
        hd = pd.DataFrame({"d": pd.to_datetime(cs["entry_date"]).to_numpy(), "v": pl}).groupby("d")["v"].mean() \
            if n else pd.Series(dtype=float)
        bd = pd.DataFrame({"d": pd.to_datetime(bs_st["entry_date"]).to_numpy(),
                           "v": per_lot(bs_st)}).groupby("d")["v"].mean() if base_n else pd.Series(dtype=float)
        common = hd.index.intersection(bd.index)
        if len(common) < MIN_TRADES:
            criteria.append(_crit("C1", "beats baseline at verdict cost", INSUFFICIENT, value=len(common),
                                  threshold=MIN_TRADES, detail=f"only {len(common)} common entry dates"))
        else:
            diff = float(hd.loc[common].mean() - bd.loc[common].mean())
            st = PASS if diff > 0 else FAIL
            criteria.append(_crit("C1", "beats baseline at verdict cost", st, value=diff, threshold=0.0,
                                  detail=(f"paired mean diff {diff:+.1f} Rs/lot over {len(common)} dates; "
                                          f"candidate {hd.loc[common].mean():+.1f}, baseline {bd.loc[common].mean():+.1f}")))

    # C2: expectancy > 0.
    if not enough:
        criteria.append(_crit("C2", "per-lot expectancy > 0", INSUFFICIENT, value=n, threshold=MIN_TRADES,
                              detail=f"{n} trades in the verdict window"))
    else:
        exp = float(pl.mean())
        criteria.append(_crit("C2", "per-lot expectancy > 0", PASS if exp > 0 else FAIL, value=exp, threshold=0.0,
                              detail=f"{exp:+.1f} Rs/lot over {n} trades"))

    if window == "dev":
        # C3: year-cluster bootstrap CI lower bound > 0.
        boot = year_cluster_bootstrap(pl, years, n_boot=n_boot, seed=seed) if n else None
        # Monthly-block CI: reported only. C3 (the pass criterion) stays on the year cluster.
        blk = monthly_block_bootstrap(pl, cs["entry_date"], n_boot=n_boot, seed=seed) if n else None
        if not enough:
            criteria.append(_crit("C3", "year-cluster bootstrap 95% CI lower bound > 0", INSUFFICIENT,
                                  value=n, threshold=MIN_TRADES, detail=f"{n} trades"))
        else:
            criteria.append(_crit("C3", "year-cluster bootstrap 95% CI lower bound > 0",
                                  PASS if boot["lo"] > 0 else FAIL, value=boot["lo"], threshold=0.0,
                                  detail=f"CI [{boot['lo']:+.1f}, {boot['hi']:+.1f}], {boot['n_years']} years, "
                                         f"{boot['n_boot']} draws, seed {boot['seed']}"))

        # C4: at least 4 of 5 development years positive.
        yc = year_consistency(pl, years, DEV_YEARS, MIN_POSITIVE_YEARS) if n else None
        if yc is None or yc["status"] == INSUFFICIENT or not enough:
            present = yc["years_present"] if yc else 0
            criteria.append(_crit("C4", ">= 4 of 5 dev years positive", INSUFFICIENT, value=present,
                                  threshold=len(DEV_YEARS), detail=f"{present} of 5 dev years present"))
        else:
            criteria.append(_crit("C4", ">= 4 of 5 dev years positive", yc["status"], value=yc["positive"],
                                  threshold=MIN_POSITIVE_YEARS,
                                  detail=f"{yc['positive']} of {yc['years_present']} dev years positive"))
    else:
        # Test / holdout windows: C3' on the monthly-block CI (same n_boot and seed), C4' on every window year.
        boot = None      # the year-cluster CI has fewer than 5 clusters here and is not a criterion
        blk = monthly_block_bootstrap(pl, cs["entry_date"], n_boot=n_boot, seed=seed) if n else None
        if not enough:
            criteria.append(_crit("C3'", "monthly-block bootstrap 95% CI lower bound > 0", INSUFFICIENT,
                                  value=n, threshold=MIN_TRADES, detail=f"{n} trades"))
        else:
            criteria.append(_crit("C3'", "monthly-block bootstrap 95% CI lower bound > 0",
                                  PASS if blk["lo"] > 0 else FAIL, value=blk["lo"], threshold=0.0,
                                  detail=f"block CI [{blk['lo']:+.1f}, {blk['hi']:+.1f}], {blk['n_clusters']} months, "
                                         f"{blk['n_boot']} draws, seed {blk['seed']}"))
        if window == "test":
            wyears = TEST_YEARS
        else:
            wyears = tuple(sorted({int(y) for y in years})) if n else ()
        yc = year_consistency(pl, years, wyears, len(wyears)) if (n and wyears) else None
        if yc is None or yc["status"] == INSUFFICIENT or not enough:
            present = yc["years_present"] if yc else 0
            criteria.append(_crit("C4'", "every window year has positive per-lot expectancy", INSUFFICIENT,
                                  value=present, threshold=len(wyears),
                                  detail=f"{present} of {len(wyears)} window years present"))
        else:
            criteria.append(_crit("C4'", "every window year has positive per-lot expectancy", yc["status"],
                                  value=yc["positive"], threshold=len(wyears),
                                  detail=f"{yc['positive']} of {yc['years_present']} window years positive"))

    # C5: Holm-adjusted one-sided t-test over the whole registry.
    tt = nonoverlap_ttest(pl, cs["entry_date"], cs["exit_date"]) if n else {"p_one_sided": float("nan"), "n": 0}
    if not enough or not np.isfinite(tt["p_one_sided"]):
        # Recorded without a p-value: it still counts as a cut examined (Holm ignores it until it has one).
        registry.add(cut_key, None, kind="verdict",
                     detail=f"{name} at {verdict_slippage:g}x{wdesc}: not evaluated ({n} trades)")
        criteria.append(_crit("C5", "Holm-adjusted p < 0.05", INSUFFICIENT, value=None, threshold=ALPHA,
                              detail=f"non-overlapping n={tt.get('n', 0)}"))
        p_holm = None
    else:
        registry.add(cut_key, tt["p_one_sided"], kind="verdict", detail=f"{name} at {verdict_slippage:g}x{wdesc}")
        p_holm = registry.holm()[cut_key]
        criteria.append(_crit("C5", "Holm-adjusted p < 0.05", PASS if p_holm < ALPHA else FAIL,
                              value=p_holm, threshold=ALPHA,
                              detail=(f"raw one-sided p {tt['p_one_sided']:.4f} (non-overlapping n={tt['n']}, "
                                      f"t={tt['t']:.2f}); Holm over {registry.n_cuts} recorded cuts")))

    statuses = [c["status"] for c in criteria]
    if FAIL in statuses:
        criteria_verdict = FAIL
    elif INSUFFICIENT in statuses:
        criteria_verdict = INSUFFICIENT
    else:
        criteria_verdict = PASS

    reasons = [f"{c['id']} {c['name']}: {c['status']} ({c['detail']})" for c in criteria]
    if n == 0:
        reasons.insert(0, "no trades remain in the verdict window after the guards")
    if bs_capped:
        verdict = INDICATIVE
        reasons.insert(0, "priced with Black-Scholes (pricing_source='bs'): PASS is not allowed, verdict "
                          "capped at INDICATIVE_ONLY; criteria above are reported for information only")
    else:
        verdict = criteria_verdict

    if window == "dev":
        holdout_note = ("holdout (entries after 2023-12-31) INCLUDED: allow_holdout=True"
                        if allow_holdout else "holdout (entries after 2023-12-31) excluded")
    else:
        holdout_note = f"window '{window}': {cand_info['rows_kept']} candidate trades kept; criteria C3' and C4' apply"
    reasons.append(holdout_note)

    out = {
        "verdict": verdict,
        "criteria_verdict": criteria_verdict,
        "criteria": criteria,
        "reasons": reasons,
        "cost_level": {"slippage_mult": verdict_slippage, "haircut": verdict_haircut},
        "guards": {
            "pricing_sources": sorted(sources_all), "bs_capped": bs_capped,
            "candidate_window": cand_info, "baseline_window": base_info,
            "allow_holdout": bool(allow_holdout),
        },
        "n_trades": int(n), "n_baseline": int(base_n),
        "expectancy_per_lot_at_verdict_cost": float(pl.mean()) if n else float("nan"),
        "bootstrap": boot, "block_bootstrap": blk, "year_consistency": yc,
        "nonoverlap_ttest": tt, "p_holm": p_holm, "cut_key": cut_key,
        "holdout_look": holdout_look,
        "registry": registry.to_dict(), "prereg": PREREG_REF,
    }
    if window != "dev":
        out["window"] = window
    return out
