"""Mechanical walk-forward selection inside the development window. No manual choice.

Windows (by entry date; a trade whose holding period crosses the end of its window is purged from that
window, so no trade's P&L is shared between TRAIN and TEST):
  TRAIN    2019-02-11..2021-12-31   the only data the selection sees
  TEST     2022-01-01..2023-12-31   scores the one selected candidate (and the baseline, for context)
  HOLDOUT  2024-01-01 onward        never read unless allow_holdout=True (one ledgered look)

walk_forward_select() ranks every candidate on TRAIN by expectancy per lot at the verdict slippage
(1.5x, no haircut), among candidates with at least MIN_TRADES TRAIN trades. It then reports that single
candidate on TEST. TEST data never enters the ranking, and TRAIN data never enters the TEST score.

Registry: the choice is recorded as one cut, kind='selection'. Its p-value is 1 - DSR of the selected
candidate on the TRAIN grid (Bailey and Lopez de Prado, with N = number of candidates considered), so the
selection enters the Holm family like any other cut. The cut name holds the candidate set and the choice,
so re-running the same set with changed TRAIN data is refused by the registry (as for any changed cut).

Holdout: any trade with entry_date >= 2024-01-01 in a candidate or the baseline raises HoldoutAccessError
unless allow_holdout=True. With it, the holdout is appended to the ledger (before anything is scored) and
counted as a registry cut, and the holdout metrics of the selected candidate only are returned.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from strategy_eval.holdout_ledger import append_holdout_look
from strategy_eval.metrics import core_metrics
from strategy_eval.schema import normalize
from strategy_eval.stats import deflated_sharpe_grid, resolve_registry
from strategy_eval.stress import per_lot, stress_trades
from strategy_eval.verdict import DEV_END, DEV_START, HOLDOUT_START, MIN_TRADES, VERDICT_SLIPPAGE

TRAIN_START = DEV_START
TRAIN_END = date(2021, 12, 31)
TEST_START = date(2022, 1, 1)
TEST_END = DEV_END
HOLDOUT_FROM = HOLDOUT_START
METRIC = "expectancy"

_TABLE_COLS = ["name", "role", "n", "expectancy_per_lot", "win_rate_actual", "p5_per_lot",
               "worst_per_lot", "max_drawdown_per_lot", "straddle_purged"]


class HoldoutAccessError(ValueError):
    """A candidate or the baseline holds trades entered on or after HOLDOUT_FROM and allow_holdout is off."""


def _split(df: pd.DataFrame) -> dict:
    """Train, test and holdout frames by entry date. Straddling trades are counted and dropped."""
    e = pd.to_datetime(df["entry_date"])
    x = pd.to_datetime(df["exit_date"])
    t = pd.Timestamp
    in_train = (e >= t(TRAIN_START)) & (e <= t(TRAIN_END))
    in_test = (e >= t(TEST_START)) & (e <= t(TEST_END))
    return {
        "train": df[in_train & (x <= t(TRAIN_END))].reset_index(drop=True),
        "test": df[in_test & (x <= t(TEST_END))].reset_index(drop=True),
        "holdout": df[e >= t(HOLDOUT_FROM)].reset_index(drop=True),
        "purged": {"train": int((in_train & (x > t(TRAIN_END))).sum()),
                   "test": int((in_test & (x > t(TEST_END))).sum())},
    }


def _score(df: pd.DataFrame, slippage: float) -> tuple[np.ndarray, dict]:
    """Per-lot net P&L at the given slippage multiplier (no haircut), and core metrics of that table."""
    if df.empty:
        return np.array([], dtype=float), {"n": 0}
    s = stress_trades(df, 0.0, slippage)
    return per_lot(s), core_metrics(s)


def _row(name: str, role: str, pl: np.ndarray, m: dict, purged: int) -> dict:
    n = int(len(pl))
    return {"name": name, "role": role, "n": n,
            "expectancy_per_lot": float(pl.mean()) if n else float("nan"),
            "win_rate_actual": m.get("win_rate_actual", float("nan")),
            "p5_per_lot": m.get("p5_per_lot", float("nan")),
            "worst_per_lot": m.get("worst_per_lot", float("nan")),
            "max_drawdown_per_lot": m.get("max_drawdown_per_lot", float("nan")),
            "straddle_purged": int(purged)}


def walk_forward_select(candidates: dict[str, pd.DataFrame], baseline: pd.DataFrame | None = None, *,
                        registry=None, metric: str = METRIC, slippage: float = VERDICT_SLIPPAGE,
                        allow_holdout: bool = False) -> dict:
    """Choose the best candidate on TRAIN and report it on TEST. See the module docstring.

    candidates  {name: normalised (or normalisable) trade table}; at least one with MIN_TRADES TRAIN trades
    baseline    optional trade table, reported on TRAIN and TEST for context; never selectable
    registry    TestRegistry, path, or None (None -> logs/eval_registry.json, auto-registered)
    Returns a dict with: selected, metric, slippage_mult, windows, train_table, test_table (DataFrames,
    one row per candidate / for the selected candidate and the baseline), n_candidates,
    deflated_sharpe_ratio (of the selected row on the TRAIN grid), registry_cut, holdout (None unless
    allow_holdout), and holdout_trades_in_input (count per candidate, before any allow_holdout).
    """
    if metric != METRIC:
        raise ValueError(f"metric {metric!r} not supported; only {METRIC!r} is defined")
    if not candidates:
        raise ValueError("candidates must be a non-empty dict of {name: trade table}")
    names = list(candidates)
    frames = {n: normalize(df) for n, df in candidates.items()}
    base = normalize(baseline) if baseline is not None else None

    # Holdout guard first: nothing is scored, and no ledger row is written, unless the caller asked for it.
    held = {n: int((f["entry_date"] >= pd.Timestamp(HOLDOUT_FROM)).sum()) for n, f in frames.items()}
    if base is not None:
        held["baseline"] = int((base["entry_date"] >= pd.Timestamp(HOLDOUT_FROM)).sum())
    held_nonzero = {k: v for k, v in held.items() if v}
    if held_nonzero and not allow_holdout:
        raise HoldoutAccessError(
            f"trades entered on or after {HOLDOUT_FROM} (the holdout) in {held_nonzero}. The walk-forward "
            "reads only TRAIN and TEST. Pass allow_holdout=True for the one pre-registered holdout look "
            "(it is ledgered and counted as a cut).")

    registry = resolve_registry(registry)
    splits = {n: _split(f) for n, f in frames.items()}
    base_split = _split(base) if base is not None else None

    # Selection: TRAIN only.
    train_scores = {n: _score(splits[n]["train"], slippage) for n in names}
    eligible = [n for n in names if len(train_scores[n][0]) >= MIN_TRADES]
    if not eligible:
        raise ValueError(f"no candidate has >= {MIN_TRADES} TRAIN trades ({TRAIN_START}..{TRAIN_END}); "
                         "nothing can be selected")
    selected = max(eligible, key=lambda n: float(train_scores[n][0].mean()))   # ties: first in input order

    # Deflated Sharpe over the whole TRAIN grid (all candidates considered, eligible or not).
    grid = deflated_sharpe_grid({n: train_scores[n][0] for n in names})
    row = next(r for r in grid["rows"] if r["name"] == selected)
    dsr = {"sr_hat": row["sr"], "sr0": row["sr0"], "dsr": row["dsr"], "p_value": row["p_value"],
           "n_obs": row["n"], "n_trials": grid["n_trials"], "var_sharpe": grid["var_sharpe"]}

    set_name = "+".join(sorted(names))
    p_cut = row["p_value"] if np.isfinite(row["p_value"]) else None
    cut = registry.add(f"walkforward|select|{set_name}|chose={selected}", p_cut, kind="selection",
                       detail=(f"selected {selected} on TRAIN {TRAIN_START}..{TRAIN_END} at {slippage:g}x {metric}; "
                               f"n_candidates={len(names)}; DSR p={p_cut if p_cut is None else round(p_cut, 6)}"))

    # Train table: every candidate, plus the baseline for context.
    train_rows = []
    for n in names:
        pl, m = train_scores[n]
        r = _row(n, "candidate", pl, m, splits[n]["purged"]["train"])
        r.update({"eligible": n in eligible, "selected": n == selected})
        train_rows.append(r)
    if base_split is not None:
        pl, m = _score(base_split["train"], slippage)
        r = _row("baseline", "baseline", pl, m, base_split["purged"]["train"])
        r.update({"eligible": False, "selected": False})
        train_rows.append(r)
    train_table = pd.DataFrame(train_rows, columns=_TABLE_COLS + ["eligible", "selected"])

    # Test table: the selected candidate only, plus the baseline. Scored on TEST entries only.
    pl, m = _score(splits[selected]["test"], slippage)
    test_rows = [_row(selected, "candidate", pl, m, splits[selected]["purged"]["test"])]
    if base_split is not None:
        pl_b, m_b = _score(base_split["test"], slippage)
        test_rows.append(_row("baseline", "baseline", pl_b, m_b, base_split["purged"]["test"]))
    test_table = pd.DataFrame(test_rows, columns=_TABLE_COLS)

    holdout = None
    if allow_holdout:
        # Ledger first, before any holdout trade is scored. Each call is one look.
        window = {"walk_forward": True, "train": [str(TRAIN_START), str(TRAIN_END)],
                  "test": [str(TEST_START), str(TEST_END)], "holdout_from": str(HOLDOUT_FROM),
                  "candidate_holdout_trades": held.get(selected, 0),
                  "baseline_holdout_trades": held.get("baseline"), "slippage_mult": slippage,
                  "selected": selected, "n_candidates": len(names)}
        look = append_holdout_look(selected, window)
        registry.add(f"{selected}|walkforward-holdout-look#{look['index']}", None, kind="holdout_look",
                     detail=f"walk-forward holdout look {look['index']} at {look['timestamp']}")
        pl_h, m_h = _score(splits[selected]["holdout"], slippage)
        holdout = {"look": look, **_row(selected, "candidate", pl_h, m_h, 0)}

    return {
        "selected": selected,
        "metric": metric,
        "slippage_mult": float(slippage),
        "windows": {"train": [str(TRAIN_START), str(TRAIN_END)], "test": [str(TEST_START), str(TEST_END)],
                    "holdout_from": str(HOLDOUT_FROM)},
        "train_table": train_table,
        "test_table": test_table,
        "n_candidates": len(names),
        "deflated_sharpe_ratio": dsr,
        "registry_cut": cut,
        "holdout": holdout,
        "allow_holdout": bool(allow_holdout),
        "holdout_trades_in_input": held,
    }
