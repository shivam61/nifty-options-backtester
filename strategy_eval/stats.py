"""Statistics: year-cluster bootstrap, non-overlapping t-test, Holm correction, cut registry.

Multiple testing: every cut examined (bucket, structure, filter threshold, cost level used for a
verdict) is recorded in a TestRegistry. Holm is applied over all recorded p-values, so the
denominator is visible in the report. Cuts are keyed by name; re-recording the same name is a
no-op (it is not a new cut), and re-recording it with a different p-value is an error.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

DEFAULT_SEED = 20261111
N_BOOT_DEFAULT = 10_000


def year_cluster_bootstrap(pl: np.ndarray, years: np.ndarray, n_boot: int = N_BOOT_DEFAULT,
                           seed: int = DEFAULT_SEED, alpha: float = 0.05) -> dict:
    """Percentile CI for the mean per-lot P&L, resampling whole calendar years with replacement.

    Each draw picks Y years with replacement and takes the mean over all trades in the picked years
    (trade-weighted). Deterministic for a given seed.
    """
    pl = np.asarray(pl, dtype=float)
    years = np.asarray(years)
    if pl.size == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_years": 0,
                "n_boot": n_boot, "seed": seed, "alpha": alpha}
    uniq = np.unique(years)
    sums = np.array([pl[years == y].sum() for y in uniq])
    counts = np.array([(years == y).sum() for y in uniq], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"mean": float(pl.mean()), "lo": float(lo), "hi": float(hi), "n_years": int(len(uniq)),
            "n_boot": int(n_boot), "seed": int(seed), "alpha": float(alpha)}


def nonoverlapping_subsample(entry: pd.Series, exit_: pd.Series) -> np.ndarray:
    """Indices of trades whose holding period does not overlap the previous selected trade.

    Trades are scanned in entry order; a trade is kept when it enters on or after the last kept exit.
    """
    order = np.argsort(pd.to_datetime(entry).to_numpy(), kind="mergesort")
    ent = pd.to_datetime(entry).to_numpy()
    ex = pd.to_datetime(exit_).to_numpy()
    keep, last_exit = [], None
    for i in order:
        if last_exit is None or ent[i] >= last_exit:
            keep.append(i)
            last_exit = ex[i]
    return np.array(keep, dtype=int)


def nonoverlap_ttest(pl: np.ndarray, entry: pd.Series, exit_: pd.Series) -> dict:
    """One-sided t-test of H0: mean <= 0 on the non-overlapping subsample (H1: mean > 0)."""
    idx = nonoverlapping_subsample(entry, exit_)
    x = np.asarray(pl, dtype=float)[idx]
    n = len(x)
    if n < 3:
        return {"n": n, "t": float("nan"), "p_one_sided": float("nan"), "mean": float(x.mean()) if n else float("nan")}
    sd = x.std(ddof=1)
    if sd == 0:
        t = float("inf") if x.mean() > 0 else float("nan")
        p = 0.0 if x.mean() > 0 else float("nan")
    else:
        t = float(x.mean() / (sd / math.sqrt(n)))
        p = float(sps.t.sf(t, df=n - 1))
    return {"n": int(n), "t": t, "p_one_sided": p, "mean": float(x.mean())}


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in the input order.

    Sort ascending; adjusted p_(i) = max over j <= i of min(1, (m - j + 1) * p_(j)).
    NaN inputs stay NaN and do not count toward m.
    """
    p = np.asarray(pvalues, dtype=float)
    adj = np.full(p.shape, np.nan)
    valid = np.where(np.isfinite(p))[0]
    m = len(valid)
    if m == 0:
        return adj.tolist()
    order = valid[np.argsort(p[valid], kind="mergesort")]
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return adj.tolist()


class TestRegistry:
    """Record of every cut examined. Holm adjustment is computed over all recorded p-values."""

    __test__ = False  # not a pytest test class despite the name

    def __init__(self) -> None:
        self._cuts: dict[str, dict] = {}

    def add(self, name: str, p_value: float | None = None, kind: str = "cut", detail: str = "") -> dict:
        """Record a cut. Returns the stored record. Duplicate names are not counted twice."""
        p = None if p_value is None or not np.isfinite(p_value) else float(p_value)
        if name in self._cuts:
            prev = self._cuts[name]["p_value"]
            if prev != p and not (prev is None and p is None):
                raise ValueError(f"cut {name!r} already registered with p={prev}; refusing p={p}")
            return self._cuts[name]
        self._cuts[name] = {"name": name, "kind": kind, "p_value": p, "detail": detail}
        return self._cuts[name]

    @property
    def n_cuts(self) -> int:
        return len(self._cuts)

    def holm(self) -> dict:
        """name -> Holm-adjusted p for every cut that has a p-value."""
        names = [k for k, v in self._cuts.items() if v["p_value"] is not None]
        adj = holm_adjust([self._cuts[k]["p_value"] for k in names])
        return dict(zip(names, adj))

    def to_dict(self) -> dict:
        adj = self.holm()
        cuts = []
        for k, v in self._cuts.items():
            cuts.append({**v, "p_holm": adj.get(k)})
        return {"n_cuts": self.n_cuts, "n_with_p": len(adj), "cuts": cuts}

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict()["cuts"], indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "TestRegistry":
        reg = cls()
        p = Path(path)
        if p.exists():
            for rec in json.loads(p.read_text(encoding="utf-8")):
                reg.add(rec["name"], rec.get("p_value"), rec.get("kind", "cut"), rec.get("detail", ""))
        return reg


def year_consistency(pl: np.ndarray, years: np.ndarray, dev_years: tuple[int, ...],
                     min_positive: int = 4) -> dict:
    """Per calendar year mean per-lot P&L over the dev years, and how many are positive."""
    years = np.asarray(years)
    pl = np.asarray(pl, dtype=float)
    per_year = {}
    for y in dev_years:
        m = years == y
        if m.any():
            per_year[int(y)] = {"n": int(m.sum()), "mean_per_lot": float(pl[m].mean())}
    present = len(per_year)
    positive = sum(1 for v in per_year.values() if v["mean_per_lot"] > 0)
    return {"dev_years": list(dev_years), "years_present": present, "positive": positive,
            "min_positive": min_positive, "per_year": per_year,
            "status": ("INSUFFICIENT_DATA" if present < len(dev_years)
                       else ("PASS" if positive >= min_positive else "FAIL"))}
