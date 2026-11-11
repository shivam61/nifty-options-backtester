"""Normalised trade table: column contract, validation and file readers.

One row = one closed trade of one strategy (or hedged variant) at `lots` lots.

Units and conventions (every Rs column is a TOTAL for the trade at `lots` lots):
  strategy         label of the strategy / variant (string)
  entry_date       trade entry (fill) date
  exit_date        trade exit date (expiry settle for hold-to-expiry trades)
  expiry           option expiry date (NaT when not applicable)
  lots             lots traded (integer >= 1); per-lot figures are value / lots
  credit_rs        net premium received at entry, Rs (> 0 for a credit strategy)
  max_loss_rs      defined worst loss at expiry, Rs (NaN when the structure has undefined risk)
  pnl_gross_rs     P&L before costs, including hedge P&L and slippage already in the fills
  cost_rs          all costs, Rs (fees, slippage, hedge costs)
  pnl_net_rs       net P&L, identity: pnl_net_rs = pnl_gross_rs - cost_rs (within 1 Rs)
  exit_reason      why the trade closed (string; 'unknown' if not recorded)
  entry_vix        India VIX at entry (NaN if not recorded)
  hedge_cost_rs    part of cost_rs attributable to a hedge (0 for unhedged trades)
  slippage_rs      optional. Part of the costs/fills that is slippage. Lets the stress scale
                   slippage alone. NaN = unknown: stress then scales the whole cost_rs.
  base_haircut_pct optional. Credit haircut (percent) already baked into the file's pricing,
                   e.g. 30 for a file priced under the 30% haircut regime. Default 0.
  pricing_source   'bs' (Black-Scholes model prices), 'chain' (real EOD archive settles) or
                   'live' (quote log / real fills). Only 'chain' and 'live' can yield PASS.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "strategy", "entry_date", "exit_date", "lots", "credit_rs",
    "pnl_gross_rs", "cost_rs", "pnl_net_rs", "pricing_source",
]
# Optional columns and the value used when a file does not carry them.
OPTIONAL_DEFAULTS: dict = {
    "expiry": pd.NaT,
    "max_loss_rs": np.nan,
    "exit_reason": "unknown",
    "entry_vix": np.nan,
    "hedge_cost_rs": 0.0,
    "slippage_rs": np.nan,
    "base_haircut_pct": 0.0,
}
NUMERIC_COLUMNS = [
    "credit_rs", "max_loss_rs", "pnl_gross_rs", "cost_rs", "pnl_net_rs",
    "entry_vix", "hedge_cost_rs", "slippage_rs", "base_haircut_pct",
]
TRADE_COLUMNS = REQUIRED_COLUMNS[:3] + ["expiry"] + ["lots"] + [
    "credit_rs", "max_loss_rs", "pnl_gross_rs", "cost_rs", "pnl_net_rs",
    "exit_reason", "entry_vix", "hedge_cost_rs", "slippage_rs", "base_haircut_pct",
    "pricing_source",
]
PRICING_SOURCES = ("bs", "chain", "live")
IDENTITY_TOL_RS = 1.0


class SchemaError(ValueError):
    """Raised when a trade table does not satisfy the normalised schema."""


def validate(df: pd.DataFrame) -> None:
    """Check a normalised frame. Raises SchemaError listing every problem found."""
    problems: list[str] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"missing required columns: {missing}")
    if df.empty:
        return
    if df["strategy"].isna().any():
        problems.append("strategy has missing values")
    for col in ("entry_date", "exit_date"):
        if df[col].isna().any():
            problems.append(f"{col} has missing values")
    bad_src = sorted(set(df["pricing_source"].astype(str)) - set(PRICING_SOURCES))
    if bad_src:
        problems.append(f"pricing_source must be one of {PRICING_SOURCES}, got {bad_src}")
    lots = df["lots"]
    if (lots.isna() | (lots < 1)).any():
        problems.append("lots must be an integer >= 1 on every row")
    if ((df["exit_date"] < df["entry_date"])).any():
        problems.append("exit_date before entry_date on some rows")
    for col in ("credit_rs", "pnl_gross_rs", "cost_rs", "pnl_net_rs"):
        if not np.isfinite(df[col].to_numpy(float)).all():
            problems.append(f"{col} has non-finite values")
    if (df["hedge_cost_rs"] < -IDENTITY_TOL_RS).any():
        problems.append("hedge_cost_rs must be >= 0")
    if (df["hedge_cost_rs"] > df["cost_rs"] + IDENTITY_TOL_RS).any():
        problems.append("hedge_cost_rs cannot exceed cost_rs (hedge cost is part of cost_rs)")
    identity = df["pnl_gross_rs"] - df["cost_rs"] - df["pnl_net_rs"]
    if (identity.abs() > IDENTITY_TOL_RS).any():
        problems.append(
            f"pnl_net_rs != pnl_gross_rs - cost_rs on {int((identity.abs() > IDENTITY_TOL_RS).sum())} rows")
    hc = df["base_haircut_pct"]
    if ((hc < 0) | (hc >= 100)).any():
        problems.append("base_haircut_pct must be in [0, 100)")
    if problems:
        raise SchemaError("; ".join(problems))


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Fill optional columns, coerce types, validate, and sort by entry then exit date."""
    out = df.copy()
    missing = [c for c in REQUIRED_COLUMNS if c not in out.columns]
    if missing:
        raise SchemaError(f"missing required columns: {missing}")
    for col, default in OPTIONAL_DEFAULTS.items():
        if col not in out.columns:
            out[col] = default
    out["entry_date"] = pd.to_datetime(out["entry_date"]).dt.normalize()
    out["exit_date"] = pd.to_datetime(out["exit_date"]).dt.normalize()
    out["expiry"] = pd.to_datetime(out["expiry"]).dt.normalize()
    for col in NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype(float)
    out["hedge_cost_rs"] = out["hedge_cost_rs"].fillna(0.0)
    out["base_haircut_pct"] = out["base_haircut_pct"].fillna(0.0)
    out["lots"] = pd.to_numeric(out["lots"], errors="coerce")
    out["pricing_source"] = out["pricing_source"].astype(str).str.strip().str.lower()
    out["exit_reason"] = out["exit_reason"].fillna("unknown").astype(str)
    out["strategy"] = out["strategy"].astype(str)
    if out["lots"].notna().all():
        out["lots"] = out["lots"].round().astype(int)
    validate(out)
    out = out.sort_values(["entry_date", "exit_date"], kind="mergesort").reset_index(drop=True)
    return out


def read_normalized(path: str | Path) -> pd.DataFrame:
    """Read an already-normalised table from CSV, pickle (DataFrame or record list) or JSON records."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        raw = pd.read_csv(path)
    elif suffix in (".pkl", ".pickle"):
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
        raw = obj if isinstance(obj, pd.DataFrame) else pd.DataFrame(obj)
    elif suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        records = obj["trades"] if isinstance(obj, dict) and "trades" in obj else obj
        raw = pd.DataFrame(records)
    else:
        raise SchemaError(f"unsupported trade file type: {path.suffix}")
    return normalize(raw)
