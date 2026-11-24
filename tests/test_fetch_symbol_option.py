"""parse_bhavcopy symbol option and CLI args (synthetic bytes, no network)."""
import io
import os
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import fetch_nse_fo_archive as f  # noqa: E402

LEG_HDR = "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,"
UD_HDR = ("TradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,OpnPric,HghPric,LwPric,ClsPric,"
          "SttlmPric,TtlTradgVol,OpnIntrst,UndrlygPric")


def _zip(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", text)
    return b.getvalue()


def _legacy():
    rows = [LEG_HDR]
    for sym in ("NIFTY", "BANKNIFTY"):
        for opt in ("CE", "PE"):
            rows.append(f"OPTIDX,{sym},28-OCT-2010,5000,{opt},1,2,0.5,1.5,1.4,10,0,20,0,14-OCT-2010,")
    rows.append("FUTIDX,NIFTY,28-OCT-2010,0,XX,1,2,0.5,1.5,1.4,10,0,20,0,14-OCT-2010,")
    return _zip("\n".join(rows))


def _udiff():
    rows = [UD_HDR]
    for sym in ("NIFTY", "BANKNIFTY"):
        for opt in ("CE", "PE"):
            rows.append(f"2025-01-02,IDO,{sym},2025-01-30,20000,{opt},1,2,0.5,1.5,1.4,10,20,23000")
    rows.append("2025-01-02,STO,RELIANCE,2025-01-30,1000,CE,1,2,0.5,1.5,1.4,10,20,1000")
    return _zip("\n".join(rows))


def test_default_nifty_legacy():
    rows = f.parse_bhavcopy(_legacy(), date(2010, 10, 14), "legacy")
    assert len(rows) == 2 and {r[3] for r in rows} == {"CE", "PE"}
    assert rows[0] == ["2010-10-14", "2010-10-28", "5000.0", "CE", "1.0", "2.0", "0.5", "1.5", "1.4",
                       "10", "20", ""]
    assert f.parse_bhavcopy(_legacy(), date(2010, 10, 14), "legacy", "NIFTY") == rows


def test_default_nifty_udiff():
    rows = f.parse_bhavcopy(_udiff(), date(2025, 1, 2), "udiff")
    assert len(rows) == 2 and rows[0][-1] == "23000.0"


def test_banknifty_symbol():
    for raw, d, fmt in ((_legacy(), date(2010, 10, 14), "legacy"), (_udiff(), date(2025, 1, 2), "udiff")):
        rows = f.parse_bhavcopy(raw, d, fmt, "BANKNIFTY")
        assert len(rows) == 2
        f.validate_rows(rows, d)


def test_cli_args():
    a = f.parse_args(["--symbol", "BANKNIFTY", "--out-dir", "/tmp/x", "--end", "2020-01-01"])
    assert a.symbol == "BANKNIFTY" and a.archive_dir == "/tmp/x" and a.end == date(2020, 1, 1)
    d = f.parse_args([])
    assert d.symbol == "NIFTY" and d.archive_dir is None and d.start == f.DEFAULT_START


def test_legacy_date_two_digit_year():
    from datetime import date
    import fetch_nse_fo_archive as f
    assert f._legacy_date("14-May-12") == date(2012, 5, 14)
    assert f._legacy_date("11-FEB-2019") == date(2019, 2, 11)
