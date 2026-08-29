"""
FastAPI server for paper trading journal and live signal generation.

Endpoints:
  - POST /journals — Create journal session
  - GET /journals — List all sessions
  - GET /journals/{journal_id} — Get session summary
  - PATCH /journals/{journal_id} — Update session
  - GET /status?journal_id=<id> — Account snapshot
  - GET /signal — Entry signals (weekly + monthly)
  - GET /trades?journal_id=<id>&status=open|closed|all — Trade list
  - GET /monitor?journal_id=<id> — Exit recommendations for open trades
  - POST /trades/open — Record new trade
  - POST /trades/{trade_id}/close — Close trade
  - POST /journal/daily-log — Log daily account snapshot
  - POST /market/refresh — Reload market data cache
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date, datetime, time
import traceback
import logging

# Existing codebase imports
from data.market_data import MarketDataFetcher
from models.regime_aware_learner import RegimeAwareLearner
from models.trade_monitor import load_active_trades, add_trade, close_trade, ExitStrategyEngine
from strategies.multi_strategy import RegimeAdaptiveStrategy
from backtester.position_sizer import PositionSizer
from config import BacktestConfig, WeeklyBacktestConfig

# API modules
from api.journal import (
    create_session, list_sessions, get_session, update_session,
    get_session_summary, add_trade_to_session, append_trade_csv,
    close_trade_csv, append_daily_log
)
from api.signal_wrapper import (
    wrap_regime_aware_signal, wrap_position_sizing, wrap_entry_signal_for_track,
    wrap_full_signal_response, wrap_active_trade, wrap_exit_recommendation
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# FastAPI app and global state
# ============================================================================

app = FastAPI(
    title="Nifty Options Backtester API",
    description="REST API for paper trading journal and live signal generation",
    version="1.0.0"
)

_state = {
    "market_df": None,
    "latest_row": None,
    "models": {},
    "market_fetcher": None
}


@app.on_event("startup")
async def startup_event():
    """Load market data and models on startup."""
    try:
        logger.info("Loading market data...")
        market_fetcher = MarketDataFetcher(start_date=date(2009, 1, 1), end_date=date.today())
        _state["market_fetcher"] = market_fetcher
        _state["market_df"] = market_fetcher.build_combined_dataset()
        _state["latest_row"] = _state["market_df"].iloc[-1]

        logger.info("Loading ML models...")
        _state["models"]["entry_model"] = RegimeAwareLearner.load_cached()
        _state["models"]["exit_model"] = ExitStrategyEngine.load_cached()

        logger.info("✓ Startup complete. Market data ready.")
    except Exception as e:
        logger.error(f"Startup error: {e}")
        logger.error(traceback.format_exc())
        raise


# ============================================================================
# Pydantic request/response schemas
# ============================================================================

class JournalSessionCreateRequest(BaseModel):
    journal_id: str
    label: str
    initial_capital: float
    strategy_track: str
    notes: str = ""


class JournalSessionUpdateRequest(BaseModel):
    label: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class TradeOpenRequest(BaseModel):
    journal_id: str
    trade_id: str
    strategy: str
    entry_date: str
    expiry_date: str
    legs_str: str  # "SELL 24800 PE 85 @ 520; BUY 24600 PE 40 @ 520"
    lots: int
    capital_deployed: float
    ml_score: float
    entry_time_ist: str
    strike: Optional[float] = None
    vix: Optional[float] = None
    regime: Optional[str] = None
    notes: str = ""


class TradeCloseRequest(BaseModel):
    exit_price_per_unit: float
    exit_reason: str
    exit_time_ist: str
    brokerage: float = 0.0
    notes: str = ""


class DailyLogRequest(BaseModel):
    journal_id: str
    date: Optional[str] = None
    account_equity: float
    cumulative_pnl: float
    open_trades_count: int
    vix_close: float
    market_regime: str
    win_rate_ytd_pct: Optional[float] = None
    avg_trade_pnl_ytd: Optional[float] = None
    account_dd_pct: float = 0.0
    notes: str = ""


# ============================================================================
# Journal Session Endpoints
# ============================================================================

@app.post("/journals")
async def create_journal_session(req: JournalSessionCreateRequest) -> Dict[str, Any]:
    """Create a new journal session."""
    try:
        session = create_session(
            journal_id=req.journal_id,
            label=req.label,
            initial_capital=req.initial_capital,
            strategy_track=req.strategy_track,
            notes=req.notes
        )
        return {
            "success": True,
            "journal_id": session.journal_id,
            "label": session.label,
            "status": session.status,
            "created_at": session.created_at
        }
    except Exception as e:
        logger.error(f"Error creating journal: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/journals")
async def list_journal_sessions() -> Dict[str, Any]:
    """List all journal sessions with summary metrics."""
    try:
        sessions = list_sessions()
        summaries = []
        for session in sessions:
            try:
                summary = get_session_summary(session.journal_id)
                summaries.append({
                    "journal_id": summary["journal_id"],
                    "label": summary["label"],
                    "status": summary["status"],
                    "created_at": summary["created_at"],
                    "strategy_track": summary["strategy_track"],
                    "open_trades": summary["open_trades"],
                    "closed_trades": summary["closed_trades"],
                    "total_pnl": summary["total_pnl"],
                    "win_rate_pct": summary["win_rate_pct"],
                    "account_dd_pct": summary["account_dd_pct"]
                })
            except Exception as e:
                logger.warning(f"Could not summarize journal {session.journal_id}: {e}")
        return {"journals": summaries}
    except Exception as e:
        logger.error(f"Error listing journals: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/journals/{journal_id}")
async def get_journal_session(journal_id: str) -> Dict[str, Any]:
    """Get full summary for one journal session."""
    try:
        summary = get_session_summary(journal_id)
        return summary
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting journal {journal_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/journals/{journal_id}")
async def update_journal_session(
    journal_id: str,
    req: JournalSessionUpdateRequest
) -> Dict[str, Any]:
    """Update journal session metadata."""
    try:
        update_data = {}
        if req.label is not None:
            update_data["label"] = req.label
        if req.notes is not None:
            update_data["notes"] = req.notes
        if req.status is not None:
            update_data["status"] = req.status

        session = update_session(journal_id, **update_data)
        return {
            "success": True,
            "journal_id": session.journal_id,
            "label": session.label,
            "status": session.status
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating journal: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Account Status Endpoint
# ============================================================================

@app.get("/status")
async def get_account_status(journal_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Get current account snapshot, optionally scoped to a journal session."""
    try:
        if not _state["latest_row"] is not None:
            raise RuntimeError("Market data not loaded. Call /market/refresh or wait for startup.")

        latest_row = _state["latest_row"]
        spot = float(latest_row.get("nifty_close", 0))
        vix = float(latest_row.get("vix_close", 0))
        market_date = latest_row.get("date", date.today())

        # Load active + closed trades
        active_trades = load_active_trades()
        active_by_journal = [t for t in active_trades if getattr(t, "journal_id", "default") == (journal_id or "default")]
        open_count = len(active_by_journal)

        # Get session info if journal_id provided
        if journal_id:
            session = get_session(journal_id)
            if not session:
                raise HTTPException(status_code=404, detail=f"Journal {journal_id} not found")
            initial_capital = session.initial_capital
            label = session.label
        else:
            initial_capital = 1_500_000
            label = "Global"

        # Compute P&L from trades
        summary = {}
        if journal_id:
            summary = get_session_summary(journal_id)

        cumulative_pnl = summary.get("total_pnl", 0.0)
        account_dd_pct = summary.get("account_dd_pct", 0.0)
        win_rate_pct = summary.get("win_rate_pct")

        account_equity = initial_capital + cumulative_pnl
        available_capital = account_equity * 0.80  # 80% for trading
        reserve_capital = account_equity * 0.20  # 20% reserve

        return {
            "journal_id": journal_id or "global",
            "label": label,
            "account_equity": account_equity,
            "initial_capital": initial_capital,
            "cumulative_pnl": cumulative_pnl,
            "account_dd_pct": account_dd_pct,
            "open_trades": open_count,
            "closed_trades": summary.get("closed_trades", 0),
            "win_rate_pct": win_rate_pct,
            "available_capital": available_capital,
            "reserve_capital": reserve_capital,
            "vix_now": vix,
            "spot_now": spot,
            "regime": _infer_regime(vix),
            "market_date": str(market_date),
            "backtest_baseline_cagr": 12.07,
            "backtest_baseline_win_rate": 78.0
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Signal Endpoint
# ============================================================================

@app.get("/signal")
async def get_entry_signal() -> Dict[str, Any]:
    """Get ML-driven entry signals for weekly and monthly tracks."""
    try:
        if _state["latest_row"] is None:
            raise RuntimeError("Market data not loaded")

        latest_row = _state["latest_row"]
        spot = float(latest_row.get("nifty_close", 25000))
        vix = float(latest_row.get("vix_close", 20))
        regime = _infer_regime(vix)

        # Check entry window (11:00–13:00 IST)
        now_ist = datetime.utcnow().replace(tzinfo=None)  # Approximate
        within_window = 11 <= now_ist.hour < 13

        # Get eligibile strategies
        entry_model = _state["models"].get("entry_model")
        if not entry_model:
            raise RuntimeError("Entry model not loaded")

        try:
            eligible_strats = RegimeAdaptiveStrategy.get_eligible_strategies(
                spot=spot,
                vix=vix,
                market_data_dict=latest_row.to_dict() if hasattr(latest_row, "to_dict") else dict(latest_row)
            )
        except:
            eligible_strats = ["put_credit_spread", "iron_condor"]  # Fallback

        # Get ML prediction for each track
        try:
            pred = entry_model.predict(latest_row, eligible_strats)
            quality_score = float(pred.get("quality_score", 0.0))
            signal_str = pred.get("signal", "AVOID")
            recommended_strategy = pred.get("strategy")
            macro_context = pred.get("macro_context", [])
            reasoning = pred.get("reasoning", [])
        except Exception as e:
            logger.warning(f"ML prediction error: {e}")
            quality_score = 0.0
            signal_str = "AVOID"
            recommended_strategy = None
            macro_context = ["ML model unavailable"]
            reasoning = [str(e)]

        # Get position sizing
        equity = 1_500_000
        try:
            position_sizer = PositionSizer()
            sizing = position_sizer.compute_lots(
                equity=equity,
                vix=vix,
                regime=regime,
                win_prob=quality_score,
                drawdown_pct=0.0
            )
            sizing_dict = wrap_position_sizing(sizing, equity * 0.80, equity)
        except Exception as e:
            logger.warning(f"Position sizing error: {e}")
            sizing_dict = {
                "suggested_lots": 0,
                "available_capital": equity * 0.80,
                "capital_to_deploy": 0
            }

        # Wrap signals for each track
        weekly_pred = wrap_regime_aware_signal(
            {"quality_score": quality_score, "signal": signal_str, "strategy": recommended_strategy,
             "macro_context": macro_context, "reasoning": reasoning},
            spot, vix, regime, eligible_strats
        )
        weekly_signal = wrap_entry_signal_for_track(
            "weekly", weekly_pred, sizing_dict, equity * 0.80,
            BacktestConfig.weekly_entry_threshold, dte_window="3–8"
        )

        # Monthly signal (currently disabled in Phase 1)
        monthly_pred = wrap_regime_aware_signal(
            {"quality_score": 0.0, "signal": "AVOID", "strategy": None,
             "macro_context": ["Monthly disabled in Phase 1"], "reasoning": []},
            spot, vix, regime, []
        )
        monthly_signal = wrap_entry_signal_for_track(
            "monthly", monthly_pred, {"suggested_lots": 0, "available_capital": 0, "capital_to_deploy": 0},
            0, BacktestConfig.monthly_entry_threshold,
            skip_reason="monthly_paused_phase1"
        )

        return wrap_full_signal_response(
            spot=spot,
            vix=vix,
            regime=regime,
            weekly_signal=weekly_signal,
            monthly_signal=monthly_signal,
            macro_context=macro_context,
            reasoning=reasoning,
            within_entry_window=within_window
        )

    except Exception as e:
        logger.error(f"Error getting signal: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Trades Endpoints
# ============================================================================

@app.get("/trades")
async def get_trades(
    journal_id: Optional[str] = Query(None),
    status: str = Query("open", regex="^(open|closed|all)$")
) -> Dict[str, Any]:
    """List trades filtered by journal session and status."""
    try:
        active_trades = load_active_trades()

        # Filter by journal
        if journal_id:
            active_trades = [t for t in active_trades if getattr(t, "journal_id", "default") == journal_id]

        # Build response
        trades = []
        for trade in active_trades:
            if status in ("open", "all"):
                trade_dict = wrap_active_trade(trade, {}, 0.0)
                trades.append(trade_dict)

        return {
            "count": len(trades),
            "trades": trades
        }

    except Exception as e:
        logger.error(f"Error listing trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trades/open")
async def open_trade(req: TradeOpenRequest) -> Dict[str, Any]:
    """Record a newly opened paper trade."""
    try:
        # Validate journal exists
        session = get_session(req.journal_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Journal {req.journal_id} not found")

        # Add to session's trade list
        add_trade_to_session(req.journal_id, req.trade_id)

        # Append to TRADES.csv
        append_trade_csv(
            trade_id=req.trade_id,
            journal_id=req.journal_id,
            entry_data={
                "entry_date": req.entry_date,
                "entry_time_ist": req.entry_time_ist,
                "strategy": req.strategy,
                "vix": req.vix or 0,
                "regime": req.regime or "UNKNOWN",
                "ml_score": req.ml_score,
                "entry_price": 0.0,  # Will be filled from legs
                "lots": req.lots,
                "capital_deployed": req.capital_deployed,
                "strike": req.strike or 0,
                "expiry_dte": 0,  # Compute from dates
                "notes": req.notes
            }
        )

        return {
            "success": True,
            "trade_id": req.trade_id,
            "journal_id": req.journal_id,
            "message": f"Trade {req.trade_id} opened"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error opening trade: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/trades/{trade_id}/close")
async def close_trade_endpoint(
    trade_id: str,
    journal_id: Optional[str] = Query(None),
    req: Optional[TradeCloseRequest] = None
) -> Dict[str, Any]:
    """Close an open trade."""
    try:
        if not journal_id:
            raise HTTPException(status_code=400, detail="journal_id query parameter required")

        # Validate journal exists
        session = get_session(journal_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Journal {journal_id} not found")

        if not req:
            raise HTTPException(status_code=400, detail="Request body required with exit details")

        # Update TRADES.csv
        close_trade_csv(
            trade_id=trade_id,
            journal_id=journal_id,
            exit_data={
                "exit_date": date.today().isoformat(),
                "exit_time_ist": req.exit_time_ist,
                "exit_price": req.exit_price_per_unit,
                "exit_reason": req.exit_reason,
                "days_held": 0,  # Compute from entry date
                "gross_pnl": 0,
                "brokerage": req.brokerage,
                "slippage_bp": 0,
                "net_pnl": 0,
                "win_loss": "W",  # Determine from P&L
                "pnl_vs_max_profit_pct": 0,
                "backtest_deviation_pct": 0,
                "notes": req.notes
            }
        )

        return {
            "success": True,
            "trade_id": trade_id,
            "journal_id": journal_id,
            "message": f"Trade {trade_id} closed"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error closing trade: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Monitor Endpoint
# ============================================================================

@app.get("/monitor")
async def monitor_open_trades(journal_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Get exit recommendations for all open trades."""
    try:
        if _state["latest_row"] is None:
            raise RuntimeError("Market data not loaded")

        active_trades = load_active_trades()

        # Filter by journal
        if journal_id:
            active_trades = [t for t in active_trades if getattr(t, "journal_id", "default") == journal_id]

        exit_model = _state["models"].get("exit_model")
        if not exit_model:
            raise RuntimeError("Exit model not loaded")

        recommendations = []
        for trade in active_trades:
            try:
                rec = exit_model.analyze_trade(trade, _state["latest_row"])
                rec_dict = wrap_exit_recommendation(rec, trade.trade_id)
                recommendations.append(rec_dict)
            except Exception as e:
                logger.warning(f"Could not analyze trade {trade.trade_id}: {e}")

        return {
            "count": len(recommendations),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "recommendations": recommendations
        }

    except Exception as e:
        logger.error(f"Error monitoring trades: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Daily Log Endpoint
# ============================================================================

@app.post("/journal/daily-log")
async def log_daily_snapshot(req: DailyLogRequest) -> Dict[str, Any]:
    """Append daily account snapshot to DAILY_LOG.csv."""
    try:
        # Validate journal exists
        session = get_session(req.journal_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Journal {req.journal_id} not found")

        # Append to DAILY_LOG.csv
        append_daily_log(
            journal_id=req.journal_id,
            snapshot={
                "date": req.date or date.today().isoformat(),
                "account_equity": req.account_equity,
                "cumulative_pnl": req.cumulative_pnl,
                "open_trades_count": req.open_trades_count,
                "vix_close": req.vix_close,
                "market_regime": req.market_regime,
                "open_trades_weekly": req.open_trades_count,  # For Phase 1, all are weekly
                "win_rate_ytd_pct": req.win_rate_ytd_pct,
                "avg_trade_pnl_ytd": req.avg_trade_pnl_ytd,
                "account_dd_pct": req.account_dd_pct,
                "notes": req.notes
            }
        )

        return {
            "success": True,
            "date": req.date or date.today().isoformat(),
            "journal_id": req.journal_id,
            "message": "Daily snapshot logged"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging daily snapshot: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Market Refresh Endpoint
# ============================================================================

@app.post("/market/refresh")
async def refresh_market_data() -> Dict[str, Any]:
    """Force reload of market data cache."""
    try:
        logger.info("Refreshing market data...")
        market_fetcher = _state.get("market_fetcher")
        if not market_fetcher:
            market_fetcher = MarketDataFetcher(start_date=date(2009, 1, 1), end_date=date.today())
            _state["market_fetcher"] = market_fetcher

        _state["market_df"] = market_fetcher.build_combined_dataset()
        _state["latest_row"] = _state["market_df"].iloc[-1]

        latest_date = _state["latest_row"].get("date", date.today())
        num_rows = len(_state["market_df"])

        logger.info(f"✓ Market data refreshed: {num_rows} rows, latest date {latest_date}")

        return {
            "status": "refreshed",
            "latest_date": str(latest_date),
            "rows": num_rows
        }

    except Exception as e:
        logger.error(f"Error refreshing market data: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Simple health check."""
    return {
        "status": "healthy",
        "market_data_loaded": _state["latest_row"] is not None,
        "models_loaded": len(_state["models"]) > 0,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


# ============================================================================
# Helper Functions
# ============================================================================

def _infer_regime(vix: float) -> str:
    """Infer market regime from VIX level."""
    if vix < 14:
        return "VERY_LOW_VOL"
    elif vix < 18:
        return "LOW_VOL"
    elif vix < 22:
        return "NORMAL"
    elif vix < 28:
        return "ELEVATED"
    elif vix < 35:
        return "HIGH"
    else:
        return "CRISIS"


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
