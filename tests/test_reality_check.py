"""Synthetic checks for scripts/reality_check.py: noise cells give high p, a planted edge gives low p."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import reality_check as rc  # noqa: E402


def test_noise_cells_high_p():
    rng = np.random.default_rng(1)
    D = rng.normal(0, 100, (1200, 20))
    r = rc.reality_check(D, n_boot=600, mean_block=10, seed=3)
    assert r["p_rc"] > 0.15
    assert r["p_spa"] > 0.15


def test_planted_edge_low_p():
    rng = np.random.default_rng(2)
    D = rng.normal(0, 100, (1200, 20))
    D[:, 7] += 40
    r = rc.reality_check(D, n_boot=600, mean_block=10, seed=3)
    assert r["best_idx"] == 7
    assert r["p_rc"] < 0.05
    assert r["p_spa"] < 0.05


def test_holm_monotone_and_bounds():
    p = np.array([0.001, 0.04, 0.2, 0.5])
    a = rc.holm(p)
    assert np.all(a >= p) and np.all(a <= 1)
    assert np.isclose(a[0], 0.004)
    assert np.all(np.diff(a[np.argsort(p)]) >= 0)


def test_noise_holm_and_dsr():
    rng = np.random.default_rng(5)
    xs = [rng.normal(0, 100, 150) for _ in range(30)]
    ps = [rc.trade_stats(x)["p_raw"] for x in xs]
    assert rc.holm(ps).min() > 0.05
    srs = [x.mean() / x.std(ddof=1) for x in xs]
    d = rc.deflated_sharpe(xs[int(np.argmax(srs))], 30, float(np.var(srs, ddof=1)))
    assert d["dsr"] < 0.9
    edge = rng.normal(60, 100, 150)
    assert rc.trade_stats(edge)["p_raw"] < 0.001
