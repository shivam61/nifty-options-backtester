from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingFlowConfig:
    """
    Fixed training defaults for evolve / layered retraining.

    These values are intentionally not exposed through CLI flags so model
    training stays deterministic across production runs.

    Execution-only switches (environment variables, results are identical for
    every setting; read in models/layered_evolve.py at call time):
      NIFTY_SIM_WINDOW  default "1": per-stage entry simulation visits only the
                        entry bars that can land in the stage window.  "0" =
                        original simulate-everything-then-filter path.
      NIFTY_SIM_JOBS    default "1": worker processes for the per-stage entry
                        simulation.  "0" or negative = all cores; capped at 8.
    """

    evolve_target: str = "sharpe"
    strategy_evolve_entry_every_n_days: int = 5
    multi_expiry_entry_every_n_days: int = 15
    layered_stage_count: int = 4
    layered_entry_every_n_days: int = 3
    layered_retrain_interval_bars: int = 21
    layered_train_pct: float = 0.75
    layered_min_trades: int = 8
    weekly_training_min_samples: int = 20
    monthly_entry_every_n_days: int = 3
    monthly_exit_entry_every_n_days: int = 10
    weekly_entry_every_n_days: int = 2


TRAINING_FLOW = TrainingFlowConfig()
