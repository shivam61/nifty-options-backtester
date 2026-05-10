from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class QualityReport:
    summary: pd.DataFrame
    coverage_by_year: pd.DataFrame
    duplicates: pd.DataFrame
    missing_dates: pd.DataFrame
    net_mismatches: pd.DataFrame
    suspicious_spikes: pd.DataFrame
    missing_months: pd.DataFrame


def validate_net_consistency(df: pd.DataFrame, tolerance: float = 0.11) -> pd.DataFrame:
    frame = df.copy()
    calc_net = frame["buy_value"] - frame["sell_value"]
    mask = (
        frame["buy_value"].notna()
        & frame["sell_value"].notna()
        & frame["net_value"].notna()
        & ((calc_net - frame["net_value"]).abs() > tolerance)
    )
    return frame.loc[mask]


def find_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    subset = ["date", "participant_type", "market_segment", "sector", "series_kind", "source_name"]
    return df[df.duplicated(subset=subset, keep=False)].sort_values(subset)


def detect_missing_dates(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    participant_frames = []
    for participant_type, part_df in frame.groupby("participant_type"):
        calendar = pd.date_range(part_df["date"].min(), part_df["date"].max(), freq="B")
        present = set(part_df["date"].dt.normalize())
        missing = [ts.date() for ts in calendar if ts.normalize() not in present]
        participant_frames.append(
            pd.DataFrame({"participant_type": participant_type, "missing_date": missing})
        )
    return pd.concat(participant_frames, ignore_index=True) if participant_frames else pd.DataFrame()


def coverage_by_year(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame["year"] = pd.to_datetime(frame["date"]).dt.year
    return (
        frame.groupby(["year", "participant_type"])
        .agg(rows=("date", "count"), sources=("source_name", lambda s: sorted(set(s))))
        .reset_index()
    )


def summarize_dataset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["metric", "value"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    metrics = [
        {"metric": "rows", "value": int(len(frame))},
        {"metric": "start_date", "value": str(frame["date"].min().date())},
        {"metric": "end_date", "value": str(frame["date"].max().date())},
        {"metric": "participant_types", "value": ", ".join(sorted(set(frame["participant_type"].dropna().astype(str))))},
        {"metric": "source_names", "value": ", ".join(sorted(set(frame["source_name"].dropna().astype(str))))},
        {"metric": "series_kinds", "value": ", ".join(sorted(set(frame["series_kind"].dropna().astype(str))))},
    ]
    return pd.DataFrame(metrics)


def detect_missing_months(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["participant_type", "missing_month"])
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    outputs: list[pd.DataFrame] = []
    for participant_type, part_df in frame.groupby("participant_type"):
        month_index = pd.period_range(part_df["date"].min(), part_df["date"].max(), freq="M")
        present = set(part_df["date"].dt.to_period("M"))
        missing = [str(period) for period in month_index if period not in present]
        outputs.append(pd.DataFrame({"participant_type": participant_type, "missing_month": missing}))
    return pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame(columns=["participant_type", "missing_month"])


def detect_suspicious_spikes(df: pd.DataFrame, z_threshold: float = 4.0) -> pd.DataFrame:
    frame = df.copy()
    candidate = frame[frame["net_value"].notna()].copy()
    spike_frames = []
    for participant_type, part_df in candidate.groupby("participant_type"):
        series = part_df["net_value"].astype(float)
        z = (series - series.mean()) / series.std(ddof=0) if len(series) > 1 else pd.Series([0.0] * len(series))
        part_df = part_df.assign(z_score=z.values)
        spike_frames.append(part_df[part_df["z_score"].abs() >= z_threshold])
    return pd.concat(spike_frames, ignore_index=True) if spike_frames else pd.DataFrame()


def build_quality_report(df: pd.DataFrame) -> QualityReport:
    return QualityReport(
        summary=summarize_dataset(df),
        coverage_by_year=coverage_by_year(df),
        duplicates=find_duplicates(df),
        missing_dates=detect_missing_dates(df),
        net_mismatches=validate_net_consistency(df),
        suspicious_spikes=detect_suspicious_spikes(df),
        missing_months=detect_missing_months(df),
    )
