#!/usr/bin/env python3
"""
Full end-to-end diagnostic for Fyers live price integration.
Run this during market hours to trace exactly what's happening.
"""

import os, sys
from pathlib import Path
from datetime import datetime as _dt

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(override=True)

print("=" * 70)
print("FYERS LIVE PRICE DIAGNOSTIC")
print("=" * 70)

# ── Step 1: Token ──────────────────────────────────────────────────────────
print("\n[1] Token status")
from fyers_apiv3 import fyersModel
client_id = os.getenv("FYERS_CLIENT_ID")
token = os.getenv("FYERS_ACCESS_TOKEN")
print(f"  Client ID : {client_id}")
print(f"  Token     : {token[:40]}...")

fyers = fyersModel.FyersModel(client_id=client_id, token=token, log_path="")

# ── Step 2: Spot and VIX ───────────────────────────────────────────────────
print("\n[2] Spot / VIX quotes")
r = fyers.quotes(data={"symbols": "NSE:NIFTY50-INDEX,NSE:INDIAVIX-INDEX"})
print(f"  API status: {r.get('s')}")
if r.get("s") != "ok":
    print(f"  ERROR: {r}")
    print("\n  *** TOKEN IS INVALID — regenerate with: python scripts/generate_fyers_token.py ***")
    sys.exit(1)

for item in r.get("d", []):
    print(f"  {item['n']}: lp={item['v'].get('lp')}")

# ── Step 3: Trade legs ─────────────────────────────────────────────────────
print("\n[3] Active trade legs")
from models.trade_monitor import load_active_trades
trades = load_active_trades()
if not trades:
    print("  No active trades found in data/.cache/active_trades.json")
    sys.exit(1)

for trade in trades:
    print(f"  Trade: {trade.trade_id}  expiry: {trade.expiry_date}")
    for leg in trade.get_legs():
        print(f"    {leg.action} {leg.strike} {leg.option_type} @ entry ₹{leg.entry_price}")

# ── Step 4: Build symbols ──────────────────────────────────────────────────
print("\n[4] Fyers option symbols")
from data.fyers_live_data import FyersLiveDataClient

MONTH_CODES = {
    1:'JAN',2:'FEB',3:'MAR',4:'APR',5:'MAY',6:'JUN',
    7:'JUL',8:'AUG',9:'SEP',10:'OCT',11:'NOV',12:'DEC'
}

def make_symbol(strike, opt_type, expiry_str):
    d = _dt.strptime(expiry_str, "%Y-%m-%d")
    yy = str(d.year)[-2:]
    mon = MONTH_CODES[d.month]
    day = str(d.day).zfill(2)
    return f"NSE:NIFTY{yy}{mon}{day}{int(strike)}{opt_type}-FO"

symbols = []
for trade in trades:
    for leg in trade.get_legs():
        sym = make_symbol(leg.strike, leg.option_type, trade.expiry_date)
        symbols.append(sym)
        print(f"  {sym}")

# ── Step 5: Fetch option quotes ────────────────────────────────────────────
print("\n[5] Fyers option quotes")
r2 = fyers.quotes(data={"symbols": ",".join(symbols)})
print(f"  API status: {r2.get('s')}")
if r2.get("s") != "ok":
    print(f"  ERROR: {r2}")
    sys.exit(1)

print(f"  Items returned: {len(r2.get('d', []))}")
for item in r2.get("d", []):
    sym = item["n"]
    v = item["v"]
    lp  = v.get("lp", "MISSING")
    bid = v.get("bid", "MISSING")
    ask = v.get("ask", "MISSING")
    oi  = v.get("oi", "MISSING")
    vol = v.get("volume", "MISSING")
    print(f"  {sym}")
    print(f"    lp={lp}  bid={bid}  ask={ask}  oi={oi}  vol={vol}")
    if lp == 0 or lp == "MISSING":
        print(f"    *** WARNING: LTP is {lp}! Full dict keys: {list(v.keys())}")

# ── Step 6: Simulate analyze_trade lookup ──────────────────────────────────
print("\n[6] Simulating analyze_trade lookup")
_live_ltp = {}
for item in r2.get("d", []):
    sym = item["n"]
    ltp = item["v"].get("lp", 0)
    # Find matching leg info
    for trade in trades:
        for leg in trade.get_legs():
            if sym == make_symbol(leg.strike, leg.option_type, trade.expiry_date):
                # Store with int key (same as snapshot code)
                _live_ltp[(int(leg.strike), leg.option_type)] = ltp
                print(f"  Stored key=({int(leg.strike)}, '{leg.option_type}') ltp={ltp}")

print()
for trade in trades:
    for leg in trade.get_legs():
        # Exact lookup the way analyze_trade does it
        found_float = _live_ltp.get((leg.strike, leg.option_type))
        found_int   = _live_ltp.get((int(leg.strike), leg.option_type))
        found_any   = found_float or found_int
        print(f"  {leg.action} {leg.strike} {leg.option_type}:")
        print(f"    float key lookup -> {found_float}")
        print(f"    int   key lookup -> {found_int}")
        print(f"    will use LIVE? -> {'YES ✓' if found_any and found_any > 0 else 'NO ✗ (falls back to BS)'}")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
