#!/usr/bin/env python3
"""Evaluate an options-selling strategy against the pre-registered pass rule.

Reads a trade table (normalised CSV/pickle/JSON, or a chain-engine, run69-style or H9-style output),
optionally a baseline table on the same entry dates, and writes a markdown report and a JSON summary.
Win rate is shown for context only; the verdict is PASS / FAIL / INSUFFICIENT_DATA / INDICATIVE_ONLY.

Development window 2019-02-11..2023-12-31. Entries after 2023-12-31 are excluded unless
--allow-holdout is passed (the one-time holdout step for a single pre-registered candidate).
Trades priced with pricing_source='bs' are capped at INDICATIVE_ONLY.

Examples:
    python scripts/eval_strategy.py --trades path/trades.csv
    python scripts/eval_strategy.py --trades hedged.csv --baseline unhedged.csv --capital 2500000 \
        --risk-cap 50000 --out logs/eval_hedged.md --registry logs/eval_registry.json
    python scripts/eval_strategy.py --trades h9_trades_H9spec_regA.csv --adapter h9 --input-haircut-pct 30

Outputs: --out (default logs/eval_<name>.md) and --json-out (default: same path with .json).
logs/ is gitignored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategy_eval import DEV_END, TestRegistry, load_trades, run_evaluation, write_report  # noqa: E402
from strategy_eval.stats import DEFAULT_SEED, N_BOOT_DEFAULT  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_metrics as pm  # noqa: E402  (Tier 2 numbers; no verdict logic lives there)


def _print_summary(res: dict) -> None:
    v = res["verdict"]
    print(f"strategy: {res['name']}")
    win = res.get("window", "dev")
    print(f"VERDICT: {v['verdict']}  (criteria: {v['criteria_verdict']}"
          + ("" if win == "dev" else f"; window: {win}") + ")")
    for c in v["criteria"]:
        print(f"  {c['id']} {c['status']:<17} {c['name']}: {c['detail']}")
    m = res["metrics"]["at_verdict_cost"]
    print(f"expectancy per lot at {v['cost_level']['slippage_mult']:g}x: {m.get('expectancy_per_lot', float('nan')):+,.1f} Rs"
          f"  (n={m.get('n')}, win rate {m.get('win_rate_actual', float('nan')):.1%} context only)")
    s = res["sizing"]
    if s.get("lots_cap"):
        print(f"sizing: lots={s['lots_cap']} worst loss {s['worst_loss_at_lots_rs']:,.0f} Rs, "
              f"implied CAGR {s['implied_cagr']:.2%}")
    if res.get("scorecard"):
        sc = res["scorecard"]
        print(f"hedge: paired diff {sc['paired_diff_per_lot']['mean']:+,.1f} Rs/lot, "
              f"cost {sc['hedge_cost_pct_of_credit']:.2f}% of credit -> {sc['decision']}")
    print(f"cuts recorded: {v['registry']['n_cuts']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", type=Path, required=True, help="candidate trade file")
    ap.add_argument("--baseline", type=Path, default=None, help="baseline trade file on the same entry dates")
    ap.add_argument("--capital", type=float, default=2_500_000.0, help="capital in Rs (default %(default)s)")
    ap.add_argument("--risk-cap", type=float, default=50_000.0,
                    help="max worst-case loss per trade in Rs; lots are capped to fit (default %(default)s = 2%% of 25L)")
    ap.add_argument("--out", type=Path, default=None, help="markdown report path (default logs/eval_<name>.md)")
    ap.add_argument("--json-out", type=Path, default=None, help="JSON summary path (default: --out with .json)")
    ap.add_argument("--allow-holdout", action="store_true",
                    help=f"include entries after {DEV_END} (pre-registered holdout step only). Each use appends "
                         "a row to logs/holdout_ledger.json and counts as a registry cut.")
    ap.add_argument("--name", type=str, default=None, help="strategy label (default: candidate file stem)")
    ap.add_argument("--adapter", choices=["auto", "normal", "chain", "run69", "h9"], default="auto",
                    help="input format (default: auto-detect)")
    ap.add_argument("--input-haircut-pct", type=float, default=0.0,
                    help="credit haircut (%%) already baked into an h9 CSV (regime A = 30). Default 0.")
    ap.add_argument("--lot-size", type=int, default=65, help="lot size for chain-engine records (default 65)")
    ap.add_argument("--registry", type=Path, default=None,
                    help="JSON file of cuts examined; every cut is written here automatically "
                         "(default logs/eval_registry.json). Holm runs over all cuts in it.")
    ap.add_argument("--window", choices=["dev", "test", "holdout"], default="dev",
                    help="verdict window: dev (default, C3/C4 on 2019-2023), test (2022-2023, C3'/C4' with "
                         "every year positive), holdout (2024+, needs --allow-holdout). See docs/STRATEGY_EVAL.md.")
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--equity-curve", type=Path, default=None,
                    help="capital-mode daily equity CSV (date,equity), e.g. from run_candidates.py --capital-mode. "
                         "Adds the Tier 2 portfolio block (CAGR, MaxDD, Sharpe) beside the verdict; no verdict change.")
    a = ap.parse_args(argv)

    if a.window == "holdout" and not a.allow_holdout:
        ap.error("--window holdout requires --allow-holdout (one ledgered holdout look)")
    if a.window == "test" and a.allow_holdout:
        ap.error("--window test does not use --allow-holdout")
    name = a.name or a.trades.stem
    cand = load_trades(a.trades, adapter=a.adapter, name=name,
                       input_haircut_pct=a.input_haircut_pct, lot_size=a.lot_size)
    base = None
    if a.baseline is not None:
        base = load_trades(a.baseline, adapter=a.adapter, name="baseline",
                           input_haircut_pct=a.input_haircut_pct, lot_size=a.lot_size)
    # Cuts are written to the registry file as they are recorded; save() also creates the file on a run
    # that recorded nothing new.
    registry = TestRegistry.open(a.registry)
    res = run_evaluation(cand, base, name=name, capital=a.capital, risk_cap=a.risk_cap,
                         allow_holdout=a.allow_holdout, registry=registry, n_boot=a.n_boot, seed=a.seed,
                         window=a.window)
    registry.save()

    out = a.out or (REPO_ROOT / "logs" / f"eval_{name}.md")
    out = Path(out)
    write_report(res, out, a.json_out, source=str(a.trades),
                 baseline_source=str(a.baseline) if a.baseline else "")
    json_path = Path(a.json_out) if a.json_out else out.with_suffix(".json")
    t2 = None
    if a.equity_curve is not None:
        dates, equity = pm.read_equity_curve(a.equity_curve)
        t2 = pm.portfolio_metrics(dates, equity, capital_rs=a.capital)
        out.write_text(out.read_text(encoding="utf-8") + "\n" + pm.tier2_markdown(t2, str(a.equity_curve)),
                       encoding="utf-8")
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        summary["tier2_portfolio"] = t2
        json_path.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    _print_summary(res)
    if t2 is not None:
        print(f"tier 2 (portfolio, not a verdict): CAGR {t2['cagr_pct']}%  MaxDD {t2['max_dd_pct']}%  "
              f"Sharpe(daily) {t2['sharpe_daily_ann']}  final Rs {t2['final_equity']:,.0f}")
    print(f"report: {out}")
    print(f"json:   {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
