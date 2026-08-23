"""
Model Validation Suite — Walk-Forward Validation + Permutation Tests

Ensures ML models are learning real signal, not overfitting to noise.

Walk-Forward Validation:
  Train: 2019-2021 → Test: 2022
  Train: 2019-2022 → Test: 2023
  Train: 2019-2023 → Test: 2024
  Train: 2019-2024 → Test: 2025

Permutation Test (Label Shuffling):
  Shuffle target labels → retrain → compare metrics.
  If shuffled model performs ~equally, the model learned nothing.
"""

import numpy as np
import pandas as pd
from datetime import date
from typing import Optional

from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from backtester.rolling_simulator import RollingWindowSimulator, SimConfig
from training_config import TRAINING_FLOW


def walk_forward_entry_model(
    full_data: pd.DataFrame,
    lots: int = 8,
    lot_size: int = 75,
    min_train_years: int = 3,
    verbose: bool = True,
) -> dict:
    """
    Walk-forward validation for the entry model (TradeLearner).

    Expanding window: each fold adds one year of training, tests on next year.
    This is the gold standard for time-series model validation.
    """
    from models.trade_learner import TradeLearner, FeatureExtractor

    years = sorted(full_data.index.year.unique())
    if len(years) < min_train_years + 1:
        return {"error": f"Need at least {min_train_years + 1} years, got {len(years)}"}

    results = []

    for test_year_idx in range(min_train_years, len(years)):
        test_year = years[test_year_idx]
        train_years = years[:test_year_idx]

        train_data = full_data[full_data.index.year.isin(train_years)]
        test_data = full_data[full_data.index.year == test_year]

        if len(train_data) < 200 or len(test_data) < 50:
            continue

        if verbose:
            print(f"  Fold: Train {train_years[0]}-{train_years[-1]} → Test {test_year}")

        sim_cfg = SimConfig(
            lots=lots,
            lot_size=lot_size,
            entry_every_n_days=TRAINING_FLOW.strategy_evolve_entry_every_n_days,
        )
        sim = RollingWindowSimulator(train_data, config=sim_cfg)
        train_trades = sim.simulate_all()

        if len(train_trades) < 20:
            if verbose:
                print(f"    Skipped: only {len(train_trades)} training trades")
            continue

        model = TradeLearner()
        model.train(train_trades, train_data)

        if not model.is_trained:
            if verbose:
                print(f"    Skipped: model failed to train")
            continue

        test_sim_cfg = SimConfig(
            lots=lots,
            lot_size=lot_size,
            entry_every_n_days=TRAINING_FLOW.strategy_evolve_entry_every_n_days,
        )
        test_sim = RollingWindowSimulator(test_data, config=test_sim_cfg)
        test_trades = test_sim.simulate_all()

        if len(test_trades) < 5:
            if verbose:
                print(f"    Skipped: only {len(test_trades)} test trades")
            continue

        y_true, y_pred_prob, y_pred_signal = [], [], []
        for trade in test_trades:
            entry_date = pd.Timestamp(trade.entry_date)
            idx = test_data.index.get_indexer([entry_date], method="nearest")[0]
            if idx >= len(test_data):
                continue
            row = test_data.iloc[idx]
            prediction = model.predict(row)
            if "error" in prediction:
                continue

            actual_win = 1 if trade.total_pnl > 0 else 0
            y_true.append(actual_win)
            y_pred_prob.append(prediction.get("probability_profitable", 0.5))
            signal = prediction.get("signal", "AVOID")
            y_pred_signal.append(1 if signal in ("STRONG_ENTRY", "MODERATE_ENTRY") else 0)

        if len(y_true) < 5:
            continue

        y_true = np.array(y_true)
        y_pred_prob = np.array(y_pred_prob)
        y_pred_signal = np.array(y_pred_signal)
        y_pred_class = (y_pred_prob >= 0.5).astype(int)

        fold_result = {
            "train_period": f"{train_years[0]}-{train_years[-1]}",
            "test_year": test_year,
            "n_train_trades": len(train_trades),
            "n_test_trades": len(test_trades),
            "n_evaluated": len(y_true),
            "accuracy": float(accuracy_score(y_true, y_pred_class)),
            "f1": float(f1_score(y_true, y_pred_class, zero_division=0)),
            "precision": float(precision_score(y_true, y_pred_class, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred_class, zero_division=0)),
            "actual_win_rate": float(y_true.mean()),
            "predicted_win_rate": float(y_pred_class.mean()),
            "signal_entry_rate": float(y_pred_signal.mean()),
        }
        try:
            if len(set(y_true)) > 1:
                fold_result["auc_roc"] = float(roc_auc_score(y_true, y_pred_prob))
        except Exception:
            pass

        # Profitability of ML-filtered trades vs all trades
        filtered_pnls = [
            t.total_pnl for t, sig in zip(test_trades[:len(y_pred_signal)], y_pred_signal)
            if sig == 1
        ]
        all_pnls = [t.total_pnl for t in test_trades[:len(y_true)]]
        fold_result["avg_pnl_all_trades"] = float(np.mean(all_pnls)) if all_pnls else 0
        fold_result["avg_pnl_ml_filtered"] = float(np.mean(filtered_pnls)) if filtered_pnls else 0
        fold_result["pnl_improvement_pct"] = (
            (fold_result["avg_pnl_ml_filtered"] - fold_result["avg_pnl_all_trades"])
            / abs(fold_result["avg_pnl_all_trades"]) * 100
            if fold_result["avg_pnl_all_trades"] != 0 else 0
        )

        results.append(fold_result)
        if verbose:
            print(f"    Acc: {fold_result['accuracy']:.1%} | F1: {fold_result['f1']:.1%} | "
                  f"AUC: {fold_result.get('auc_roc', 'N/A'):.3f} | "
                  f"Signal rate: {fold_result['signal_entry_rate']:.0%} | "
                  f"P&L imp: {fold_result['pnl_improvement_pct']:+.1f}%")

    if not results:
        return {"error": "No valid walk-forward folds"}

    summary = {
        "n_folds": len(results),
        "folds": results,
        "avg_accuracy": float(np.mean([r["accuracy"] for r in results])),
        "avg_f1": float(np.mean([r["f1"] for r in results])),
        "avg_auc": float(np.mean([r.get("auc_roc", 0.5) for r in results])),
        "avg_pnl_improvement_pct": float(np.mean([r["pnl_improvement_pct"] for r in results])),
        "stability": float(np.std([r["accuracy"] for r in results])),
    }

    if verbose:
        print(f"\n  Walk-Forward Summary ({summary['n_folds']} folds):")
        print(f"    Avg Accuracy:  {summary['avg_accuracy']:.1%} ± {summary['stability']:.1%}")
        print(f"    Avg F1:        {summary['avg_f1']:.1%}")
        print(f"    Avg AUC-ROC:   {summary['avg_auc']:.3f}")
        print(f"    Avg P&L Lift:  {summary['avg_pnl_improvement_pct']:+.1f}%")

    return summary


def walk_forward_exit_model(
    full_data: pd.DataFrame,
    evolved_strategies: dict,
    min_train_years: int = 3,
    verbose: bool = True,
) -> dict:
    """
    Walk-forward validation for the exit model (ExitStrategyEngine).

    Uses time-based splits to avoid data leakage.
    """
    from models.trade_monitor import ExitStrategyEngine
    from pricing.black_scholes import price_option, iv_from_vix, OptionType

    years = sorted(full_data.index.year.unique())
    if len(years) < min_train_years + 1:
        return {"error": f"Need at least {min_train_years + 1} years, got {len(years)}"}

    results = []

    for test_year_idx in range(min_train_years, len(years)):
        test_year = years[test_year_idx]
        train_years = years[:test_year_idx]

        train_data = full_data[full_data.index.year.isin(train_years)]
        test_data = full_data[full_data.index.year == test_year]

        if len(train_data) < 200 or len(test_data) < 50:
            continue

        if verbose:
            print(f"  Fold: Train {train_years[0]}-{train_years[-1]} → Test {test_year}")

        engine = ExitStrategyEngine(train_data)
        engine.train_from_simulations(evolved_strategies, verbose=False)

        if not engine.is_trained:
            continue

        # Generate test snapshots from test_data
        test_snapshots = _generate_exit_snapshots(test_data, evolved_strategies)
        if len(test_snapshots) < 20:
            if verbose:
                print(f"    Skipped: only {len(test_snapshots)} test snapshots")
            continue

        df_test = pd.DataFrame(test_snapshots)
        feature_cols = engine.exit_feature_cols
        X_test = df_test.reindex(columns=feature_cols, fill_value=0).fillna(0).replace([np.inf, -np.inf], 0)
        y_test = df_test["_label_should_exit"].values

        y_pred = engine.exit_classifier.predict(X_test)
        y_pred_prob = engine.exit_classifier.predict_proba(X_test)
        exit_class_idx = list(engine.exit_classifier.classes_).index(1) if 1 in engine.exit_classifier.classes_ else 0
        y_pred_exit_prob = y_pred_prob[:, exit_class_idx]

        fold_result = {
            "train_period": f"{train_years[0]}-{train_years[-1]}",
            "test_year": test_year,
            "n_test_snapshots": len(y_test),
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "exit_rate_actual": float(y_test.mean()),
            "exit_rate_predicted": float(y_pred.mean()),
        }
        try:
            if len(set(y_test)) > 1:
                fold_result["auc_roc"] = float(roc_auc_score(y_test, y_pred_exit_prob))
        except Exception:
            pass

        results.append(fold_result)
        if verbose:
            print(f"    Acc: {fold_result['accuracy']:.1%} | F1: {fold_result['f1']:.1%} | "
                  f"AUC: {fold_result.get('auc_roc', 'N/A'):.3f} | "
                  f"Exit rate: actual {fold_result['exit_rate_actual']:.0%} vs pred {fold_result['exit_rate_predicted']:.0%}")

    if not results:
        return {"error": "No valid exit model folds"}

    summary = {
        "n_folds": len(results),
        "folds": results,
        "avg_accuracy": float(np.mean([r["accuracy"] for r in results])),
        "avg_f1": float(np.mean([r["f1"] for r in results])),
        "avg_auc": float(np.mean([r.get("auc_roc", 0.5) for r in results])),
        "stability": float(np.std([r["accuracy"] for r in results])),
    }

    if verbose:
        print(f"\n  Exit Walk-Forward Summary ({summary['n_folds']} folds):")
        print(f"    Avg Accuracy:  {summary['avg_accuracy']:.1%} ± {summary['stability']:.1%}")
        print(f"    Avg F1:        {summary['avg_f1']:.1%}")
        print(f"    Avg AUC-ROC:   {summary['avg_auc']:.3f}")

    return summary


def permutation_test_entry_model(
    data: pd.DataFrame,
    lots: int = 8,
    lot_size: int = 75,
    n_permutations: int = 20,
    verbose: bool = True,
) -> dict:
    """
    Permutation test (label shuffling) for the entry model.

    Instead of recreating TradeResult objects (complex dataclass), we:
    1. Extract features + labels from trades
    2. Train real model on real labels
    3. Shuffle labels N times, retrain, compare OOS metrics

    If the real model doesn't significantly outperform shuffled-label models,
    the model is learning noise, not signal.
    """
    from models.trade_learner import TradeLearner, FeatureExtractor
    from lightgbm import LGBMClassifier
    from sklearn.model_selection import TimeSeriesSplit

    sim_cfg = SimConfig(
        lots=lots,
        lot_size=lot_size,
        entry_every_n_days=TRAINING_FLOW.strategy_evolve_entry_every_n_days,
    )
    sim = RollingWindowSimulator(data, config=sim_cfg)
    trades = sim.simulate_all()

    if len(trades) < 30:
        return {"error": f"Need at least 30 trades, got {len(trades)}"}

    extractor = FeatureExtractor(data)
    X_rows, y_labels = [], []
    for trade in trades:
        entry_date = pd.Timestamp(trade.entry_date)
        idx = data.index.get_indexer([entry_date], method="nearest")[0]
        if idx >= len(data):
            continue
        features = extractor.extract(data.iloc[idx])
        if features is None:
            continue
        X_rows.append(features)
        y_labels.append(1 if trade.total_pnl > 0 else 0)

    X = pd.DataFrame(X_rows).fillna(0).replace([np.inf, -np.inf], 0)
    y = np.array(y_labels)

    # Time-based 80/20 split
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if verbose:
        print(f"  Permutation test: {len(X_train)} train / {len(X_test)} test samples")
        print(f"  Train win rate: {y_train.mean():.1%} | Test win rate: {y_test.mean():.1%}")

    n_est = min(100, max(30, len(X_train) * 2))
    max_d = 4 if len(X_train) > 20 else 3
    min_leaf = max(2, len(X_train) // 10)

    # Real model
    real_clf = LGBMClassifier(
        n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
        min_child_samples=min_leaf, subsample=0.8, random_state=42,
        n_jobs=-1, verbosity=-1,
    )
    real_clf.fit(X_train, y_train)
    real_pred = real_clf.predict(X_test)
    real_prob = real_clf.predict_proba(X_test)
    real_acc = float(accuracy_score(y_test, real_pred))
    real_f1 = float(f1_score(y_test, real_pred, zero_division=0))
    try:
        win_idx = list(real_clf.classes_).index(1)
        real_auc = float(roc_auc_score(y_test, real_prob[:, win_idx]))
    except Exception:
        real_auc = 0.5

    if verbose:
        print(f"  Real model:     Acc={real_acc:.1%} | F1={real_f1:.1%} | AUC={real_auc:.3f}")

    # Shuffled models
    shuffled_accs, shuffled_f1s, shuffled_aucs = [], [], []
    rng = np.random.RandomState(42)

    for i in range(n_permutations):
        y_shuffled = y_train.copy()
        rng.shuffle(y_shuffled)
        clf_s = LGBMClassifier(
            n_estimators=n_est, max_depth=max_d, learning_rate=0.08,
            min_child_samples=min_leaf, subsample=0.8, random_state=42,
            n_jobs=-1, verbosity=-1,
        )
        clf_s.fit(X_train, y_shuffled)
        pred_s = clf_s.predict(X_test)
        shuffled_accs.append(float(accuracy_score(y_test, pred_s)))
        shuffled_f1s.append(float(f1_score(y_test, pred_s, zero_division=0)))
        try:
            win_idx_s = list(clf_s.classes_).index(1) if 1 in clf_s.classes_ else 0
            shuffled_aucs.append(float(roc_auc_score(y_test, clf_s.predict_proba(X_test)[:, win_idx_s])))
        except Exception:
            shuffled_aucs.append(0.5)

    p_value_acc = float(np.mean([s >= real_acc for s in shuffled_accs]))
    p_value_f1 = float(np.mean([s >= real_f1 for s in shuffled_f1s]))
    p_value_auc = float(np.mean([s >= real_auc for s in shuffled_aucs]))

    result = {
        "real_accuracy": real_acc,
        "real_f1": real_f1,
        "real_auc": real_auc,
        "shuffled_mean_accuracy": float(np.mean(shuffled_accs)),
        "shuffled_std_accuracy": float(np.std(shuffled_accs)),
        "shuffled_mean_f1": float(np.mean(shuffled_f1s)),
        "shuffled_mean_auc": float(np.mean(shuffled_aucs)),
        "p_value_accuracy": p_value_acc,
        "p_value_f1": p_value_f1,
        "p_value_auc": p_value_auc,
        "n_permutations": n_permutations,
        "significant_at_5pct": p_value_acc < 0.05,
    }

    if verbose:
        print(f"  Shuffled mean:  Acc={result['shuffled_mean_accuracy']:.1%} ± "
              f"{result['shuffled_std_accuracy']:.1%} | F1={result['shuffled_mean_f1']:.1%} | "
              f"AUC={result['shuffled_mean_auc']:.3f}")
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │  ENTRY MODEL PERMUTATION TEST                          │")
        print(f"  ├─────────────┬─────────┬───────────┬────────────────────┤")
        print(f"  │ Metric      │  Real   │  Shuffled │ p-value            │")
        print(f"  ├─────────────┼─────────┼───────────┼────────────────────┤")
        sig_a = "✓ SIGNAL" if p_value_acc < 0.05 else "✗ NOISE"
        sig_f = "✓ SIGNAL" if p_value_f1 < 0.05 else "✗ NOISE"
        sig_r = "✓ SIGNAL" if p_value_auc < 0.05 else "✗ NOISE"
        print(f"  │ Accuracy    │ {real_acc:>5.1%}  │  {result['shuffled_mean_accuracy']:>5.1%}   │ {p_value_acc:.3f}  {sig_a:<10} │")
        print(f"  │ F1 Score    │ {real_f1:>5.1%}  │  {result['shuffled_mean_f1']:>5.1%}   │ {p_value_f1:.3f}  {sig_f:<10} │")
        print(f"  │ AUC-ROC     │ {real_auc:>5.3f}  │  {result['shuffled_mean_auc']:>5.3f}   │ {p_value_auc:.3f}  {sig_r:<10} │")
        print(f"  └─────────────┴─────────┴───────────┴────────────────────┘")

        if result["significant_at_5pct"]:
            print(f"\n  VERDICT: Model IS learning real signal (p < 0.05)")
        else:
            print(f"\n  VERDICT: Model may be learning NOISE (p >= 0.05)")

    return result


def permutation_test_exit_model(
    data: pd.DataFrame,
    evolved_strategies: dict,
    n_permutations: int = 20,
    verbose: bool = True,
) -> dict:
    """
    Permutation test for exit model. Shuffles exit labels and compares.
    """
    from models.trade_monitor import ExitStrategyEngine

    # Generate ALL snapshots
    snapshots = _generate_exit_snapshots(data, evolved_strategies)
    if len(snapshots) < 100:
        return {"error": f"Need at least 100 snapshots, got {len(snapshots)}"}

    df = pd.DataFrame(snapshots)
    feature_cols = [c for c in df.columns if not c.startswith("_label_")]
    X = df[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
    y = df["_label_should_exit"].values

    # Time-based 80/20 split
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if verbose:
        print(f"  Permutation test: {len(X_train)} train / {len(X_test)} test snapshots")

    from lightgbm import LGBMClassifier
    from sklearn.utils.class_weight import compute_sample_weight

    # Real model
    sw = compute_sample_weight("balanced", y_train)
    real_clf = LGBMClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.08,
        subsample=0.8, min_child_samples=8, random_state=42,
        n_jobs=-1, verbosity=-1,
    )
    real_clf.fit(X_train, y_train, sample_weight=sw)
    real_pred = real_clf.predict(X_test)
    real_f1 = f1_score(y_test, real_pred, zero_division=0)
    real_acc = accuracy_score(y_test, real_pred)
    try:
        exit_idx = list(real_clf.classes_).index(1)
        real_auc = roc_auc_score(y_test, real_clf.predict_proba(X_test)[:, exit_idx])
    except Exception:
        real_auc = 0.5

    if verbose:
        print(f"  Real model:     F1={real_f1:.1%} | Acc={real_acc:.1%} | AUC={real_auc:.3f}")

    # Shuffled models
    shuffled_f1s, shuffled_accs, shuffled_aucs = [], [], []
    rng = np.random.RandomState(42)

    for i in range(n_permutations):
        y_shuffled = y_train.copy()
        rng.shuffle(y_shuffled)
        sw_s = compute_sample_weight("balanced", y_shuffled)
        clf_s = LGBMClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.08,
            subsample=0.8, min_child_samples=8, random_state=42,
            n_jobs=-1, verbosity=-1,
        )
        clf_s.fit(X_train, y_shuffled, sample_weight=sw_s)
        pred_s = clf_s.predict(X_test)
        shuffled_f1s.append(f1_score(y_test, pred_s, zero_division=0))
        shuffled_accs.append(accuracy_score(y_test, pred_s))
        try:
            exit_idx_s = list(clf_s.classes_).index(1) if 1 in clf_s.classes_ else 0
            shuffled_aucs.append(roc_auc_score(y_test, clf_s.predict_proba(X_test)[:, exit_idx_s]))
        except Exception:
            shuffled_aucs.append(0.5)

    p_value_f1 = float(np.mean([s >= real_f1 for s in shuffled_f1s]))
    p_value_acc = float(np.mean([s >= real_acc for s in shuffled_accs]))
    p_value_auc = float(np.mean([s >= real_auc for s in shuffled_aucs]))

    result = {
        "real_f1": real_f1, "real_accuracy": real_acc, "real_auc": real_auc,
        "shuffled_mean_f1": float(np.mean(shuffled_f1s)),
        "shuffled_mean_accuracy": float(np.mean(shuffled_accs)),
        "shuffled_mean_auc": float(np.mean(shuffled_aucs)),
        "p_value_f1": p_value_f1,
        "p_value_accuracy": p_value_acc,
        "p_value_auc": p_value_auc,
        "n_permutations": n_permutations,
        "significant_at_5pct": p_value_f1 < 0.05,
    }

    if verbose:
        print(f"  Shuffled mean:  F1={result['shuffled_mean_f1']:.1%} | "
              f"Acc={result['shuffled_mean_accuracy']:.1%} | AUC={result['shuffled_mean_auc']:.3f}")
        print(f"\n  ┌─────────────────────────────────────────────────────────┐")
        print(f"  │  EXIT MODEL PERMUTATION TEST                           │")
        print(f"  ├─────────────┬─────────┬───────────┬────────────────────┤")
        print(f"  │ Metric      │  Real   │  Shuffled │ p-value            │")
        print(f"  ├─────────────┼─────────┼───────────┼────────────────────┤")
        sig_f = "✓ SIGNAL" if p_value_f1 < 0.05 else "✗ NOISE"
        sig_a = "✓ SIGNAL" if p_value_acc < 0.05 else "✗ NOISE"
        sig_r = "✓ SIGNAL" if p_value_auc < 0.05 else "✗ NOISE"
        print(f"  │ F1 Score    │ {real_f1:>5.1%}  │  {result['shuffled_mean_f1']:>5.1%}   │ {p_value_f1:.3f}  {sig_f:<10} │")
        print(f"  │ Accuracy    │ {real_acc:>5.1%}  │  {result['shuffled_mean_accuracy']:>5.1%}   │ {p_value_acc:.3f}  {sig_a:<10} │")
        print(f"  │ AUC-ROC     │ {real_auc:>5.3f}  │  {result['shuffled_mean_auc']:>5.3f}   │ {p_value_auc:.3f}  {sig_r:<10} │")
        print(f"  └─────────────┴─────────┴───────────┴────────────────────┘")

        if result["significant_at_5pct"]:
            print(f"\n  VERDICT: Exit model IS learning real exit signals (p < 0.05)")
        else:
            print(f"\n  VERDICT: Exit model may be learning NOISE (p >= 0.05)")

    return result


def walk_forward_weekly_entry_model(
    full_data: pd.DataFrame,
    lots: int = 10,
    lot_size: int = 65,
    min_train_years: int = 3,
    verbose: bool = True,
) -> dict:
    """
    Walk-forward validation for the weekly entry model (WeeklyEntryLearner).

    Expanding window by year, trains on simulated weekly trades from earlier years,
    tests on the next year's weekly trades.
    """
    from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
    from models.weekly_entry_learner import WeeklyEntryLearner

    years = sorted(full_data.index.year.unique())
    if len(years) < min_train_years + 1:
        return {"error": f"Need at least {min_train_years + 1} years, got {len(years)}"}

    results = []

    for test_year_idx in range(min_train_years, len(years)):
        test_year = years[test_year_idx]
        train_years = years[:test_year_idx]

        train_data = full_data[full_data.index.year.isin(train_years)]
        test_data = full_data[full_data.index.year == test_year]

        if len(train_data) < 200 or len(test_data) < 50:
            continue

        if verbose:
            print(f"  Fold: Train {train_years[0]}-{train_years[-1]} → Test {test_year}")

        sim_cfg = WeeklySimConfig(lots=lots, lot_size=lot_size)
        sim = WeeklyRollingSimulator(train_data, config=sim_cfg)
        train_trades = sim.simulate_all()

        if len(train_trades) < 20:
            if verbose:
                print(f"    Skipped: only {len(train_trades)} training trades")
            continue

        model = WeeklyEntryLearner()
        stats = model.train(train_trades, train_data, verbose=False)

        if not model.is_trained:
            if verbose:
                print(f"    Skipped: model failed to train")
            continue

        test_sim = WeeklyRollingSimulator(test_data, config=sim_cfg)
        test_trades = test_sim.simulate_all()

        if len(test_trades) < 5:
            if verbose:
                print(f"    Skipped: only {len(test_trades)} test trades")
            continue

        y_true, y_pred_scores = [], []
        COST_HURDLE = 5.0
        for trade in test_trades:
            entry_date = pd.Timestamp(trade.entry_date)
            idx = test_data.index.get_indexer([entry_date], method="nearest")[0]
            if idx >= len(test_data):
                continue
            row = test_data.iloc[idx]
            score = model.predict(row, market_data_idx=idx)
            y_true.append(1 if trade.pnl_pct > COST_HURDLE else 0)
            y_pred_scores.append(score)

        if len(y_true) < 5:
            continue

        y_true = np.array(y_true)
        y_scores = np.array(y_pred_scores)
        y_pred_class = (y_scores >= 0.55).astype(int)

        fold_result = {
            "train_period": f"{train_years[0]}-{train_years[-1]}",
            "test_year": test_year,
            "n_train_trades": len(train_trades),
            "n_test_trades": len(test_trades),
            "n_evaluated": len(y_true),
            "accuracy": float(accuracy_score(y_true, y_pred_class)),
            "f1": float(f1_score(y_true, y_pred_class, zero_division=0)),
            "precision": float(precision_score(y_true, y_pred_class, zero_division=0)),
            "recall": float(recall_score(y_true, y_pred_class, zero_division=0)),
            "actual_positive_rate": float(y_true.mean()),
            "predicted_positive_rate": float(y_pred_class.mean()),
        }
        try:
            if len(set(y_true)) > 1:
                fold_result["auc_roc"] = float(roc_auc_score(y_true, y_scores))
        except Exception:
            pass

        # P&L lift: ML-filtered vs all
        filtered_pnls = [
            t.pnl_pct for t, pred in zip(test_trades[:len(y_pred_class)], y_pred_class)
            if pred == 1
        ]
        all_pnls = [t.pnl_pct for t in test_trades[:len(y_true)]]
        fold_result["avg_pnl_pct_all"] = float(np.mean(all_pnls)) if all_pnls else 0
        fold_result["avg_pnl_pct_filtered"] = float(np.mean(filtered_pnls)) if filtered_pnls else 0

        results.append(fold_result)
        if verbose:
            auc = fold_result.get("auc_roc", "N/A")
            auc_str = f"{auc:.3f}" if isinstance(auc, float) else auc
            print(f"    Acc: {fold_result['accuracy']:.1%} | F1: {fold_result['f1']:.1%} | "
                  f"AUC: {auc_str} | "
                  f"Filtered P&L: {fold_result['avg_pnl_pct_filtered']:+.1f}% vs All: {fold_result['avg_pnl_pct_all']:+.1f}%")

    if not results:
        return {"error": "No valid walk-forward folds"}

    summary = {
        "n_folds": len(results),
        "folds": results,
        "avg_accuracy": float(np.mean([r["accuracy"] for r in results])),
        "avg_f1": float(np.mean([r["f1"] for r in results])),
        "avg_auc": float(np.mean([r.get("auc_roc", 0.5) for r in results])),
        "stability": float(np.std([r["accuracy"] for r in results])),
    }

    if verbose:
        print(f"\n  Weekly Entry Walk-Forward Summary ({summary['n_folds']} folds):")
        print(f"    Avg Accuracy:  {summary['avg_accuracy']:.1%} ± {summary['stability']:.1%}")
        print(f"    Avg F1:        {summary['avg_f1']:.1%}")
        print(f"    Avg AUC-ROC:   {summary['avg_auc']:.3f}")

    return summary


def permutation_test_weekly_entry(
    data: pd.DataFrame,
    lots: int = 10,
    lot_size: int = 65,
    n_permutations: int = 20,
    verbose: bool = True,
) -> dict:
    """Permutation test for weekly entry model — shuffles quality labels."""
    from backtester.weekly_simulator import WeeklyRollingSimulator, WeeklySimConfig
    from models.weekly_entry_learner import WeeklyEntryLearner
    from models.trade_learner import FeatureExtractor
    from lightgbm import LGBMClassifier
    COST_HURDLE_PCT = WeeklyEntryLearner.COST_HURDLE_PCT

    sim_cfg = WeeklySimConfig(lots=lots, lot_size=lot_size)
    sim = WeeklyRollingSimulator(data, config=sim_cfg)
    trades = sim.simulate_all()

    if len(trades) < 30:
        return {"error": f"Need at least 30 trades, got {len(trades)}"}

    extractor = FeatureExtractor(data)
    X_rows, y_labels = [], []
    for trade in trades:
        entry_date = pd.Timestamp(trade.entry_date)
        idx = data.index.get_indexer([entry_date], method="nearest")[0]
        if idx >= len(data):
            continue
        features = extractor.extract(data.iloc[idx])
        if features is None:
            continue
        features["entry_weekday"] = trade.entry_date.weekday()
        features["dte_at_entry"] = trade.dte_at_entry
        X_rows.append(features)
        y_labels.append(1 if trade.pnl_pct > COST_HURDLE_PCT else 0)

    X = pd.DataFrame(X_rows).fillna(0).replace([np.inf, -np.inf], 0)
    y = np.array(y_labels)

    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if verbose:
        print(f"  Permutation test: {len(X_train)} train / {len(X_test)} test samples")
        print(f"  Train positive rate: {y_train.mean():.1%} | Test positive rate: {y_test.mean():.1%}")

    n_est = min(150, max(50, len(X_train)))
    real_clf = LGBMClassifier(
        n_estimators=n_est, max_depth=4, learning_rate=0.08,
        min_child_samples=max(2, len(X_train) // 10), subsample=0.8, random_state=42,
        n_jobs=-1, verbosity=-1,
    )
    real_clf.fit(X_train, y_train)
    real_pred = real_clf.predict(X_test)
    real_acc = float(accuracy_score(y_test, real_pred))
    real_f1 = float(f1_score(y_test, real_pred, zero_division=0))
    try:
        pos_idx = list(real_clf.classes_).index(1)
        real_auc = float(roc_auc_score(y_test, real_clf.predict_proba(X_test)[:, pos_idx]))
    except Exception:
        real_auc = 0.5

    if verbose:
        print(f"  Real model:     Acc={real_acc:.1%} | F1={real_f1:.1%} | AUC={real_auc:.3f}")

    shuffled_accs, shuffled_f1s, shuffled_aucs = [], [], []
    rng = np.random.RandomState(42)
    for _ in range(n_permutations):
        y_shuffled = y_train.copy()
        rng.shuffle(y_shuffled)
        clf_s = LGBMClassifier(
            n_estimators=n_est, max_depth=4, learning_rate=0.08,
            min_child_samples=max(2, len(X_train) // 10), subsample=0.8, random_state=42,
            n_jobs=-1, verbosity=-1,
        )
        clf_s.fit(X_train, y_shuffled)
        pred_s = clf_s.predict(X_test)
        shuffled_accs.append(float(accuracy_score(y_test, pred_s)))
        shuffled_f1s.append(float(f1_score(y_test, pred_s, zero_division=0)))
        try:
            pi = list(clf_s.classes_).index(1) if 1 in clf_s.classes_ else 0
            shuffled_aucs.append(float(roc_auc_score(y_test, clf_s.predict_proba(X_test)[:, pi])))
        except Exception:
            shuffled_aucs.append(0.5)

    p_acc = float(np.mean([s >= real_acc for s in shuffled_accs]))
    p_f1 = float(np.mean([s >= real_f1 for s in shuffled_f1s]))
    p_auc = float(np.mean([s >= real_auc for s in shuffled_aucs]))

    result = {
        "real_accuracy": real_acc, "real_f1": real_f1, "real_auc": real_auc,
        "shuffled_mean_accuracy": float(np.mean(shuffled_accs)),
        "shuffled_mean_f1": float(np.mean(shuffled_f1s)),
        "shuffled_mean_auc": float(np.mean(shuffled_aucs)),
        "p_value_accuracy": p_acc, "p_value_f1": p_f1, "p_value_auc": p_auc,
        "n_permutations": n_permutations,
        "significant_at_5pct": p_auc < 0.05,
    }

    if verbose:
        print(f"  Shuffled mean:  Acc={result['shuffled_mean_accuracy']:.1%} | "
              f"F1={result['shuffled_mean_f1']:.1%} | AUC={result['shuffled_mean_auc']:.3f}")
        sig_a = "SIGNAL" if p_acc < 0.05 else "NOISE"
        sig_f = "SIGNAL" if p_f1 < 0.05 else "NOISE"
        sig_r = "SIGNAL" if p_auc < 0.05 else "NOISE"
        print(f"\n  Weekly Entry Permutation Results:")
        print(f"    Accuracy  p={p_acc:.3f}  {sig_a}")
        print(f"    F1        p={p_f1:.3f}  {sig_f}")
        print(f"    AUC-ROC   p={p_auc:.3f}  {sig_r}")
        verdict = "learning real signal" if result["significant_at_5pct"] else "may be learning NOISE"
        print(f"  VERDICT: Weekly entry model {verdict}")

    return result


def validate_regime_classifier(
    data: pd.DataFrame,
    min_folds: int = 3,
    verbose: bool = True,
) -> dict:
    """
    Walk-forward validation for the RegimeClassifier.

    Uses expanding yearly windows with accuracy as the primary metric.
    """
    from models.regime_classifier import RegimeClassifier

    years = sorted(data.index.year.unique())
    if len(years) < 4:
        return {"error": f"Need at least 4 years, got {len(years)}"}

    results = []
    for test_year_idx in range(3, len(years)):
        test_year = years[test_year_idx]
        train_years = years[:test_year_idx]

        train_data = data[data.index.year.isin(train_years)]
        test_data = data[data.index.year == test_year]

        if len(train_data) < 200 or len(test_data) < 50:
            continue

        if verbose:
            print(f"  Fold: Train {train_years[0]}-{train_years[-1]} → Test {test_year}")

        clf = RegimeClassifier()
        stats = clf.train(train_data, verbose=False)

        if not clf.is_trained:
            continue

        from models.regime_classifier import label_regime_rules

        correct = 0
        total = 0
        for _, row in test_data.iterrows():
            pred = clf.predict(row)
            actual = label_regime_rules(row)
            if pred == actual:
                correct += 1
            total += 1

        if total < 10:
            continue

        accuracy = correct / total
        fold_result = {
            "train_period": f"{train_years[0]}-{train_years[-1]}",
            "test_year": test_year,
            "n_test": total,
            "accuracy": accuracy,
            "train_cv_accuracy": stats.get("cv_accuracy", 0),
        }
        results.append(fold_result)
        if verbose:
            print(f"    OOS Accuracy: {accuracy:.1%} | Train CV: {fold_result['train_cv_accuracy']:.1%}")

    if not results:
        return {"error": "No valid regime folds"}

    summary = {
        "n_folds": len(results),
        "folds": results,
        "avg_accuracy": float(np.mean([r["accuracy"] for r in results])),
        "stability": float(np.std([r["accuracy"] for r in results])),
    }

    if verbose:
        print(f"\n  Regime Classifier Summary ({summary['n_folds']} folds):")
        print(f"    Avg OOS Accuracy: {summary['avg_accuracy']:.1%} ± {summary['stability']:.1%}")

    return summary


def _generate_exit_snapshots(data: pd.DataFrame, evolved_strategies: dict) -> list[dict]:
    """
    Generate exit decision snapshots using CAUSAL labels (no future leakage).

    Mirrors the labeling in ExitStrategyEngine.train_from_simulations:
    - Observable danger signals (zero future info)
    - Fixed 3-day forward return (bounded horizon)
    """
    from models.trade_learner import FeatureExtractor
    from pricing.black_scholes import price_option, iv_from_vix, OptionType

    extractor = FeatureExtractor(data)
    snapshots = []
    n_rows = len(data)
    forward_horizon = 3

    for regime, strat in evolved_strategies.items():
        direction = strat.direction
        sd = strat.sd
        spread_width = strat.spread_width
        hold_days = strat.hold_days
        opt_type = OptionType.PUT if direction == "put" else OptionType.CALL

        for entry_idx in range(50, n_rows, 5):
            if entry_idx + hold_days >= n_rows:
                continue

            row = data.iloc[entry_idx]
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)
            if pd.isna(spot) or spot == 0 or pd.isna(vix):
                continue
            if vix < strat.min_vix or vix >= strat.max_vix:
                continue

            annual_vol = vix / 100.0
            period_vol = annual_vol / (252**0.5) * (hold_days**0.5)

            if direction == "put":
                short_strike = round((spot - spot * period_vol * sd) / 50) * 50
                long_strike = short_strike - spread_width
            else:
                short_strike = round((spot + spot * period_vol * sd) / 50) * 50
                long_strike = short_strike + spread_width

            s_iv = iv_from_vix(vix, short_strike, spot, opt_type)
            l_iv = iv_from_vix(vix, long_strike, spot, opt_type)
            s_prem = price_option(spot, short_strike, hold_days, s_iv, 0.065, opt_type).premium
            l_prem = price_option(spot, long_strike, hold_days, l_iv, 0.065, opt_type).premium
            entry_credit = s_prem - l_prem
            if entry_credit <= 0:
                continue

            max_loss_unit = spread_width - entry_credit

            full_pnls = [0.0]
            for d in range(1, hold_days + 1):
                idx2 = entry_idx + d
                if idx2 >= n_rows:
                    full_pnls.append(full_pnls[-1])
                    continue
                dr = data.iloc[idx2]
                ds = dr.get("nifty_close", spot)
                dv = dr.get("vix", vix)
                dte_r = max(hold_days - d, 1)
                if pd.isna(ds) or pd.isna(dv):
                    full_pnls.append(full_pnls[-1])
                    continue
                si2 = iv_from_vix(dv, short_strike, ds, opt_type)
                li2 = iv_from_vix(dv, long_strike, ds, opt_type)
                sn = price_option(ds, short_strike, dte_r, si2, 0.065, opt_type).premium
                ln = price_option(ds, long_strike, dte_r, li2, 0.065, opt_type).premium
                full_pnls.append(entry_credit - (sn - ln))

            if len(full_pnls) < forward_horizon + 2:
                continue

            peak_pnl = 0.0
            for d in range(1, len(full_pnls) - forward_horizon):
                idx2 = entry_idx + d
                if idx2 >= n_rows:
                    break

                current_pnl = full_pnls[d]
                if current_pnl > peak_pnl:
                    peak_pnl = current_pnl
                pnl_from_peak = current_pnl - peak_pnl

                pnl_pct = (current_pnl / entry_credit * 100) if entry_credit > 0 else 0

                dr = data.iloc[idx2]
                ds = dr.get("nifty_close", spot)
                dv = dr.get("vix", vix)

                dte_remaining = hold_days - d
                if direction == "put":
                    dist_short = (ds - short_strike) / ds * 100
                else:
                    dist_short = (short_strike - ds) / ds * 100

                vix_change = (dv - vix) / vix if vix > 0 else 0

                # --- CAUSAL LABEL ---
                should_exit = 0
                if dist_short < 2.0 and pnl_pct < 0:
                    should_exit = 1
                elif vix_change > 0.25 and pnl_pct < -10:
                    should_exit = 1
                elif pnl_pct < -60:
                    should_exit = 1
                elif d > hold_days * 0.6 and pnl_pct < 15 and pnl_pct > -30:
                    should_exit = 1

                if should_exit == 0:
                    fwd_idx = min(d + forward_horizon, len(full_pnls) - 1)
                    pnl_3d_later = full_pnls[fwd_idx]
                    forward_return = pnl_3d_later - current_pnl
                    if forward_return < -entry_credit * 0.10:
                        should_exit = 1

                market_features = extractor.extract(dr)
                if market_features is None:
                    continue

                pnl_3d_ago = full_pnls[max(d - 3, 0)]
                pnl_velocity_3d = (current_pnl - pnl_3d_ago) / 3 if d >= 3 else current_pnl / max(d, 1)

                trade_features = {
                    "pnl_pct": pnl_pct,
                    "dte_remaining": dte_remaining,
                    "days_in_trade": d,
                    "dist_to_short_strike_pct": dist_short,
                    "vix_now": dv,
                    "vix_change_since_entry": vix_change,
                    "spot_change_since_entry": (ds - spot) / spot * 100,
                    "pnl_velocity": current_pnl / d if d > 0 else 0,
                    "credit_captured_pct": pnl_pct,
                    "max_loss_proximity": abs(current_pnl) / max_loss_unit if current_pnl < 0 and max_loss_unit > 0 else 0,
                    "theta_estimate": entry_credit / hold_days,
                    "pnl_from_peak": pnl_from_peak,
                    "pnl_velocity_3d": pnl_velocity_3d,
                    "days_since_peak": d - full_pnls[:d + 1].index(peak_pnl) if peak_pnl > 0 else 0,
                }

                snapshot = {**market_features, **trade_features}
                snapshot["_label_should_exit"] = should_exit
                snapshots.append(snapshot)

    return snapshots


def _score_entry_model(model, test_trades, data) -> dict:
    """Score an entry model on a set of test trades."""
    y_true, y_pred_prob = [], []
    for trade in test_trades:
        entry_date = pd.Timestamp(trade.entry_date)
        idx = data.index.get_indexer([entry_date], method="nearest")[0]
        if idx >= len(data):
            continue
        row = data.iloc[idx]
        prediction = model.predict(row)
        if "error" in prediction:
            continue
        y_true.append(1 if trade.total_pnl > 0 else 0)
        y_pred_prob.append(prediction.get("probability_profitable", 0.5))

    if len(y_true) < 3:
        return {"accuracy": 0, "f1": 0}

    y_true = np.array(y_true)
    y_pred_prob = np.array(y_pred_prob)
    y_pred_class = (y_pred_prob >= 0.5).astype(int)

    result = {
        "accuracy": float(accuracy_score(y_true, y_pred_class)),
        "f1": float(f1_score(y_true, y_pred_class, zero_division=0)),
    }
    try:
        if len(set(y_true)) > 1:
            result["auc_roc"] = float(roc_auc_score(y_true, y_pred_prob))
    except Exception:
        pass
    return result


def run_full_validation(
    data: pd.DataFrame,
    evolved_strategies: dict,
    lots: int = 8,
    lot_size: int = 75,
    weekly_lots: int = 10,
    weekly_lot_size: int = 65,
    n_permutations: int = 20,
    verbose: bool = True,
) -> dict:
    """
    Run the complete production validation suite for ALL models:
      1. Walk-forward: Monthly entry model (TradeLearner v4)
      2. Walk-forward: Monthly exit model (ExitStrategyEngine)
      3. Walk-forward: Weekly entry model (WeeklyEntryLearner)
      4. Regime classifier OOS validation
      5. Permutation test: Monthly entry model
      6. Permutation test: Monthly exit model
      7. Permutation test: Weekly entry model
    """
    print("\n" + "=" * 80)
    print("  PRODUCTION MODEL VALIDATION SUITE")
    print("  Walk-Forward + Permutation Tests for ALL Models")
    print("=" * 80)

    # 1. Walk-forward: Monthly Entry
    print("\n─── [1/7] WALK-FORWARD: MONTHLY ENTRY MODEL (TradeLearner v4) ───")
    wf_entry = walk_forward_entry_model(data, lots, lot_size, verbose=verbose)

    # 2. Walk-forward: Monthly Exit
    print("\n─── [2/7] WALK-FORWARD: MONTHLY EXIT MODEL (ExitStrategyEngine) ───")
    wf_exit = walk_forward_exit_model(data, evolved_strategies, verbose=verbose)

    # 3. Walk-forward: Weekly Entry
    print("\n─── [3/7] WALK-FORWARD: WEEKLY ENTRY MODEL (WeeklyEntryLearner) ───")
    wf_weekly = walk_forward_weekly_entry_model(data, weekly_lots, weekly_lot_size, verbose=verbose)

    # 4. Regime Classifier
    print("\n─── [4/7] WALK-FORWARD: REGIME CLASSIFIER ───")
    regime_val = validate_regime_classifier(data, verbose=verbose)

    # 5. Permutation: Monthly Entry
    print(f"\n─── [5/7] PERMUTATION TEST: MONTHLY ENTRY ({n_permutations} shuffles) ───")
    perm_entry = permutation_test_entry_model(data, lots, lot_size, n_permutations, verbose=verbose)

    # 6. Permutation: Monthly Exit
    print(f"\n─── [6/7] PERMUTATION TEST: MONTHLY EXIT ({n_permutations} shuffles) ───")
    perm_exit = permutation_test_exit_model(data, evolved_strategies, n_permutations, verbose=verbose)

    # 7. Permutation: Weekly Entry
    print(f"\n─── [7/7] PERMUTATION TEST: WEEKLY ENTRY ({n_permutations} shuffles) ───")
    perm_weekly = permutation_test_weekly_entry(data, weekly_lots, weekly_lot_size, n_permutations, verbose=verbose)

    # ── Final Summary ──
    print("\n" + "=" * 80)
    print("  PRODUCTION VALIDATION SUMMARY")
    print("=" * 80)

    entry_wf_ok = wf_entry.get("avg_auc", 0.5) > 0.55
    exit_wf_ok = wf_exit.get("avg_auc", 0.5) > 0.55
    weekly_wf_ok = wf_weekly.get("avg_auc", 0.5) > 0.55
    regime_ok = regime_val.get("avg_accuracy", 0) > 0.60
    entry_perm_ok = perm_entry.get("significant_at_5pct", False)
    exit_perm_ok = perm_exit.get("significant_at_5pct", False)
    weekly_perm_ok = perm_weekly.get("significant_at_5pct", False)

    checks = [
        ("Monthly Entry WF AUC", wf_entry.get("avg_auc", 0), "> 0.55", entry_wf_ok),
        ("Monthly Entry Permutation", perm_entry.get("p_value_accuracy", 1), "p < 0.05", entry_perm_ok),
        ("Monthly Exit WF AUC", wf_exit.get("avg_auc", 0), "> 0.55", exit_wf_ok),
        ("Monthly Exit Permutation", perm_exit.get("p_value_f1", 1), "p < 0.05", exit_perm_ok),
        ("Weekly Entry WF AUC", wf_weekly.get("avg_auc", 0), "> 0.55", weekly_wf_ok),
        ("Weekly Entry Permutation", perm_weekly.get("p_value_auc", 1), "p < 0.05", weekly_perm_ok),
        ("Regime Classifier OOS", regime_val.get("avg_accuracy", 0), "> 0.60", regime_ok),
    ]

    print(f"\n  {'Model / Check':<30s} {'Value':>8s}  {'Threshold':>10s}  {'Status':>8s}")
    print(f"  {'-' * 62}")
    for name, val, thresh, passed in checks:
        status = "PASS" if passed else "FAIL"
        val_str = f"{val:.3f}" if isinstance(val, float) else str(val)
        print(f"  {name:<30s} {val_str:>8s}  {thresh:>10s}  {status:>8s}")

    total_passed = sum(c[3] for c in checks)
    total_checks = len(checks)
    print(f"\n  Overall: {total_passed}/{total_checks} checks passed")

    if total_passed >= 6:
        verdict = "ALL MODELS PRODUCTION-READY — strong signal across all validation methods"
    elif total_passed >= 4:
        verdict = "MOSTLY READY — core models validated, minor weaknesses in some areas"
    elif total_passed >= 2:
        verdict = "PARTIAL VALIDATION — some models adding value, others may be noise"
    else:
        verdict = "NOT READY — models may be overfitting, rely more on rule-based logic"
    print(f"  VERDICT: {verdict}")

    return {
        "walk_forward_entry": wf_entry,
        "walk_forward_exit": wf_exit,
        "walk_forward_weekly": wf_weekly,
        "regime_classifier": regime_val,
        "permutation_entry": perm_entry,
        "permutation_exit": perm_exit,
        "permutation_weekly": perm_weekly,
        "checks": checks,
        "total_passed": total_passed,
        "total_checks": total_checks,
        "overall_pass_rate": total_passed / total_checks,
    }
