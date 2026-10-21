"""Tests for scripts/audit_vrp.py on a tiny synthetic archive written to tmp_path (no network,
no real archive). Expected numbers are hand-computed in the comments.
"""
import gzip
from datetime import date

import numpy as np
import pandas as pd
import pytest

import scripts.audit_vrp as audit
from data.nse_fo_archive import NseFoArchive

COLS = ["date", "expiry", "strike", "opt", "open", "high", "low", "close", "settle",
        "contracts", "open_int", "underlying"]
E0 = date(2023, 1, 5)     # Thursday expiry (signal day); fill = F
F = date(2023, 1, 6)      # fill session, spot 20000, VIX 15 (DTE 6 to E1)
E1 = date(2023, 1, 12)    # target weekly expiry, index settles at 20200
END = date(2023, 1, 12)
SPOT_F, VIX_F = 20000.0, 15.0
SETTLE_E1 = 20200.0
STRIKES = [19000.0 + 50 * i for i in range(41)]  # 19000..21000


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


def _world(root, *, atm_pe_contracts=100, atm_pe_oi=1000):
    """E0 expiry file, F fill file (chain of E1), E1 expiry file with the index settle."""
    # 0.9 SD strikes at (20000, VIX 15, DTE 6): put 19600, call 20400 (hand: 0.9*20000*0.15/sqrt(252)*sqrt(6)
    # = 416.7 -> 19583 -> 19600 and 20416 -> 20400); settle 40 put, 30 call
    p_sp, p_sc = 19600.0, 20400.0
    # E0 expiry-day file (index settle 19950 on every row; expiry E0 only)
    _write(root, E0, [_row(E0, E0, k, o, 19950.0) for k in STRIKES for o in ("CE", "PE")])
    # F fill-day file: chain of E1
    rows = []
    for k in STRIKES:
        for o in ("CE", "PE"):
            s = 5.0
            if k == 20000.0:
                s = 150.0 if o == "CE" else 130.0            # ATM straddle = 280
            if k == p_sp and o == "PE":
                s = 40.0
            if k == p_sc and o == "CE":
                s = 30.0
            c, oi = 100, 1000
            if k == 20000.0 and o == "PE":
                c, oi = atm_pe_contracts, atm_pe_oi
            rows.append(_row(F, E1, k, o, s, contracts=c, oi=oi))
    _write(root, F, rows)
    # E1 expiry-day file: index settle 20200 on every row
    _write(root, E1, [_row(E1, E1, k, o, SETTLE_E1) for k in STRIKES for o in ("CE", "PE")])


def _arch(root, cut=END):
    return NseFoArchive(archive_dir=str(root), max_date=cut)


def test_straddle_and_realised_move_hand_computed(tmp_path):
    _world(tmp_path)
    arch = _arch(tmp_path)
    market = _market([E0, F, E1])
    df, skips = audit.run_audit(arch, market, E0, END, cadences=("weekly",))
    assert len(df) == 1, (df, skips)
    r = df.iloc[0]
    assert r["fill_date"] == str(F) and r["expiry"] == str(E1) and r["dte"] == 6
    assert r["atm_k"] == 20000.0 and r["straddle"] == pytest.approx(280.0)     # 150 + 130
    assert r["implied_move"] == pytest.approx(280.0 / 20000.0)                 # 1.40%
    assert r["settle_T"] == pytest.approx(SETTLE_E1)
    assert r["realised_move"] == pytest.approx(200.0 / 20000.0)                # |20200-20000|/20000 = 1.00%
    assert r["ratio"] == pytest.approx(1.0 / 1.4)
    assert bool(r["implied_gt_realised"]) is True
    assert r["straddle_pnl_unit"] == pytest.approx(280.0 - 200.0)              # 80 per unit
    assert r["vix_bucket"] == "13-16"


def test_otm_short_strangle_at_0p9_sd_hand_computed(tmp_path):
    _world(tmp_path)
    arch = _arch(tmp_path)
    df, _ = audit.run_audit(arch, _market([E0, F, E1]), E0, END, cadences=("weekly",))
    r = df.iloc[0]
    assert (r["put_k"], r["call_k"]) == (19600.0, 20400.0)
    # the repo's own put credit spread short put (put_sd 0.9) is the same strike
    from strategies.weekly_strategies import WeeklyPutCreditSpread
    sp = [l.strike for l in WeeklyPutCreditSpread(lots=1, lot_size=65).generate_legs(SPOT_F, VIX_F, 6, 0.065)
          if l.is_short][0]
    assert sp == r["put_k"]
    assert r["put_prem"] == 40.0 and r["call_prem"] == 30.0
    assert r["put_pnl_unit"] == pytest.approx(40.0)     # put expires OTM: 19600 < 20200
    assert r["call_pnl_unit"] == pytest.approx(30.0)    # call expires OTM: 20400 > 20200
    assert r["strangle_pnl_unit"] == pytest.approx(70.0)


def test_otm_payoff_when_index_settles_through_the_short_strike(tmp_path):
    # Same world but E1 settles at 19500: short put ITM by 100, call still OTM.
    _world(tmp_path)
    _write(tmp_path, E1, [_row(E1, E1, k, o, 19500.0) for k in STRIKES for o in ("CE", "PE")])
    arch = _arch(tmp_path)
    df, _ = audit.run_audit(arch, _market([E0, F, E1]), E0, END, cadences=("weekly",))
    r = df.iloc[0]
    assert r["put_pnl_unit"] == pytest.approx(40.0 - (19600.0 - 19500.0))    # 40 - 100 = -60
    assert r["call_pnl_unit"] == pytest.approx(30.0)


def test_zero_contracts_and_oi_on_atm_leg_skips_the_cycle(tmp_path):
    _world(tmp_path, atm_pe_contracts=0, atm_pe_oi=0)
    arch = _arch(tmp_path)
    df, skips = audit.run_audit(arch, _market([E0, F, E1]), E0, END, cadences=("weekly",))
    assert df.empty
    assert skips["weekly"].get("untradeable_or_unsettled") == 1


def test_archive_cut_drops_rows_after_end_at_load(tmp_path):
    _world(tmp_path)
    arch = _arch(tmp_path, cut=E0)  # rows after E0 never indexed
    assert arch.trading_days() == [E0]
    assert arch.n_rows == len(STRIKES) * 2
    df, _ = audit.run_audit(arch, _market([E0, F, E1]), E0, E0, cadences=("weekly",))
    assert df.empty  # F and E1 are not in the cut archive, so nothing can be measured


def test_check_window_refuses_after_dev_end_unless_flagged():
    audit.check_window(date(2023, 12, 31), allow_holdout=False)     # boundary is allowed
    with pytest.raises(SystemExit):
        audit.check_window(date(2024, 1, 1), allow_holdout=False)
    audit.check_window(date(2024, 1, 1), allow_holdout=True)        # explicit flag only


def test_cli_refuses_holdout_end_before_touching_any_data(tmp_path):
    # the refusal is checked before the market cache or the archive is opened
    with pytest.raises(SystemExit) as exc:
        audit.main(["--end", "2024-01-05", "--out", str(tmp_path / "o")])
    assert "2023-12-31" in str(exc.value)
    assert not (tmp_path / "o").exists()


def test_bootstrap_helpers_are_deterministic_and_bracket_the_mean():
    x = np.array([10.0, -5.0, 20.0, 0.0, 15.0, -10.0])
    a = audit._boot_mean_ci(x, 1)
    assert a == audit._boot_mean_ci(x, 1)
    assert a[0] < x.mean() < a[1]
