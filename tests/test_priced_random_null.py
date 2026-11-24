import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from priced_random_null import compare, resample_null  # noqa: E402


def _data():
    rng = np.random.default_rng(1)
    yrs = np.repeat([2019, 2020, 2021], 40)
    ym = np.array([f"{y}-{(i % 12) + 1:02d}" for y in (2019, 2020, 2021) for i in range(40)])
    pl = rng.normal(0, 100, 120)
    return pl, yrs, ym


def test_stratified_sizes_and_determinism():
    pl, yrs, _ = _data()
    counts = {2019: 10, 2020: 5, 2021: 20}
    m1, s1 = resample_null(pl, yrs, counts, draws=50, seed=3)
    m2, _ = resample_null(pl, yrs, counts, draws=50, seed=3)
    assert (s1 == 35).all() and np.allclose(m1, m2)


def test_null_mean_near_population_mean():
    pl, yrs, _ = _data()
    m, _ = resample_null(pl, yrs, {2019: 20, 2020: 20, 2021: 20}, draws=500, seed=0)
    assert abs(m.mean() - pl.mean()) < 5


def test_block_draws_whole_months():
    pl, yrs, ym = _data()
    m, s = resample_null(pl, yrs, {2019: 10, 2020: 10, 2021: 10}, draws=50, seed=0, blocks=ym)
    assert (s >= 30).all() and np.isfinite(m).all()


def test_overdraw_raises():
    pl, yrs, _ = _data()
    with pytest.raises(ValueError):
        resample_null(pl, yrs, {2019: 99}, draws=2)


def test_compare_extremes():
    null = np.linspace(-1, 1, 1000)
    hi = compare(5.0, null)
    assert hi["percentile"] == 100.0 and hi["p_one_sided"] < 0.01
    lo = compare(-5.0, null)
    assert lo["percentile"] == 0.0 and lo["p_one_sided"] > 0.99
