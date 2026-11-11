"""Pricing and cost stress: pure functions that rescore a normalised trade table.

Convention (credit haircut): a haircut h removes the fraction h of the credit actually received.
P&L falls by h * credit, as in scratchpad structure_search.py regime A
(`cr = cr_bs * (1 - haircut)`, `gross = (cr - payoff) * QTY`). Strikes, exits, fills of the
hedge and the expiry payoff are unchanged. Limitation: the haircut shifts only the credit. It does
not re-derive exchange/STT fees on the lower notional (a small, conservative omission), and it
does not re-run stop or exit triggers that depend on premium paths.

If a file was already priced under a base haircut b (base_haircut_pct), only the incremental
haircut is applied, so the total haircut equals h: x = (h - b) / (1 - b), applied to the credit
that remains. Stresses at or below b leave the trade unchanged.

Convention (slippage multiplier m): extra cost = (m - 1) * slippage_rs, where slippage_rs is the
slippage part of the costs (NaN means unknown; then the whole cost_rs is scaled, which
overstates the stress because fees do not scale with slippage). This is linear in m. The
engine re-run at a different multiplier can differ slightly because exit triggers depend on fills.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HAIRCUTS_DEFAULT = (0.0, 0.15, 0.30)
SLIPPAGE_DEFAULT = (1.0, 1.5, 2.0)


def stress_trades(df: pd.DataFrame, haircut: float = 0.0, slippage_mult: float = 1.0) -> pd.DataFrame:
    """Return a copy of `df` rescored at credit haircut `haircut` (0..1) and slippage `slippage_mult`.

    Updates pnl_gross_rs, cost_rs and pnl_net_rs so that the schema identity still holds.
    The input frame is not modified.
    """
    if not 0.0 <= haircut < 1.0:
        raise ValueError("haircut must be in [0, 1)")
    out = df.copy()
    base = out["base_haircut_pct"].to_numpy(float) / 100.0
    h_inc = np.clip((haircut - base) / (1.0 - base), 0.0, 1.0)
    haircut_rs = h_inc * out["credit_rs"].to_numpy(float)

    slip = out["slippage_rs"].to_numpy(float)
    slip_base = np.where(np.isfinite(slip), slip, out["cost_rs"].to_numpy(float))
    extra_cost = (slippage_mult - 1.0) * slip_base

    out["pnl_gross_rs"] = out["pnl_gross_rs"].to_numpy(float) - haircut_rs
    out["cost_rs"] = out["cost_rs"].to_numpy(float) + extra_cost
    out["pnl_net_rs"] = out["pnl_gross_rs"] - out["cost_rs"]
    return out


def per_lot(df: pd.DataFrame, col: str = "pnl_net_rs") -> np.ndarray:
    """Per-lot Rs values of a column (value / lots)."""
    return (df[col].to_numpy(float) / df["lots"].to_numpy(float))


def stress_grid(df: pd.DataFrame, haircuts=HAIRCUTS_DEFAULT, slippages=SLIPPAGE_DEFAULT) -> pd.DataFrame:
    """One summary row per (haircut, slippage) cell: n, expectancy per lot, win rate, P5, worst."""
    rows = []
    for h in haircuts:
        for m in slippages:
            s = stress_trades(df, haircut=h, slippage_mult=m)
            pl = per_lot(s)
            rows.append({
                "haircut": h, "slippage_mult": m, "n": int(len(pl)),
                "expectancy_per_lot": float(np.mean(pl)) if len(pl) else float("nan"),
                "win_rate": float(np.mean(pl > 0)) if len(pl) else float("nan"),
                "p5_per_lot": float(np.percentile(pl, 5)) if len(pl) else float("nan"),
                "worst_per_lot": float(np.min(pl)) if len(pl) else float("nan"),
                "total_per_lot": float(np.sum(pl)),
            })
    return pd.DataFrame(rows)
