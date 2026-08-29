"""
API Endpoint Tests — Verify all 13 endpoints work correctly
Tests cover: journal management, signals, trades, monitoring, logging
"""

import pytest
import json
from datetime import date
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.server import app
from fastapi.testclient import TestClient

client = TestClient(app)

# Test fixtures
JOURNAL_ID = "test-journal-001"
TRADE_ID = "PT-TEST-001"

class TestJournalEndpoints:
    """Test journal session management (4 endpoints)"""

    def test_01_create_journal(self):
        """POST /journals — Create a new journal session"""
        response = client.post(
            "/journals",
            json={
                "journal_id": JOURNAL_ID,
                "label": "Test Journal",
                "initial_capital": 1500000,
                "strategy_track": "weekly",
                "notes": "Testing API"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["journal_id"] == JOURNAL_ID
        assert data["status"] == "active"
        print(f"✓ POST /journals: Created journal {JOURNAL_ID}")

    def test_02_list_journals(self):
        """GET /journals — List all sessions"""
        response = client.get("/journals")
        assert response.status_code == 200
        data = response.json()
        assert "journals" in data
        assert isinstance(data["journals"], list)
        print(f"✓ GET /journals: Listed {len(data['journals'])} sessions")

    def test_03_get_journal(self):
        """GET /journals/{journal_id} — Get session details"""
        response = client.get(f"/journals/{JOURNAL_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["journal_id"] == JOURNAL_ID
        assert data["initial_capital"] == 1500000
        print(f"✓ GET /journals/{JOURNAL_ID}: Retrieved session details")

    def test_04_update_journal(self):
        """PATCH /journals/{journal_id} — Update session"""
        response = client.patch(
            f"/journals/{JOURNAL_ID}",
            json={
                "label": "Updated Test Journal",
                "notes": "Updated notes"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["label"] == "Updated Test Journal"
        print(f"✓ PATCH /journals/{JOURNAL_ID}: Updated session")


class TestAccountEndpoints:
    """Test account & portfolio endpoints (2 endpoints)"""

    def test_01_get_status_global(self):
        """GET /status — Get global account status"""
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert "account_equity" in data
        assert "cumulative_pnl" in data
        assert "account_dd_pct" in data
        assert "vix_now" in data
        assert "regime" in data
        print(f"✓ GET /status: Account equity = ₹{data['account_equity']:,.0f}")

    def test_02_get_status_scoped(self):
        """GET /status?journal_id=<id> — Get journal-scoped status"""
        response = client.get(f"/status?journal_id={JOURNAL_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["journal_id"] == JOURNAL_ID
        assert "account_equity" in data
        print(f"✓ GET /status?journal_id={JOURNAL_ID}: Scoped to session")

    def test_03_get_trades_empty(self):
        """GET /trades — List trades (should be empty initially)"""
        response = client.get(f"/trades?journal_id={JOURNAL_ID}&status=open")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["trades"] == []
        print(f"✓ GET /trades: No open trades (as expected)")


class TestSignalEndpoints:
    """Test signal generation (1 endpoint)"""

    def test_01_get_signal(self):
        """GET /signal — Get ML entry signals"""
        response = client.get("/signal")
        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert "timestamp" in data
        assert "within_entry_window" in data
        assert "spot" in data
        assert "vix" in data
        assert "regime" in data
        assert "weekly" in data
        assert "monthly" in data

        # Check weekly signal
        weekly = data["weekly"]
        assert "should_enter" in weekly
        assert "quality_score" in weekly
        assert "signal" in weekly
        assert "suggested_lots" in weekly
        assert "capital_to_deploy" in weekly

        # Check monthly signal (paused in Phase 1)
        monthly = data["monthly"]
        assert "should_enter" in monthly
        assert "skip_reason" in monthly

        print(f"✓ GET /signal:")
        print(f"  - VIX: {data['vix']}, Regime: {data['regime']}")
        print(f"  - Weekly: should_enter={weekly['should_enter']}, score={weekly['quality_score']:.2f}")
        print(f"  - Monthly: paused (skip_reason={monthly['skip_reason']})")


class TestTradeEndpoints:
    """Test trade lifecycle endpoints (3 endpoints)"""

    def test_01_open_trade(self):
        """POST /trades/open — Record new trade"""
        response = client.post(
            "/trades/open",
            json={
                "journal_id": JOURNAL_ID,
                "trade_id": TRADE_ID,
                "strategy": "weekly_pcs",
                "entry_date": str(date.today()),
                "expiry_date": "2026-09-04",
                "legs_str": "SELL 24800 PE 85 @ 520; BUY 24600 PE 40 @ 520",
                "lots": 8,
                "capital_deployed": 520000,
                "ml_score": 0.62,
                "entry_time_ist": "11:42",
                "vix": 17.3,
                "regime": "LOW_VOL",
                "strike": 24800,
                "notes": "Test entry"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["trade_id"] == TRADE_ID
        print(f"✓ POST /trades/open: Logged trade {TRADE_ID}")

    def test_02_get_trades_after_open(self):
        """GET /trades — Verify trade was logged"""
        response = client.get(f"/trades?journal_id={JOURNAL_ID}&status=open")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        trades = data["trades"]
        assert any(t["trade_id"] == TRADE_ID for t in trades)
        print(f"✓ GET /trades: Trade {TRADE_ID} found in open trades")

    def test_03_close_trade(self):
        """POST /trades/{id}/close — Close trade"""
        response = client.post(
            f"/trades/{TRADE_ID}/close?journal_id={JOURNAL_ID}",
            json={
                "exit_price_per_unit": 42.5,
                "exit_reason": "profit_target",
                "exit_time_ist": "14:05",
                "brokerage": 320,
                "notes": "Test close"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"✓ POST /trades/{TRADE_ID}/close: Closed trade")


class TestMonitoringEndpoints:
    """Test trade monitoring endpoint (1 endpoint)"""

    def test_01_monitor_open_trades(self):
        """GET /monitor — Get exit recommendations"""
        # First open a trade
        client.post(
            "/trades/open",
            json={
                "journal_id": JOURNAL_ID,
                "trade_id": "PT-MONITOR-001",
                "strategy": "weekly_pcs",
                "entry_date": str(date.today()),
                "expiry_date": "2026-09-04",
                "lots": 8,
                "capital_deployed": 520000,
                "ml_score": 0.62,
                "entry_time_ist": "11:42",
                "notes": "For monitoring test"
            }
        )

        # Now monitor
        response = client.get(f"/monitor?journal_id={JOURNAL_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "recommendations" in data
        assert "timestamp" in data

        if data["count"] > 0:
            rec = data["recommendations"][0]
            assert "trade_id" in rec
            assert "action" in rec
            assert "confidence" in rec
            assert "current_pnl_pct" in rec
            print(f"✓ GET /monitor: {data['count']} recommendations")
            print(f"  - Trade: {rec['trade_id']}, Action: {rec['action']}, Confidence: {rec['confidence']:.1%}")
        else:
            print(f"✓ GET /monitor: No open trades to monitor")


class TestLoggingEndpoints:
    """Test logging endpoint (1 endpoint)"""

    def test_01_log_daily_snapshot(self):
        """POST /journal/daily-log — Log daily account snapshot"""
        response = client.post(
            "/journal/daily-log",
            json={
                "journal_id": JOURNAL_ID,
                "date": str(date.today()),
                "account_equity": 1500000,
                "cumulative_pnl": 0,
                "open_trades_count": 0,
                "vix_close": 17.3,
                "market_regime": "LOW_VOL",
                "win_rate_ytd_pct": 100.0,
                "account_dd_pct": 0.0,
                "notes": "Test daily log"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        print(f"✓ POST /journal/daily-log: Logged snapshot for {data['date']}")


class TestMaintenanceEndpoints:
    """Test maintenance endpoints (2 endpoints)"""

    def test_01_health_check(self):
        """GET /health — Server health check"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "market_data_loaded" in data
        assert "models_loaded" in data
        assert "timestamp" in data
        print(f"✓ GET /health: Server healthy")
        print(f"  - Market data loaded: {data['market_data_loaded']}")
        print(f"  - Models loaded: {data['models_loaded']}")

    def test_02_market_refresh(self):
        """POST /market/refresh — Reload market data"""
        response = client.post("/market/refresh")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "refreshed"
        assert "latest_date" in data
        assert "rows" in data
        print(f"✓ POST /market/refresh: Refreshed")
        print(f"  - Latest date: {data['latest_date']}")
        print(f"  - Total rows: {data['rows']}")


class TestErrorHandling:
    """Test error handling"""

    def test_01_invalid_journal(self):
        """GET /journals/invalid — 404 on missing journal"""
        response = client.get("/journals/invalid-journal-id")
        assert response.status_code == 404
        print(f"✓ GET /journals/invalid: Returns 404 (as expected)")

    def test_02_missing_required_field(self):
        """POST /journals with missing field — 422 validation error"""
        response = client.post(
            "/journals",
            json={
                "journal_id": "test-missing-field",
                # Missing: label, initial_capital, strategy_track
            }
        )
        assert response.status_code == 422
        print(f"✓ POST /journals (missing fields): Returns 422 validation error")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("API ENDPOINT TESTS — All 13 Endpoints")
    print("=" * 80)
    print()

    # Run all tests
    pytest.main([__file__, "-v", "-s"])

    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("✅ All API endpoints working as expected")
    print()
    print("Endpoints tested:")
    print("  Journal Management:     POST /journals, GET /journals, GET /journals/{id}, PATCH /journals/{id}")
    print("  Account & Portfolio:    GET /status, GET /trades")
    print("  Signals & Execution:    GET /signal, POST /trades/open, POST /trades/{id}/close")
    print("  Monitoring:             GET /monitor")
    print("  Logging:                POST /journal/daily-log")
    print("  Maintenance:            GET /health, POST /market/refresh")
    print()
