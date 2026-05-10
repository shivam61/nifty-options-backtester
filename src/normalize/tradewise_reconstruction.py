from __future__ import annotations

import io
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from src.utils.xlsx_stream import excel_serial_to_date


DOCUMENTED_TRANSACTION_TYPES: dict[str, dict[str, str]] = {
    "01": {"label": "purchase_secondary_market", "action": "buy"},
    "02": {"label": "purchase_primary_market", "action": "buy"},
    "03": {"label": "preferential_allotment", "action": "buy"},
    "04": {"label": "sale_secondary_market", "action": "sell"},
    "05": {"label": "rights_issue_purchase", "action": "buy"},
    "07": {"label": "bonus_entitlement", "action": "neutral"},
    "08": {"label": "stock_split_or_consolidation", "action": "neutral"},
    "10": {"label": "buyback_acceptance", "action": "sell"},
    "11": {"label": "merger_demerger_scheme", "action": "neutral"},
    "12": {"label": "redemption_or_extinguishment", "action": "sell"},
    "13": {"label": "amalgamation_or_scheme_allotment", "action": "buy"},
    "14": {"label": "open_offer_or_delisting_acceptance", "action": "sell"},
    "15": {"label": "call_money_or_forfeiture_adjustment", "action": "neutral"},
    "16": {"label": "other_corporate_action", "action": "neutral"},
}


@dataclass(frozen=True)
class ReconstructionProfile:
    name: str
    include_actions: tuple[str, ...]
    include_report_types: tuple[str, ...]
    date_basis: str = "report_date"
    signed_delete: bool = False
    include_instrument_prefixes: tuple[str, ...] = ("REG_DL_INSTR_EQ",)


DEFAULT_PROFILES: tuple[ReconstructionProfile, ...] = (
    ReconstructionProfile(
        name="strict_cash_new_only",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N",),
    ),
    ReconstructionProfile(
        name="cash_new_and_amend",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N", "DL_RPT_TYPE_A"),
    ),
    ReconstructionProfile(
        name="cash_signed_with_delete",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N", "DL_RPT_TYPE_A", "DL_RPT_TYPE_D"),
        signed_delete=True,
    ),
    ReconstructionProfile(
        name="strict_cash_new_only_trade_date",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N",),
        date_basis="trade_date",
    ),
    ReconstructionProfile(
        name="cash_plus_scheme_buy_sell",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N", "DL_RPT_TYPE_A"),
    ),
    ReconstructionProfile(
        name="strict_cash_new_eq_plus_eu",
        include_actions=("buy", "sell"),
        include_report_types=("DL_RPT_TYPE_N",),
        include_instrument_prefixes=("REG_DL_INSTR_EQ", "REG_DL_INSTR_EU"),
    ),
)


def parse_tradewise_zip(zip_path: str | Path) -> pd.DataFrame:
    frame = _read_tradewise_table(zip_path)
    if frame.empty:
        return pd.DataFrame()
    frame.columns = [str(column).strip() for column in frame.columns]
    header_map = {column: column for column in frame.columns}
    required_headers = {
        "RFDE_CUST_REG_NUM",
        "RFDE_TXN_ID",
        "RFDE_RPT_DT",
        "TR_DATE",
        "TR_TYPE(*)",
        "VALUE (in Rs)",
        "RFDE_INSTR_TYPE",
        "RFDE_RPT_TYPE",
        "FII",
        "SUB_ACC",
        "ISIN",
        "SCRIP_NAME",
    }
    wanted = {
        header_name: column
        for column, header_name in header_map.items()
        if header_name in required_headers
    }
    missing_headers = sorted(required_headers.difference(wanted.values()))
    if missing_headers:
        raise ValueError(f"Missing required headers in tradewise file {zip_path}: {', '.join(missing_headers)}")
    working = pd.DataFrame(
        {
            "trade_date": frame[wanted["TR_DATE"]].map(_safe_trade_date),
            "report_date": frame[wanted["RFDE_RPT_DT"]].map(_safe_trade_date),
            "cust_reg_num": _clean_string_series(frame[wanted["RFDE_CUST_REG_NUM"]]),
            "transaction_id": _clean_string_series(frame[wanted["RFDE_TXN_ID"]]),
            "fii_id": _clean_string_series(frame[wanted["FII"]]),
            "sub_account_id": _clean_string_series(frame[wanted["SUB_ACC"]]),
            "isin": _clean_string_series(frame[wanted["ISIN"]]),
            "scrip_name": _clean_string_series(frame[wanted["SCRIP_NAME"]]),
            "transaction_code": frame[wanted["TR_TYPE(*)"]].map(_coerce_transaction_code),
            "report_type": _clean_string_series(frame[wanted["RFDE_RPT_TYPE"]]),
            "instrument_type": _clean_string_series(frame[wanted["RFDE_INSTR_TYPE"]]),
            "value_crore": pd.to_numeric(frame[wanted["VALUE (in Rs)"]], errors="coerce").fillna(0.0) / 1e7,
        }
    )
    working = working.loc[working["trade_date"].notna()].copy()
    working["report_date"] = working["report_date"].where(working["report_date"].notna(), working["trade_date"])
    transaction_meta = working["transaction_code"].map(
        lambda code: DOCUMENTED_TRANSACTION_TYPES.get(code, {"label": "unknown", "action": "unknown"})
    )
    working["transaction_label"] = transaction_meta.map(lambda item: item["label"])
    working["transaction_action"] = transaction_meta.map(lambda item: item["action"])
    return working[
        [
            "trade_date",
            "report_date",
            "cust_reg_num",
            "transaction_id",
            "fii_id",
            "sub_account_id",
            "isin",
            "scrip_name",
            "transaction_code",
            "transaction_label",
            "transaction_action",
            "report_type",
            "instrument_type",
            "value_crore",
        ]
    ].reset_index(drop=True)


def _clean_string_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _safe_trade_date(value: object) -> date | pd.NaT:
    try:
        return _coerce_trade_date(value)
    except Exception:
        return pd.NaT


def _coerce_trade_date(value: object) -> date:
    if pd.isna(value):
        raise ValueError("missing date")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return excel_serial_to_date(str(value))
    text = str(value).strip()
    if not text:
        raise ValueError("missing date")
    for fmt, dayfirst in (
        ("%d/%m/%Y", True),
        ("%m/%d/%Y", False),
        ("%Y-%m-%d", False),
        ("%Y-%m-%d %H:%M:%S", False),
    ):
        try:
            return pd.to_datetime(text, format=fmt, dayfirst=dayfirst, errors="raise").date()
        except Exception:
            pass
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"unparseable date: {value}")
    return parsed.date()


def _coerce_transaction_code(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return f"{int(float(text)):02d}"
    except Exception:
        return text.zfill(2) if text.isdigit() else text


def _read_tradewise_table(path: str | Path) -> pd.DataFrame:
    payload = Path(path).read_bytes()
    return _read_tradewise_table_from_payload(payload, Path(path).name)


def _read_tradewise_table_from_payload(payload: bytes, name: str) -> pd.DataFrame:
    lower_name = name.lower()
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if any(member.startswith("xl/") for member in names):
                return pd.read_excel(io.BytesIO(payload))
            if not names:
                return pd.DataFrame()
            inner_name = names[0]
            inner_payload = archive.read(inner_name)
            return _read_tradewise_table_from_payload(inner_payload, inner_name)

    if lower_name.endswith(".csv"):
        return pd.read_csv(io.BytesIO(payload), low_memory=False)

    if lower_name.endswith(".xls") or lower_name.endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(payload))

    decoded = payload.decode("utf-8", errors="ignore")
    if "," in decoded.partition("\n")[0]:
        return pd.read_csv(io.BytesIO(payload), low_memory=False)

    raise ValueError(f"Unsupported tradewise payload format: {name}")


def aggregate_reconstruction(
    trade_df: pd.DataFrame,
    profile: ReconstructionProfile,
) -> pd.DataFrame:
    frame = trade_df.copy()
    if frame.empty:
        return pd.DataFrame(columns=["date", "buy", "sell", "net"])

    instrument_mask = frame["instrument_type"].astype(str).str.startswith(profile.include_instrument_prefixes)
    report_mask = frame["report_type"].isin(profile.include_report_types)
    action_mask = frame["transaction_action"].isin(profile.include_actions)
    filtered = frame.loc[instrument_mask & report_mask & action_mask].copy()

    if filtered.empty:
        return pd.DataFrame(columns=["date", "buy", "sell", "net"])

    multiplier = pd.Series(1.0, index=filtered.index)
    if profile.signed_delete:
        multiplier = multiplier.where(filtered["report_type"] != "DL_RPT_TYPE_D", -1.0)
    filtered["signed_value"] = filtered["value_crore"] * multiplier
    date_column = profile.date_basis
    if date_column not in filtered.columns:
        date_column = "trade_date"

    buy_df = (
        filtered.loc[filtered["transaction_action"] == "buy"]
        .groupby(date_column, as_index=False)["signed_value"]
        .sum()
        .rename(columns={date_column: "date", "signed_value": "buy"})
    )
    sell_df = (
        filtered.loc[filtered["transaction_action"] == "sell"]
        .groupby(date_column, as_index=False)["signed_value"]
        .sum()
        .rename(columns={date_column: "date", "signed_value": "sell"})
    )
    merged = buy_df.merge(sell_df, on="date", how="outer").fillna(0.0)
    merged["net"] = merged["buy"] - merged["sell"]
    merged["profile"] = profile.name
    return merged.sort_values("date")


def summarize_codes(trade_df: pd.DataFrame) -> pd.DataFrame:
    if trade_df.empty:
        return pd.DataFrame(columns=["transaction_code", "transaction_label", "transaction_action", "rows", "value_crore"])
    return (
        trade_df.groupby(["transaction_code", "transaction_label", "transaction_action"], as_index=False)
        .agg(rows=("transaction_id", "count"), value_crore=("value_crore", "sum"))
        .sort_values(["rows", "value_crore"], ascending=False)
    )


def coerce_month_start(value: object) -> date:
    period = pd.Period(pd.Timestamp(value), freq="M")
    return period.start_time.date()


def iter_month_starts(start_date: object, end_date: object) -> list[date]:
    start_period = pd.Period(pd.Timestamp(start_date), freq="M")
    end_period = pd.Period(pd.Timestamp(end_date), freq="M")
    return [period.start_time.date() for period in pd.period_range(start_period, end_period, freq="M")]


def expand_month_window(month_starts: list[date], window_months: int = 1) -> list[date]:
    if not month_starts:
        return []
    periods = {pd.Period(month_start, freq="M") for month_start in month_starts}
    expanded: set[pd.Period] = set()
    for period in periods:
        for offset in range(-window_months, window_months + 1):
            expanded.add(period + offset)
    return [period.start_time.date() for period in sorted(expanded)]


def month_key_from_archive_record(record: dict[str, object]) -> date | None:
    year = record.get("year")
    href = str(record.get("href") or "")
    month_label = str(record.get("month_label") or "")
    candidates = [Path(href).stem.replace("_", " ")]
    if month_label:
        candidates.append(month_label)
    if year is not None:
        candidates = [f"{candidate} {year}" for candidate in candidates if candidate] + candidates
    for candidate in candidates:
        cleaned = candidate.replace(".zip", "").strip()
        if not cleaned:
            continue
        parsed = pd.to_datetime(cleaned, errors="coerce")
        if pd.notna(parsed) and parsed.year >= 1900:
            return pd.Period(parsed, freq="M").start_time.date()
    return None


def build_archive_month_index(records: list[dict[str, object]]) -> dict[date, dict[str, object]]:
    month_index: dict[date, dict[str, object]] = {}
    for record in records:
        month_key = month_key_from_archive_record(record)
        if month_key is None:
            continue
        month_index[month_key] = record
    return month_index


def parse_tradewise_zip_many(zip_paths: list[str | Path]) -> pd.DataFrame:
    frames = [parse_tradewise_zip(path) for path in zip_paths]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def reconstruct_streaming_for_date_range(
    zip_paths: list[str | Path],
    profile: ReconstructionProfile,
    start_date: object | None = None,
    end_date: object | None = None,
    max_workers: int | None = None,
) -> pd.DataFrame:
    aggregates: list[pd.DataFrame] = []
    normalized_paths = [str(path) for path in zip_paths]
    worker_count = max_workers if max_workers is not None else min(4, os.cpu_count() or 1)
    if worker_count <= 1 or len(normalized_paths) <= 1:
        for zip_path in normalized_paths:
            aggregated = _aggregate_single_zip(zip_path, profile)
            if aggregated.empty:
                continue
            aggregates.append(aggregated[["date", "buy", "sell", "net"]])
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for aggregated in executor.map(_aggregate_single_zip_star, [(zip_path, profile) for zip_path in normalized_paths]):
                if aggregated.empty:
                    continue
                aggregates.append(aggregated[["date", "buy", "sell", "net"]])

    if not aggregates:
        return pd.DataFrame(columns=["date", "buy", "sell", "net", "profile"])

    reconstructed = (
        pd.concat(aggregates, ignore_index=True)
        .groupby("date", as_index=False)[["buy", "sell", "net"]]
        .sum()
        .sort_values("date")
    )
    reconstructed["profile"] = profile.name
    if start_date is not None:
        reconstructed = reconstructed[reconstructed["date"] >= start_date]
    if end_date is not None:
        reconstructed = reconstructed[reconstructed["date"] <= end_date]
    return reconstructed.reset_index(drop=True)


def reconstruct_for_date_range(
    zip_paths: list[str | Path],
    profile: ReconstructionProfile,
    start_date: object | None = None,
    end_date: object | None = None,
    max_workers: int | None = None,
) -> pd.DataFrame:
    return reconstruct_streaming_for_date_range(
        zip_paths=zip_paths,
        profile=profile,
        start_date=start_date,
        end_date=end_date,
        max_workers=max_workers,
    )


def _aggregate_single_zip(zip_path: str, profile: ReconstructionProfile) -> pd.DataFrame:
    trade_df = parse_tradewise_zip(zip_path)
    if trade_df.empty:
        return pd.DataFrame(columns=["date", "buy", "sell", "net", "profile"])
    return aggregate_reconstruction(trade_df, profile)


def _aggregate_single_zip_star(args: tuple[str, ReconstructionProfile]) -> pd.DataFrame:
    return _aggregate_single_zip(*args)
