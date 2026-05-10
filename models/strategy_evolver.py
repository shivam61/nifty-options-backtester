"""
Strategy Evolver — data-driven optimization of strategy parameters per market regime.

Instead of hand-tuning strategy parameters, this module:
1. Defines a parameter search space (direction, SD, width, targets, hold period)
2. Runs rolling simulations for each parameter combination across 7 years
3. Evaluates performance per VIX regime using Sharpe-like metrics
4. Selects the best parameter set per regime
5. Discovers "new" strategies that are regime-conditional optimal configs
6. Feeds optimized configs back for ML training

The optimization target (label) is configurable:
  - "sharpe": Maximize risk-adjusted returns (default)
  - "total_pnl": Maximize absolute profit
  - "win_rate": Maximize consistency
  - "min_drawdown": Minimize worst-case loss
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from itertools import product
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pricing.black_scholes import price_option, iv_from_vix, OptionType
from backtester.engine import TradeResult

EVOLVED_CACHE = Path(__file__).parent / "../data/.cache/evolved_strategies.json"


@dataclass
class EvolvedStrategy:
    """A strategy configuration discovered by the evolver."""
    name: str
    direction: str
    sd: float
    spread_width: int
    profit_target_pct: float
    stop_loss_pct: float
    hold_days: int
    min_vix: float
    max_vix: float
    # Performance metrics from optimization
    sharpe: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    num_trades: int = 0
    max_drawdown: float = 0.0
    avg_pnl: float = 0.0

    def to_sim_config(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "sd": self.sd,
            "spread_width": self.spread_width,
            "min_vix": self.min_vix,
            "max_vix": self.max_vix,
        }


# Smart grid — 2 × 4 × 3 × 3 × 2 × 2 = 288 combos (fast enough for <5 min)
PARAM_GRID = {
    "direction": ["put", "call"],
    "sd": [0.7, 0.9, 1.1, 1.4],
    "spread_width": [300, 500, 700],
    "profit_target_pct": [30, 50, 70],
    "stop_loss_pct": [50, 70],
    "hold_days": [14, 21],
}

# Multi-expiry strategy grid for calendar and diagonal spreads.
# Separate from PARAM_GRID because these require dual-DTE simulation.
MULTI_EXPIRY_PARAM_GRID = {
    "strategy_type": ["calendar", "diagonal"],
    "short_sd": [0.8, 1.0, 1.2],
    "long_sd_offset": [0.0, 0.3, 0.5],  # 0.0 = calendar (same strike), >0 = diagonal
    "near_dte": [21, 28],
    "far_dte_gap": [21, 30],
    "profit_target_pct": [30, 40, 50],
    "max_loss_pct": [50, 70],
    "max_rolls": [1, 2],
}

VIX_REGIMES = {
    "low_vix_12_15": (12, 15),
    "mid_vix_15_20": (15, 20),
    "high_vix_20_30": (20, 30),
    "extreme_vix_30+": (30, 100),
}


class StrategyEvolver:
    """
    Evolves strategy parameters using exhaustive simulation across regimes.

    The evolver runs a parameter sweep, evaluates each combination per regime,
    and returns the optimal EvolvedStrategy for each regime.
    """

    def __init__(self, data: pd.DataFrame, lots: int = 2, lot_size: int = 75):
        self.data = data
        self.lots = lots
        self.lot_size = lot_size
        self.n_rows = len(data)
        self.evolved_strategies: dict[str, EvolvedStrategy] = {}
        self.all_results: list[dict] = []

    def evolve(
        self,
        target: str = "sharpe",
        entry_every_n_days: int = 10,
        min_trades: int = 8,
        oos_validation: bool = True,
        train_pct: float = 0.75,
        save_cache: bool = True,
        verbose: bool = True,
    ) -> dict[str, EvolvedStrategy]:
        """
        Run the full evolution pipeline with out-of-sample validation.

        Optimization is done on the first `train_pct` of data.  The selected
        strategy is then validated on the held-out portion.  If validation
        Sharpe is negative or < 30% of train Sharpe, we fall back to the
        next-best candidate that passes validation, preventing overfitting
        to lucky historical trades.

        Args:
            target: Optimization label — "sharpe", "total_pnl", "win_rate", "min_drawdown"
            entry_every_n_days: How often to simulate entries (5 = every week)
            min_trades: Minimum trades per config to be considered valid
            oos_validation: Whether to run out-of-sample validation
            train_pct: Fraction of data used for optimization (rest = validation)
        """
        if verbose:
            total_combos = 1
            for v in PARAM_GRID.values():
                total_combos *= len(v)
            print(f"  Parameter space: {total_combos} combinations × {len(VIX_REGIMES)} regimes")

        train_cutoff = int(self.n_rows * train_pct) if oos_validation else self.n_rows
        if verbose and oos_validation:
            train_end = self.data.index[min(train_cutoff, self.n_rows - 1)]
            val_start = self.data.index[min(train_cutoff + 1, self.n_rows - 1)]
            print(f"  Train/Val split: train up to row {train_cutoff} ({train_end.date()}), "
                  f"validate from ({val_start.date()})")

        regime_entries = self._compute_regime_entries(entry_every_n_days)
        if oos_validation:
            train_entries = {
                regime: [i for i in indices if i < train_cutoff]
                for regime, indices in regime_entries.items()
            }
            val_entries = {
                regime: [i for i in indices if i >= train_cutoff]
                for regime, indices in regime_entries.items()
            }
        else:
            train_entries = regime_entries
            val_entries = {}

        if verbose:
            for regime, indices in train_entries.items():
                val_count = len(val_entries.get(regime, []))
                print(f"    {regime}: {len(indices)} train days, {val_count} validation days")

        all_results = []
        param_keys = list(PARAM_GRID.keys())
        param_values = list(PARAM_GRID.values())
        total_combos = 1
        for v in param_values:
            total_combos *= len(v)

        for i, combo in enumerate(product(*param_values)):
            params = dict(zip(param_keys, combo))

            if verbose and (i + 1) % 200 == 0:
                print(f"    Testing combo {i+1}/{total_combos}...")

            for regime_name, (vix_lo, vix_hi) in VIX_REGIMES.items():
                entries = train_entries.get(regime_name, [])
                if len(entries) < min_trades:
                    continue

                trades = self._simulate_param_set(entries, params)
                if len(trades) < min_trades:
                    continue

                metrics = self._compute_metrics(trades)
                metrics["regime"] = regime_name
                metrics["params"] = params.copy()
                all_results.append(metrics)

        self.all_results = all_results

        if verbose:
            print(f"  Evaluated {len(all_results)} valid config-regime combinations")

        sort_key = {
            "sharpe": lambda r: r["sharpe"],
            "total_pnl": lambda r: r["total_pnl"],
            "win_rate": lambda r: r["win_rate"],
            "min_drawdown": lambda r: -r["max_drawdown"],
        }.get(target, lambda r: r["sharpe"])

        best = {}
        for regime_name in VIX_REGIMES:
            regime_results = [r for r in all_results if r["regime"] == regime_name]
            if not regime_results:
                continue

            regime_results.sort(key=sort_key, reverse=True)

            vix_lo, vix_hi = VIX_REGIMES[regime_name]
            selected = None

            candidates = regime_results[:10] if oos_validation else regime_results[:1]
            for candidate in candidates:
                p = candidate["params"]

                if oos_validation and val_entries.get(regime_name):
                    val_trades = self._simulate_param_set(val_entries[regime_name], p)
                    if len(val_trades) >= 3:
                        val_metrics = self._compute_metrics(val_trades)
                        val_sharpe = val_metrics["sharpe"]
                        train_sharpe = candidate["sharpe"]

                        degradation = (
                            val_sharpe / train_sharpe if train_sharpe > 0 else 0
                        )

                        if val_sharpe < 0:
                            if verbose:
                                print(f"    {regime_name}: candidate sd={p['sd']} w={p['spread_width']} "
                                      f"REJECTED (val Sharpe {val_sharpe:.2f} < 0)")
                            continue
                        if train_sharpe > 0 and degradation < 0.3:
                            if verbose:
                                print(f"    {regime_name}: candidate sd={p['sd']} w={p['spread_width']} "
                                      f"REJECTED (val Sharpe {val_sharpe:.2f} = {degradation:.0%} of train {train_sharpe:.2f})")
                            continue

                        if verbose:
                            print(f"    {regime_name}: sd={p['sd']} w={p['spread_width']} "
                                  f"PASSED (train Sharpe {train_sharpe:.2f} → val {val_sharpe:.2f}, "
                                  f"{degradation:.0%} retention)")

                strat_name = f"evolved_{p['direction']}_{regime_name}"
                selected = EvolvedStrategy(
                    name=strat_name,
                    direction=p["direction"],
                    sd=p["sd"],
                    spread_width=p["spread_width"],
                    profit_target_pct=p["profit_target_pct"],
                    stop_loss_pct=p["stop_loss_pct"],
                    hold_days=p["hold_days"],
                    min_vix=vix_lo,
                    max_vix=vix_hi,
                    sharpe=candidate["sharpe"],
                    total_pnl=candidate["total_pnl"],
                    win_rate=candidate["win_rate"],
                    num_trades=candidate["num_trades"],
                    max_drawdown=candidate["max_drawdown"],
                    avg_pnl=candidate["avg_pnl"],
                )
                break

            if selected is None and regime_results:
                if verbose:
                    print(f"    {regime_name}: no candidate passed OOS — using top-1 as fallback")
                p = regime_results[0]["params"]
                top = regime_results[0]
                strat_name = f"evolved_{p['direction']}_{regime_name}"
                selected = EvolvedStrategy(
                    name=strat_name,
                    direction=p["direction"],
                    sd=p["sd"],
                    spread_width=p["spread_width"],
                    profit_target_pct=p["profit_target_pct"],
                    stop_loss_pct=p["stop_loss_pct"],
                    hold_days=p["hold_days"],
                    min_vix=vix_lo,
                    max_vix=vix_hi,
                    sharpe=top["sharpe"],
                    total_pnl=top["total_pnl"],
                    win_rate=top["win_rate"],
                    num_trades=top["num_trades"],
                    max_drawdown=top["max_drawdown"],
                    avg_pnl=top["avg_pnl"],
                )

            if selected:
                best[regime_name] = selected

        self.evolved_strategies = best
        if save_cache:
            self._save_cache()
        return best

    def _save_cache(self):
        """Save evolved strategies to disk for fast loading in signal mode."""
        cache_data = {
            "evolved_at": str(date.today()),
            "target": "sharpe",
            "strategies": {
                regime: asdict(strat)
                for regime, strat in self.evolved_strategies.items()
            },
        }
        EVOLVED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(EVOLVED_CACHE, "w") as f:
            json.dump(cache_data, f, indent=2, default=str)

    @staticmethod
    def load_from_cache() -> Optional[dict[str, "EvolvedStrategy"]]:
        """Load evolved strategies from disk. Returns None if stale or missing."""
        if not EVOLVED_CACHE.exists():
            return None
        try:
            with open(EVOLVED_CACHE) as f:
                cache_data = json.load(f)

            evolved_at = date.fromisoformat(cache_data["evolved_at"])
            age_days = (date.today() - evolved_at).days

            strategies = {}
            for regime, d in cache_data["strategies"].items():
                strategies[regime] = EvolvedStrategy(**d)

            return strategies
        except Exception:
            return None

    @staticmethod
    def cache_age_days() -> Optional[int]:
        """Returns how old the cache is in days, or None if no cache."""
        if not EVOLVED_CACHE.exists():
            return None
        try:
            with open(EVOLVED_CACHE) as f:
                cache_data = json.load(f)
            evolved_at = date.fromisoformat(cache_data["evolved_at"])
            return (date.today() - evolved_at).days
        except Exception:
            return None

    def get_evolved_sim_configs(self) -> list[dict]:
        """Convert evolved strategies to STRATEGY_CONFIGS format for RollingWindowSimulator."""
        configs = []
        for regime, strat in self.evolved_strategies.items():
            configs.append({
                "name": strat.name,
                "direction": strat.direction,
                "sd": strat.sd,
                "spread_width": strat.spread_width,
                "min_vix": strat.min_vix,
                "max_vix": strat.max_vix,
            })
        return configs

    def compare_with_baseline(
        self, baseline_configs: list[dict], entry_every_n_days: int = 5
    ) -> dict:
        """Compare evolved strategies against baseline (hand-tuned) configs."""
        regime_entries = self._compute_regime_entries(entry_every_n_days)

        results = {"baseline": {}, "evolved": {}}

        for regime_name, (vix_lo, vix_hi) in VIX_REGIMES.items():
            entries = regime_entries.get(regime_name, [])
            if len(entries) < 5:
                continue

            # Baseline
            baseline_trades = []
            for cfg in baseline_configs:
                if cfg.get("min_vix", 0) <= vix_lo and cfg.get("max_vix", 100) >= vix_hi:
                    params = {
                        "direction": cfg["direction"],
                        "sd": cfg["sd"],
                        "spread_width": cfg["spread_width"],
                        "profit_target_pct": 50.0,
                        "stop_loss_pct": 60.0,
                        "hold_days": 21,
                    }
                    baseline_trades.extend(self._simulate_param_set(entries, params))

            if baseline_trades:
                results["baseline"][regime_name] = self._compute_metrics(baseline_trades)

            # Evolved
            if regime_name in self.evolved_strategies:
                strat = self.evolved_strategies[regime_name]
                params = {
                    "direction": strat.direction,
                    "sd": strat.sd,
                    "spread_width": strat.spread_width,
                    "profit_target_pct": strat.profit_target_pct,
                    "stop_loss_pct": strat.stop_loss_pct,
                    "hold_days": strat.hold_days,
                }
                evolved_trades = self._simulate_param_set(entries, params)
                if evolved_trades:
                    results["evolved"][regime_name] = self._compute_metrics(evolved_trades)

        return results

    def generate_training_trades(self, entry_every_n_days: int = 3) -> list[TradeResult]:
        """Generate training data using evolved strategies."""
        if not self.evolved_strategies:
            raise ValueError("Run evolve() first")

        regime_entries = self._compute_regime_entries(entry_every_n_days)
        all_trades = []

        for regime_name, strat in self.evolved_strategies.items():
            entries = regime_entries.get(regime_name, [])
            params = {
                "direction": strat.direction,
                "sd": strat.sd,
                "spread_width": strat.spread_width,
                "profit_target_pct": strat.profit_target_pct,
                "stop_loss_pct": strat.stop_loss_pct,
                "hold_days": strat.hold_days,
            }
            trades = self._simulate_param_set(entries, params)
            all_trades.extend(trades)

        all_trades.sort(key=lambda t: t.entry_date)
        return all_trades

    def top_n_per_regime(self, n: int = 5, target: str = "sharpe") -> dict[str, list[dict]]:
        """Return top N parameter combos per regime for analysis."""
        top = {}
        for regime_name in VIX_REGIMES:
            regime_results = [r for r in self.all_results if r["regime"] == regime_name]
            if target == "sharpe":
                regime_results.sort(key=lambda r: r["sharpe"], reverse=True)
            elif target == "total_pnl":
                regime_results.sort(key=lambda r: r["total_pnl"], reverse=True)
            elif target == "win_rate":
                regime_results.sort(key=lambda r: r["win_rate"], reverse=True)
            top[regime_name] = regime_results[:n]
        return top

    # ── Private helpers ──

    def _compute_regime_entries(self, entry_every_n_days: int) -> dict[str, list[int]]:
        regime_entries = {name: [] for name in VIX_REGIMES}
        for idx in range(50, self.n_rows):
            if (idx - 50) % entry_every_n_days != 0:
                continue
            row = self.data.iloc[idx]
            vix = row.get("vix", 15)
            if pd.isna(vix):
                continue
            for regime_name, (vix_lo, vix_hi) in VIX_REGIMES.items():
                if vix_lo <= vix < vix_hi:
                    regime_entries[regime_name].append(idx)
                    break
        return regime_entries

    def _simulate_param_set(
        self, entry_indices: list[int], params: dict
    ) -> list[TradeResult]:
        direction = params["direction"]
        sd = params["sd"]
        spread_width = params["spread_width"]
        profit_target_pct = params["profit_target_pct"]
        stop_loss_pct = params["stop_loss_pct"]
        hold_days = params["hold_days"]
        opt_type = OptionType.PUT if direction == "put" else OptionType.CALL

        trades = []
        for entry_idx in entry_indices:
            if entry_idx + hold_days >= self.n_rows:
                continue

            row = self.data.iloc[entry_idx]
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)
            if pd.isna(spot) or spot == 0:
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
            exit_reason = "expiry"
            exit_idx = min(entry_idx + hold_days, self.n_rows - 1)
            pnl_per_unit = 0

            for day_offset in range(1, hold_days + 1):
                idx = entry_idx + day_offset
                if idx >= self.n_rows:
                    break
                day_row = self.data.iloc[idx]
                day_spot = day_row.get("nifty_close", spot)
                day_vix = day_row.get("vix", vix)
                dte_remaining = max(hold_days - day_offset, 1)
                if pd.isna(day_spot) or pd.isna(day_vix):
                    continue

                s_iv2 = iv_from_vix(day_vix, short_strike, day_spot, opt_type)
                l_iv2 = iv_from_vix(day_vix, long_strike, day_spot, opt_type)
                s_now = price_option(day_spot, short_strike, dte_remaining, s_iv2, 0.065, opt_type).premium
                l_now = price_option(day_spot, long_strike, dte_remaining, l_iv2, 0.065, opt_type).premium
                pnl_per_unit = entry_credit - (s_now - l_now)

                if pnl_per_unit >= entry_credit * profit_target_pct / 100:
                    exit_reason = "profit_target"
                    exit_idx = idx
                    break
                if pnl_per_unit < 0 and abs(pnl_per_unit) > max_loss_unit * stop_loss_pct / 100:
                    exit_reason = "stop_loss"
                    exit_idx = idx
                    break
                if dte_remaining <= 3:
                    exit_reason = "dte_limit"
                    exit_idx = idx
                    break

            total_pnl = pnl_per_unit * self.lots * self.lot_size
            entry_date = self.data.index[entry_idx]
            exit_date = self.data.index[exit_idx]
            if hasattr(entry_date, "date"):
                entry_date = entry_date.date()
            if hasattr(exit_date, "date"):
                exit_date = exit_date.date()

            strat_name = "put_credit_spread" if direction == "put" else "put_credit_wide"
            trades.append(TradeResult(
                signal_date=entry_date,
                entry_date=entry_date,
                exit_date=exit_date,
                strategy=strat_name,
                entry_spot=spot,
                exit_spot=self.data.iloc[exit_idx].get("nifty_close", spot),
                entry_vix=vix,
                exit_vix=self.data.iloc[exit_idx].get("vix", vix),
                net_credit=entry_credit,
                pnl_per_unit=pnl_per_unit,
                total_pnl=total_pnl,
                pnl_pct=(pnl_per_unit / entry_credit * 100) if entry_credit > 0 else 0,
                exit_reason=exit_reason,
                holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
                legs_detail=f"{direction} sd={sd} w={spread_width} pt={profit_target_pct} sl={stop_loss_pct} h={hold_days}",
            ))

        return trades

    def _simulate_multi_expiry_param_set(
        self, entry_indices: list[int], params: dict
    ) -> list[TradeResult]:
        """Simulate calendar or diagonal spread with rolling capability."""
        strategy_type = params["strategy_type"]
        short_sd = params["short_sd"]
        long_sd_offset = params["long_sd_offset"]
        near_dte = params["near_dte"]
        far_dte_gap = params["far_dte_gap"]
        profit_target_pct = params["profit_target_pct"]
        max_loss_pct = params["max_loss_pct"]
        max_rolls = params["max_rolls"]
        opt_type = OptionType.PUT

        total_max_hold = near_dte + max_rolls * near_dte
        trades = []

        for entry_idx in entry_indices:
            if entry_idx + total_max_hold >= self.n_rows:
                continue

            row = self.data.iloc[entry_idx]
            spot = row.get("nifty_close", 0)
            vix = row.get("vix", 15)
            if pd.isna(spot) or spot == 0:
                continue

            annual_vol = vix / 100.0
            period_vol = annual_vol / (252 ** 0.5) * (near_dte ** 0.5)

            short_strike = round((spot - spot * period_vol * short_sd) / 50) * 50
            if long_sd_offset > 0:
                long_strike = round((spot - spot * period_vol * (short_sd + long_sd_offset)) / 50) * 50
            else:
                long_strike = short_strike

            s_iv = iv_from_vix(vix, short_strike, spot, opt_type)
            l_iv = iv_from_vix(vix, long_strike if long_strike != short_strike else short_strike, spot, opt_type)
            s_prem = price_option(spot, short_strike, near_dte, s_iv, 0.065, opt_type).premium
            l_prem = price_option(spot, long_strike if long_strike != short_strike else short_strike,
                                  near_dte + far_dte_gap, l_iv, 0.065, opt_type).premium
            entry_debit = l_prem - s_prem

            strat_name = "calendar_spread"
            rolls_done = 0
            cumulative_pnl = 0.0
            current_short_strike = short_strike
            current_near_dte_start = entry_idx
            current_near_dte_len = near_dte
            exit_reason = "expiry"
            exit_idx = entry_idx

            for roll_iter in range(max_rolls + 1):
                for day_offset in range(1, current_near_dte_len + 1):
                    idx = current_near_dte_start + day_offset
                    if idx >= self.n_rows:
                        break
                    day_row = self.data.iloc[idx]
                    day_spot = day_row.get("nifty_close", spot)
                    day_vix = day_row.get("vix", vix)
                    dte_remaining = max(current_near_dte_len - day_offset, 1)
                    if pd.isna(day_spot) or pd.isna(day_vix):
                        continue

                    s_iv2 = iv_from_vix(day_vix, current_short_strike, day_spot, opt_type)
                    s_now = price_option(day_spot, current_short_strike, dte_remaining, s_iv2, 0.065, opt_type).premium

                    far_dte_rem = max(current_near_dte_len + far_dte_gap - day_offset + (near_dte * roll_iter), 1)
                    l_target = long_strike if long_strike != short_strike else current_short_strike
                    l_iv2 = iv_from_vix(day_vix, l_target, day_spot, opt_type)
                    l_now = price_option(day_spot, l_target, far_dte_rem, l_iv2, 0.065, opt_type).premium

                    spread_value = l_now - s_now
                    pnl_per_unit = spread_value - entry_debit

                    if pnl_per_unit >= abs(entry_debit) * profit_target_pct / 100:
                        exit_reason = "profit_target"
                        exit_idx = idx
                        cumulative_pnl += pnl_per_unit
                        break

                    if pnl_per_unit < 0 and abs(pnl_per_unit) > abs(entry_debit) * max_loss_pct / 100:
                        exit_reason = "stop_loss"
                        exit_idx = idx
                        cumulative_pnl += pnl_per_unit
                        break

                    if dte_remaining <= 3:
                        if rolls_done < max_rolls:
                            theta_collected = s_prem - s_now
                            cumulative_pnl += theta_collected
                            rolls_done += 1
                            current_near_dte_start = idx
                            dv = annual_vol / (252 ** 0.5) * (near_dte ** 0.5)
                            current_short_strike = round((day_spot - day_spot * dv * short_sd) / 50) * 50
                            s_iv_new = iv_from_vix(day_vix, current_short_strike, day_spot, opt_type)
                            s_prem = price_option(day_spot, current_short_strike, near_dte,
                                                  s_iv_new, 0.065, opt_type).premium
                            exit_reason = "roll"
                            exit_idx = idx
                            break
                        else:
                            exit_reason = "dte_limit"
                            exit_idx = idx
                            cumulative_pnl += pnl_per_unit
                            break

                    exit_idx = idx
                else:
                    cumulative_pnl += pnl_per_unit if 'pnl_per_unit' in dir() else 0
                    break

                if exit_reason in ("profit_target", "stop_loss", "dte_limit"):
                    break

            total_pnl = cumulative_pnl * self.lots * self.lot_size
            entry_date = self.data.index[entry_idx]
            exit_date = self.data.index[exit_idx]
            if hasattr(entry_date, "date"):
                entry_date = entry_date.date()
            if hasattr(exit_date, "date"):
                exit_date = exit_date.date()

            trades.append(TradeResult(
                signal_date=entry_date,
                entry_date=entry_date,
                exit_date=exit_date,
                strategy=strat_name,
                entry_spot=spot,
                exit_spot=self.data.iloc[exit_idx].get("nifty_close", spot),
                entry_vix=vix,
                exit_vix=self.data.iloc[exit_idx].get("vix", vix),
                net_credit=s_prem,
                pnl_per_unit=cumulative_pnl,
                total_pnl=total_pnl,
                pnl_pct=(cumulative_pnl / abs(entry_debit) * 100) if entry_debit != 0 else 0,
                exit_reason=exit_reason,
                holding_days=(exit_date - entry_date).days if isinstance(exit_date, date) else 0,
                legs_detail=(f"{strategy_type} sd={short_sd} off={long_sd_offset} "
                             f"dte={near_dte}+{far_dte_gap} rolls={rolls_done}/{max_rolls}"),
            ))

        return trades

    def evolve_multi_expiry(
        self,
        target: str = "sharpe",
        entry_every_n_days: int = 15,
        min_trades: int = 5,
        verbose: bool = True,
    ) -> dict[str, EvolvedStrategy]:
        """Evolve calendar/diagonal spread parameters per regime."""
        if verbose:
            total_combos = 1
            for v in MULTI_EXPIRY_PARAM_GRID.values():
                total_combos *= len(v)
            print(f"  Multi-expiry parameter space: {total_combos} combinations × {len(VIX_REGIMES)} regimes")

        regime_entries = self._compute_regime_entries(entry_every_n_days)

        sort_key = {
            "sharpe": lambda r: r["sharpe"],
            "total_pnl": lambda r: r["total_pnl"],
            "win_rate": lambda r: r["win_rate"],
        }.get(target, lambda r: r["sharpe"])

        param_keys = list(MULTI_EXPIRY_PARAM_GRID.keys())
        param_values = list(MULTI_EXPIRY_PARAM_GRID.values())
        all_results = []

        for combo in product(*param_values):
            params = dict(zip(param_keys, combo))
            if params["strategy_type"] == "calendar" and params["long_sd_offset"] > 0:
                continue
            if params["strategy_type"] == "diagonal" and params["long_sd_offset"] == 0:
                continue

            for regime_name in VIX_REGIMES:
                entries = regime_entries.get(regime_name, [])
                if len(entries) < min_trades:
                    continue
                trades = self._simulate_multi_expiry_param_set(entries, params)
                if len(trades) < min_trades:
                    continue
                metrics = self._compute_metrics(trades)
                metrics["regime"] = regime_name
                metrics["params"] = params.copy()
                metrics["strategy_type"] = params["strategy_type"]
                all_results.append(metrics)

        best = {}
        for regime_name in VIX_REGIMES:
            regime_results = [r for r in all_results if r["regime"] == regime_name]
            if not regime_results:
                continue
            regime_results.sort(key=sort_key, reverse=True)
            top = regime_results[0]
            p = top["params"]
            vix_lo, vix_hi = VIX_REGIMES[regime_name]
            strat_name = f"evolved_{p['strategy_type']}_{regime_name}"

            best[regime_name] = EvolvedStrategy(
                name=strat_name,
                direction="put",
                sd=p["short_sd"],
                spread_width=int(p["long_sd_offset"] * 1000),
                profit_target_pct=p["profit_target_pct"],
                stop_loss_pct=p["max_loss_pct"],
                hold_days=p["near_dte"] * (1 + p["max_rolls"]),
                min_vix=vix_lo,
                max_vix=vix_hi,
                sharpe=top["sharpe"],
                total_pnl=top["total_pnl"],
                win_rate=top["win_rate"],
                num_trades=top["num_trades"],
                max_drawdown=top["max_drawdown"],
                avg_pnl=top["avg_pnl"],
            )

            if verbose:
                print(f"  {regime_name}: best={p['strategy_type']} sd={p['short_sd']} "
                      f"dte={p['near_dte']}+{p['far_dte_gap']} rolls={p['max_rolls']} "
                      f"Sharpe={top['sharpe']:.2f} WR={top['win_rate']:.0f}%")

        self.evolved_multi_expiry = best
        return best

    def _compute_metrics(self, trades: list[TradeResult]) -> dict:
        if not trades:
            return {"sharpe": -999, "total_pnl": 0, "win_rate": 0,
                    "num_trades": 0, "max_drawdown": 0, "avg_pnl": 0}

        pnls = np.array([t.total_pnl for t in trades])
        wins = np.sum(pnls > 0)
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = running_max - cumulative
        max_dd = float(drawdowns.max()) if len(drawdowns) > 0 else 0

        mean_pnl = pnls.mean()
        std_pnl = pnls.std() if pnls.std() > 0 else 1
        sharpe = float(mean_pnl / std_pnl * np.sqrt(len(trades) / 7))  # annualized-ish

        return {
            "sharpe": sharpe,
            "total_pnl": float(pnls.sum()),
            "win_rate": float(wins / len(trades) * 100),
            "num_trades": len(trades),
            "max_drawdown": float(max_dd),
            "avg_pnl": float(mean_pnl),
        }
