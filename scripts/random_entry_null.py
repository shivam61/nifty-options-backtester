#!/usr/bin/env python3
"""Mean-zero bootstrap null for the per-lot expectancy of a trade file (audit fix 6). NOT an entry-timing test.

What it does. Reads one trade file (any format strategy_eval.load_trades accepts, chain-engine format included),
keeps the trades whose entry date falls in --start..--end, and takes per-lot net P&L (pnl_net_rs / lots). It then:

    1. centres the per-lot P&L at zero (subtracts its mean), which is the null H0: mean <= 0;
    2. bootstrap-resamples n trades with replacement from the centred values, --n-boot times (default 10,000),
       with numpy default_rng(--seed), seed 20261111 by default;
    3. reports the one-sided p of the OBSERVED mean: the share of bootstrap means >= the observed mean, with the
       usual +1 correction so p is never reported as exactly 0;
    4. reports the 5th and 95th percentiles of the null (bootstrap) distribution of the mean.

What this tests, and what it does not. This tests ONLY whether the mean per-lot P&L is greater than zero, under
resampling of the trades as if they were independent draws from a zero-mean distribution. It is NOT an entry-timing
test. It does not ask whether the entry dates carry any information: the trades keep their own P&L, and only the
mean is tested. A strategy with a positive mean from a bad entry rule passes it. A random-entry null (500 random-entry
draws priced via chain settle lookups, as in the pre-registration's timing question) is a separate, larger job. It is
NOT done here.

Window. Only the dates --start..--end are used. Any window end later than 2023-12-31 is refused: this script does not
read the 2024+ holdout, and it takes no --allow-holdout flag.

Example:
    python scripts/random_entry_null.py --trades logs/round2/train_x1/trades_C2.json \
        --start 2019-02-11 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from strategy_eval import DEV_END, load_trades  # noqa: E402
from strategy_eval.stress import per_lot  # noqa: E402

DEFAULT_SEED = 20261111
DEFAULT_N_BOOT = 10_000


def window_per_lot(trades: pd.DataFrame, start: date, end: date) -> np.ndarray:
    """Per-lot net P&L of the trades whose entry date is in [start, end] (inclusive). Order is the file order."""
    entry = pd.to_datetime(trades["entry_date"]).dt.date
    keep = (entry >= start) & (entry <= end)
    return per_lot(trades.loc[keep.to_numpy()], "pnl_net_rs")


def mean_zero_bootstrap(pl, n_boot: int = DEFAULT_N_BOOT, seed: int = DEFAULT_SEED) -> dict:
    """One-sided mean-zero bootstrap test of H0: mean <= 0 (see the module docstring for what this does not test).

    p = (1 + #{boot mean >= observed}) / (1 + n_boot). Raises ValueError for fewer than 2 trades.
    """
    x = np.asarray(pl, dtype=float)
    n = int(x.size)
    if n < 2 or not np.all(np.isfinite(x)):
        raise ValueError(f"need at least 2 finite per-lot P&L values, got {n}")
    observed = float(x.mean())
    centred = x - observed
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = centred[idx].mean(axis=1)
    p = (1 + int(np.sum(boot_means >= observed))) / (1 + n_boot)
    return {
        "n": n, "observed_mean_per_lot": observed, "p_one_sided": float(p),
        "null_p5": float(np.percentile(boot_means, 5)), "null_p95": float(np.percentile(boot_means, 95)),
        "n_boot": int(n_boot), "seed": int(seed),
        "null": "mean-zero bootstrap of per-lot net P&L (tests mean > 0 only; not an entry-timing test)",
    }


def run_null(trades_path: Path, start: date, end: date, n_boot: int = DEFAULT_N_BOOT,
             seed: int = DEFAULT_SEED) -> dict:
    if end > DEV_END:
        raise ValueError(f"refusing window end {end}: later than {DEV_END} (no 2024+ data in this script)")
    if start > end:
        raise ValueError("start is after end")
    df = load_trades(trades_path)
    res = mean_zero_bootstrap(window_per_lot(df, start, end), n_boot=n_boot, seed=seed)
    res.update({"trades": str(trades_path), "start": str(start), "end": str(end)})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", type=Path, required=True, help="trade file (chain-engine or normalised format)")
    ap.add_argument("--start", type=date.fromisoformat, default=date(2019, 2, 11),
                    help="first entry date (default 2019-02-11)")
    ap.add_argument("--end", type=date.fromisoformat, default=DEV_END, help="last entry date (default 2023-12-31)")
    ap.add_argument("--n-boot", type=int, default=DEFAULT_N_BOOT, help="bootstrap draws (default %(default)s)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (default %(default)s)")
    ap.add_argument("--out", type=Path, default=None, help="optional JSON output path")
    a = ap.parse_args(argv)
    try:
        res = run_null(a.trades, a.start, a.end, n_boot=a.n_boot, seed=a.seed)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"n={res['n']} observed mean per lot {res['observed_mean_per_lot']:+,.1f} Rs")
    print(f"mean-zero bootstrap ({res['n_boot']} draws, seed {res['seed']}): one-sided p = {res['p_one_sided']:.4f}")
    print(f"null distribution of the mean: 5th pct {res['null_p5']:+,.1f} Rs, 95th pct {res['null_p95']:+,.1f} Rs")
    print("tests mean > 0 only; NOT an entry-timing test (random-entry null not done here)")
    if a.out is not None:
        a.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
