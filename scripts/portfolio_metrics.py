"""Tier 2 portfolio metrics of a capital-mode equity curve (reported beside the per-lot verdict).

Equity is the daily session curve of a capital-mode run: capital + realised + open mark-to-market.
    CAGR    = (final / capital)^(365.25 / calendar days) - 1 over the curve span
    MaxDD   = largest peak-to-trough fall of the curve
    Sharpe  = mean / sample-sd of daily equity returns x sqrt(252), risk-free rate 0
These are the same definitions as ChainBacktest.capital_summary; tests/test_candidate_engine_ext.py checks that
the two agree on one run. This module reports numbers only. It sets no pass threshold: the Tier 2 floors
(CAGR, MaxDD, Sharpe) belong in the round-2 pre-registration, not here.

Input: a CSV with columns date,equity (written from ChainBacktest.capital_curve by scripts/run_candidates.py
with --capital-mode), or any (dates, equity) sequences passed to portfolio_metrics().
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _as_date(x):
    return pd.Timestamp(x).date()


def portfolio_metrics(dates: Sequence, equity: Sequence[float], capital_rs: float) -> dict:
    """Portfolio metrics of one equity curve. Returns None for a metric that is undefined on the curve."""
    cap = float(capital_rs)
    ds = [_as_date(d) for d in dates]
    eqs = [float(e) for e in equity]
    if len(ds) != len(eqs):
        raise ValueError("dates and equity must have the same length")
    final = eqs[-1] if eqs else cap
    years = (ds[-1] - ds[0]).days / 365.25 if len(ds) > 1 else 0.0
    cagr = ((final / cap) ** (1.0 / years) - 1.0) * 100.0 if years > 0 and final > 0 and cap > 0 else None
    peak, max_dd = -math.inf, 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - e / peak)
    rets = [b / a - 1.0 for a, b in zip(eqs, eqs[1:]) if a > 0]
    sharpe = None
    if len(rets) > 1:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
        sharpe = mu / sd * math.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else None
    return {
        "capital_rs": cap,
        "start": str(ds[0]) if ds else None,
        "end": str(ds[-1]) if ds else None,
        "n_sessions": len(eqs),
        "years": round(years, 4),
        "final_equity": round(final, 2),
        "total_return_pct": round((final / cap - 1.0) * 100.0, 3) if cap else None,
        "cagr_pct": round(cagr, 3) if cagr is not None else None,
        "max_dd_pct": round(max_dd * 100.0, 3),
        "sharpe_daily_ann": round(sharpe, 3) if sharpe is not None else None,
    }


def read_equity_curve(path: str | Path) -> tuple[list, list[float]]:
    """(dates, equity) from a CSV with columns date,equity, sorted by date (audit fix 4).

    The sort is stable, so rows with the same date keep their file order. The returns and drawdown are defined on
    the time order, so an unsorted file must not change the metrics.
    """
    df = pd.read_csv(path)
    missing = {"date", "equity"} - set(df.columns)
    if missing:
        raise ValueError(f"equity curve {path} lacks columns {sorted(missing)}")
    df = df.assign(_d=[pd.Timestamp(d).date() for d in df["date"]])
    df = df.sort_values("_d", kind="mergesort")
    return list(df["_d"]), [float(e) for e in df["equity"]]


def tier2_markdown(m: dict, source: str) -> str:
    """Markdown block for the report. Numbers only; no pass or fail is attached."""
    def f(v, unit=""):
        return "n/a" if v is None else f"{v:,.2f}{unit}"
    return "\n".join([
        "## Tier 2: capital-mode portfolio (reported, not a verdict)",
        "",
        f"Source: `{source}`. Curve {m['start']} to {m['end']} ({m['n_sessions']} sessions, {m['years']} years). "
        f"Capital base Rs {m['capital_rs']:,.0f}.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| final equity (Rs) | {f(m['final_equity'])} |",
        f"| total return | {f(m['total_return_pct'], '%')} |",
        f"| CAGR | {f(m['cagr_pct'], '%')} |",
        f"| max drawdown | {f(m['max_dd_pct'], '%')} |",
        f"| Sharpe (daily returns, rf 0, annualised) | {f(m['sharpe_daily_ann'])} |",
        "",
        "Tier 1 (the per-lot verdict above) is unchanged by this block.",
        "",
    ])
