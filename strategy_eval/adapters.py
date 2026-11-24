"""Adapters from existing research outputs to the normalised trade schema (strategy_eval.schema).

Adapters:
  from_chain_trades   backtester.chain_engine.ChainBacktest trade records (trades_x<m>.json)
  from_run69_trades   combined-engine trade dumps (scratch run69_trades.json, track/strategy records)
  from_h9_frame       scratch H9 hedge CSVs (entry, expiry, opt_pnl, fut_pnl, opt_cost, fut_cost, net)

defined_max_loss_per_unit() computes the worst expiry loss of any leg set from its payoff, so
the chain adapter does not depend on the repo's approximate Trade.max_loss heuristic.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_eval.schema import SchemaError, normalize, read_normalized, REQUIRED_COLUMNS

DEFAULT_LOT_SIZE = 65


def _is_call(option_type) -> bool:
    s = str(option_type).upper()
    return "CALL" in s or s in ("C", "CE") or s.endswith(".CE")


def defined_max_loss_per_unit(legs: list[dict], credit_per_unit: float) -> float:
    """Worst expiry loss per unit (index points) of a leg set, or NaN if the loss is unbounded.

    legs: dicts with keys 'type' ('CE'/'PE' or call/put), 'strike', 'short' (bool); quantity 1 each.
    The payoff is piecewise linear in the settle X, so its minimum sits at X = 0, at a strike,
    or at X -> infinity. A negative slope at infinity (more short calls than long calls) means
    the loss is unbounded and NaN is returned.
    """
    if not legs:
        return 0.0
    strikes = sorted({float(l["strike"]) for l in legs})
    short_calls = sum(1 for l in legs if l["short"] and _is_call(l["type"]))
    long_calls = sum(1 for l in legs if not l["short"] and _is_call(l["type"]))
    if short_calls > long_calls:
        return float("nan")

    def pnl_at(x: float) -> float:
        total = float(credit_per_unit)
        for l in legs:
            k = float(l["strike"])
            intr = max(x - k, 0.0) if _is_call(l["type"]) else max(k - x, 0.0)
            total += -intr if l["short"] else intr
        return total

    worst = min(pnl_at(x) for x in [0.0] + strikes)
    return max(0.0, -worst)


def from_chain_trades(records: list[dict], lot_size: int = DEFAULT_LOT_SIZE) -> pd.DataFrame:
    """Chain-engine trade records -> normalised frame (pricing_source='chain').

    Mapping (chain_engine.ChainBacktest._close):
      entry_date <- fill_date, exit_date <- exit date, expiry <- expiry, lots <- lots
      credit_rs <- entry_credit_fill (points/unit) * lot_size * lots
      max_loss_rs <- defined_max_loss_per_unit(legs, entry_credit_fill) * lot_size * lots
      pnl_gross_rs <- gross_fill_rs (fills vs archive settle, includes slippage)
      cost_rs <- fee_rs (per-order fee schedule); pnl_net_rs = pnl (= gross_fill_rs - fee_rs)
      slippage_rs <- entry_pen_rs + close_slip_rs (both already Rs totals in the engine)
    """
    rows = []
    for r in records:
        lots = int(r["lots"])
        credit_ps = float(r["entry_credit_fill"])
        ml_ps = defined_max_loss_per_unit(r.get("legs", []), credit_ps)
        rows.append({
            "strategy": str(r.get("strategy", "chain")),
            "entry_date": r["fill_date"],
            "exit_date": r["exit_date"],
            "expiry": r.get("expiry"),
            "lots": lots,
            "credit_rs": credit_ps * lot_size * lots,
            "max_loss_rs": ml_ps * lot_size * lots if not math.isnan(ml_ps) else float("nan"),
            "pnl_gross_rs": float(r["gross_fill_rs"]),
            "cost_rs": float(r["fee_rs"]),
            "pnl_net_rs": float(r["gross_fill_rs"]) - float(r["fee_rs"]),
            "exit_reason": str(r.get("exit_reason", "unknown")),
            "entry_vix": r.get("entry_vix", float("nan")),
            "hedge_cost_rs": 0.0,
            "slippage_rs": float(r.get("entry_pen_rs", 0.0)) + float(r.get("close_slip_rs", 0.0)),
            "base_haircut_pct": 0.0,
            "pricing_source": "chain",
        })
    return normalize(pd.DataFrame(rows))


def from_run69_trades(records: list[dict]) -> pd.DataFrame:
    """Combined-engine trade records (run69-style dump) -> normalised frame (pricing_source='bs').

    The dump's 'max_loss_per_unit' is the repo's Trade.max_loss, which is a TOTAL in Rs for the
    trade (it already includes lots and lot size; checked: value / (lots*65) is about 186 pts per
    unit). It is used as max_loss_rs directly. That heuristic is not reproduced here.
    Monthly and weekly tracks are kept as one table; strategy = '<track>:<strategy>'.
    """
    rows = []
    for r in records:
        lots = int(r["lots"])
        lot_size = int(r.get("lot_size", DEFAULT_LOT_SIZE))
        gross = float(r["gross_pnl_pre_cost"])
        net = float(r["total_pnl"])
        rows.append({
            "strategy": f"{r.get('track', 'trade')}:{r.get('strategy', '?')}",
            "entry_date": r["entry_date"],
            "exit_date": r["exit_date"],
            "expiry": None,
            "lots": lots,
            "credit_rs": float(r["net_credit_per_unit"]) * lot_size * lots,
            "max_loss_rs": float(r["max_loss_per_unit"]),
            "pnl_gross_rs": gross,
            "cost_rs": gross - net,
            "pnl_net_rs": net,
            "exit_reason": str(r.get("exit_reason", "unknown")),
            "entry_vix": r.get("entry_vix", float("nan")),
            "hedge_cost_rs": 0.0,
            "slippage_rs": float("nan"),
            "base_haircut_pct": 0.0,
            "pricing_source": "bs",
        })
    return normalize(pd.DataFrame(rows))


def from_h9_frame(df: pd.DataFrame, input_haircut_pct: float = 0.0) -> pd.DataFrame:
    """Scratch H9 hedge CSV (h9_sim.policy_sim output) -> normalised frame (pricing_source='bs').

    Each row is one trade at 1 lot (the sim divides whole-lot books back to per-lot Rs).
    Mapping: entry_date <- entry, expiry <- expiry, exit_date <- expiry (hold to expiry, cash
    settled), credit_rs <- credit, pnl_gross_rs <- opt_pnl + fut_pnl, cost_rs <- opt_cost + fut_cost,
    pnl_net_rs <- net, hedge_cost_rs <- fut_cost (futures hedge costs), max_loss_rs NaN (short
    strangle, undefined risk without a long wing).
    input_haircut_pct: the haircut the file was priced with (regA files = 30, regB = 0). It is
    recorded so that stress haircuts apply only on top of it.
    """
    need = ["entry", "expiry", "credit", "opt_pnl", "fut_pnl", "opt_cost", "fut_cost", "net"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise SchemaError(f"H9 csv missing columns {miss}")
    d = pd.DataFrame({
        "strategy": "h9",
        "entry_date": pd.to_datetime(df["entry"]),
        "exit_date": pd.to_datetime(df["expiry"]),
        "expiry": pd.to_datetime(df["expiry"]),
        "lots": 1,
        "credit_rs": df["credit"].astype(float),
        "max_loss_rs": np.nan,
        "pnl_gross_rs": df["opt_pnl"].astype(float) + df["fut_pnl"].astype(float),
        "cost_rs": df["opt_cost"].astype(float) + df["fut_cost"].astype(float),
        "pnl_net_rs": df["net"].astype(float),
        "exit_reason": "expiry",
        "entry_vix": df["V0"].astype(float) if "V0" in df.columns else np.nan,
        "hedge_cost_rs": df["fut_cost"].astype(float),
        "slippage_rs": np.nan,
        "base_haircut_pct": float(input_haircut_pct),
        "pricing_source": "bs",
    })
    return normalize(d)


def _csv_has(path: Path, cols: list[str]) -> bool:
    head = pd.read_csv(path, nrows=0).columns
    return all(c in head for c in cols)


def load_trades(path: str | Path, *, adapter: str = "auto", name: str | None = None,
                input_haircut_pct: float = 0.0, lot_size: int = DEFAULT_LOT_SIZE) -> pd.DataFrame:
    """Load any supported trade file into the normalised schema.

    adapter: 'auto' (detect), 'normal' (already normalised), 'chain', 'run69' or 'h9'.
    Auto detection: JSON with 'pnl_per_lot' records -> chain; JSON with 'gross_pnl_pre_cost' ->
    run69; CSV with H9 columns -> h9; otherwise the normalised schema.
    """
    path = Path(path)
    if adapter == "auto":
        adapter = _detect(path)
    if adapter == "normal":
        return read_normalized(path)
    if adapter == "chain":
        recs = json.loads(path.read_text(encoding="utf-8"))["trades"]
        return from_chain_trades(recs, lot_size=lot_size)
    if adapter == "run69":
        obj = json.loads(path.read_text(encoding="utf-8"))
        recs = obj["trades"] if isinstance(obj, dict) else obj
        return from_run69_trades(recs)
    if adapter == "h9":
        return from_h9_frame(pd.read_csv(path), input_haircut_pct=input_haircut_pct)
    raise SchemaError(f"unknown adapter {adapter!r}")


def _detect(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        obj = json.loads(path.read_text(encoding="utf-8"))
        recs = obj["trades"] if isinstance(obj, dict) and "trades" in obj else obj
        if recs and "pnl_per_lot" in recs[0]:
            return "chain"
        if recs and "gross_pnl_pre_cost" in recs[0]:
            return "run69"
        return "normal"
    if suffix == ".csv":
        if _csv_has(path, REQUIRED_COLUMNS):
            return "normal"
        if _csv_has(path, ["entry", "expiry", "opt_pnl", "fut_pnl", "net"]):
            return "h9"
        raise SchemaError(f"cannot detect adapter for {path.name}")
    return "normal"
