# CLAUDE.md — Nifty Options Backtester

## What This Is

A Python backtester + live-signal system for **NSE Nifty 50 index options selling** (Indian market). Fetches 17 years of data (2009–present) from Yahoo Finance, engineers 100+ features, trains per-regime LightGBM models to time entries, then runs a combined **monthly (50% capital) + weekly (50% capital)** options backtest. Entries are timed to the **11:00–13:00 IST mid-session window** (tighter bid-ask, stable spot). Capital base ₹5L INR, lot size 65. Every run auto-appends to `BACKTEST_CHANGELOG.md` and `backtest_runs.jsonl`.

---

## Layer Map

| Layer | Folder | Key File | Role |
|-------|--------|----------|------|
| Data | `data/` | `market_data.py` | Fetches 16 Yahoo Finance tickers → builds 100+ column DataFrame; parquet cache in `data/.cache/` |
| Strategy | `strategies/` | `multi_strategy.py` | 8 strategy classes + `RegimeAdaptiveStrategy` which routes ML picks to sub-strategies via `force_strategy_selection()` |
| Backtester | `backtester/` | `combined_engine.py` | `CombinedBacktestEngine` runs monthly + weekly tracks concurrently with DD kill-switch, VIX gates, production safety rules |
| ML | `models/` | `trade_learner.py` | `FeatureExtractor` (52 features, 8 groups) + `TradeLearner` (win-prob classifier + P&L regressor); cached in `data/.cache/` |

---

## Key Constants

| Constant | Value | Source |
|----------|-------|--------|
| `lot_size` | 65 | `config.BacktestConfig` |
| `initial_capital` | ₹500,000 | `config.BacktestConfig` |
| `_MONDAY_CUTOVER` | 2024-04-04 | `data/expiry_calendar.py` — NSE switched from Thursday to Monday expiry |
| `entry_threshold` | 0.50 | `config.BacktestConfig.monthly_entry_threshold` → `CombinedBacktestEngine` |
| `monthly_max_lots_cap` | 30 | `CombinedBacktestEngine.__init__` (`safe_monthly_cap`) |
| `monthly_budget_pct` | 50% | `main.py:_monthly_pct` in `run_backtest_combined()` |
| `weekly_budget_pct` | 50% | `main.py:_weekly_pct` in `run_backtest_combined()` |
| `mid_session_intraday_alpha` | 0.40 | `config.BacktestConfig` — fraction of open→close move by 11 AM |
| `mid_session_slippage_scale` | 0.75 | `config.BacktestConfig` / `WeeklyBacktestConfig` — 25% tighter fills |
| `entry_window_start_hour` | 11 | `config.BacktestConfig` — signal mode live gate start (IST) |
| `entry_window_end_hour` | 13 | `config.BacktestConfig` — signal mode live gate end (IST) |
| `vix_simultaneous_cap` | 25.0 | `run_backtest_combined()` — blocks weekly entries when VIX > 25 and monthly trade is open |
| `dd_kill_pct` | 0.20 | `ProductionRulesConfig` in `run_backtest_combined()` |
| `dd_recovery_pct` | 0.16 | same — engine re-enables after kill-switch when DD recovers to this level |
| `BWB max_vix` default | 30.0 | `BrokenWingButterflyStrategy(max_vix=30)` — aligns with router's VIX 22–30 zone |
| Circuit breaker — 50d drawdown | -18% | `RegimeAdaptiveStrategy.get_eligible_strategies()` |
| Circuit breaker — crash score v2 | ≥ 0.80 | same |
| Circuit breaker — multi-asset stress | ≥ 0.80 | same |
| Weekly `stop_loss_pct` | 100% | `config.WeeklyBacktestConfig` |

---

## CLI Quick Reference

```bash
python main.py --mode evolve              # Grid-search params + train all ML models (run first)
python main.py --mode backtest-combined   # Monthly 50% + weekly 50% combined backtest (mid-session fills)
python main.py --mode backtest            # Monthly-only backtest
python main.py --mode signal-combined     # Live combined signal (Fyers API)
python main.py --mode signal              # Live monthly signal (Yahoo + NSE chain)
python main.py --mode monitor             # ML exit scoring for active trades in JSON journal
python main.py --mode validate            # Walk-forward + permutation tests
python main.py --mode ablation            # Drop-one-out strategy contribution analysis
python main.py --mode stress              # Crisis period replay (2008, 2020, 2022, 2025)
python main.py --start 2019-01-01 --capital 1000000 --lots 25 --run-label "v5 test"
```

**Model caches** (`data/.cache/*.pkl`) must exist before running backtest/signal modes. Run `--mode evolve` first or after any strategy/feature changes.

---

## Data Flow (5 Steps)

1. **Fetch** → `MarketDataFetcher.build_combined_dataset()` — 16 tickers (Nifty, India VIX, Crude, USD/INR, Gold, DXY, US VIX, US 10Y, S&P 500, Bank Nifty, Silver, Nifty IT, EEM, Hang Seng, EuroStoxx50); parquet cache per ticker+date range
2. **Features** → 100+ derived columns: returns, RSI, Bollinger, SMA, drawdown, crash scores (V1+V2), VRP, multi-asset stress, cross-geo composites (`crude_inr_composite`, `dxy_crude_composite`, `vix_premium_over_us`, `fii_flow_proxy`)
3. **Regime + ML** → `RegimeAwareLearner` classifies day into LOW_VOL/HIGH_VOL/CRASH/TRENDING; GBM+RF ensemble scores win probability; entry allowed if `win_prob ≥ entry_threshold`
4. **Entry** → `RegimeAdaptiveStrategy.get_eligible_strategies()` filters by VIX zone and circuit breakers → `ExpirySelector.select_best()` scores 2–3 upcoming expiries via EV + theta quality formula → `force_strategy_selection()` activates chosen strategy
5. **Exit** → `ExitStrategyEngine` (GBM) re-scores daily; also rule-based: 50% profit target, 2× credit stop-loss, DTE limit, trailing peak/drop, VIX-adaptive thresholds

---

## ML Model Map

| Model | File | Cache | Purpose |
|-------|------|-------|---------|
| `RegimeClassifier` | `models/regime_classifier.py` | `data/.cache/entry_model_v4.pkl` | 4-class GBM regime label (used as feature in v4) |
| `RegimeAwareLearner` | `models/regime_aware_learner.py` | `data/.cache/entry_model_v4.pkl` | Win-prob + strategy selector; single model v4 with regime as feature |
| `ExitStrategyEngine` | `models/trade_monitor.py` | `data/.cache/exit_model.pkl` | GBM should-exit decision; top features: pnl_pct, credit_captured_pct, pnl_velocity |
| `WeeklyRiskEngine` | `models/weekly_risk_engine.py` | `data/.cache/weekly_risk_engine_v2.pkl` | Tail-loss risk scorer for weekly entry gates; AUC ~0.62 |

---

## Test Suite (220 tests, ~4s)

```
tests/conftest.py          — Shared fixtures: synthetic 200-day market_data (seeded, no network)
tests/test_black_scholes.py — Option pricing, Greeks sign-correctness, IV smile shape
tests/test_strategies.py   — Entry/exit logic, leg generation, circuit breaker for all strategies
tests/test_models.py       — Regime labeling, feature extraction shape/NaN handling, classifier
tests/test_base.py         — Leg/Trade P&L math, net credit, max loss properties
tests/test_data.py         — Expiry calendar (era-aware: Thursday pre-2024, Monday post-2024), config
tests/test_multi_expiry.py — Calendar roll logic, AdjustmentAction, ExpirySelector scoring
tests/test_position_sizer.py — Position sizing across regimes, drawdown, confidence tiers
tests/test_fixes.py        — Regression: bug fixes #1–#6 + CAGR improvements #1–#6
```

Run: `source .venv/bin/activate && python -m pytest tests/ -q`

---

## Agent Workflow

- Keep `graphify-out/` current. Run `scripts/update_graphify.sh` for a one-shot
  refresh or `scripts/watch_graphify.sh` while editing. This checkout is wired
  to `.githooks/` with `git config core.hooksPath .githooks`; the pre-commit
  hook refreshes and stages `graphify-out/`.
- Check `docs/AGENT_MEMORY.md` before non-trivial changes. Add repeatable
  pitfalls with `python3 scripts/agent_memory.py add ...`, mark useful memories
  with `--helpful`, mark stale ones with `--stale`, and run
  `python3 scripts/agent_memory.py decay` to archive low-signal records.

### Git Commit + Push Policy (mandatory)

After **every logical unit of work** (a fix, a feature, a config change, a
refactor), the agent MUST:
1. `git add <changed files>`
2. `git commit -m "..."` with a descriptive conventional-commit message
3. `git push origin main` — push to remote immediately after committing

Never leave uncommitted edits at the end of a session. Never commit without
pushing. This protects work against connectivity drops and keeps the remote
in sync.

### Long-Running Training / Backtest Policy (mandatory)

Any command expected to run longer than ~5 min (e.g., `--mode evolve`,
`--mode backtest-combined` on 17yr data) MUST be launched with `nohup` so
that Claude Code session disconnection or terminal closure does not kill it:

```bash
# Training (evolve):
nohup python3 main.py --mode evolve > logs/evolve_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "PID=$!"

# Backtest:
nohup python3 main.py --mode backtest-combined --run-label "my_run" \
  > logs/backtest_$(date +%Y%m%d_%H%M).log 2>&1 &
echo "PID=$!"
```

Check progress with `tail -f logs/<logfile>`. Kill with `kill <PID>` if needed.
The `logs/` directory is gitignored. Create it with `mkdir -p logs` if absent.

---

## Key Gotchas

- **NSE expiry cutover (2024-04-04)** — Before this date expiry = last Thursday; on/after = last Monday. Always pass `ref_date` to `get_monthly_expiry()` when backtesting periods that straddle this boundary. `BacktestEngine._get_expiry_date()` uses `get_best_expiry_for_dte()` which handles this automatically.

- **`overnight_gap_pct` column name** — `market_data.py` produces this column (renamed from an older `nifty_gap_pct`). `FeatureExtractor` reads `overnight_gap_pct`. Any cached parquet written before the rename will produce NaN for this feature — delete cache and regenerate.

- **BWB VIX routing** — `BrokenWingButterflyStrategy` has a `max_vix` param (default 30). The `RegimeAdaptiveStrategy` router sends it VIX 22–30. Before the fix this was hardcoded `> 20`, silently blocking all high-VIX entries. If you change `max_vix`, also check `get_eligible_strategies()` zone boundaries.

- **ML entry model AUC 0.696** — After adding 18 trade-structure features (11 one-hot strategy flags + 7 continuous metrics) and migrating to LightGBM, `RegimeAwareLearner` v4 CV AUC reached 0.696. Gate 8 (`monthly_entry_threshold=0.50`) is active and blocks ~43% of days. Don't re-enable bypass unless AUC drops below 0.55.

- **Capital utilization ~48%** — At default settings with 50/50 split and Gate 8 at 0.50, ~52% of capital days are idle. Main levers: `vix_simultaneous_cap` (25), `monthly_entry_threshold` (0.50), `dd_recovery_pct` (0.16).

- **Mid-session fill is the baseline** — `nifty_mid_session = nifty_open + 0.40*(nifty_close−nifty_open)` is used as fill price for all entries (proxy for ~11 AM spot). Slippage is scaled 0.75× vs open-market baseline. Do NOT switch back to `nifty_open`-only fills — benchmarked +2.47% CAGR, MaxDD 8.9%→4.7%. Old cached parquets without `nifty_mid_session` will fall back to `nifty_open` automatically.

- **Black-Scholes as pricing proxy** — No real NSE option chain history before 2019. Premiums estimated via `price_option()` + `iv_from_vix()` linear skew model. Pre-2019 P&L is directionally indicative only. `iv_from_vix()` returns IV as a **percentage** (e.g., `18.5` = 18.5%); `price_option()` divides by 100 internally — never divide again before calling it.

- **Weekly DTE gate is now config-driven** — `_fill_pending_weekly_entry` enforces `WeeklyBacktestConfig.min_dte_entry` (default 3) and `max_dte_entry` (default 8). Signals outside this window are logged as `WARNING: Weekly entry dropped: DTE=N outside [3, 8]` and counted in `weekly_etl_skips`. Previously the guard was hard-coded `DTE < 1` and silent. To widen the acceptance window, set `WeeklyBacktestConfig(min_dte_entry=2)`.

- **`--mode evolve` must run before backtest/signal** — Deleting `data/.cache/*.pkl` requires a full retrain. Evolve takes ~15–20 min on 17yr data. Feature column changes or strategy changes → always retrain. Use `nohup` (see Agent Workflow section) — evolve will be killed by session disconnection otherwise.

- **ETL gate is now configurable** — `WeeklyRiskEngine` previously had a hardcoded `etl > entry_credit` (1.0×) skip threshold that blocked ~363/465 weekly entries over 17yr (78% collapse). Now controlled by `WeeklyBacktestConfig.etl_skip_multiplier` (default 1.5). The multiplier is applied at runtime via `CombinedBacktestEngine.__init__` — no retrain needed to change it. After any retrain, check `ETL > credit skips` in backtest output; target < 100 over 17yr.
