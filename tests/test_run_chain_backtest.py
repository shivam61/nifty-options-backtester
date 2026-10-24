"""CLI test for scripts/run_chain_backtest.py on a tiny synthetic NSE F&O archive in tmp_path.

The market frame is replaced by a synthetic one (the real loader needs the repo's parquet
cache, which CI does not have). Everything else (archive loader, ChainBacktest, JSON/CSV
output, slippage loop, summary) runs for real. The IC round trip is the one hand-computed in
tests/test_chain_engine.py: 1 lot, 1x slippage -> pnl 1590.6556.
"""

import gzip
import importlib.util
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from strategies.weekly_strategies import WeeklyIronCondor

REPO = Path(__file__).resolve().parents[1]
S = date(2025, 1, 2)   # expiry-day signal
F = date(2025, 1, 3)   # fill
E = date(2025, 1, 9)   # trade expiry (DTE 6 at fill)
X = date(2025, 1, 8)   # dte_limit exit (DTE 1)
D6, D7 = date(2025, 1, 6), date(2025, 1, 7)
SPOT = 23000.0
COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_chain_backtest", REPO / "scripts" / "run_chain_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load_cli()


def _row(d, exp, k, opt, settle, contracts=100, oi=1000):
    return [d.isoformat(), exp.isoformat(), float(k), opt, 0.0, 0.0, 0.0, settle, settle,
            contracts, oi, float("nan")]


def _write(root: Path, d: date, rows):
    path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        pd.DataFrame(rows, columns=COLS).to_csv(fh, index=False)


def _write_ic_archive(root: Path):
    legs = WeeklyIronCondor(lots=1, lot_size=65).generate_legs(SPOT, 15.0, 6, 0.065)
    got = {(l.option_type, l.is_short): l.strike for l in legs}
    assert got == {("CE", True): 23350, ("CE", False): 23600, ("PE", True): 22450, ("PE", False): 22200}
    fill = {(23350, "CE"): 30.0, (23600, "CE"): 10.0, (22450, "PE"): 25.0, (22200, "PE"): 8.0}
    exit_px = {(23350, "CE"): 5.0, (23600, "CE"): 2.0, (22450, "PE"): 6.0, (22200, "PE"): 3.0}
    _write(root, S, [_row(S, S, 23000, "PE", 1.0)])
    for d in (F, D6, D7):
        _write(root, d, [_row(d, E, k, opt, v) for (k, opt), v in fill.items()])
    _write(root, X, [_row(X, E, k, opt, v) for (k, opt), v in exit_px.items()])
    return [S, F, D6, D7, X]


def _synthetic_market(days):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    return pd.DataFrame({
        "nifty_close": [SPOT] * len(days),
        "vix": [15.0] * len(days),
        "nifty_return_5d": [0.0] * len(days),
        "vix_change_5d": [0.0] * len(days),
    }, index=idx)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    arch_dir = tmp_path / "archive"
    days = _write_ic_archive(arch_dir)
    calls = []

    def fake_load_market(end, market_start=None):
        calls.append((end, market_start))
        return _synthetic_market(days)

    monkeypatch.setattr(cli, "load_market", fake_load_market)
    return arch_dir, calls


def test_cli_writes_trades_diag_skips_and_summary(tmp_path, synthetic):
    arch_dir, calls = synthetic
    out = tmp_path / "out"
    rc = cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "2.0",
                   "--archive-dir", str(arch_dir), "--out", str(out),
                   "--legacy-settlement", "--legacy-costs", "--allow-holdout"])
    assert rc == 0
    assert calls == [(X, cli.DEFAULT_MARKET_START)]     # pinned end (= last exit date, archive cut here), default market history start

    t1 = json.load(open(out / "trades_x1.json"))
    t2 = json.load(open(out / "trades_x2.json"))
    assert t1["variant"] == "chain_x1" and t1["n"] == 1 and t2["variant"] == "chain_x2"
    trade = t1["trades"][0]
    assert trade["strategy"] == "weekly_ic" and trade["exit_reason"] == "dte_limit"
    assert trade["pnl"] == pytest.approx(1590.6556, abs=0.01)     # hand-computed in test_chain_engine
    assert trade["pnl_per_lot"] == pytest.approx(trade["pnl"])
    # 2x slippage costs more on both entry and exit
    assert t2["trades"][0]["pnl"] < trade["pnl"]

    d1 = json.load(open(out / "diag_x1.json"))
    assert d1["mult"] == 1.0 and d1["trades"] == 1 and d1["start"] == str(S)
    assert (out / "skips_x1.csv").exists() and (out / "skips_x2.csv").exists()

    summary = json.load(open(out / "summary.json"))
    assert [r["tag"] for r in summary["runs"]] == ["x1", "x2"]
    assert summary["runs"][0]["trades"] == 1
    assert summary["runs"][0]["exp_per_lot"] == pytest.approx(round(trade["pnl_per_lot"], 1))


def test_cli_rejects_inverted_window(tmp_path, synthetic):
    arch_dir, _ = synthetic
    with pytest.raises(SystemExit):
        cli.main(["--start", str(E), "--end", str(X), "--archive-dir", str(arch_dir),
                  "--out", str(tmp_path / "bad"), "--allow-holdout"])


def test_check_window_refuses_after_dev_end_unless_flagged():
    cli.check_window(date(2023, 12, 31), allow_holdout=False)     # boundary is allowed
    with pytest.raises(SystemExit):
        cli.check_window(date(2024, 1, 1), allow_holdout=False)
    cli.check_window(date(2024, 1, 1), allow_holdout=True)


def test_cli_refuses_holdout_end_without_flag(tmp_path, synthetic):
    arch_dir, _ = synthetic
    with pytest.raises(SystemExit):
        cli.main(["--start", str(S), "--end", "2024-06-30", "--archive-dir", str(arch_dir),
                  "--out", str(tmp_path / "out")])
    assert cli.DEFAULT_END == date(2023, 12, 31)


def test_analyze_cli_on_chain_output(tmp_path, synthetic):
    spec = importlib.util.spec_from_file_location("analyze_chain_trades", REPO / "scripts" / "analyze_chain_trades.py")
    an = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(an)
    arch_dir, _ = synthetic
    out = tmp_path / "out"
    cli.main(["--start", str(S), "--end", str(X), "--slippage", "1.0", "--archive-dir", str(arch_dir),
              "--out", str(out), "--legacy-settlement", "--legacy-costs", "--allow-holdout"])
    res_path = tmp_path / "analysis.json"
    assert an.main(["--trades", str(out), "--out", str(res_path)]) == 0
    res = json.load(open(res_path))
    overall = res["runs"]["x1"]["overall"]
    assert overall["n"] == 1 and overall["exp_per_lot"] == pytest.approx(1590.7, abs=0.05)
    # a single trade: no bootstrap spread is defined for the year clusters
    assert overall["ci95_year_lo"] != overall["ci95_year_lo"]  # NaN
