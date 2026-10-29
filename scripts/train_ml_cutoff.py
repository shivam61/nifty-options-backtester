#!/usr/bin/env python3
"""
Train the weekly entry learner (WeeklyEntryLearner) and the exit engine
(ExitStrategyEngine) with a hard training-date cutoff, for out-of-sample tests.

Usage (repo root):
    .venv/bin/python scripts/train_ml_cutoff.py --end 2021-12-31 --out-dir ~/edge_explore/ml_wf/2022

Outputs in --out-dir: weekly_entry.pkl, exit_model.pkl, meta.json.

Data: MarketDataFetcher with MARKET_DATA_CACHE_ONLY=1 (no network). The combined
frame is clipped to --end before anything is fitted. Nothing is written under
data/.cache or data/.cache_seed (the out-dir is asserted to be outside both).

Model paths mirror the repo's own training code:
  weekly_entry: backtester/walk_forward.py::WalkForwardManager._load_or_train_weekly_entry
  exit:         main.py::run_evolve (StrategyEvolver.evolve with save_cache=False), then
                ExitStrategyEngine.train_from_simulations. Single stage, not layered.

Not used: closed_trades.json (neither model reads it) and RegimeClassifier (neither
model needs it). Evolved strategies are re-evolved on the cutoff data; the cached
data/.cache/evolved_strategies.json (fit on full history) is never read.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

os.environ["MARKET_DATA_CACHE_ONLY"] = "1"

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

FORBIDDEN_DIRS = (REPO / "data" / ".cache", REPO / "data" / ".cache_seed")


class CutoffViolation(RuntimeError):
    pass


def _parse_date(text: str) -> date:
    return date.fromisoformat(text)


def _check_out_dir(out_dir: Path) -> Path:
    out = out_dir.expanduser().resolve()
    for forbidden in FORBIDDEN_DIRS:
        f = forbidden.resolve()
        if out == f or f in out.parents:
            raise SystemExit(f"refusing to write under {f}: {out}")
    return out


def _git_info() -> tuple[str, bool]:
    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                                capture_output=True, text=True).stdout.strip())
    return sha, dirty


def _assert_dates_within(label: str, dates, end_ts: pd.Timestamp) -> pd.Timestamp | None:
    stamps = [pd.Timestamp(d) for d in dates if d is not None]
    if not stamps:
        return None
    mx = max(stamps)
    if mx > end_ts:
        raise CutoffViolation(f"CUTOFF VIOLATION in {label}: max date {mx.date()} > --end {end_ts.date()}")
    return mx


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if hasattr(obj, "__dict__"):
        return dict(vars(obj))
    return str(obj)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--end", required=True, type=_parse_date, help="hard training cutoff, YYYY-MM-DD (inclusive)")
    ap.add_argument("--out-dir", required=True, help="output directory (must be outside data/.cache*)")
    ap.add_argument("--start", default="2009-01-01", type=_parse_date, help="first data date (default 2009-01-01)")
    args = ap.parse_args(argv)

    out = _check_out_dir(Path(args.out_dir))
    out.mkdir(parents=True, exist_ok=True)
    end: date = args.end
    end_ts = pd.Timestamp(end)
    timings: dict[str, float] = {}
    t_all = time.monotonic()

    from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
    from config import BacktestConfig, WeeklyBacktestConfig
    from data.market_data import MarketDataFetcher
    from models.cache_utils import ModelPeriodMetadata
    from models.strategy_evolver import StrategyEvolver
    from models.trade_monitor import ExitStrategyEngine
    from models.weekly_entry_learner import WeeklyEntryLearner
    from training_config import TRAINING_FLOW

    print(f"[cutoff] --end {end}  start {args.start}  out {out}", flush=True)

    # 1. Data: cache-only build, then hard clip to the cutoff.
    t0 = time.monotonic()
    fetcher = MarketDataFetcher(args.start, end)
    raw = fetcher.build_combined_dataset()
    data = raw.loc[raw.index <= end_ts].copy()
    if data.empty:
        raise SystemExit("no rows on or before --end")
    _assert_dates_within("market data", [data.index.max()], end_ts)
    timings["data_s"] = round(time.monotonic() - t0, 1)
    n_rows = len(data)
    print(f"[data] rows={n_rows} {data.index.min().date()}..{data.index.max().date()} "
          f"({timings['data_s']}s) integrity: {fetcher.integrity_summary or 'n/a'}", flush=True)

    train_start = data.index[0].date()
    git_sha, git_dirty = _git_info()

    # 2. Weekly entry learner (mirrors WalkForwardManager._load_or_train_weekly_entry).
    t0 = time.monotonic()
    wcfg = WeeklyBacktestConfig()
    weekly_sim_cfg = WeeklySimConfig(
        lots=wcfg.max_lots,
        lot_size=wcfg.lot_size,
        entry_every_n_days=TRAINING_FLOW.weekly_entry_every_n_days,
        min_dte=wcfg.min_dte_entry,
        max_dte=wcfg.max_dte_entry,
    )
    weekly_trades = WeeklyRollingSimulator(data, weekly_sim_cfg).simulate_all()
    weekly_max_label = _assert_dates_within(
        "weekly trade labels",
        [d for t in weekly_trades for d in (t.signal_date, t.entry_date, t.exit_date)],
        end_ts,
    )
    print(f"[weekly] simulated trades={len(weekly_trades)} (max label date {weekly_max_label and weekly_max_label.date()})",
          flush=True)

    learner = WeeklyEntryLearner()
    weekly_stats = learner.train(weekly_trades, data, verbose=True)
    if "error" in weekly_stats or not learner.is_trained:
        raise SystemExit(f"weekly entry training failed: {weekly_stats}")
    weekly_md = ModelPeriodMetadata.build(
        model_type="weekly_entry",
        train_start=train_start,
        train_end=end,
        feature_version="weekly_entry_v1",
        config={
            "lots": wcfg.max_lots,
            "lot_size": wcfg.lot_size,
            "entry_every_n_days": TRAINING_FLOW.weekly_entry_every_n_days,
            "min_dte": wcfg.min_dte_entry,
            "max_dte": wcfg.max_dte_entry,
        },
    )
    weekly_path = out / "weekly_entry.pkl"
    learner.save(weekly_path, period_metadata=weekly_md)
    timings["weekly_s"] = round(time.monotonic() - t0, 1)
    print(f"[weekly] saved {weekly_path} ({timings['weekly_s']}s)", flush=True)

    # 3. Exit engine (mirrors run_evolve: evolve without cache write, then train on the same frame).
    t0 = time.monotonic()
    bcfg = BacktestConfig()
    evolver = StrategyEvolver(data, lots=bcfg.max_lots, lot_size=bcfg.lot_size)
    evolved = evolver.evolve(
        target=TRAINING_FLOW.evolve_target,
        entry_every_n_days=TRAINING_FLOW.strategy_evolve_entry_every_n_days,
        train_pct=TRAINING_FLOW.layered_train_pct,
        min_trades=TRAINING_FLOW.layered_min_trades,
        save_cache=False,
        verbose=False,
    )
    if not evolved:
        raise SystemExit("StrategyEvolver.evolve returned no strategies on the cutoff data")
    timings["evolve_s"] = round(time.monotonic() - t0, 1)
    print(f"[exit] evolved {len(evolved)} regime strategies ({timings['evolve_s']}s)", flush=True)

    t0 = time.monotonic()
    exit_engine = ExitStrategyEngine(data)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exit_engine.train_from_simulations(evolved, verbose=True)
    exit_log = buf.getvalue()
    print(exit_log, end="", flush=True)
    if not exit_engine.is_trained:
        raise SystemExit("exit model training produced no classifier (too few snapshots?)")
    snap_m = re.search(r"Generated (\d+) exit training snapshots", exit_log)
    lab_m = re.search(r"Labels: (\d+)/(\d+) exit signals", exit_log)
    f1_m = re.search(r"TimeSeriesCV F1: ([\d.]+)%", exit_log)
    exit_pos = int(lab_m.group(1)) if lab_m else None
    exit_total = int(lab_m.group(2)) if lab_m else None
    exit_f1 = float(f1_m.group(1)) / 100.0 if f1_m else None
    exit_cols = list(exit_engine.exit_feature_cols)

    exit_md = ModelPeriodMetadata.build(
        model_type="monthly_exit",
        train_start=train_start,
        train_end=end,
        feature_version="exit_v1",
        config={
            "lots": bcfg.max_lots,
            "lot_size": bcfg.lot_size,
            "evolve_target": TRAINING_FLOW.evolve_target,
            "evolve_entry_every_n_days": TRAINING_FLOW.strategy_evolve_entry_every_n_days,
            "train_pct": TRAINING_FLOW.layered_train_pct,
            "min_trades": TRAINING_FLOW.layered_min_trades,
        },
    )
    exit_path = out / "exit_model.pkl"
    exit_engine.save(exit_path, period_metadata=exit_md)
    timings["exit_s"] = round(time.monotonic() - t0, 1)
    print(f"[exit] saved {exit_path} ({timings['exit_s']}s)", flush=True)

    # 4. Reload both models from disk and score one row (last cutoff day).
    t0 = time.monotonic()
    last_idx = n_rows - 1
    last_row = data.iloc[last_idx]
    reloaded_w = WeeklyEntryLearner.load(data, weekly_path, require_period_metadata=True)
    weekly_score = reloaded_w.predict(last_row, last_idx)
    if reloaded_w.period_metadata.train_end_date != end:
        raise SystemExit("weekly pickle metadata train_end does not match --end")

    reloaded_e = ExitStrategyEngine.load(data, exit_path, require_period_metadata=True)
    exit_cols_persisted = hasattr(reloaded_e, "exit_feature_cols")
    if reloaded_e.period_metadata.train_end_date != end:
        raise SystemExit("exit pickle metadata train_end does not match --end")
    # save()/load() do not persist exit_feature_cols (pre-existing gap); restore it from meta for scoring.
    reloaded_e.exit_feature_cols = exit_cols
    mf = reloaded_e.feature_extractor.extract(last_row)
    if mf is None:
        raise SystemExit("exit feature extraction returned None for the last row")
    X_exit = pd.DataFrame([mf]).reindex(columns=exit_cols, fill_value=0).fillna(0)
    probs = reloaded_e.exit_classifier.predict_proba(X_exit)[0]
    classes = list(reloaded_e.exit_classifier.classes_)
    exit_score = float(probs[classes.index(1)]) if 1 in classes else 0.5
    timings["load_check_s"] = round(time.monotonic() - t0, 1)

    # 5. Hard cutoff audit over everything the models were fitted on.
    weekly_label_max = weekly_max_label
    max_label = max([d for d in (data.index.max(), weekly_label_max) if d is not None])
    if max_label > end_ts:
        raise CutoffViolation(f"CUTOFF VIOLATION: max training date {max_label.date()} > --end {end}")

    meta = {
        "train_end": end.isoformat(),
        "start": args.start.isoformat(),
        "first_row_date": train_start.isoformat(),
        "n_rows": n_rows,
        "max_row_date": data.index.max().date().isoformat(),
        "max_label_date": max_label.date().isoformat(),
        "git_sha": git_sha,
        "git_dirty_at_train": git_dirty,
        "model_files": {"weekly_entry": weekly_path.name, "exit_model": exit_path.name},
        "label_counts": {
            "weekly_trades_simulated": len(weekly_trades),
            "weekly_samples_after_features": weekly_stats.get("num_samples"),
            "weekly_positive": weekly_stats.get("num_positive"),
            "weekly_negative": weekly_stats.get("num_negative"),
            "exit_snapshots": int(snap_m.group(1)) if snap_m else None,
            "exit_positive": exit_pos,
            "exit_total": exit_total,
        },
        "cv_auc": weekly_stats.get("cv_auc"),
        "cv_std": weekly_stats.get("cv_std"),
        "cv_note": "weekly cv_auc is 3-fold in-window CV (not out-of-sample); exit reports TimeSeriesCV F1 instead",
        "exit_cv_f1": exit_f1,
        "closed_trades_used": False,
        "closed_trades_note": "neither WeeklyEntryLearner nor ExitStrategyEngine.train_from_simulations reads closed_trades.json",
        "weekly_selected_features": learner.selected_features,
        "exit_feature_cols": exit_cols,
        "exit_feature_cols_persisted_in_pkl": exit_cols_persisted,
        "evolved_strategies": {k: _to_jsonable(v) for k, v in evolved.items()},
        "integrity_summary": fetcher.integrity_summary,
        "load_check": {"weekly_score_last_row": weekly_score, "exit_score_last_row": exit_score,
                       "exit_trade_features": "zeros (no live trade)"},
        "elapsed_s": {**timings, "total_s": round(time.monotonic() - t_all, 1)},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"[done] wrote {out / 'meta.json'} total {meta['elapsed_s']['total_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CutoffViolation as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
