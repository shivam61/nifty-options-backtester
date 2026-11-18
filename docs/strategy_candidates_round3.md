# Round 3 candidate list: strategies and combinations to search for an edge

Date: 2026-11-18. Status: **catalogue, not a pre-registration**. Nothing here has been run. A shortlist from this list becomes a frozen
pre-registration (`docs/preregistration_round3.md`) before any run. Each entry is chosen from a stated mechanism, not from looking at results.

## 0. What round 1 and 2 taught (drives the list)

1. **Cost drag is the main enemy.** Credit per weekly spread is about Rs 370/lot (lots=10) against round-trip fixed costs. Edges under about Rs 100/lot are
   invisible at 40-80 trades per window. Structures with larger credit per trade (monthly, wider) or fewer round trips win on cost.
2. **Capital sits idle.** Round 2 test utilisation was about 1.3% of Rs 25L. A 12-18% return can come from three sources: collateral yield, premium,
   and (separately labelled) market beta. Round 2 measured premium only, at a tiny size.
3. **Power is low.** One regime (2019-2023, one crash). Fixed-rule walk-forward over the whole dev window beats a single train/test split for power.
4. Short premium has been positive only at VIX 16-25 (audit); at VIX 25+ it is -57.7 pts/unit. Anything that sells vol at spike levels needs a post-spike rule.

## 1. Return sources to separate in every result

| Source | What it is | Honest label |
|---|---|---|
| Collateral yield | Idle capital in liquid fund / pledged securities (about 6.5-7%/yr, rate to be pre-stated, not assumed) | carry, not an edge |
| Premium (vol risk premium) | Option selling P&L net of costs | the thing being tested |
| Beta | Long Nifty exposure (covered call, collar) | market return, not an edge |

A candidate "reaches 12%" only in the Tier 2 sense if it says which source did it. Premium must be positive on its own (Tier 1).

## 2. Candidate list

Engine support: **Y** = runnable now in candidate mode; **S** = small engine change; **L** = large engine change; **N** = data not available.
Prior = drafter's plausibility before any run (H/M/L), not a result.

| # | Candidate | Mechanism (why it might work) | Why it might fail | Engine | Trades/yr | Prior |
|---|---|---|---|---|---|---|
| 1 | **Monthly hedged iron condor**, DTE 20-30, k in 1.0-1.3 | Same premium, about 4x credit per trade against fixed costs; fewer round trips | Gap risk inside 4 weeks; fewer trades, weaker CI | Y (monthly cadence needs `S`) | 12 | M |
| 2 | **Monthly put credit spread** | As above, put-skew only | Tail on crash months (2020) | S | 12 | M |
| 3 | **Weekly iron condor, wider k (1.3-1.5), wider wings** | Lower hit rate cost, safer strikes, same fixed cost | Credit too small after costs | Y | 50 | L-M |
| 4 | **Post-spike mean reversion**: sell hedged IC/PCS when VIX fell >= X% from a 20-day high above 25 | Vol risk premium is large right after spikes; removes the VIX 25+ losses | Few events (about 5-8 in dev); regime may continue up | S (entry filter exists) | 5-10 | M |
| 5 | **Term-structure gate**: sell weekly only when weekly IV <= monthly IV (contango) | Backwardation signals stress; contango is calm | Archive IV needs derivation from settle; noise | S | 30 | M |
| 6 | **Trend-filtered credit spreads**: PCS when close > 50d SMA, CCS when below | Sell the side away from drift | Whipsaws; filter only reduces trades | Y (PCS, CCS exist) | 30 | L-M |
| 7 | **IV-rank gate**: trade only when VIX is in the top 40% of its 1-year range | Premium richer when IV is high relative to own history | Overlaps VIX band already tested | S | 30 | L |
| 8 | **Event-skip**: weekly IC skipping RBI/Budget/Fed/results weeks | Removes known jump risk | Also removes the event premium | S (calendar exists in `production_rules`) | 40 | L-M |
| 9 | **Calendar / diagonal**: short weekly, long monthly same strike | Vega-hedged theta | Needs multi-expiry legs, margin netting, price tick risk | L | 40 | unknown |
| 10 | **Broken-wing butterfly / 1x2 with hedge** | Skewed payoff, small debit or credit | Complex, pin risk at expiry | L | 40 | L |
| 11 | **1-2 DTE iron condor** (EOD-to-EOD, enter 1-2 days before expiry) | Highest theta per day | EOD fills hide intraday risk; SEBI rules on expiry | Y (DTE window change) | 50 | L-M |
| 12 | **Covered call / collar on Nifty (beta + premium)** | Beta return 10-12% with premium offset and tail put | Return is mostly beta; not selling-premium edge | L (needs spot leg) | 12-50 | benchmark only |
| 13 | **Collateral-yield overlay** (any survivor + liquid fund) | Uses the 98% idle capital | Needs margin rules (pledge haircut) stated, not assumed | S (reporting layer) | n/a | carry |
| 14 | **Bank Nifty / Finnifty** | More liquid skew, different VIX | Not in the archive (`N`) | N | | skip |

## 3. Combinations (only after two singles each clear Tier 1 on train)

| Combo | Rationale | Pre-condition |
|---|---|---|
| 1 + 4 | Monthly condor plus spike-reversion events: different VIX regimes | both survive train |
| 1 + 6 | Monthly condor as base, weekly trend-filtered spreads as satellite | both survive train |
| (best single) + 13 | Collateral yield overlay on the best Tier 1 survivor | Tier 1 PASS first |
| 2 + 3 | Put-skew monthly plus symmetric weekly (check correlation: both short puts) | correlation < 0.7 on train |

F in round 2 combined two highly correlated short-put cells and added nothing. Rule: combine only cells with train daily-PnL correlation below 0.7.

## 4. Proposed shortlist for round 3 (7 cells, within a hard cap of about 14 cuts)

Chosen by mechanism and cost advantage, not by result: **1** (2 cells: k 1.0, 1.3), **2** (1 cell), **4** (1 cell), **5** (1 cell), **6** (1 cell), **3** (1 cell).
Test and holdout budget: 3 test + 1 holdout. Entries 7-14 stay on the list for a later round or are skipped for engine cost.
Engine work first: monthly cadence, term-structure filter, trend and spike filters (all through `candidate_entry_filter`, leak-tested).

## 5. Rules carried into round 3

- Frozen document before any run; Holm over the whole registry (now 15 cuts, each new cut raises the bar).
- 1.0x slippage pass bar plus 0.5x/1.5x sensitivity; zero-contract entries skipped; Rs 25L equity sizing; same Tier 1 / Tier 2 reporting with source labels (Section 1).
- Cells fixed by mechanism: no k/W search beyond the declared values. Fixed-rule walk-forward across 2019-2023 in two folds is allowed only if declared up front.
- Holdout 2024+ stays sealed unless a cell passes test; one look.
- Quote logging continues in parallel (live, market hours) to recalibrate slippage; that is the user's collector, not part of this round's verdicts.

## 6. Honest expectation

Round 2 found Tier 1 edge near zero. Monthly structures and the post-spike rule are the two with a structural reason to do better. A realistic outcome of round 3 is again
"no Tier 1 edge", with the 12% target then reachable only through collateral yield and beta, which are not edges. That result is valid and would be reported as such.
