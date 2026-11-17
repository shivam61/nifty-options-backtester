"""Markdown and JSON rendering of a run_evaluation() result."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _clean(obj):
    """Make a result JSON-safe: NaN/inf -> None, numpy scalars -> python, dates -> str."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return str(obj)


def _f(x, nd: int = 1, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+,.{nd}f}" if sign else f"{x:,.{nd}f}"


def _pct(x) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.1f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(res: dict, source: str = "", baseline_source: str = "") -> str:
    v = res["verdict"]
    m = res["metrics"]["at_verdict_cost"]
    m1 = res["metrics"]["at_1x"]
    lines: list[str] = []
    lines.append(f"# Strategy evaluation: {res['name']}")
    lines.append("")
    lines.append(f"- Trades file: `{source}`")
    if baseline_source:
        lines.append(f"- Baseline file: `{baseline_source}`")
    lines.append(f"- Capital Rs {res['capital']:,.0f}; risk cap Rs {res['risk_cap']:,.0f} per trade (worst loss)")
    if res.get("window", "dev") == "dev":
        lines.append(f"- Pass rule: `{v['prereg']}`; development window 2019-02-11..2023-12-31; "
                     f"holdout {'INCLUDED (allow_holdout)' if res['allow_holdout'] else 'excluded'}")
    else:
        lines.append(f"- Pass rule: `{v['prereg']}`; window `{res['window']}` (C3' and C4', not the development "
                     "window)")
    lines.append("")
    lines.append(f"## Verdict: **{v['verdict']}**")
    lines.append("")
    if v["verdict"] != v["criteria_verdict"]:
        lines.append(f"Criteria result (information only): **{v['criteria_verdict']}**")
        lines.append("")
    for r in v["reasons"]:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("### Pass-rule criteria (verdict cost: "
                 f"{v['cost_level']['slippage_mult']:g}x slippage, haircut {v['cost_level']['haircut']:.0%})")
    lines.append("")
    rows = []
    for c in v["criteria"]:
        rows.append([c["id"], c["name"], c["status"], c["detail"]])
    lines.append(_table(["id", "criterion", "status", "detail"], rows))
    lines.append("")

    lines.append("## Expectancy, payoff and tails (Rs per lot)")
    lines.append("")
    lines.append(_table(
        ["measure", "at verdict cost", "at 1x (as priced)"],
        [
            ["trades (n)", str(m.get("n")), str(m1.get("n"))],
            ["expectancy per lot", _f(m.get("expectancy_per_lot"), sign=True), _f(m1.get("expectancy_per_lot"), sign=True)],
            ["total per lot", _f(m.get("total_per_lot"), 0, sign=True), _f(m1.get("total_per_lot"), 0, sign=True)],
            ["actual win rate (context only)", _pct(m.get("win_rate_actual")), _pct(m1.get("win_rate_actual"))],
            ["breakeven win rate (context only)", _pct(m.get("breakeven_win_rate")), _pct(m1.get("breakeven_win_rate"))],
            ["payoff ratio (avg win / avg loss)", _f(m.get("payoff_ratio"), 2), _f(m1.get("payoff_ratio"), 2)],
            ["P5 per lot", _f(m.get("p5_per_lot"), 0, sign=True), _f(m1.get("p5_per_lot"), 0, sign=True)],
            ["worst trade per lot", _f(m.get("worst_per_lot"), 0, sign=True), _f(m1.get("worst_per_lot"), 0, sign=True)],
            ["mean credit per lot", _f(m.get("credit_per_lot"), 0), _f(m1.get("credit_per_lot"), 0)],
            ["tail ratio (worst / credit)", _f(m.get("tail_ratio_worst_over_credit"), 2), _f(m1.get("tail_ratio_worst_over_credit"), 2)],
            ["max drawdown per lot (cumulative)", _f(m.get("max_drawdown_per_lot"), 0), _f(m1.get("max_drawdown_per_lot"), 0)],
            ["Sharpe-like (annualised)", _f(m.get("sharpe_like"), 2), _f(m1.get("sharpe_like"), 2)],
            ["span (years)", _f(m.get("span_years"), 2), _f(m1.get("span_years"), 2)],
        ]))
    lines.append("")

    lines.append("## Statistics")
    lines.append("")
    boot = v.get("bootstrap") or {}
    tt = v.get("nonoverlap_ttest") or {}
    lines.append(f"- Year-cluster bootstrap 95% CI of per-lot expectancy (verdict cost): "
                 f"[{_f(boot.get('lo'), 1, True)}, {_f(boot.get('hi'), 1, True)}] Rs/lot, "
                 f"{boot.get('n_boot')} draws, seed {boot.get('seed')}")
    lines.append(f"- Non-overlapping subsample n={tt.get('n')}, t={_f(tt.get('t'), 2)}, "
                 f"one-sided p={_f(tt.get('p_one_sided'), 4)}, Holm-adjusted p={_f(v.get('p_holm'), 4)}")
    blk = v.get("block_bootstrap") or {}
    if blk:
        lines.append(f"- Monthly-block bootstrap 95% CI of per-lot expectancy (verdict cost, information only, "
                     f"not the C3 pass criterion): [{_f(blk.get('lo'), 1, True)}, {_f(blk.get('hi'), 1, True)}] Rs/lot, "
                     f"{blk.get('n_clusters')} months, {blk.get('n_boot')} draws, seed {blk.get('seed')}")
    reg = v["registry"]
    lines.append(f"- Multiple testing: **{reg['n_cuts']} cuts** recorded in the registry "
                 f"(`{reg.get('path') or 'in memory'}`, written automatically; Holm applied over all cuts with a p-value).")
    hl = v.get("holdout_look")
    if hl:
        lines.append(f"- Holdout look #{hl['index']} recorded in the holdout ledger at {hl['timestamp']} "
                     f"(window {hl['window']['holdout_from']} onward; "
                     f"{hl['window']['candidate_holdout_trades']} candidate holdout trades).")
    lines.append("")
    yc = v.get("year_consistency") or {}
    if yc:
        lines.append(f"Dev years positive at verdict cost: {yc.get('positive')} of {yc.get('years_present')} present "
                     f"(needs {yc.get('min_positive')} of {len(yc.get('dev_years', []))}).")
        lines.append("")

    lines.append("## Cut registry")
    lines.append("")
    rows = [[c["name"].replace("|", "/"), c["kind"], _f(c["p_value"], 4) if c["p_value"] is not None else "n/a",
             _f(c["p_holm"], 4) if c.get("p_holm") is not None else "n/a"] for c in reg["cuts"]]
    lines.append(_table(["cut", "kind", "raw p", "Holm p"], rows) if rows else "_no cuts recorded_")
    lines.append("")

    lines.append("## Pricing and cost stress (per lot, all cells)")
    lines.append("")
    rows = [[f"{g['haircut']:.0%}", f"{g['slippage_mult']:g}x", str(g["n"]),
             _f(g["expectancy_per_lot"], 1, True), _pct(g["win_rate"]),
             _f(g["p5_per_lot"], 0, True), _f(g["worst_per_lot"], 0, True)]
            for g in res["stress_grid"]]
    lines.append(_table(["credit haircut", "slippage", "n", "expectancy", "win rate", "P5", "worst"], rows))
    lines.append("")
    base_hc = res.get("base_haircut_pct") or 0.0
    if base_hc > 0:
        lines.append(f"**The trades file is already priced under a {base_hc:g}% credit haircut**, so haircut "
                     f"rows at or below {base_hc:g}% equal the file as priced. Only stresses above it change P&L.")
        lines.append("")
    lines.append("Convention: haircut h removes h of the credit (P&L falls by h x credit); slippage m adds "
                 "(m-1) x slippage_rs (or x whole cost where slippage is unknown). A file priced under a base "
                 "haircut only takes the incremental haircut. Limitations: fees are not re-derived on the lower "
                 "notional; exit triggers are not re-run.")
    lines.append("")

    lines.append("## Per-year (verdict cost)")
    lines.append("")
    rows = [[str(y["year"]), str(y["n"]), _pct(y["win_rate"]), _f(y["mean_per_lot"], 1, True),
             _f(y["total_per_lot"], 0, True), "yes" if y["positive"] else "no"]
            for y in res["per_year"]]
    lines.append(_table(["year (entry)", "n", "win rate", "mean per lot", "total per lot", "positive"], rows)
                 if rows else "_no trades_")
    lines.append("")

    lines.append("## Exit-reason mix (verdict cost)")
    lines.append("")
    rows = [[e["exit_reason"], str(e["n"]), _pct(e["share"]), _f(e["mean_per_lot"], 1, True)]
            for e in res["exit_mix"]]
    lines.append(_table(["exit reason", "n", "share", "mean per lot"], rows) if rows else "_no trades_")
    lines.append("")

    lines.append("## VIX bucket breakdown (verdict cost, entry VIX)")
    lines.append("")
    vb = res.get("vix_buckets") or {"available": False}
    if vb.get("available"):
        rows = [[r["bucket"], str(r["n"]), _pct(r["share"]), _f(r["expectancy_per_lot"], 1, True),
                 _pct(r["win_rate"])] for r in vb["rows"]]
        lines.append(_table(["entry VIX", "n", "share", "expectancy per lot", "win rate (context)"], rows))
        lines.append("")
        if vb.get("unknown_vix_n"):
            lines.append(f"{vb['unknown_vix_n']} trades have no entry VIX and are not in any bucket.")
            lines.append("")
    else:
        lines.append("n/a: the trade table has no entry_vix values (optional column).")
        lines.append("")
    lines.append("Regime is read as the VIX bucket here; the table has no separate regime column.")
    lines.append("")

    s = res["sizing"]
    lines.append("## Sizing and implied return (verdict cost)")
    lines.append("")
    if s.get("lots_cap"):
        lines.append(_table(["item", "value"], [
            ["lots (capped so worst loss <= risk cap)", str(s["lots_cap"])],
            ["worst loss per lot used for sizing (Rs)", _f(s["worst_loss_per_lot"], 0)],
            ["worst loss at chosen lots (Rs)", _f(s["worst_loss_at_lots_rs"], 0)],
            ["trades without a defined max loss", str(s["trades_without_defined_max_loss"])],
            ["total P&L at chosen lots (Rs)", _f(s["total_pnl_at_lots_cap"], 0, True)],
            ["annual P&L at chosen lots (Rs/yr)", _f(s["annual_pnl_at_lots_cap"], 0, True)],
            ["implied CAGR on capital", _pct(s["implied_cagr"])],
            ["return on risk cap (margin proxy, annual)", _pct(s["return_on_margin_proxy"])],
        ]))
        lines.append("")
        lines.append("Margin is proxied by the risk cap; exchange SPAN margin is not modelled. Lots are fixed "
                     "(no compounding).")
    else:
        lines.append(f"Cannot size: {s.get('note', 'n/a')}")
    lines.append("")

    sc = res.get("scorecard")
    if sc:
        lines.append("## Hedge scorecard (candidate vs baseline, same entry dates, verdict cost)")
        lines.append("")
        pdiff = sc.get("paired_diff_per_lot") or {}
        lines.append(_table(["measure", "value"], [
            ["paired dates", str(sc.get("n_pairs"))],
            ["paired difference per lot (hedged - baseline)", _f(pdiff.get("mean"), 1, True)],
            ["  year-cluster 95% CI", f"[{_f(pdiff.get('lo'), 1, True)}, {_f(pdiff.get('hi'), 1, True)}]"],
            ["hedge cost per lot", _f(sc.get("hedge_cost_per_lot"), 1)],
            ["hedge cost as % of credit", _f(sc.get("hedge_cost_pct_of_credit"), 2)],
            ["P5 baseline / hedged", f"{_f(sc.get('p5_baseline'), 0, True)} / {_f(sc.get('p5_hedged'), 0, True)}"],
            ["worst baseline / hedged", f"{_f(sc.get('worst_baseline'), 0, True)} / {_f(sc.get('worst_hedged'), 0, True)}"],
            ["tail loss removed per lot (baseline worst 5% dates)", _f(sc.get("tail_removed_per_lot"), 1, True)],
            ["hedge decision", sc.get("decision", "n/a")],
        ]))
        lines.append("")
    lines.append("---")
    lines.append("Generated by scripts/eval_strategy.py. Win rate is shown for context and is not part of the verdict.")
    return "\n".join(lines) + "\n"


def write_report(res: dict, md_path: str | Path, json_path: str | Path | None = None,
                 source: str = "", baseline_source: str = "") -> None:
    """Write the markdown report and the JSON summary (default JSON path: md path with .json)."""
    md_path = Path(md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(res, source, baseline_source), encoding="utf-8")
    json_path = Path(json_path) if json_path else md_path.with_suffix(".json")
    json_path.write_text(json.dumps(_clean(res), indent=1, default=str), encoding="utf-8")
