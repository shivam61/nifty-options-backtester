"""
Journal session management and CSV read/write operations.
Handles:
  - Journal session CRUD (create, list, get, update)
  - TRADES.csv append/update operations
  - DAILY_LOG.csv append operations
  - Filtering trades by journal_id
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# Paths
JOURNAL_SESSIONS_PATH = Path("data/.cache/journal_sessions.json")
TRADES_CSV_PATH = Path("paper_trading/tracker/TRADES.csv")
DAILY_LOG_CSV_PATH = Path("paper_trading/tracker/DAILY_LOG.csv")


@dataclass
class JournalSession:
    """A journaling session for grouping trades."""
    journal_id: str
    label: str
    created_at: str
    initial_capital: float
    strategy_track: str  # "weekly" or "monthly" or "combined"
    status: str  # "active" or "closed"
    trade_ids: List[str]  # trades in this session
    notes: str = ""


def _ensure_dir():
    """Ensure cache and paper trading directories exist."""
    JOURNAL_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRADES_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_LOG_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_sessions() -> Dict[str, JournalSession]:
    """Load journal sessions from JSON file."""
    _ensure_dir()
    if not JOURNAL_SESSIONS_PATH.exists():
        return {}
    try:
        with open(JOURNAL_SESSIONS_PATH, "r") as f:
            data = json.load(f)
        return {k: JournalSession(**v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_sessions(sessions: Dict[str, JournalSession]):
    """Save journal sessions to JSON file."""
    _ensure_dir()
    data = {k: asdict(v) for k, v in sessions.items()}
    with open(JOURNAL_SESSIONS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def create_session(
    journal_id: str,
    label: str,
    initial_capital: float,
    strategy_track: str,
    notes: str = ""
) -> JournalSession:
    """Create a new journal session."""
    sessions = _load_sessions()
    if journal_id in sessions:
        raise ValueError(f"Journal session '{journal_id}' already exists")

    session = JournalSession(
        journal_id=journal_id,
        label=label,
        created_at=datetime.utcnow().isoformat(),
        initial_capital=initial_capital,
        strategy_track=strategy_track,
        status="active",
        trade_ids=[],
        notes=notes
    )
    sessions[journal_id] = session
    _save_sessions(sessions)
    return session


def list_sessions() -> List[JournalSession]:
    """List all journal sessions."""
    sessions = _load_sessions()
    return list(sessions.values())


def get_session(journal_id: str) -> Optional[JournalSession]:
    """Get a journal session by ID."""
    sessions = _load_sessions()
    return sessions.get(journal_id)


def update_session(journal_id: str, **kwargs) -> JournalSession:
    """Update a journal session (label, notes, status)."""
    sessions = _load_sessions()
    if journal_id not in sessions:
        raise ValueError(f"Journal session '{journal_id}' not found")

    session = sessions[journal_id]
    for key, value in kwargs.items():
        if hasattr(session, key):
            setattr(session, key, value)
    sessions[journal_id] = session
    _save_sessions(sessions)
    return session


def add_trade_to_session(journal_id: str, trade_id: str):
    """Add a trade_id to a journal session's trade_ids list."""
    session = get_session(journal_id)
    if not session:
        raise ValueError(f"Journal session '{journal_id}' not found")
    if trade_id not in session.trade_ids:
        session.trade_ids.append(trade_id)
        update_session(journal_id, trade_ids=session.trade_ids)


def get_session_summary(journal_id: str) -> Dict[str, Any]:
    """
    Compute summary metrics for a journal session.
    Reads TRADES.csv and calculates P&L, win rate, DD, etc.
    """
    session = get_session(journal_id)
    if not session:
        raise ValueError(f"Journal session '{journal_id}' not found")

    # Read TRADES.csv and filter by journal_id
    trades_by_journal = _read_trades_csv_by_journal(journal_id)

    open_count = len([t for t in trades_by_journal if t.get("Date_Exit") is None])
    closed_count = len([t for t in trades_by_journal if t.get("Date_Exit") is not None])

    closed_trades = [t for t in trades_by_journal if t.get("Date_Exit") is not None]

    total_pnl = sum(float(t.get("Net_P&L_₹", 0) or 0) for t in closed_trades)
    wins = sum(1 for t in closed_trades if t.get("Win_Loss") == "W")
    losses = sum(1 for t in closed_trades if t.get("Win_Loss") == "L")
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else None

    # Compute max drawdown from closed trades
    peak_equity = session.initial_capital
    trough = session.initial_capital
    account_dd_pct = 0.0
    cumulative_pnl = 0.0
    for trade in closed_trades:
        cumulative_pnl += float(trade.get("Net_P&L_₹", 0) or 0)
        current_equity = session.initial_capital + cumulative_pnl
        peak_equity = max(peak_equity, current_equity)
        dd = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0
        account_dd_pct = max(account_dd_pct, dd)

    return {
        "journal_id": journal_id,
        "label": session.label,
        "status": session.status,
        "created_at": session.created_at,
        "initial_capital": session.initial_capital,
        "strategy_track": session.strategy_track,
        "open_trades": open_count,
        "closed_trades": closed_count,
        "total_pnl": total_pnl,
        "win_rate_pct": win_rate,
        "account_dd_pct": account_dd_pct,
        "trades": trades_by_journal
    }


def _read_trades_csv_by_journal(journal_id: str) -> List[Dict[str, str]]:
    """Read TRADES.csv and return all rows with matching journal_id."""
    _ensure_dir()
    if not TRADES_CSV_PATH.exists():
        return []

    trades = []
    try:
        with open(TRADES_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Journal_ID") == journal_id:
                    trades.append(row)
    except (FileNotFoundError, KeyError):
        pass

    return trades


def append_trade_csv(
    trade_id: str,
    journal_id: str,
    entry_data: Dict[str, Any]
) -> None:
    """
    Append a new row to TRADES.csv with entry data.
    Columns: Trade_ID, Journal_ID, Date_Entry, Entry_Time_IST, Strategy, Signal_VIX, Signal_Regime,
             ML_Score, Entry_Price_Fill, Lots_Size, Capital_Deployed_₹, Strike_Entry, Expiry_DTE,
             Date_Exit, Exit_Time_IST, Exit_Price_Fill, Exit_Reason, Days_Held, Gross_P&L_₹,
             Brokerage_₹, Slippage_vs_Backtest_bp, Net_P&L_₹, Win_Loss, P&L_vs_Max_Profit_%,
             Backtest_Expected_P&L_₹, Backtest_Deviation_%, Notes
    """
    _ensure_dir()

    # Ensure header exists
    if not TRADES_CSV_PATH.exists():
        with open(TRADES_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "Trade_ID", "Journal_ID", "Date_Entry", "Entry_Time_IST", "Strategy", "Signal_VIX",
                "Signal_Regime", "ML_Score", "Entry_Price_Fill", "Lots_Size", "Capital_Deployed_₹",
                "Strike_Entry", "Expiry_DTE", "Date_Exit", "Exit_Time_IST", "Exit_Price_Fill",
                "Exit_Reason", "Days_Held", "Gross_P&L_₹", "Brokerage_₹", "Slippage_vs_Backtest_bp",
                "Net_P&L_₹", "Win_Loss", "P&L_vs_Max_Profit_%", "Backtest_Expected_P&L_₹",
                "Backtest_Deviation_%", "Notes"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    # Append new row
    row = {
        "Trade_ID": trade_id,
        "Journal_ID": journal_id,
        "Date_Entry": entry_data.get("entry_date", ""),
        "Entry_Time_IST": entry_data.get("entry_time_ist", ""),
        "Strategy": entry_data.get("strategy", ""),
        "Signal_VIX": entry_data.get("vix", ""),
        "Signal_Regime": entry_data.get("regime", ""),
        "ML_Score": entry_data.get("ml_score", ""),
        "Entry_Price_Fill": entry_data.get("entry_price", ""),
        "Lots_Size": entry_data.get("lots", ""),
        "Capital_Deployed_₹": entry_data.get("capital_deployed", ""),
        "Strike_Entry": entry_data.get("strike", ""),
        "Expiry_DTE": entry_data.get("expiry_dte", ""),
        "Date_Exit": "",
        "Exit_Time_IST": "",
        "Exit_Price_Fill": "",
        "Exit_Reason": "",
        "Days_Held": "",
        "Gross_P&L_₹": "",
        "Brokerage_₹": "",
        "Slippage_vs_Backtest_bp": "",
        "Net_P&L_₹": "",
        "Win_Loss": "",
        "P&L_vs_Max_Profit_%": "",
        "Backtest_Expected_P&L_₹": entry_data.get("backtest_expected_pnl", ""),
        "Backtest_Deviation_%": "",
        "Notes": entry_data.get("notes", "")
    }

    with open(TRADES_CSV_PATH, "a", encoding="utf-8", newline="") as f:
        fieldnames = [
            "Trade_ID", "Journal_ID", "Date_Entry", "Entry_Time_IST", "Strategy", "Signal_VIX",
            "Signal_Regime", "ML_Score", "Entry_Price_Fill", "Lots_Size", "Capital_Deployed_₹",
            "Strike_Entry", "Expiry_DTE", "Date_Exit", "Exit_Time_IST", "Exit_Price_Fill",
            "Exit_Reason", "Days_Held", "Gross_P&L_₹", "Brokerage_₹", "Slippage_vs_Backtest_bp",
            "Net_P&L_₹", "Win_Loss", "P&L_vs_Max_Profit_%", "Backtest_Expected_P&L_₹",
            "Backtest_Deviation_%", "Notes"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(row)


def close_trade_csv(
    trade_id: str,
    journal_id: str,
    exit_data: Dict[str, Any]
) -> None:
    """
    Update TRADES.csv row to mark trade as closed with exit data.
    """
    _ensure_dir()
    if not TRADES_CSV_PATH.exists():
        raise FileNotFoundError(f"TRADES.csv not found at {TRADES_CSV_PATH}")

    rows = []
    found = False
    try:
        with open(TRADES_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                if row.get("Trade_ID") == trade_id and row.get("Journal_ID") == journal_id:
                    # Update exit data
                    row["Date_Exit"] = exit_data.get("exit_date", "")
                    row["Exit_Time_IST"] = exit_data.get("exit_time_ist", "")
                    row["Exit_Price_Fill"] = exit_data.get("exit_price", "")
                    row["Exit_Reason"] = exit_data.get("exit_reason", "")
                    row["Days_Held"] = exit_data.get("days_held", "")
                    row["Gross_P&L_₹"] = exit_data.get("gross_pnl", "")
                    row["Brokerage_₹"] = exit_data.get("brokerage", "")
                    row["Slippage_vs_Backtest_bp"] = exit_data.get("slippage_bp", "")
                    row["Net_P&L_₹"] = exit_data.get("net_pnl", "")
                    row["Win_Loss"] = exit_data.get("win_loss", "")
                    row["P&L_vs_Max_Profit_%"] = exit_data.get("pnl_vs_max_profit_pct", "")
                    row["Backtest_Deviation_%"] = exit_data.get("backtest_deviation_pct", "")
                    row["Notes"] = exit_data.get("notes", "")
                    found = True
                rows.append(row)
    except FileNotFoundError:
        raise

    if found:
        with open(TRADES_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def append_daily_log(
    journal_id: str,
    snapshot: Dict[str, Any]
) -> None:
    """
    Append a daily account snapshot to DAILY_LOG.csv.
    Columns: Date, Journal_ID, Account_Equity_₹, Cumulative_P&L_₹, Open_Trades_Count,
             VIX_Close, Market_Regime, Open_Trades_Count_Weekly, Win_Rate_%_YTD,
             Avg_Trade_P&L_₹_YTD, Account_DD_%, Notes
    """
    _ensure_dir()

    # Ensure header exists
    if not DAILY_LOG_CSV_PATH.exists():
        with open(DAILY_LOG_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            fieldnames = [
                "Date", "Journal_ID", "Account_Equity_₹", "Cumulative_P&L_₹", "Open_Trades_Count",
                "VIX_Close", "Market_Regime", "Open_Trades_Count_Weekly", "Win_Rate_%_YTD",
                "Avg_Trade_P&L_₹_YTD", "Account_DD_%", "Notes"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

    # Append new row
    row = {
        "Date": snapshot.get("date", ""),
        "Journal_ID": journal_id,
        "Account_Equity_₹": snapshot.get("account_equity", ""),
        "Cumulative_P&L_₹": snapshot.get("cumulative_pnl", ""),
        "Open_Trades_Count": snapshot.get("open_trades_count", ""),
        "VIX_Close": snapshot.get("vix_close", ""),
        "Market_Regime": snapshot.get("market_regime", ""),
        "Open_Trades_Count_Weekly": snapshot.get("open_trades_weekly", ""),
        "Win_Rate_%_YTD": snapshot.get("win_rate_ytd_pct", ""),
        "Avg_Trade_P&L_₹_YTD": snapshot.get("avg_trade_pnl_ytd", ""),
        "Account_DD_%": snapshot.get("account_dd_pct", ""),
        "Notes": snapshot.get("notes", "")
    }

    with open(DAILY_LOG_CSV_PATH, "a", encoding="utf-8", newline="") as f:
        fieldnames = [
            "Date", "Journal_ID", "Account_Equity_₹", "Cumulative_P&L_₹", "Open_Trades_Count",
            "VIX_Close", "Market_Regime", "Open_Trades_Count_Weekly", "Win_Rate_%_YTD",
            "Avg_Trade_P&L_₹_YTD", "Account_DD_%", "Notes"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(row)
