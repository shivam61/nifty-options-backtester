from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _hash_snapshot(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass
class MonthlyDiagnosticsCollector:
    """Monthly-only trade funnel and exit attribution recorder."""

    output_dir: Optional[Path] = None
    prediction_rows: list[dict[str, Any]] = field(default_factory=list)
    candidate_rows: list[dict[str, Any]] = field(default_factory=list)
    sizing_rows: list[dict[str, Any]] = field(default_factory=list)
    trade_rows: list[dict[str, Any]] = field(default_factory=list)
    _open_trade_context: dict[str, Any] = field(default_factory=dict)
    _candidate_counts: Counter = field(default_factory=Counter)

    def set_output_dir(self, output_dir: str | Path | None) -> None:
        if output_dir is None:
            self.output_dir = None
            return
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def record_prediction(
        self,
        *,
        signal_date,
        threshold: float,
        score: float,
        win_prob: float,
        train_start,
        train_end,
        feature_version: str,
        model_version: str,
        entry_features: dict[str, Any],
        eligible_strategies: list[str],
        accepted: bool,
        rejection_reason: str | None,
        regime: str,
        vix: float,
    ) -> None:
        row = {
            "signal_date": str(signal_date),
            "threshold": _safe_float(threshold),
            "score": _safe_float(score),
            "win_prob": _safe_float(win_prob),
            "train_start": str(train_start),
            "train_end": str(train_end),
            "feature_version": feature_version,
            "model_version": model_version,
            "entry_snapshot_hash": _hash_snapshot(entry_features),
            "eligible_strategies": ",".join(eligible_strategies),
            "accepted": bool(accepted),
            "rejection_reason": rejection_reason or "",
            "regime": regime,
            "vix": _safe_float(vix),
            "calibration_bucket": self._calibration_bucket(score),
            "near_miss": bool(not accepted and score >= threshold - 0.03),
        }
        self.prediction_rows.append(row)

    def record_candidate_funnel(
        self,
        *,
        signal_date,
        regime: str,
        vix: float,
        eligible_count: int,
        candidate_count: int,
        accepted: bool,
        rejection_breakdown: dict[str, int],
        selection_reason: str | None,
    ) -> None:
        self._candidate_counts.update(rejection_breakdown)
        self.candidate_rows.append({
            "signal_date": str(signal_date),
            "year": pd.Timestamp(signal_date).year if signal_date is not None else None,
            "regime": regime,
            "vix": _safe_float(vix),
            "eligible_count": int(eligible_count),
            "candidate_count": int(candidate_count),
            "accepted": bool(accepted),
            "selection_reason": selection_reason or "",
            **{f"reject_{k}": int(v) for k, v in rejection_breakdown.items()},
        })

    def record_sizing(
        self,
        *,
        signal_date,
        capital_available: float,
        base_lots: float,
        confidence_scale: float,
        regime_scale: float,
        dd_scale: float,
        final_lots: int,
        lots_before_cap: int,
        lots_cap_reason: str,
        utilization_contribution: float,
    ) -> None:
        self.sizing_rows.append({
            "signal_date": str(signal_date),
            "year": pd.Timestamp(signal_date).year if signal_date is not None else None,
            "capital_available": _safe_float(capital_available),
            "base_lots": _safe_float(base_lots),
            "confidence_scale": _safe_float(confidence_scale),
            "regime_scale": _safe_float(regime_scale),
            "dd_scale": _safe_float(dd_scale),
            "lots_before_cap": int(lots_before_cap),
            "final_lots": int(final_lots),
            "lots_cap_reason": lots_cap_reason,
            "notional_utilization_contribution": _safe_float(utilization_contribution),
        })

    def start_trade(self, **context: Any) -> None:
        context = dict(context)
        context.setdefault("pnl_history", [])
        self._open_trade_context = context

    def update_open_trade(self, pnl_per_unit: float) -> None:
        if not self._open_trade_context:
            return
        self._open_trade_context.setdefault("pnl_history", []).append(_safe_float(pnl_per_unit))

    def close_trade(
        self,
        *,
        entry_date,
        exit_date,
        exit_reason: str,
        trade,
        net_pnl: float,
        exit_signal_score: float | None = None,
    ) -> dict[str, Any]:
        pnl_history = list(self._open_trade_context.get("pnl_history", []))
        if not pnl_history:
            pnl_history = [_safe_float(getattr(trade, "pnl_per_unit", 0.0))]

        mfe = max(pnl_history)
        mae = min(pnl_history)
        realized_per_unit = _safe_float(getattr(trade, "pnl_per_unit", 0.0))
        realized_vs_max_attainable = (
            realized_per_unit / mfe if mfe > 0 else 0.0
        )
        winner_cut_early = (
            bool(realized_per_unit > 0 and mfe > 0 and realized_per_unit < mfe * 0.8)
        )

        row = {
            "entry_date": str(entry_date),
            "exit_date": str(exit_date),
            "holding_days": int(getattr(trade, "holding_days", 0)),
            "signal_date": str(self._open_trade_context.get("signal_date", entry_date)),
            "entry_signal_score": _safe_float(self._open_trade_context.get("score", 0.0)),
            "entry_win_prob": _safe_float(self._open_trade_context.get("win_prob", 0.0)),
            "entry_threshold": _safe_float(self._open_trade_context.get("threshold", 0.0)),
            "entry_regime": self._open_trade_context.get("regime", ""),
            "entry_vix": _safe_float(self._open_trade_context.get("vix", 0.0)),
            "exit_vix": _safe_float(getattr(trade, "exit_vix", 0.0)),
            "features_hash": self._open_trade_context.get("entry_snapshot_hash", ""),
            "feature_version": self._open_trade_context.get("feature_version", ""),
            "model_version": self._open_trade_context.get("model_version", ""),
            "train_start": self._open_trade_context.get("train_start", ""),
            "train_end": self._open_trade_context.get("train_end", ""),
            "strategy_name": getattr(trade, "strategy_name", ""),
            "gross_premium": _safe_float(getattr(trade, "net_credit", 0.0)),
            "risk": _safe_float(getattr(trade, "max_loss", 0.0)),
            "expected_reward": _safe_float(getattr(trade, "net_credit", 0.0)),
            "exit_reason": exit_reason,
            "exit_signal_score": _safe_float(exit_signal_score, default=np.nan)
            if exit_signal_score is not None else np.nan,
            "winner_cut_early": bool(winner_cut_early),
            "mfe": _safe_float(mfe),
            "mae": _safe_float(mae),
            "realized_pnl_per_unit": realized_per_unit,
            "realized_pnl": _safe_float(net_pnl),
            "realized_vs_max_attainable": _safe_float(realized_vs_max_attainable),
            "pnl_history": pnl_history,
            "calibration_bucket": self._calibration_bucket(self._open_trade_context.get("score", 0.0)),
        }
        self.trade_rows.append(row)
        self._open_trade_context = {}
        return row

    def summary(self) -> dict[str, Any]:
        preds = pd.DataFrame(self.prediction_rows)
        candidates = pd.DataFrame(self.candidate_rows)
        sizing = pd.DataFrame(self.sizing_rows)
        trades = pd.DataFrame(self.trade_rows)

        if trades.empty:
            return {
                "total_trades": 0,
                "candidate_count": len(candidates),
                "accepted_trades": 0,
            }

        pnls = trades["realized_pnl"].astype(float)
        winners = pnls[pnls > 0]
        losers = pnls[pnls <= 0]
        avg_win = float(winners.mean()) if len(winners) else 0.0
        avg_loss = float(losers.mean()) if len(losers) else 0.0
        profit_factor = float(winners.sum() / abs(losers.sum())) if len(losers) and abs(losers.sum()) > 0 else float("inf")
        expectancy = float(pnls.mean())
        payoff_ratio = float(avg_win / abs(avg_loss)) if avg_loss < 0 else 0.0

        out: dict[str, Any] = {
            "trade_distribution": {
                "total_trades": int(len(trades)),
                "win_rate": round(float((pnls > 0).mean() * 100), 1) if len(trades) else 0.0,
                "total_pnl": round(float(pnls.sum()), 0),
                "avg_pnl": round(float(pnls.mean()), 2),
                "median_pnl": round(float(pnls.median()), 2),
                "avg_winner": round(avg_win, 2),
                "median_winner": round(float(winners.median()), 2) if len(winners) else 0.0,
                "avg_loser": round(avg_loss, 2),
                "median_loser": round(float(losers.median()), 2) if len(losers) else 0.0,
                "payoff_ratio": round(payoff_ratio, 3),
                "profit_factor": round(profit_factor, 3) if np.isfinite(profit_factor) else float("inf"),
                "expectancy": round(expectancy, 2),
                "avg_hold": round(float(trades["holding_days"].mean()), 1),
                "hold_p10": round(float(trades["holding_days"].quantile(0.1)), 1),
                "hold_p50": round(float(trades["holding_days"].median()), 1),
                "hold_p90": round(float(trades["holding_days"].quantile(0.9)), 1),
                "yearly_pnl": self._yearly_pnl(trades),
                "regime_pnl": self._group_pnl(trades, "entry_regime"),
                "score_decile_pnl": self._score_deciles(trades),
                "entry_month_pnl": self._month_pnl(trades),
            },
            "exit_decomposition": {
                "winner_cut_early_pct": round(float(trades["winner_cut_early"].mean() * 100), 1),
                "avg_mfe": round(float(trades["mfe"].mean()), 2),
                "avg_mae": round(float(trades["mae"].mean()), 2),
                "avg_realized_vs_max_attainable": round(float(trades["realized_vs_max_attainable"].mean()), 3),
                "exit_reason_counts": trades["exit_reason"].value_counts().to_dict(),
            },
            "acceptance_funnel": {
                "candidate_count": int(len(candidates)) if not candidates.empty else int(len(preds)),
                "accepted_trades": int(len(trades)),
                "near_miss_count": int(preds["near_miss"].sum()) if not preds.empty else 0,
                "accepted_rate": round(float(len(trades) / max(len(preds), 1) * 100), 1) if not preds.empty else 0.0,
                "rejections": dict(self._candidate_counts),
                "acceptance_by_year": self._acceptance_by_year(candidates if not candidates.empty else preds),
                "acceptance_by_regime": self._acceptance_by_regime(candidates if not candidates.empty else preds),
            },
            "sizing": {
                "avg_base_lots": round(float(sizing["base_lots"].mean()), 2) if not sizing.empty else 0.0,
                "avg_confidence_scale": round(float(sizing["confidence_scale"].mean()), 3) if not sizing.empty else 0.0,
                "avg_regime_scale": round(float(sizing["regime_scale"].mean()), 3) if not sizing.empty else 0.0,
                "avg_dd_scale": round(float(sizing["dd_scale"].mean()), 3) if not sizing.empty else 0.0,
                "avg_final_lots": round(float(sizing["final_lots"].mean()), 2) if not sizing.empty else 0.0,
                "avg_capital_available": round(float(sizing["capital_available"].mean()), 2) if not sizing.empty else 0.0,
                "avg_utilization_contribution": round(float(sizing["notional_utilization_contribution"].mean()), 3) if not sizing.empty else 0.0,
            },
            "model": self._model_summary(preds, trades),
        }
        return out

    def write_artifacts(self, output_dir: str | Path) -> dict[str, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        summary = self.summary()
        paths = {}

        def _write_json(name: str, data: Any) -> None:
            path = output_dir / name
            path.write_text(json.dumps(data, indent=2, default=str))
            paths[name] = path

        def _write_csv(name: str, rows: list[dict[str, Any]]) -> None:
            path = output_dir / name
            pd.DataFrame(rows).to_csv(path, index=False)
            paths[name] = path

        _write_json("monthly_diagnostic_report.json", summary)
        _write_csv("monthly_diagnostic_trades.csv", self.trade_rows)
        _write_csv("monthly_diagnostic_candidates.csv", self.candidate_rows)
        _write_csv("monthly_diagnostic_predictions.csv", self.prediction_rows)
        _write_csv("monthly_diagnostic_sizing.csv", self.sizing_rows)

        md_path = output_dir / "monthly_diagnostic_report.md"
        md_path.write_text(self._render_markdown(summary))
        paths["monthly_diagnostic_report.md"] = md_path

        html_path = output_dir / "monthly_diagnostic_report.html"
        html_path.write_text(self._render_html(summary))
        paths["monthly_diagnostic_report.html"] = html_path

        return paths

    def _yearly_pnl(self, trades: pd.DataFrame) -> dict[str, float]:
        out = {}
        grouped = trades.copy()
        grouped["year"] = pd.to_datetime(grouped["exit_date"]).dt.year
        for year, grp in grouped.groupby("year"):
            out[str(year)] = round(float(grp["realized_pnl"].sum()), 2)
        return out

    def _group_pnl(self, trades: pd.DataFrame, column: str) -> dict[str, float]:
        out = {}
        for key, grp in trades.groupby(column):
            out[str(key)] = round(float(grp["realized_pnl"].sum()), 2)
        return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))

    def _score_deciles(self, trades: pd.DataFrame) -> dict[str, float]:
        if trades.empty:
            return {}
        work = trades.copy()
        try:
            work["decile"] = pd.qcut(work["entry_signal_score"].rank(method="first"), 10, labels=False, duplicates="drop")
        except Exception:
            work["decile"] = 0
        out = {}
        for decile, grp in work.groupby("decile"):
            out[str(int(decile) + 1)] = round(float(grp["realized_pnl"].sum()), 2)
        return out

    def _month_pnl(self, trades: pd.DataFrame) -> dict[str, float]:
        out = {}
        work = trades.copy()
        work["month"] = pd.to_datetime(work["exit_date"]).dt.to_period("M").astype(str)
        for month, grp in work.groupby("month"):
            out[month] = round(float(grp["realized_pnl"].sum()), 2)
        return dict(sorted(out.items()))

    def _acceptance_by_year(self, rows: pd.DataFrame) -> dict[str, float]:
        if rows.empty:
            return {}
        work = rows.copy()
        if "signal_date" in work.columns:
            work["year"] = pd.to_datetime(work["signal_date"]).dt.year
        elif "year" not in work.columns:
            return {}
        out = {}
        for year, grp in work.groupby("year"):
            accepted = grp["accepted"].sum() if "accepted" in grp.columns else len(grp)
            out[str(int(year))] = round(float(accepted / len(grp) * 100), 1) if len(grp) else 0.0
        return out

    def _acceptance_by_regime(self, rows: pd.DataFrame) -> dict[str, float]:
        if rows.empty or "regime" not in rows.columns:
            return {}
        out = {}
        for regime, grp in rows.groupby("regime"):
            accepted = grp["accepted"].sum() if "accepted" in grp.columns else len(grp)
            out[str(regime)] = round(float(accepted / len(grp) * 100), 1) if len(grp) else 0.0
        return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))

    def _model_summary(self, preds: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
        if preds.empty:
            return {}
        accepted = preds[preds["accepted"]]
        rejected = preds[~preds["accepted"]]
        return {
            "train_windows": self._train_windows(preds),
            "score_distribution_by_year": self._score_by_year(preds),
            "accepted_score_distribution": self._score_distribution(accepted),
            "rejected_score_distribution": self._score_distribution(rejected),
            "calibration_buckets": self._calibration_summary(preds, trades),
        }

    def _train_windows(self, preds: pd.DataFrame) -> list[dict[str, Any]]:
        cols = ["train_start", "train_end", "feature_version", "model_version"]
        if not set(cols).issubset(preds.columns):
            return []
        windows = preds[cols].drop_duplicates().to_dict("records")
        return windows[:20]

    def _score_by_year(self, preds: pd.DataFrame) -> dict[str, dict[str, float]]:
        if preds.empty or "signal_date" not in preds.columns:
            return {}
        work = preds.copy()
        work["year"] = pd.to_datetime(work["signal_date"]).dt.year
        out = {}
        for year, grp in work.groupby("year"):
            out[str(int(year))] = {
                "mean_score": round(float(grp["score"].mean()), 3),
                "accepted_mean_score": round(float(grp.loc[grp["accepted"], "score"].mean()), 3) if grp["accepted"].any() else 0.0,
                "rejected_mean_score": round(float(grp.loc[~grp["accepted"], "score"].mean()), 3) if (~grp["accepted"]).any() else 0.0,
            }
        return out

    def _score_distribution(self, rows: pd.DataFrame) -> dict[str, float]:
        if rows.empty:
            return {}
        return {
            "count": int(len(rows)),
            "p10": round(float(rows["score"].quantile(0.1)), 3),
            "p50": round(float(rows["score"].quantile(0.5)), 3),
            "p90": round(float(rows["score"].quantile(0.9)), 3),
            "mean": round(float(rows["score"].mean()), 3),
        }

    def _calibration_bucket(self, score: float) -> str:
        if score < 0.45:
            return "<0.45"
        if score < 0.50:
            return "0.45-0.50"
        if score < 0.55:
            return "0.50-0.55"
        if score < 0.60:
            return "0.55-0.60"
        return "0.60+"

    def _calibration_summary(self, preds: pd.DataFrame, trades: pd.DataFrame) -> list[dict[str, Any]]:
        if preds.empty:
            return []
        merged = preds.copy()
        if not trades.empty and "signal_date" in trades.columns:
            trade_map = trades.set_index("signal_date")["realized_pnl"].to_dict()
            merged["realized_pnl"] = merged["signal_date"].map(trade_map).fillna(np.nan)
        else:
            merged["realized_pnl"] = np.nan
        merged["is_win"] = merged["realized_pnl"] > 0
        buckets = []
        for bucket, grp in merged.groupby("calibration_bucket"):
            if grp.empty:
                continue
            accepted = grp["accepted"].sum()
            accepted_wins = grp.loc[grp["accepted"] & grp["is_win"]].shape[0]
            buckets.append({
                "bucket": bucket,
                "count": int(len(grp)),
                "accepted": int(accepted),
                "win_rate": round(float(accepted_wins / max(accepted, 1) * 100), 1) if accepted else 0.0,
                "mean_score": round(float(grp["score"].mean()), 3),
                "mean_realized_pnl": round(float(grp["realized_pnl"].mean()), 2) if grp["realized_pnl"].notna().any() else 0.0,
            })
        return buckets

    def _render_markdown(self, summary: dict[str, Any]) -> str:
        lines = ["# Monthly Diagnostic Report", ""]
        dist = summary.get("trade_distribution", {})
        lines += [
            "## Trade Distribution",
            f"- Total trades: {dist.get('total_trades', 0)}",
            f"- Win rate: {dist.get('win_rate', 0)}%",
            f"- Total P&L: ₹{dist.get('total_pnl', 0):,.0f}",
            f"- Avg P&L/trade: ₹{dist.get('avg_pnl', 0):,.2f}",
            f"- Median P&L/trade: ₹{dist.get('median_pnl', 0):,.2f}",
            f"- Avg winner: ₹{dist.get('avg_winner', 0):,.2f}",
            f"- Avg loser: ₹{dist.get('avg_loser', 0):,.2f}",
            f"- Payoff ratio: {dist.get('payoff_ratio', 0)}",
            f"- Profit factor: {dist.get('profit_factor', 0)}",
            f"- Expectancy: ₹{dist.get('expectancy', 0):,.2f}",
            f"- Avg hold: {dist.get('avg_hold', 0)}d",
            "",
        ]
        lines += [
            "## Exit Decomposition",
            f"- Winner cut early: {summary.get('exit_decomposition', {}).get('winner_cut_early_pct', 0)}%",
            f"- Avg MFE: {summary.get('exit_decomposition', {}).get('avg_mfe', 0)}",
            f"- Avg MAE: {summary.get('exit_decomposition', {}).get('avg_mae', 0)}",
            f"- Avg realized vs max attainable: {summary.get('exit_decomposition', {}).get('avg_realized_vs_max_attainable', 0)}",
            f"- Exit reasons: {summary.get('exit_decomposition', {}).get('exit_reason_counts', {})}",
            "",
        ]
        lines += [
            "## Acceptance Funnel",
            f"- Candidate count: {summary.get('acceptance_funnel', {}).get('candidate_count', 0)}",
            f"- Accepted trades: {summary.get('acceptance_funnel', {}).get('accepted_trades', 0)}",
            f"- Near misses: {summary.get('acceptance_funnel', {}).get('near_miss_count', 0)}",
            f"- Rejections: {summary.get('acceptance_funnel', {}).get('rejections', {})}",
            f"- Acceptance by year: {summary.get('acceptance_funnel', {}).get('acceptance_by_year', {})}",
            f"- Acceptance by regime: {summary.get('acceptance_funnel', {}).get('acceptance_by_regime', {})}",
            "",
        ]
        lines += [
            "## Sizing",
            f"- Avg base lots: {summary.get('sizing', {}).get('avg_base_lots', 0)}",
            f"- Avg confidence scale: {summary.get('sizing', {}).get('avg_confidence_scale', 0)}",
            f"- Avg regime scale: {summary.get('sizing', {}).get('avg_regime_scale', 0)}",
            f"- Avg DD scale: {summary.get('sizing', {}).get('avg_dd_scale', 0)}",
            f"- Avg final lots: {summary.get('sizing', {}).get('avg_final_lots', 0)}",
            f"- Avg capital available: ₹{summary.get('sizing', {}).get('avg_capital_available', 0):,.0f}",
            "",
        ]
        lines.append("## Model")
        model = summary.get("model", {})
        lines.append(f"- Train windows: {model.get('train_windows', [])}")
        lines.append(f"- Score distribution by year: {model.get('score_distribution_by_year', {})}")
        lines.append(f"- Accepted score distribution: {model.get('accepted_score_distribution', {})}")
        lines.append(f"- Rejected score distribution: {model.get('rejected_score_distribution', {})}")
        lines.append(f"- Calibration buckets: {model.get('calibration_buckets', [])}")
        return "\n".join(lines)

    def _render_html(self, summary: dict[str, Any]) -> str:
        parts = ["<html><body><pre>", self._render_markdown(summary), "</pre></body></html>"]
        return "\n".join(parts)
