from __future__ import annotations

from datetime import date

import pandas as pd

from backtester.entry_engine import EntryDecisionEngine
from analysis.monthly_diagnostics import MonthlyDiagnosticsCollector
from models.trade_learner import TradeLearner
from strategies.base import Leg, Trade, ExitReason
from strategies.multi_strategy import RegimeAdaptiveStrategy


class _DummyEntryModel:
    def predict(self, row, eligible_strategies=None):
        return {
            "quality_score": 0.9,
            "probability_profitable": 0.9,
            "recommended_strategy": "iron_condor",
            "strategy_scores": {
                "iron_condor": {"composite_score": 1.0},
            },
        }


class _BlockedStrategy:
    def get_eligible_strategies(self, spot, vix, market_data):
        return []


def test_bwb_can_be_pruned_from_monthly_universe():
    strat = RegimeAdaptiveStrategy(lots=1, lot_size=65, allow_bwb=False)
    eligible = strat.get_eligible_strategies(
        22000.0,
        24.0,
        {
            "vix": 24.0,
            "crash_risk_score": 0.05,
            "crash_risk_score_v2": 0.05,
            "nifty_consec_down_days": 0,
            "nifty_drawdown_from_20d_high_pct": -1.0,
            "nifty_drawdown_from_50d_high_pct": -2.0,
            "crude_spike_10d_pct": 0.0,
            "vix_accel_3d_pct": 0.0,
            "multi_asset_stress": 0.0,
            "rvol_10d_z": 0.0,
            "vrp_negative": 0.0,
        },
    )
    assert "broken_wing_butterfly" not in eligible


def test_entry_engine_tracks_skip_reasons():
    engine = EntryDecisionEngine(
        entry_model=_DummyEntryModel(),
        strategy=_BlockedStrategy(),
        entry_threshold=0.48,
    )
    row = pd.Series({"vix": 25.0, "nifty_close": 22000.0}, name=date(2026, 1, 5))
    decision = engine.check(row, 22000.0, 25.0, {"vix": 25.0, "nifty_close": 22000.0})
    assert decision.should_enter is False
    assert decision.skip_reason == "circuit_breaker"
    assert engine.skip_reasons["circuit_breaker"] == 1
    assert engine.ml_skip_count == 1


def test_regime_rerank_boosts_strong_high_vol_sleeve():
    learner = TradeLearner()
    learner.is_trained = True
    learner.regime_strategy_stats = {
        "HIGH_VOL": {
            "iron_condor": {"trades": 20, "wins": 15, "win_rate": 75.0, "total_pnl": 120000, "avg_pnl": 6000},
            "put_credit_spread": {"trades": 20, "wins": 9, "win_rate": 45.0, "total_pnl": 15000, "avg_pnl": 750},
        }
    }
    learner.strategy_stats = {
        "iron_condor": {"win_rate": 60.0, "total_pnl": 100000},
        "put_credit_spread": {"win_rate": 60.0, "total_pnl": 100000},
    }
    mult_ic, _ = learner._regime_multiplier("HIGH_VOL", "iron_condor", strength=0.18)
    mult_pcs, _ = learner._regime_multiplier("HIGH_VOL", "put_credit_spread", strength=0.18)
    assert mult_ic > 1.0
    assert mult_pcs < 1.0


def test_threshold_sweep_prefers_higher_quality_cutoff():
    learner = TradeLearner()
    learner.label_threshold = 0.5
    scores = pd.Series([0.41, 0.45, 0.52, 0.56, 0.61, 0.66]).to_numpy()
    returns = pd.Series([-0.8, -0.2, 0.4, 0.6, 1.0, 1.3]).to_numpy()
    labels = pd.Series([0, 0, 1, 1, 1, 1]).to_numpy()
    sweep = learner._sweep_thresholds(scores, returns, labels)
    assert 0.40 <= sweep["recommended_threshold"] <= 0.70
    assert sweep["threshold_table"]


def test_monthly_diagnostic_report_generation(tmp_path):
    collector = MonthlyDiagnosticsCollector()
    collector.record_prediction(
        signal_date=date(2026, 1, 5),
        threshold=0.55,
        score=0.62,
        win_prob=0.63,
        train_start=date(2025, 1, 1),
        train_end=date(2025, 12, 31),
        feature_version="v4",
        model_version="v4",
        entry_features={"vix_current": 16.0, "nifty_weekly_return_pct": 0.01},
        eligible_strategies=["put_credit_spread"],
        accepted=True,
        rejection_reason=None,
        regime="LOW_VOL",
        vix=16.0,
    )
    collector.record_candidate_funnel(
        signal_date=date(2026, 1, 5),
        regime="LOW_VOL",
        vix=16.0,
        eligible_count=1,
        candidate_count=2,
        accepted=True,
        rejection_breakdown={"risk_constraints": 1},
        selection_reason="put_credit_spread",
    )
    collector.record_sizing(
        signal_date=date(2026, 1, 5),
        capital_available=500000,
        base_lots=10.0,
        confidence_scale=1.0,
        regime_scale=1.0,
        dd_scale=1.0,
        final_lots=4,
        lots_before_cap=6,
        lots_cap_reason="test",
        utilization_contribution=0.12,
    )
    trade = Trade(
        strategy_name="put_credit_spread",
        entry_date=date(2026, 1, 6),
        signal_date=date(2026, 1, 5),
        exit_date=date(2026, 1, 10),
        legs=[
            Leg("PE", 22000, True, 100, 20, 4, 65),
            Leg("PE", 21500, False, 10, 5, 4, 65),
        ],
        entry_spot=22000,
        entry_vix=16.0,
        exit_spot=22300,
        exit_vix=15.0,
        exit_reason=ExitReason.PROFIT_TARGET,
        lots=4,
        lot_size=65,
    )
    collector.start_trade(
        signal_date=date(2026, 1, 5),
        threshold=0.55,
        score=0.62,
        win_prob=0.63,
        train_start=date(2025, 1, 1),
        train_end=date(2025, 12, 31),
        feature_version="v4",
        model_version="v4",
        entry_snapshot_hash="abc123",
        eligible_strategies=["put_credit_spread"],
        accepted=True,
        rejection_reason=None,
        regime="LOW_VOL",
        vix=16.0,
    )
    collector.update_open_trade(0.0)
    collector.update_open_trade(12.0)
    collector.update_open_trade(18.0)
    collector.close_trade(
        entry_date=trade.entry_date,
        exit_date=trade.exit_date,
        exit_reason="profit_target",
        trade=trade,
        net_pnl=2500.0,
        exit_signal_score=0.62,
    )
    summary = collector.summary()
    assert summary["trade_distribution"]["total_trades"] == 1
    assert summary["exit_decomposition"]["exit_reason_counts"]["profit_target"] == 1
    paths = collector.write_artifacts(tmp_path)
    assert (tmp_path / "monthly_diagnostic_report.json").exists()
    assert paths["monthly_diagnostic_report.md"].exists()
    assert paths["monthly_diagnostic_report.html"].exists()
