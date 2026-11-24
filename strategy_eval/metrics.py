"""Descriptive metrics on a normalised trade table. All per-lot figures are Rs per lot.

Win rate and breakeven win rate are reported for context only. The verdict never uses them
(see strategy_eval.verdict). Expectancy, year consistency and the bootstrap decide.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from strategy_eval.stress import per_lot


def span_years(df: pd.DataFrame) -> float:
    """Years from the first entry to the last exit (NaN for an empty or zero-length table)."""
    if df.empty:
        return float("nan")
    days = (df["exit_date"].max() - df["entry_date"].min()).days
    return days / 365.25 if days > 0 else float("nan")


def max_drawdown_per_lot(df: pd.DataFrame) -> float:
    """Maximum peak-to-trough drop of the cumulative per-lot P&L, trades ordered by exit then entry.

    The peak starts at 0, so a losing opening run counts as a drawdown. Returned as a positive Rs value.
    """
    if df.empty:
        return float("nan")
    ordered = df.sort_values(["exit_date", "entry_date"], kind="mergesort")
    cum = np.cumsum(per_lot(ordered))
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float(max(np.max(peak - cum), 0.0))


def core_metrics(df: pd.DataFrame) -> dict:
    """Expectancy, payoff, breakeven vs actual win rate, tails, drawdown, Sharpe-like, span."""
    pl = per_lot(df)
    n = len(pl)
    if n == 0:
        return {"n": 0}
    wins = pl[pl > 0]
    losses = pl[pl < 0]
    avg_win = float(wins.mean()) if len(wins) else float("nan")
    avg_loss = float(losses.mean()) if len(losses) else float("nan")
    payoff = avg_win / abs(avg_loss) if len(wins) and len(losses) else float("nan")
    breakeven = (abs(avg_loss) / (avg_win + abs(avg_loss))
                 if len(wins) and len(losses) else float("nan"))
    credit_pl = float(np.mean(df["credit_rs"].to_numpy(float) / df["lots"].to_numpy(float)))
    worst = float(pl.min())
    years = span_years(df)
    std = float(pl.std(ddof=1)) if n > 1 else float("nan")
    per_year_trades = n / years if years and not math.isnan(years) else float("nan")
    sharpe = (float(pl.mean()) / std * math.sqrt(per_year_trades)
              if std and std > 0 and not math.isnan(per_year_trades) else float("nan"))
    return {
        "n": n,
        "expectancy_per_lot": float(pl.mean()),
        "median_per_lot": float(np.median(pl)),
        "total_per_lot": float(pl.sum()),
        "win_rate_actual": float(len(wins) / n),
        "breakeven_win_rate": breakeven,
        "avg_win_per_lot": avg_win,
        "avg_loss_per_lot": avg_loss,
        "payoff_ratio": payoff,
        "p5_per_lot": float(np.percentile(pl, 5)),
        "worst_per_lot": worst,
        "credit_per_lot": credit_pl,
        "tail_ratio_worst_over_credit": (worst / credit_pl) if credit_pl > 0 else float("nan"),
        "max_drawdown_per_lot": max_drawdown_per_lot(df),
        "sharpe_like": sharpe,
        "trades_per_year": per_year_trades,
        "span_years": years,
    }


def per_year_table(df: pd.DataFrame) -> pd.DataFrame:
    """Year (by entry date): n, win rate, mean and total per-lot P&L, positive flag."""
    if df.empty:
        return pd.DataFrame(columns=["year", "n", "win_rate", "mean_per_lot", "total_per_lot", "positive"])
    tmp = pd.DataFrame({"year": df["entry_date"].dt.year.to_numpy(), "pl": per_lot(df)})
    rows = []
    for year, g in tmp.groupby("year", sort=True):
        rows.append({
            "year": int(year), "n": int(len(g)), "win_rate": float((g["pl"] > 0).mean()),
            "mean_per_lot": float(g["pl"].mean()), "total_per_lot": float(g["pl"].sum()),
            "positive": bool(g["pl"].mean() > 0),
        })
    return pd.DataFrame(rows)


VIX_BUCKETS = (("<13", -np.inf, 13.0), ("13-16", 13.0, 16.0), ("16-20", 16.0, 20.0),
               ("20-25", 20.0, 25.0), ("25+", 25.0, np.inf))


def vix_bucket_table(df: pd.DataFrame) -> dict:
    """Per entry-VIX bucket (lower bound inclusive): n, share, expectancy and win rate per lot.

    Uses the optional `entry_vix` column. If the column is absent or has no finite value, returns
    available=False and the report prints n/a. Trades without a VIX reading are counted in unknown_vix_n.
    Win rate is context only.
    """
    if df.empty or "entry_vix" not in df.columns:
        return {"available": False, "rows": [], "unknown_vix_n": int(len(df))}
    vix = df["entry_vix"].to_numpy(float)
    known = np.isfinite(vix)
    if not known.any():
        return {"available": False, "rows": [], "unknown_vix_n": int(len(df))}
    pl = per_lot(df)
    rows = []
    for label, lo, hi in VIX_BUCKETS:
        m = known & (vix >= lo) & (vix < hi)
        n = int(m.sum())
        rows.append({
            "bucket": label, "n": n, "share": n / len(df),
            "expectancy_per_lot": float(pl[m].mean()) if n else float("nan"),
            "win_rate": float((pl[m] > 0).mean()) if n else float("nan"),
        })
    return {"available": True, "rows": rows, "unknown_vix_n": int((~known).sum())}


def exit_reason_mix(df: pd.DataFrame) -> pd.DataFrame:
    """Count, share and mean per-lot P&L for each exit reason."""
    if df.empty:
        return pd.DataFrame(columns=["exit_reason", "n", "share", "mean_per_lot"])
    tmp = pd.DataFrame({"exit_reason": df["exit_reason"].to_numpy(), "pl": per_lot(df)})
    g = tmp.groupby("exit_reason").agg(n=("pl", "size"), mean_per_lot=("pl", "mean")).reset_index()
    g["share"] = g["n"] / len(tmp)
    return g.sort_values("n", ascending=False).reset_index(drop=True)


def sizing(df: pd.DataFrame, capital: float, risk_cap: float) -> dict:
    """Implied CAGR and return on the risk budget with lots capped so worst loss <= risk_cap.

    Risk per lot of a trade = max_loss_rs / lots when the structure has a defined max loss; otherwise
    the realised per-lot loss of that trade (a sizing guide, not a guarantee, for undefined-risk trades).
    worst_loss_per_lot = max over trades. lots_cap = floor(risk_cap / worst_loss_per_lot), fixed for
    the whole table (no compounding, no SPAN margin model).
    Implied CAGR = ((capital + total P&L at lots_cap) / capital) ** (1 / years) - 1.
    Return on margin (proxy) = annual P&L at lots_cap / risk_cap, where risk_cap stands in for margin.
    """
    if df.empty:
        return {"lots_cap": 0, "note": "no trades"}
    pl = per_lot(df)
    ml = df["max_loss_rs"].to_numpy(float) / df["lots"].to_numpy(float)
    realised = np.maximum(-pl, 0.0)
    risk_pl = np.where(np.isfinite(ml), ml, realised)
    worst_pl = float(np.max(risk_pl))
    undefined = int((~np.isfinite(ml)).sum())
    if worst_pl <= 0:
        return {"lots_cap": None, "note": "no positive per-lot risk; cannot size"}
    lots_cap = int(math.floor(risk_cap / worst_pl))
    years = span_years(df)
    if lots_cap < 1:
        return {"lots_cap": 0, "worst_loss_per_lot": worst_pl, "risk_cap": risk_cap,
                "note": "risk cap is below the worst loss of one lot"}
    total = float(pl.sum() * lots_cap)
    end_equity = capital + total
    cagr = (end_equity / capital) ** (1.0 / years) - 1.0 if end_equity > 0 and years else -1.0
    annual = total / years if years else float("nan")
    return {
        "capital": capital, "risk_cap": risk_cap, "lots_cap": lots_cap,
        "worst_loss_per_lot": worst_pl, "worst_loss_at_lots_rs": worst_pl * lots_cap,
        "trades_without_defined_max_loss": undefined,
        "total_pnl_at_lots_cap": total, "annual_pnl_at_lots_cap": annual,
        "implied_cagr": cagr, "return_on_margin_proxy": annual / risk_cap if risk_cap else float("nan"),
        "span_years": years,
    }
