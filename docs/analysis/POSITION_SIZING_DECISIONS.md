# Position Sizing: Decision Log

> This file records every position sizing configuration tried, what worked, what
> didn't, and why. Its purpose is to prevent re-trying failed approaches.

---

## Current Default (as of Run #7, 2026-04-08)

**Simplified 3-layer sizer** — the only sizer in the codebase.

```
final_lots = base_lots × regime_scale × dd_scale × confidence_scale
             clamped to [1, max_lots_cap]
```

| Layer | What it does | Config |
|-------|-------------|--------|
| **Base lots** | Margin-based compounding → vol-target after 20 trades | `equity * 0.80 / margin_per_lot`, then `base * (target_vol / realised_vol)` |
| **Regime scale** | VIX-driven de-risking | LOW_VOL: 1.0, TRENDING: 0.85, HIGH_VOL: 0.65, CRASH: 0.35 |
| **DD scale** | Drawdown circuit breaker | 0-5%: 1.0, 5-10%: 0.75, 10-15%: 0.50, 15%+: 0.25 |
| **Confidence scale** | Coarse ML entry model tier | wp > 0.65: 1.2x, wp > 0.55: 1.0x, else: 0.7x |

**Result**: CAGR 16.33%, Sharpe 3.69, Max DD 15.0%, 235 trades.

---

## Approaches Tried & Retired

### 1. No position sizer (Runs #1-#5)

- **What**: Hardcoded `lots = config.max_lots` or simple margin-based compounding.
- **Result**: CAGR ~16-21% depending on strategy mix. No risk scaling.
- **Why retired**: No drawdown protection, no regime awareness, no vol targeting.

### 2. Kelly Fraction as absolute lot count (Run #6, then reverted)

- **What**: Bounded Kelly formula (`f* = p - q/b`) computed an *absolute* lot count.
  `final_lots = min(vol_target_lots, kelly_lots) * regime_scale * dd_scale`.
- **Config**: `kelly_fraction=0.25` (quarter-Kelly), `_KELLY_SCALE_FLOOR=0.50`,
  `_KELLY_SCALE_CEIL=1.50`.
- **Result**: CAGR collapsed from 21.4% to **7.19%**.
- **Root cause**: Kelly as absolute lots (e.g. ~3.8) was far below compounding
  margin lots (~12.3). Using `min()` made Kelly the binding constraint on every
  trade, crushing returns.
- **DO NOT RETRY**: Kelly as an absolute lot limiter. The `min(vol, kelly)` pattern
  destroys compounding.

### 3. Kelly as multiplicative scale factor (Run #6 fix attempt)

- **What**: Changed Kelly from absolute lots to a multiplier (0.5x to 1.5x).
  `final_lots = base * kelly_scale * regime_scale * dd_scale`.
- **Config**: `kelly_fraction=0.50` (half-Kelly), normalised around `_NEUTRAL_F=0.35`.
- **Result**: CAGR ~16.6%, Sharpe 3.35, DD 17.5%.
- **Why retired**: Kelly scale was averaging 1.16x — near-neutral. All the complexity
  (per-strategy win/loss tracking, payoff ratio estimation, fraction normalisation)
  for a 16% scaling effect. The `blended_wp` input from ExpirySelector was also
  near-constant (~0.62-0.65), making Kelly a fake signal.
- **DO NOT RETRY**: Kelly with ExpirySelector's `blended_wp` as input. The signal is
  too stable to produce meaningful Kelly variation.

### 4. Simplified sizer with confidence tier (Run #7 — CURRENT DEFAULT)

- **What**: Removed Kelly entirely. Replaced with a trivial 3-tier scaler based on
  ML entry model's `win_prob`. Fixed vol-target to use `equity_at_entry` per trade
  instead of stale current equity.
- **Result**: CAGR 16.33%, Sharpe 3.69, Max DD 15.0%.
- **Why this works**: The system's edge is strategy structure + exit model + risk
  control — NOT entry prediction. The confidence tier just distinguishes "ML is
  quite confident" vs "ML is uncertain" without pretending precision. Sharpe improved
  +0.34 and DD improved -2.5pp vs Kelly version.
- **STATUS**: Active default.

---

## Key Learnings (DO NOT FORGET)

1. **Entry ML has no statistical edge for sizing precision**. Permutation test failed.
   Use it only as a coarse binary gate + 3-tier confidence tier.

2. **Kelly requires a reliable edge signal**. If `win_prob` input is near-constant
   (like ExpirySelector's `blended_wp` of ~0.62), Kelly degenerates to a fixed
   multiplier. Not worth the complexity.

3. **Kelly as `min(vol_lots, kelly_lots)` destroys compounding**. If Kelly outputs
   fewer absolute lots than margin-compounding, it becomes a hard ceiling that
   prevents portfolio growth. Never use `min()` to combine Kelly with another sizing
   method.

4. **Vol-target needs `equity_at_entry`, not `current_equity`**. Computing
   `return = pnl / current_equity` understates early-trade returns when equity has
   grown, which understates realised vol, which *overstates* lots. Use per-trade
   equity snapshots.

5. **Regime + DD scaling are reliable and should not be removed**. They survived
   every configuration change and consistently improved risk-adjusted returns.

6. **Simplicity compounds**. The 3-tier confidence scaler (3 lines of code) produces
   better risk-adjusted returns than the 70-line Kelly implementation with per-strategy
   tracking. Fewer parameters = less overfitting risk.

---

## Configuration That Should NOT Be Changed Without Evidence

| Parameter | Value | Reason |
|-----------|-------|--------|
| `_VOL_WARMUP` | 20 trades | Below this, vol estimate is unreliable |
| `alloc_pct` | 0.80 | 80% margin utilisation — leaves buffer for MTM swings |
| `target_annual_vol` | 0.15 | 15% annualised — reasonable for options selling |
| Regime thresholds | VIX 14/18/25 | Calibrated to Nifty VIX historical distribution |
| DD bands | 5/10/15% | Standard progressive de-risking |
| Confidence tiers | 0.55/0.65 | Coarse enough to avoid overfitting to exact probs |
