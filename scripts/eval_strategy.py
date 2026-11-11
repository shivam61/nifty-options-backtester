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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategy_eval import DEV_END, TestRegistry, load_trades, run_evaluation, write_report  # noqa: E402
from strategy_eval.stats import DEFAULT_SEED, N_BOOT_DEFAULT  # noqa: E402


def _print_summary(res: dict) -> None:
    v = res["verdict"]
    print(f"strategy: {res['name']}")
    print(f"VERDICT: {v['verdict']}  (criteria: {v['criteria_verdict']})")
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
                    help=f"include entries after {DEV_END} (pre-registered holdout step only)")
    ap.add_argument("--name", type=str, default=None, help="strategy label (default: candidate file stem)")
    ap.add_argument("--adapter", choices=["auto", "normal", "chain", "run69", "h9"], default="auto",
                    help="input format (default: auto-detect)")
    ap.add_argument("--input-haircut-pct", type=float, default=0.0,
                    help="credit haircut (%%) already baked into an h9 CSV (regime A = 30). Default 0.")
    ap.add_argument("--lot-size", type=int, default=65, help="lot size for chain-engine records (default 65)")
    ap.add_argument("--registry", type=Path, default=None,
                    help="JSON file of cuts examined; loaded, extended and saved (Holm runs over all of them)")
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    a = ap.parse_args(argv)

    name = a.name or a.trades.stem
    cand = load_trades(a.trades, adapter=a.adapter, name=name,
                       input_haircut_pct=a.input_haircut_pct, lot_size=a.lot_size)
    base = None
    if a.baseline is not None:
        base = load_trades(a.baseline, adapter=a.adapter, name="baseline",
                           input_haircut_pct=a.input_haircut_pct, lot_size=a.lot_size)
    registry = TestRegistry.load(a.registry) if a.registry else TestRegistry()
    res = run_evaluation(cand, base, name=name, capital=a.capital, risk_cap=a.risk_cap,
                         allow_holdout=a.allow_holdout, registry=registry, n_boot=a.n_boot, seed=a.seed)
    if a.registry:
        registry.save(a.registry)

    out = a.out or (REPO_ROOT / "logs" / f"eval_{name}.md")
    out = Path(out)
    write_report(res, out, a.json_out, source=str(a.trades),
                 baseline_source=str(a.baseline) if a.baseline else "")
    _print_summary(res)
    print(f"report: {out}")
    print(f"json:   {a.json_out or out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
