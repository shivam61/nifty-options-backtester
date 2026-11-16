"""Statistics: cluster bootstraps, non-overlapping t-test, Holm correction, cut registry,
deflated Sharpe and White's reality check.

Multiple testing: every cut examined (bucket, structure, filter threshold, cost level used for a
verdict, holdout look) is recorded in a TestRegistry. Holm is applied over all recorded p-values, so
the denominator is visible in the report. Cuts are keyed by name; re-recording the same name is a
no-op (it is not a new cut). Re-recording it with a different p-value is an error. A cut first
recorded without a p-value may later receive one (None -> value); it is never changed once set.

Auto-registration: a TestRegistry created with a path (or resolved by `resolve_registry()`, which is
what run_evaluation / evaluate_pass_rule use when no registry is passed) writes itself to that file
on every new cut. The default file is DEFAULT_REGISTRY_PATH (logs/eval_registry.json).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

DEFAULT_SEED = 20261111
N_BOOT_DEFAULT = 10_000
REPO_ROOT = Path(__file__).resolve().parents[1]
# Read at call time, so tests can redirect it. The CLI and the library both use this file by default.
DEFAULT_REGISTRY_PATH = REPO_ROOT / "logs" / "eval_registry.json"
EULER_GAMMA = 0.5772156649015329


def _cluster_bootstrap(pl: np.ndarray, labels: np.ndarray, n_boot: int, seed: int, alpha: float) -> dict:
    """Percentile CI for the mean per-lot P&L, resampling whole clusters with replacement.

    Each draw picks as many clusters as exist, with replacement, and takes the trade-weighted mean
    over all trades in the picked clusters. Deterministic for a given seed.
    """
    pl = np.asarray(pl, dtype=float)
    labels = np.asarray(labels)
    if pl.size == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n_years": 0,
                "n_clusters": 0, "n_boot": n_boot, "seed": seed, "alpha": alpha}
    uniq = np.unique(labels)
    sums = np.array([pl[labels == y].sum() for y in uniq])
    counts = np.array([(labels == y).sum() for y in uniq], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"mean": float(pl.mean()), "lo": float(lo), "hi": float(hi), "n_years": int(len(uniq)),
            "n_clusters": int(len(uniq)), "n_boot": int(n_boot), "seed": int(seed), "alpha": float(alpha)}


def year_cluster_bootstrap(pl: np.ndarray, years: np.ndarray, n_boot: int = N_BOOT_DEFAULT,
                           seed: int = DEFAULT_SEED, alpha: float = 0.05) -> dict:
    """Percentile CI for the mean per-lot P&L, resampling whole calendar years with replacement.

    This is the pass-rule bootstrap (criterion C3). Deterministic for a given seed.
    """
    return _cluster_bootstrap(pl, np.asarray(years), n_boot, seed, alpha)


def monthly_block_bootstrap(pl: np.ndarray, entry_dates, n_boot: int = N_BOOT_DEFAULT,
                            seed: int = DEFAULT_SEED, alpha: float = 0.05) -> dict:
    """Percentile CI for the mean per-lot P&L, resampling whole entry months (YYYY-MM) with replacement.

    Reported next to the year-cluster bootstrap for information. It is NOT the pass criterion: C3 stays
    on the year cluster. Monthly blocks are finer than years, so this CI is the more sensitive one to
    clustering within a year. Deterministic for a given seed.
    """
    months = pd.DatetimeIndex(pd.to_datetime(entry_dates)).strftime("%Y-%m").to_numpy()
    out = _cluster_bootstrap(pl, months, n_boot, seed, alpha)
    out.pop("n_years", None)          # the cluster unit here is the month; n_clusters is the count
    out["cluster"] = "month"
    return out


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
    """Record of every cut examined. Holm adjustment is computed over all recorded p-values.

    With a `path`, every new cut is written to that file immediately (auto-registration).
    """

    __test__ = False  # not a pytest test class despite the name

    def __init__(self, path: str | Path | None = None) -> None:
        self._cuts: dict[str, dict] = {}
        self.path = Path(path) if path is not None else None

    def _insert(self, name: str, p: float | None, kind: str, detail: str) -> None:
        self._cuts[name] = {"name": name, "kind": kind, "p_value": p, "detail": detail}

    def add(self, name: str, p_value: float | None = None, kind: str = "cut", detail: str = "") -> dict:
        """Record a cut. Returns the stored record. Duplicate names are not counted twice."""
        p = None if p_value is None or not np.isfinite(p_value) else float(p_value)
        if name in self._cuts:
            prev = self._cuts[name]["p_value"]
            if prev is not None and prev != p:
                raise ValueError(f"cut {name!r} already registered with p={prev}; refusing p={p}. "
                                 "Use a new --name for a changed candidate or dataset.")
            if prev is None and p is not None:
                self._cuts[name]["p_value"] = p          # first real p-value for a cut recorded earlier
                self._persist()
            return self._cuts[name]
        self._insert(name, p, kind, detail)
        self._persist()
        return self._cuts[name]

    def _persist(self) -> None:
        if self.path is not None:
            self.save(self.path)

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
        return {"n_cuts": self.n_cuts, "n_with_p": len(adj),
                "path": str(self.path) if self.path is not None else None, "cuts": cuts}

    def save(self, path: str | Path | None = None) -> None:
        """Write the cut list as JSON (atomic replace). Default: the registry's own path."""
        target = Path(path) if path is not None else self.path
        if target is None:
            raise ValueError("registry has no path to save to")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps([{k: v for k, v in c.items() if k != "p_holm"} for c in self.to_dict()["cuts"]],
                                  indent=1), encoding="utf-8")
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: str | Path) -> "TestRegistry":
        """Read a registry file. The returned registry keeps `path`, so new cuts are written back to it."""
        reg = cls(path)
        p = Path(path)
        if p.exists():
            for rec in json.loads(p.read_text(encoding="utf-8")):
                reg._insert(rec["name"], rec.get("p_value"), rec.get("kind", "cut"), rec.get("detail", ""))
        return reg

    @classmethod
    def open(cls, path: str | Path | None = None) -> "TestRegistry":
        """Load the registry at `path`, or at DEFAULT_REGISTRY_PATH when path is None."""
        return cls.load(Path(path) if path is not None else DEFAULT_REGISTRY_PATH)


def resolve_registry(registry: "TestRegistry | str | Path | None" = None) -> TestRegistry:
    """The registry every evaluation records into. None -> the default file (auto-registration)."""
    if isinstance(registry, TestRegistry):
        return registry
    return TestRegistry.open(registry)


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


# ----------------------------------------------------------------------------- multiple-testing helpers over a grid

def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """SR0: expected maximum of n_trials independent Sharpe estimates that are each N(0, var_sharpe).

    Bailey and Lopez de Prado (2014) approximation:
      SR0 = sqrt(V) * [(1 - g) * Phi^-1(1 - 1/N) + g * Phi^-1(1 - 1/(N e))],  g = Euler-Mascheroni.
    Returns 0 for a single trial or zero variance. Units follow the Sharpe inputs (per observation).
    """
    if n_trials < 2 or not var_sharpe > 0:
        return 0.0
    s = math.sqrt(var_sharpe)
    return float(s * ((1 - EULER_GAMMA) * sps.norm.ppf(1 - 1 / n_trials)
                      + EULER_GAMMA * sps.norm.ppf(1 - 1 / (n_trials * math.e))))


def deflated_sharpe_ratio(sr_hat: float, n_obs: int, n_trials: int, var_sharpe: float,
                          skew: float = 0.0, kurt: float = 3.0) -> dict:
    """Deflated Sharpe ratio (Bailey and Lopez de Prado 2014) for the best of a grid of trials.

    sr_hat      Sharpe of the selected candidate, per observation (NOT annualised)
    n_obs       number of return observations behind sr_hat
    n_trials    number of candidates in the grid the selection was made from
    var_sharpe  variance of the per-observation Sharpe estimates across the grid (ddof=1)
    skew, kurt  sample skew and non-excess kurtosis (3 for a normal distribution) of the returns

    DSR = Phi( (sr_hat - SR0) * sqrt(n_obs - 1) / sqrt(1 - skew*sr_hat + (kurt - 1)/4 * sr_hat^2) ).
    It is the probability that the true Sharpe exceeds the SR0 expected from selection luck alone.
    p_value = 1 - DSR. Returns NaN for dsr when the square-root argument is not positive.
    """
    sr0 = expected_max_sharpe(n_trials, var_sharpe)
    arg = 1 - skew * sr_hat + (kurt - 1) / 4.0 * sr_hat ** 2
    if n_obs < 2 or arg <= 0:
        return {"sr_hat": float(sr_hat), "sr0": sr0, "z": float("nan"), "dsr": float("nan"),
                "p_value": float("nan"), "n_obs": int(n_obs), "n_trials": int(n_trials)}
    z = (sr_hat - sr0) * math.sqrt(n_obs - 1) / math.sqrt(arg)
    dsr = float(sps.norm.cdf(z))
    return {"sr_hat": float(sr_hat), "sr0": sr0, "z": float(z), "dsr": dsr, "p_value": 1.0 - dsr,
            "n_obs": int(n_obs), "n_trials": int(n_trials)}


def deflated_sharpe_grid(returns_by_name: dict[str, np.ndarray]) -> dict:
    """Deflated Sharpe for every candidate in a grid, with the grid itself as the trial count.

    Each candidate's Sharpe is mean / std(ddof=1) of its per-trade (or per-period) returns, not annualised.
    var_sharpe is the variance of those Sharpes across the grid. The best candidate is then deflated with
    N = number of candidates. Other rows are deflated with the same SR0 for comparability. Pure function.
    """
    names = list(returns_by_name)
    k = len(names)
    srs, rows = [], []
    for name in names:
        x = np.asarray(returns_by_name[name], dtype=float)
        x = x[np.isfinite(x)]
        sd = x.std(ddof=1) if len(x) > 1 else float("nan")
        sr = float(x.mean() / sd) if sd and np.isfinite(sd) and sd > 0 else float("nan")
        srs.append(sr)
        skew = float(sps.skew(x, bias=False)) if len(x) > 2 else 0.0
        kurt = float(sps.kurtosis(x, fisher=False, bias=False)) if len(x) > 3 else 3.0
        rows.append({"name": name, "sr": sr, "n": int(len(x)), "skew": skew, "kurt": kurt})
    finite = np.array([s for s in srs if np.isfinite(s)])
    var = float(finite.var(ddof=1)) if len(finite) > 1 else 0.0
    for row in rows:
        if np.isfinite(row["sr"]):
            d = deflated_sharpe_ratio(row["sr"], row["n"], k, var, row["skew"], row["kurt"])
            row.update({"sr0": d["sr0"], "dsr": d["dsr"], "p_value": d["p_value"]})
        else:
            row.update({"sr0": float("nan"), "dsr": float("nan"), "p_value": float("nan")})
    best = max(rows, key=lambda r: r["sr"] if np.isfinite(r["sr"]) else -np.inf) if rows else None
    return {"n_trials": k, "var_sharpe": var, "sr0": expected_max_sharpe(k, var),
            "best": best["name"] if best else None, "rows": rows}


def white_reality_check(returns: np.ndarray, n_boot: int = N_BOOT_DEFAULT, seed: int = DEFAULT_SEED,
                        block_len: int = 1) -> dict:
    """White (2000) Reality Check over a grid of candidates on common dates.

    returns    (T, K) matrix: one row per date, one column per candidate, aligned by date. Subtract a
               benchmark beforehand to test outperformance. Rows must be aligned, not missing.
    H0         max over candidates of E[r_k] <= 0 (no candidate beats zero).
    Statistic  V = max_k sqrt(T) * mean_k.
    Bootstrap  circular block bootstrap of rows (block_len; 1 = i.i.d.), with each column re-centred on
               its sample mean. p = share of bootstrap maxima >= V. Deterministic for a given seed.
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2 or r.shape[0] < 2 or r.shape[1] < 1:
        raise ValueError("returns must be a (T, K) matrix with T >= 2 and K >= 1")
    if not np.isfinite(r).all():
        raise ValueError("returns must be finite; drop or align missing dates first")
    T, K = r.shape
    means = r.mean(axis=0)
    v_stat = float(np.max(math.sqrt(T) * means))
    centred = r - means
    rng = np.random.default_rng(seed)
    b = max(1, int(block_len))
    n_blocks = int(math.ceil(T / b))
    starts = rng.integers(0, T, size=(n_boot, n_blocks))
    idx = ((starts[:, :, None] + np.arange(b)) % T).reshape(n_boot, n_blocks * b)[:, :T]
    counts = np.zeros((n_boot, T))
    rows = np.repeat(np.arange(n_boot), T)
    np.add.at(counts, (rows, idx.ravel()), 1.0)
    boot_means = counts @ centred / T                     # (n_boot, K) re-centred bootstrap means
    boot_max = np.max(math.sqrt(T) * boot_means, axis=1)
    p = float(np.mean(boot_max >= v_stat))
    return {"n_dates": int(T), "n_candidates": int(K), "statistic": v_stat, "p_value": p,
            "best": int(np.argmax(means)), "n_boot": int(n_boot), "seed": int(seed), "block_len": b}
