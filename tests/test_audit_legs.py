"""Tests for scripts/audit_legs.py on a tiny synthetic archive written to tmp_path (no network,
no real archive). Expected numbers are hand-computed in the comments.
"""
import gzip
from datetime import date
from math import ceil
from statistics import NormalDist

import numpy as np
import pandas as pd
import pytest

import scripts.audit_legs as legs
import scripts.audit_vrp as audit
from data.nse_fo_archive import NseFoArchive

COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]
E0 = date(2023, 1, 5)     # Thursday expiry (signal day); fill = F
F = date(2023, 1, 6)      # fill session, spot 20000, VIX 15 (DTE 6 to E1)
E1 = date(2023, 1, 12)    # target weekly expiry, index settles at 19700
END = E1
SPOT_F, VIX_F = 20000.0, 15.0
SETTLE_E1 = 19700.0
STRIKES = [19000.0 + 50 * i for i in range(41)]  # 19000..21000

# Engine strike rule at spot 20000, VIX 15, DTE 6: 1 SD = 20000 * 0.15/sqrt(252) * sqrt(6) = 462.9 pts.
#   0.5 SD: put 19768.5 -> 19750, call 20231.5 -> 20250
#   0.9 SD: put 19583.4 -> 19600, call 20416.6 -> 20400
#   2.0 SD: put 19074.2 -> 19050, call 20925.8 -> 20950
PRICES = {
    (20000.0, "PE"): 130.0, (20000.0, "CE"): 150.0,   # ATM straddle 280
    (19750.0, "PE"): 60.0,                            # 0.5 SD put
    (19600.0, "PE"): 40.0,                            # 0.9 SD put
    (19050.0, "PE"): 3.0,                             # 2.0 SD put
    (20250.0, "CE"): 4.0,                             # 0.5 SD call
    (20400.0, "CE"): 30.0,                            # 0.9 SD call
    (20950.0, "CE"): 2.0,                             # 2.0 SD call
}
# Expiry settle 19700: put payoff = prem - max(0, K - 19700); call payoff = prem - max(0, 19700 - K)
#   put 0.5  (19750): 60 - 50 = 10          put 0.9 (19600): 40 - 0 = 40        put 2.0 (19050): 3
#   call 0.5 (20250): 4                      call 0.9 (20400): 30                 call 2.0 (20950): 2
#   straddle ATM 280 - |19700 - 20000| = -20; 0.9 strangle = 40 + 30 = 70


def _row(d, exp, k, opt, settle, contracts=100, oi=1000):
    return [d.isoformat(), exp.isoformat(), float(k), opt, 0.0, 0.0, 0.0, settle, settle,
            contracts, oi, float("nan")]


def _write(root, d, rows):
    path = root / "daily" / (d.strftime("%Y%m%d") + ".csv.gz")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        pd.DataFrame(rows, columns=COLS).to_csv(fh, index=False)


def _market(days):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    close = {E0: 19950.0, F: SPOT_F, E1: SETTLE_E1}
    return pd.DataFrame({"nifty_close": [close[d] for d in days],
                         "vix": [VIX_F] * len(days)}, index=idx)


def _world(root, *, illiquid=()):
    """E0 expiry file, F fill file (chain of E1), E1 expiry file with the index settle.
    illiquid: (strike, opt) pairs in the F chain with contracts == 0 and open_int == 0."""
    _write(root, E0, [_row(E0, E0, k, o, 19950.0) for k in STRIKES for o in ("CE", "PE")])
    rows = []
    for k in STRIKES:
        for o in ("CE", "PE"):
            s = PRICES.get((k, o), 5.0)
            c, oi = (0, 0) if (k, o) in illiquid else (100, 1000)
            rows.append(_row(F, E1, k, o, s, contracts=c, oi=oi))
    _write(root, F, rows)
    _write(root, E1, [_row(E1, E1, k, o, SETTLE_E1) for k in STRIKES for o in ("CE", "PE")])


def _arch(root, cut=END):
    return NseFoArchive(archive_dir=str(root), max_date=cut)


def test_leg_payoffs_hand_computed(tmp_path):
    _world(tmp_path)
    arch = _arch(tmp_path)
    df, skips = legs.weekly_leg_table(arch, _market([E0, F, E1]), E0, END)
    assert len(df) == 1, (df, skips)
    r = df.iloc[0]
    assert r["fill_date"] == str(F) and r["expiry"] == str(E1) and r["dte"] == 6
    assert r["vix_bucket"] == "13-16" and r["settle_src"] == "archive"
    assert (r["put_k_0.5"], r["call_k_0.5"]) == (19750.0, 20250.0)
    assert (r["put_k_0.9"], r["call_k_0.9"]) == (19600.0, 20400.0)
    assert (r["put_k_2.0"], r["call_k_2.0"]) == (19050.0, 20950.0)
    assert r["put_pnl_0.5"] == pytest.approx(10.0)
    assert r["put_pnl_0.9"] == pytest.approx(40.0)
    assert r["put_pnl_2.0"] == pytest.approx(3.0)
    assert r["call_pnl_0.5"] == pytest.approx(4.0)
    assert r["call_pnl_0.9"] == pytest.approx(30.0)
    assert r["call_pnl_2.0"] == pytest.approx(2.0)
    assert r["put_prem_0.9"] == pytest.approx(40.0)
    assert r["diff_pc_0.9"] == pytest.approx(10.0)            # 40 - 30
    assert r["strangle_pnl_0.9"] == pytest.approx(70.0)
    assert r["straddle_pnl_unit"] == pytest.approx(-20.0)      # 280 - |19700 - 20000|
    assert skips["leg"] == {}                              # every leg priced in this world
    assert skips["cycle"] == {"no_fill_session": 1}        # E1 itself has no session after it in the cut


def test_leg_payoffs_match_audit_vrp_at_engine_sd(tmp_path):
    # the 0.9 SD leg must agree with audit_vrp.measure_cycle, which is the existing audit's convention
    _world(tmp_path)
    arch = _arch(tmp_path)
    market = _market([E0, F, E1])
    old, _ = audit.run_audit(arch, market, E0, END, cadences=("weekly",))
    df, _ = legs.weekly_leg_table(arch, market, E0, END)
    assert len(old) == len(df) == 1
    assert df.iloc[0]["put_pnl_0.9"] == pytest.approx(old.iloc[0]["put_pnl_unit"])
    assert df.iloc[0]["call_pnl_0.9"] == pytest.approx(old.iloc[0]["call_pnl_unit"])
    assert df.iloc[0]["straddle_pnl_unit"] == pytest.approx(old.iloc[0]["straddle_pnl_unit"])


def test_illiquid_put_leg_is_nan_and_counted(tmp_path):
    _world(tmp_path, illiquid=[(19600.0, "PE")])          # the 0.9 SD put has no contracts and no OI
    arch = _arch(tmp_path)
    df, skips = legs.weekly_leg_table(arch, _market([E0, F, E1]), E0, END)
    assert len(df) == 1                                    # ATM still tradeable, cycle kept
    r = df.iloc[0]
    assert np.isnan(r["put_pnl_0.9"]) and np.isnan(r["strangle_pnl_0.9"]) and np.isnan(r["diff_pc_0.9"])
    assert r["call_pnl_0.9"] == pytest.approx(30.0)
    assert skips["leg"] == {"put_0.9_illiquid": 1}
    assert r["put_pnl_0.5"] == pytest.approx(10.0)         # other levels unaffected


def test_holm_hand_computed():
    # sorted p: .01 .03 .04 with m = 3 -> 3*.01=.03 ; 2*.03=.06 ; 1*.04=.04, running max -> .03 .06 .06
    assert legs.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert legs.holm([0.2]) == pytest.approx([0.2])
    assert legs.holm([0.9, 0.9]) == pytest.approx([1.0, 1.0])  # capped at 1


def test_tail_view_hand_computed():
    # 20 weeks, worst k = ceil(0.05*20) = 1 week at -100; others 1..19 (sum 190)
    vals = [-100.0] + [float(i) for i in range(1, 20)]
    df = pd.DataFrame({"x": vals, "fill_date": [f"2023-01-{i:02d}" for i in range(1, 21)]})
    summ, keep = legs.tail_view(df, "x")
    assert summ["k_worst"] == 1 and summ["tail_mean"] == pytest.approx(-100.0)
    assert summ["tail_contribution_to_mean"] == pytest.approx(-100.0 / 20)   # -5.0
    assert summ["ex_tail_contribution_to_mean"] == pytest.approx(190.0 / 20)  # 9.5
    assert int(keep.sum()) == 19 and not keep.iloc[0]


def test_power_block_formulas():
    rng = np.random.default_rng(7)
    x = rng.normal(0.0, 10.0, 250)
    df = pd.DataFrame({"s": x, "fill_date": ["2023-01-01"] * 250, "year": [2023] * 250})
    p = legs.power_block(df, {"series": "s"})[0]
    za, zb = NormalDist().inv_cdf(0.975), NormalDist().inv_cdf(0.80)
    assert p["n_weeks"] == 250
    assert p["se_iid"] == pytest.approx(p["sd"] / np.sqrt(250))
    assert p["mde_iid_pts"] == pytest.approx((za + zb) * p["se_iid"])        # ~2.80 SE
    assert p["weeks_for_target_iid"] == ceil(((za + zb) * p["sd"] / 8.0) ** 2)
    # sd 10 over 250 weeks: SE 0.63, so +8 pts is ~12.6 SE away and power is ~1
    assert 0.99 < p["power_at_target_obs_n"] <= 1.0
    # at the weeks-needed count (iid, rounded up) the one-sided power is at least 0.80
    n_need = p["weeks_for_target_iid"]
    se_need = p["sd"] / np.sqrt(n_need)
    assert NormalDist().cdf(8.0 / se_need - za) >= 0.80


def test_block_bootstrap_brackets_mean_and_p_values_behave():
    rng = np.random.default_rng(3)
    pos = 50.0 + rng.normal(0, 10, 250)
    zero = rng.normal(0, 10, 250)
    lo, hi, p_pos, se = legs._boot_block(pos, legs.BLOCK_LEN, legs.SEED_BLOCK)
    assert lo < pos.mean() < hi and p_pos < 0.01 and se > 0
    assert legs._boot_block(pos, legs.BLOCK_LEN, legs.SEED_BLOCK)[:2] == (lo, hi)   # deterministic
    _, _, p_zero, _ = legs._boot_block(zero, legs.BLOCK_LEN, legs.SEED_BLOCK)
    assert p_zero > 0.05


def test_dev_archive_view_never_opens_later_files(tmp_path):
    # 2024 daily file is corrupt: if the view ever opened it the loader would raise.
    arch_dir = tmp_path / "archive"
    _world(arch_dir)
    (arch_dir / "daily" / "20240102.csv.gz").write_bytes(b"not gzip at all")
    view, n = legs.dev_archive_view(str(arch_dir), tmp_path / "view", date(2023, 1, 12))
    linked = sorted(p.name for p in (tmp_path / "view" / "daily").iterdir())
    assert linked == ["20230105.csv.gz", "20230106.csv.gz", "20230112.csv.gz"]
    assert n == 3
    arch = NseFoArchive(archive_dir=view, max_date=date(2023, 1, 12))
    assert arch.trading_days() == [E0, F, E1]


def test_main_refuses_holdout_end_before_touching_any_data(tmp_path):
    with pytest.raises(SystemExit) as exc:
        legs.main(["--end", "2024-01-05", "--out", str(tmp_path / "o")])
    assert "2023-12-31" in str(exc.value)
    assert not (tmp_path / "o").exists()


def test_main_has_no_holdout_flag(tmp_path):
    with pytest.raises(SystemExit):
        legs.main(["--end", "2024-01-05", "--allow-holdout", "--out", str(tmp_path / "o")])
    assert not (tmp_path / "o").exists()
