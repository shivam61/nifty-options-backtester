"""Tests for the data-driven half-spread model (backtester.spread_model, ChainConfig.spread_model).

  (a) bucketing: moneyness, DTE and VIX band edges; filters (forced, off-window, non-ok, crossed) and dedupe
  (b) calibrated lookup returns median fraction of mid x price; multiplier applies on top
  (c) fallback to the flat CostModel value under min samples, under min snapshots, missing bucket, bad price
  (d) never extrapolates: a neighbouring calibrated bucket does not serve an uncalibrated one
  (e) spread_model=None and an all-fallback table leave the chain output byte-identical
  (f) a calibrated table changes the fills as hand-computed

Synthetic quote logs only (written to tmp_path). The chain fixtures are the PCS world of
tests/test_chain_capital_mode.py (SP 22650 / LP 22450, spot 23000, VIX 11, DTE 6 at fill).
"""

import json
from datetime import date

import pytest

from backtester.chain_engine import ChainBacktest, ChainConfig
from backtester.spread_model import (
    REASON_BAD_PRICE, REASON_BELOW_MIN, REASON_CALIBRATED, REASON_NO_BUCKET,
    SpreadModel, bucket_key, build_table, dte_band, load_quote_rows, moneyness_band, vix_band,
)
from data.nse_fo_archive import NseFoArchive
from tests.test_chain_capital_mode import S, X, _market, _pcs_cycle1

HEADER = ["timestamp_ist", "source", "in_window", "forced", "spot", "vix", "expiry", "dte",
          "strike", "option_type", "bid", "ask", "quote_status"]
EXP = "09-Jan-2025"


# ----------------------------------------------------------------- synthetic quote logs
def _write_log(path, quotes):
    """quotes: dicts with ts, strike, opt, bid, ask, spot, vix, dte and optional overrides."""
    lines = [",".join(HEADER)]
    for q in quotes:
        r = {"timestamp_ist": q["ts"], "source": q.get("source", "nse"), "in_window": q.get("in_window", 1),
             "forced": q.get("forced", 0), "spot": q["spot"], "vix": q["vix"], "expiry": EXP,
             "dte": q["dte"], "strike": q["strike"], "option_type": q["opt"], "bid": q["bid"],
             "ask": q["ask"], "quote_status": q.get("status", "ok")}
        lines.append(",".join(str(r[c]) for c in HEADER))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _quotes(n_snap, *, strike, spot, dte, vix, bid, ask, opt="PE", ts_prefix="2026-10-28T11:"):
    """n_snap distinct snapshots, one quote each, identical geometry."""
    return [{"ts": f"{ts_prefix}{i:02d}:00+05:30", "strike": strike, "opt": opt, "spot": spot,
             "vix": vix, "dte": dte, "bid": bid, "ask": ask} for i in range(n_snap)]


def _table(tmp_path, quotes, **kw):
    log = _write_log(tmp_path / "QUOTE_LOG_test.csv", quotes)
    rows = load_quote_rows([log])
    return build_table(rows, sources=[log.name], **kw), rows


# ----------------------------------------------------------------- (a) bucketing
@pytest.mark.parametrize("strike,spot,band", [
    (23000, 23000, "lt1pct"),
    (23000 * 1.0099, 23000, "lt1pct"),
    (23000 * 0.9905, 23000, "lt1pct"),
    (23000 * 1.015, 23000, "1to2pct"),
    (23000 * 0.9745, 23000, "2to4pct"),
    (23000 * 1.039, 23000, "2to4pct"),
    (23000 * 1.04, 23000, "gt4pct"),
    (23000 * 0.9, 23000, "gt4pct"),
])
def test_moneyness_bands(strike, spot, band):
    assert moneyness_band(strike, spot) == band


@pytest.mark.parametrize("dte,band", [(3, "dte_le5"), (5, "dte_le5"), (6, "dte_6to8"),
                                      (8, "dte_6to8"), (9, "dte_ge9"), (14, "dte_ge9")])
def test_dte_bands(dte, band):
    assert dte_band(dte) == band


@pytest.mark.parametrize("vix,band", [(12.99, "vix_lt13"), (13.0, "vix_ge13"), (16.5, "vix_ge13")])
def test_vix_bands(vix, band):
    assert vix_band(vix) == band


def test_bucket_key_joins_three_bands():
    assert bucket_key(22650, 23000, 6, 11.0) == "1to2pct|dte_6to8|vix_lt13"


def test_loader_keeps_only_two_sided_in_window_non_forced_nse_quotes(tmp_path):
    good = _quotes(1, strike=22650, spot=23000, dte=6, vix=16, bid=36, ask=44)
    bad = [
        {**good[0], "ts": "2026-10-28T11:30:00+05:30", "forced": 1},            # forced
        {**good[0], "ts": "2026-10-28T11:31:00+05:30", "in_window": 0},         # off-window
        {**good[0], "ts": "2026-10-28T11:32:00+05:30", "status": "one_sided"},  # not ok
        {**good[0], "ts": "2026-10-28T11:33:00+05:30", "source": "groww"},      # other source
        {**good[0], "ts": "2026-10-28T11:34:00+05:30", "bid": 50, "ask": 44},   # crossed
    ]
    log = _write_log(tmp_path / "q.csv", good + bad)
    rows = load_quote_rows([log])
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r["half"] == pytest.approx(4.0) and r["mid"] == pytest.approx(40.0)
    assert r["frac"] == pytest.approx(0.1)


def test_loader_dedupes_same_quote_repeated_across_structures(tmp_path):
    # IC and PCS share strike 22650 PE in one snapshot: one quote, not two observations
    q = _quotes(1, strike=22650, spot=23000, dte=6, vix=16, bid=36, ask=44)
    rows = load_quote_rows([_write_log(tmp_path / "q.csv", q + q)])
    assert len(rows) == 1


def test_build_table_counts_rows_snapshots_and_flags(tmp_path):
    q = _quotes(4, strike=22650, spot=23000, dte=6, vix=16, bid=36, ask=44)
    table, _ = _table(tmp_path, q, min_samples=3, min_snapshots=2)
    b = table["buckets"]["1to2pct|dte_6to8|vix_ge13"]
    assert b["n_rows"] == 4 and b["n_snapshots"] == 4 and b["n_dates"] == 1
    assert b["calibrated"] is True
    assert b["frac_of_mid_median"] == pytest.approx(0.1)


# ----------------------------------------------------------------- (b) calibrated lookup
def test_calibrated_bucket_returns_fraction_of_mid_times_price(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)   # frac 0.1 at mid 40
    table, _ = _table(tmp_path, q)
    model = SpreadModel(table)
    est = model.half_spread(22650, 23000, 6, 11.0, price=100.0, flat=9.9)
    assert est.calibrated is True and est.reason == REASON_CALIBRATED
    assert est.value == pytest.approx(0.1 * 100.0)
    assert est.bucket == "1to2pct|dte_6to8|vix_lt13"


def test_save_and_load_roundtrip(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)
    table, _ = _table(tmp_path, q)
    p = tmp_path / "spread_table.json"
    SpreadModel(table).save(p)
    again = SpreadModel.load(p)
    assert again.table["buckets"] == table["buckets"]
    assert json.loads(p.read_text(encoding="utf-8"))["version"] == 1


def test_unsupported_table_version_is_refused():
    with pytest.raises(ValueError):
        SpreadModel({"version": 99, "buckets": {}})


# ----------------------------------------------------------------- (c) fallback
def test_fallback_under_min_samples_uses_flat_value_and_is_flagged(tmp_path):
    q = _quotes(29, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)   # 29 < 30
    table, _ = _table(tmp_path, q)
    model = SpreadModel(table)
    est = model.half_spread(22650, 23000, 6, 11.0, price=100.0, flat=9.9)
    assert est.calibrated is False and est.reason == REASON_BELOW_MIN
    assert est.value == pytest.approx(9.9)            # the flat value passed in, not a measured one


def test_fallback_when_samples_come_from_too_few_snapshots(tmp_path):
    # 30 distinct quotes (strikes 22550..22579, all in the 1to2pct band) in only 2 snapshots
    qs = [{"ts": f"2026-10-28T11:{k % 2:02d}:00+05:30", "strike": 22550 + k, "opt": "PE", "spot": 23000,
           "vix": 11, "dte": 6, "bid": 36, "ask": 44} for k in range(30)]
    table, rows_df = _table(tmp_path, qs)
    assert rows_df["snapshot"].nunique() == 2
    b = table["buckets"]["1to2pct|dte_6to8|vix_lt13"]
    assert b["n_rows"] == 30 and b["n_snapshots"] == 2 and b["calibrated"] is False
    est = SpreadModel(table).half_spread(22650, 23000, 6, 11.0, price=100.0, flat=9.9)
    assert est.calibrated is False and est.reason == REASON_BELOW_MIN


def test_missing_bucket_falls_back_with_no_bucket_reason(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)
    model = SpreadModel(_table(tmp_path, q)[0])
    est = model.half_spread(23000, 23000, 6, 11.0, price=100.0, flat=5.0)   # ATM bucket never observed
    assert est.calibrated is False and est.reason == REASON_NO_BUCKET and est.value == 5.0


def test_bad_price_falls_back(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)
    model = SpreadModel(_table(tmp_path, q)[0])
    for price in (0.0, -1.0, float("nan"), None):
        est = model.half_spread(22650, 23000, 6, 11.0, price=price, flat=3.0)
        assert est.calibrated is False and est.reason == REASON_BAD_PRICE and est.value == 3.0


def test_fallback_without_flat_value_is_nan_not_zero(tmp_path):
    model = SpreadModel(_table(tmp_path, [])[0])
    est = model.half_spread(22650, 23000, 6, 11.0, price=100.0)
    assert est.calibrated is False and est.value != est.value    # NaN


# ----------------------------------------------------------------- (d) no extrapolation
def test_neighbouring_calibrated_bucket_does_not_serve_an_uncalibrated_one(tmp_path):
    # 2to4pct|dte_6to8|vix_lt13 calibrated; 2to4pct|dte_le5|vix_lt13 is one DTE band away, not observed
    q = _quotes(30, strike=22450, spot=23000, dte=6, vix=11, bid=13.5, ask=16.5)
    model = SpreadModel(_table(tmp_path, q)[0])
    assert model.half_spread(22450, 23000, 6, 11.0, price=15.0, flat=2.0).calibrated is True
    est = model.half_spread(22450, 23000, 5, 11.0, price=15.0, flat=2.0)
    assert est.calibrated is False and est.value == 2.0


def test_multiplier_is_not_part_of_the_table(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44)
    model = SpreadModel(_table(tmp_path, q)[0])
    assert model.half_spread(22650, 23000, 6, 11.0, price=100.0).value == pytest.approx(10.0)


# ----------------------------------------------------------------- (e) default and all-fallback are identical
def _trade_json(trades):
    return json.dumps(trades, sort_keys=True, default=str)


def test_default_and_all_fallback_table_leave_chain_output_byte_identical(tmp_path):
    days = _pcs_cycle1(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    default = ChainBacktest(arch, _market(days), ChainConfig(start=S, end=X))
    d_trades = default.run()
    assert default.spread_stats == {}

    empty_model = SpreadModel(build_table(load_quote_rows([]), sources=[]))
    fb = ChainBacktest(arch, _market(days), ChainConfig(start=S, end=X, spread_model=empty_model))
    f_trades = fb.run()
    assert len(d_trades) == 1
    assert _trade_json(f_trades) == _trade_json(d_trades)
    assert fb.spread_stats and all(k.endswith(":" + REASON_NO_BUCKET) for k in fb.spread_stats)


def test_default_slip_unit_is_the_flat_model_times_multiplier(tmp_path):
    cfg = ChainConfig(slippage_multiplier=1.5)
    bt = ChainBacktest(None, _market([S]), cfg)
    flat = cfg.weekly.cost_model.slippage_per_unit(11.0, 22650 / 23000)
    assert bt._slip_unit(11.0, 22650, 23000) == pytest.approx(flat * 1.5)


# ----------------------------------------------------------------- (f) calibrated fills, multiplier on top
def test_calibrated_table_changes_fills_and_multiplier_applies_on_top(tmp_path):
    # Short 22650 (bucket 1to2pct|dte_6to8|vix_lt13) and long 22450 (2to4pct|dte_6to8|vix_lt13)
    # half-spread = 0.10 x settle: short settle 40 -> 4.0, long settle 15 -> 1.5.
    q = (_quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44, opt="PE")
         + _quotes(30, strike=22450, spot=23000, dte=6, vix=11, bid=13.5, ask=16.5, opt="PE"))
    model = SpreadModel(_table(tmp_path, q)[0])
    days = _pcs_cycle1(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))

    trades = ChainBacktest(arch, _market(days), ChainConfig(start=S, end=X, spread_model=model)).run()
    assert len(trades) == 1
    t = trades[0]
    # fills: short 40 - 4.0 = 36.0 (sold lower), long 15 + 1.5 = 16.5 (bought higher); credit 19.5
    assert t["entry_credit_fill"] == pytest.approx(19.5)

    trades_15 = ChainBacktest(arch, _market(days),
                              ChainConfig(start=S, end=X, spread_model=model, slippage_multiplier=1.5)).run()
    # multiplier on top: short 40 - 6.0 = 34.0, long 15 + 2.25 = 17.25; credit 16.75
    assert trades_15[0]["entry_credit_fill"] == pytest.approx(16.75)


def test_usage_counts_calibrated_and_fallback_legs(tmp_path):
    q = _quotes(30, strike=22650, spot=23000, dte=6, vix=11, bid=36, ask=44, opt="PE")   # short only
    model = SpreadModel(_table(tmp_path, q)[0])
    days = _pcs_cycle1(tmp_path)
    arch = NseFoArchive(archive_dir=str(tmp_path))
    bt = ChainBacktest(arch, _market(days), ChainConfig(start=S, end=X, spread_model=model))
    bt.run()
    assert bt.spread_stats["entry:calibrated"] == 1          # short leg
    assert bt.spread_stats[f"entry:{REASON_NO_BUCKET}"] == 1  # long leg, bucket not observed
    assert sum(v for k, v in bt.spread_stats.items() if k.startswith("exit:")) >= 1


def test_usage_report_helpers_count_calibrated_vs_fallback():
    from scripts.run_chain_backtest import format_spread_usage, spread_usage

    class _BT:
        spread_stats = {"entry:calibrated": 4, "entry:below_min_samples": 2,
                        "exit:calibrated": 1, "exit:no_bucket": 3}

    u = spread_usage(_BT())
    assert u["legs_calibrated"] == 5 and u["legs_fallback"] == 5
    text = format_spread_usage(u)
    assert "entry legs calibrated=4 fallback=2" in text
    assert "exit legs calibrated=1 fallback=3" in text
    assert "below_min_samples=2" in text and "no_bucket=3" in text
