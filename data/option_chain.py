"""
Live NSE Option Chain fetcher with OI analysis, liquidity scoring, and buildup detection.

Fetches real-time option chain data from NSE India for NIFTY index options.
Provides:
1. Live LTP, OI, volume, bid/ask for all strikes
2. OI buildup analysis (long buildup, short buildup, unwinding)
3. Liquidity scoring per strike
4. Max Pain calculation
5. PCR (Put-Call Ratio) analysis
6. Strike selection for liquid options only
"""

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests


NSE_BASE = "https://www.nseindia.com"
OPTION_CHAIN_URL = f"{NSE_BASE}/api/option-chain-indices?symbol=NIFTY"
GROWW_OC_URL = "https://groww.in/v1/api/option_chain_service/v1/option_chain/nifty"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Referer": "https://www.nseindia.com/option-chain",
}

MIN_OI_THRESHOLD = 50_000     # Minimum OI for a strike to be "liquid"
MIN_VOLUME_THRESHOLD = 5_000  # Minimum volume traded today
MIN_LOT_SIZE = 75             # Nifty lot size (75 as of 2025+)


@dataclass
class StrikeData:
    strike: int
    option_type: str  # "CE" or "PE"
    ltp: float
    bid: float
    ask: float
    oi: int
    oi_change: int
    volume: int
    iv: float
    expiry: str
    liquidity_score: float = 0.0
    buildup: str = ""  # "long_buildup", "short_buildup", "long_unwinding", "short_covering"


@dataclass
class OptionChainSnapshot:
    timestamp: str
    spot_price: float
    expiry_dates: list[str]
    selected_expiry: str
    calls: list[StrikeData] = field(default_factory=list)
    puts: list[StrikeData] = field(default_factory=list)
    pcr_oi: float = 0.0
    pcr_volume: float = 0.0
    max_pain: int = 0
    total_call_oi: int = 0
    total_put_oi: int = 0
    atm_strike: int = 0


class GrowwOptionChainFetcher:
    """
    Fetches option chain from Groww (works 24/7 with last-traded prices).
    Primary source — always returns data even after market hours.
    Limitation: returns nearest expiry only via option chain endpoint.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
        })

    def fetch(self, target_expiry: Optional[str] = None) -> Optional[OptionChainSnapshot]:
        try:
            resp = self.session.get(GROWW_OC_URL, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_groww(data, target_expiry)
        except Exception as e:
            print(f"  Groww fetch failed: {e}")
            return None

    def get_available_expiries(self) -> list[str]:
        try:
            resp = self.session.get(GROWW_OC_URL, timeout=10)
            data = resp.json()
            return data.get("optionChain", {}).get("expiryDetailsDto", {}).get("expiryDates", [])
        except Exception:
            return []

    def _parse_groww(self, data: dict, target_expiry: Optional[str]) -> OptionChainSnapshot:
        oc = data.get("optionChain", {})
        chains = oc.get("optionChains", [])
        expiry_info = oc.get("expiryDetailsDto", {})
        current_expiry = expiry_info.get("currentExpiry", "")
        expiry_dates = expiry_info.get("expiryDates", [])
        lot_size = expiry_info.get("expiryLotSize", 75)

        # Groww strike prices are in paise (multiply by 100). Divide by 100 to get actual.
        # Actually looking at the data: strikePrice=2010000 corresponds to 20100
        # So it's strikePrice / 100
        calls = []
        puts = []
        spot_estimate = 0.0

        for ch in chains:
            strike = ch.get("strikePrice", 0) / 100
            if strike <= 0:
                continue

            ce = ch.get("callOption", {})
            pe = ch.get("putOption", {})

            if ce:
                c_ltp = ce.get("ltp", 0)
                calls.append(StrikeData(
                    strike=int(strike),
                    option_type="CE",
                    ltp=c_ltp,
                    bid=0,  # Groww doesn't give bid/ask, use buy/sell qty as proxy
                    ask=0,
                    oi=ce.get("openInterest", 0),
                    oi_change=ce.get("openInterest", 0) - ce.get("prevOpenInterest", 0),
                    volume=ce.get("volume", 0),
                    iv=0,  # Groww doesn't return IV directly
                    expiry=current_expiry,
                ))

            if pe:
                p_ltp = pe.get("ltp", 0)
                puts.append(StrikeData(
                    strike=int(strike),
                    option_type="PE",
                    ltp=p_ltp,
                    bid=0,
                    ask=0,
                    oi=pe.get("openInterest", 0),
                    oi_change=pe.get("openInterest", 0) - pe.get("prevOpenInterest", 0),
                    volume=pe.get("volume", 0),
                    iv=0,
                    expiry=current_expiry,
                ))

        # Estimate spot from ATM call-put parity
        for c in calls:
            for p in puts:
                if c.strike == p.strike and c.ltp > 5 and p.ltp > 5:
                    est = c.strike + c.ltp - p.ltp
                    if abs(est - c.strike) < c.strike * 0.05:
                        spot_estimate = est
                        break
            if spot_estimate > 0:
                break

        if spot_estimate == 0:
            max_oi_ce = max(calls, key=lambda x: x.oi) if calls else None
            max_oi_pe = max(puts, key=lambda x: x.oi) if puts else None
            if max_oi_ce and max_oi_pe:
                spot_estimate = (max_oi_ce.strike + max_oi_pe.strike) / 2

        atm_strike = round(spot_estimate / 50) * 50

        self._score_liquidity(calls)
        self._score_liquidity(puts)
        self._detect_buildup(calls, is_call=True)
        self._detect_buildup(puts, is_call=False)

        total_call_oi = sum(c.oi for c in calls)
        total_put_oi = sum(p.oi for p in puts)
        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 0

        total_call_vol = sum(c.volume for c in calls)
        total_put_vol = sum(p.volume for p in puts)
        pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 0

        max_pain = self._calculate_max_pain(calls, puts, spot_estimate)

        nse_expiry_fmt = ""
        if current_expiry:
            try:
                from datetime import datetime as dt
                d = dt.strptime(current_expiry, "%Y-%m-%d")
                nse_expiry_fmt = d.strftime("%d-%b-%Y")
            except ValueError:
                nse_expiry_fmt = current_expiry

        return OptionChainSnapshot(
            timestamp=f"Groww (last traded)",
            spot_price=round(spot_estimate, 2),
            expiry_dates=[nse_expiry_fmt] if nse_expiry_fmt else expiry_dates,
            selected_expiry=nse_expiry_fmt or current_expiry,
            calls=calls,
            puts=puts,
            pcr_oi=round(pcr_oi, 3),
            pcr_volume=round(pcr_vol, 3),
            max_pain=max_pain,
            total_call_oi=total_call_oi,
            total_put_oi=total_put_oi,
            atm_strike=atm_strike,
        )

    def _score_liquidity(self, strikes: list[StrikeData]):
        if not strikes:
            return
        max_oi = max((s.oi for s in strikes), default=1)
        max_vol = max((s.volume for s in strikes), default=1)
        for s in strikes:
            oi_score = min(50, (s.oi / max(max_oi, 1)) * 50)
            vol_score = min(50, (s.volume / max(max_vol, 1)) * 50)
            s.liquidity_score = round(oi_score + vol_score, 1)

    def _detect_buildup(self, strikes: list[StrikeData], is_call: bool):
        for s in strikes:
            oi_up = s.oi_change > 0
            if is_call:
                if oi_up and s.ltp > 0:
                    s.buildup = "long_buildup" if s.ltp > 5 else "short_buildup"
                elif not oi_up:
                    s.buildup = "long_unwinding" if s.ltp > 5 else "short_covering"
                else:
                    s.buildup = "short_buildup"
            else:
                if oi_up and s.ltp > 0:
                    s.buildup = "long_buildup" if s.ltp > 5 else "short_buildup"
                elif not oi_up:
                    s.buildup = "long_unwinding" if s.ltp > 5 else "short_covering"
                else:
                    s.buildup = "short_buildup"

    def _calculate_max_pain(self, calls, puts, spot):
        strikes = sorted(set(c.strike for c in calls) | set(p.strike for p in puts))
        if not strikes:
            return round(spot / 50) * 50

        call_oi = {c.strike: c.oi for c in calls}
        put_oi = {p.strike: p.oi for p in puts}

        min_pain = float("inf")
        max_pain_strike = strikes[0]

        for test_strike in strikes:
            total_pain = 0
            for s in strikes:
                if s < test_strike:
                    total_pain += call_oi.get(s, 0) * (test_strike - s)
                elif s > test_strike:
                    total_pain += put_oi.get(s, 0) * (s - test_strike)
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = test_strike
        return max_pain_strike


class NSEOptionChainFetcher:
    """
    Fetches option chain data with live NSE prices.

    Strategy:
      1. NSE allIndices API → reliable live spot + VIX (no bot protection)
      2. Groww option chain → OI, strike prices, volumes (always available)
      3. NSE option chain API → attempted as bonus (often blocked by Akamai)

    The combined result gives live prices from NSE with full OI data from Groww.
    """

    NSE_INDICES_URL = f"{NSE_BASE}/api/allIndices"
    NSE_MARKET_STATUS_URL = f"{NSE_BASE}/api/marketStatus"

    def __init__(self, max_retries: int = 2):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.max_retries = max_retries
        self._cookies_set = False
        self._groww = GrowwOptionChainFetcher()

    def _init_session(self):
        """Hit NSE homepage to get session cookies."""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        try:
            self.session.get(NSE_BASE, timeout=10)
            self._cookies_set = True
        except Exception:
            self._cookies_set = False

    def _fetch_nse_live_prices(self) -> dict:
        """Fetch live spot/VIX from NSE allIndices (works reliably)."""
        _SIMPLE_HEADERS = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            s = requests.Session()
            s.headers.update(_SIMPLE_HEADERS)
            s.get(NSE_BASE, timeout=10)
            time.sleep(0.3)
            resp = s.get(self.NSE_INDICES_URL, timeout=10)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            result = {}
            for idx in data.get("data", []):
                sym = idx.get("indexSymbol", "")
                if sym == "NIFTY 50":
                    result["spot"] = idx.get("last", idx.get("lastPrice", 0))
                    result["nifty_change"] = idx.get("percentChange", 0)
                elif sym == "INDIA VIX":
                    result["vix"] = idx.get("last", idx.get("lastPrice", 0))
                elif sym == "NIFTY BANK":
                    result["bank_nifty"] = idx.get("last", idx.get("lastPrice", 0))
            return result
        except Exception:
            return {}

    def fetch(self, target_expiry: Optional[str] = None) -> Optional[OptionChainSnapshot]:
        """
        Fetch option chain with best available data.
        target_expiry: "DD-Mon-YYYY" format (e.g., "30-Apr-2026") or None for nearest.
        """
        # Step 1: Try full NSE option chain (may fail due to Akamai bot protection)
        snapshot = self._fetch_nse_option_chain(target_expiry)
        if snapshot and snapshot.calls:
            print("  Data source: NSE (live option chain)")
            return snapshot

        # Step 2: Use Groww for option chain + NSE for live prices
        snapshot = self._groww.fetch(target_expiry)
        if snapshot and snapshot.calls:
            nse_prices = self._fetch_nse_live_prices()
            if nse_prices.get("spot"):
                snapshot.spot_price = nse_prices["spot"]
                snapshot.atm_strike = round(nse_prices["spot"] / 50) * 50
                snapshot.timestamp = f"Groww OI + NSE live spot ({nse_prices['spot']:,.1f})"
                print(f"  Data source: NSE live prices + Groww option chain")
            else:
                print(f"  Data source: Groww (last traded prices)")
            return snapshot

        return None

    def _fetch_nse_option_chain(self, target_expiry: Optional[str]) -> Optional[OptionChainSnapshot]:
        if not self._cookies_set:
            self._init_session()
            time.sleep(0.5)

        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(OPTION_CHAIN_URL, timeout=15)
                if resp.status_code in (401, 403):
                    self._cookies_set = False
                    self._init_session()
                    time.sleep(1)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if not data or not data.get("records", {}).get("data"):
                    return None
                return self._parse_response(data, target_expiry)
            except Exception:
                self._cookies_set = False
                time.sleep(0.5)
        return None

    def _parse_response(self, data: dict, target_expiry: Optional[str]) -> OptionChainSnapshot:
        records = data.get("records", {})
        filtered = data.get("filtered", {})

        spot = records.get("underlyingValue", 0)
        expiry_dates = records.get("expiryDates", [])
        timestamp = records.get("timestamp", "")

        if target_expiry and target_expiry in expiry_dates:
            selected_expiry = target_expiry
        elif target_expiry:
            selected_expiry = self._find_closest_expiry(target_expiry, expiry_dates)
        else:
            selected_expiry = expiry_dates[0] if expiry_dates else ""

        atm_strike = round(spot / 50) * 50

        calls = []
        puts = []

        all_data = records.get("data", [])
        for row in all_data:
            if row.get("expiryDate") != selected_expiry:
                continue

            strike = row.get("strikePrice", 0)

            if "CE" in row:
                ce = row["CE"]
                calls.append(StrikeData(
                    strike=strike,
                    option_type="CE",
                    ltp=ce.get("lastPrice", 0),
                    bid=ce.get("bidprice", 0),
                    ask=ce.get("askPrice", 0),
                    oi=ce.get("openInterest", 0),
                    oi_change=ce.get("changeinOpenInterest", 0),
                    volume=ce.get("totalTradedVolume", 0),
                    iv=ce.get("impliedVolatility", 0),
                    expiry=selected_expiry,
                ))

            if "PE" in row:
                pe = row["PE"]
                puts.append(StrikeData(
                    strike=strike,
                    option_type="PE",
                    ltp=pe.get("lastPrice", 0),
                    bid=pe.get("bidprice", 0),
                    ask=pe.get("askPrice", 0),
                    oi=pe.get("openInterest", 0),
                    oi_change=pe.get("changeinOpenInterest", 0),
                    volume=pe.get("totalTradedVolume", 0),
                    iv=pe.get("impliedVolatility", 0),
                    expiry=selected_expiry,
                ))

        # Calculate liquidity scores and buildup
        self._score_liquidity(calls)
        self._score_liquidity(puts)
        self._detect_buildup(calls, is_call=True)
        self._detect_buildup(puts, is_call=False)

        total_call_oi = sum(c.oi for c in calls)
        total_put_oi = sum(p.oi for p in puts)

        f_ce = filtered.get("CE", {})
        f_pe = filtered.get("PE", {})
        total_call_vol = f_ce.get("totVol", sum(c.volume for c in calls))
        total_put_vol = f_pe.get("totVol", sum(p.volume for p in puts))

        pcr_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 0
        pcr_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 0

        max_pain = self._calculate_max_pain(calls, puts, spot)

        return OptionChainSnapshot(
            timestamp=timestamp,
            spot_price=spot,
            expiry_dates=expiry_dates,
            selected_expiry=selected_expiry,
            calls=calls,
            puts=puts,
            pcr_oi=round(pcr_oi, 3),
            pcr_volume=round(pcr_vol, 3),
            max_pain=max_pain,
            total_call_oi=total_call_oi,
            total_put_oi=total_put_oi,
            atm_strike=atm_strike,
        )

    def _find_closest_expiry(self, target: str, available: list[str]) -> str:
        """Find the closest expiry to the target date."""
        try:
            target_dt = datetime.strptime(target, "%d-%b-%Y")
        except ValueError:
            return available[0] if available else ""

        best = available[0] if available else ""
        best_diff = float("inf")
        for exp in available:
            try:
                exp_dt = datetime.strptime(exp, "%d-%b-%Y")
                diff = abs((exp_dt - target_dt).days)
                if diff < best_diff:
                    best_diff = diff
                    best = exp
            except ValueError:
                continue
        return best

    def _score_liquidity(self, strikes: list[StrikeData]):
        """Score each strike's liquidity (0-100)."""
        if not strikes:
            return

        max_oi = max(s.oi for s in strikes) if strikes else 1
        max_vol = max(s.volume for s in strikes) if strikes else 1

        for s in strikes:
            oi_score = min(40, (s.oi / max(max_oi, 1)) * 40)
            vol_score = min(30, (s.volume / max(max_vol, 1)) * 30)

            spread = abs(s.ask - s.bid) if s.ask > 0 and s.bid > 0 else 999
            spread_pct = spread / s.ltp if s.ltp > 0 else 1.0
            spread_score = max(0, 30 - spread_pct * 300)

            s.liquidity_score = round(oi_score + vol_score + spread_score, 1)

    def _detect_buildup(self, strikes: list[StrikeData], is_call: bool):
        """Detect OI buildup patterns."""
        for s in strikes:
            price_up = s.ltp > 0  # Simplification — we only have current snapshot
            oi_up = s.oi_change > 0

            if is_call:
                if oi_up and price_up:
                    s.buildup = "long_buildup"
                elif oi_up and not price_up:
                    s.buildup = "short_buildup"
                elif not oi_up and not price_up:
                    s.buildup = "long_unwinding"
                else:
                    s.buildup = "short_covering"
            else:
                if oi_up and price_up:
                    s.buildup = "long_buildup"
                elif oi_up and not price_up:
                    s.buildup = "short_buildup"
                elif not oi_up and not price_up:
                    s.buildup = "long_unwinding"
                else:
                    s.buildup = "short_covering"

    def _calculate_max_pain(
        self, calls: list[StrikeData], puts: list[StrikeData], spot: float
    ) -> int:
        """Calculate max pain strike — the price at which option writers lose the least."""
        strikes = sorted(set(c.strike for c in calls) | set(p.strike for p in puts))
        if not strikes:
            return round(spot / 50) * 50

        call_oi = {c.strike: c.oi for c in calls}
        put_oi = {p.strike: p.oi for p in puts}

        min_pain = float("inf")
        max_pain_strike = strikes[0]

        for test_strike in strikes:
            total_pain = 0
            for s in strikes:
                if s < test_strike:
                    total_pain += call_oi.get(s, 0) * (test_strike - s)
                elif s > test_strike:
                    total_pain += put_oi.get(s, 0) * (s - test_strike)
            if total_pain < min_pain:
                min_pain = total_pain
                max_pain_strike = test_strike

        return max_pain_strike


def find_liquid_strikes(
    snapshot: OptionChainSnapshot,
    spot: float,
    option_type: str,
    direction: str = "OTM",
    min_oi: int = MIN_OI_THRESHOLD,
    min_volume: int = MIN_VOLUME_THRESHOLD,
    min_liquidity_score: float = 20.0,
    max_strikes: int = 10,
) -> list[StrikeData]:
    """
    Find liquid strikes near a target area.
    direction: "OTM" (out-of-money), "ITM", or "ALL"
    """
    source = snapshot.calls if option_type == "CE" else snapshot.puts

    # Filter by liquidity
    liquid = [
        s for s in source
        if s.oi >= min_oi
        and s.volume >= min_volume
        and s.liquidity_score >= min_liquidity_score
    ]

    # Filter by moneyness
    if direction == "OTM":
        if option_type == "CE":
            liquid = [s for s in liquid if s.strike > spot]
        else:
            liquid = [s for s in liquid if s.strike < spot]
    elif direction == "ITM":
        if option_type == "CE":
            liquid = [s for s in liquid if s.strike < spot]
        else:
            liquid = [s for s in liquid if s.strike > spot]

    # Sort by distance from spot
    liquid.sort(key=lambda s: abs(s.strike - spot))
    return liquid[:max_strikes]


def find_best_iron_condor_strikes(
    snapshot: OptionChainSnapshot,
    spot: float,
    call_distance_pct: float = 0.03,
    put_distance_pct: float = 0.04,
    hedge_width: int = 1000,
    min_oi: int = MIN_OI_THRESHOLD // 2,
    min_volume: int = MIN_VOLUME_THRESHOLD // 2,
) -> Optional[dict]:
    """
    Find the best liquid strikes for an Iron Condor.
    Returns actual market prices, not theoretical.
    """
    target_sc = round((spot * (1 + call_distance_pct)) / 50) * 50
    target_sp = round((spot * (1 - put_distance_pct)) / 50) * 50
    target_lc = target_sc + hedge_width
    target_lp = target_sp - hedge_width

    def find_best_strike(
        strikes: list[StrikeData], target: int, tolerance: int = 500
    ) -> Optional[StrikeData]:
        """Find the most liquid strike near a target, within tolerance."""
        candidates = [
            s for s in strikes
            if abs(s.strike - target) <= tolerance
            and s.oi >= min_oi
        ]
        if not candidates:
            # Relax OI constraint
            candidates = [
                s for s in strikes
                if abs(s.strike - target) <= tolerance
                and s.ltp > 0
            ]
        if not candidates:
            return None
        # Prefer strike closest to target, tiebreak by liquidity
        candidates.sort(key=lambda s: (abs(s.strike - target), -s.liquidity_score))
        return candidates[0]

    sc = find_best_strike(snapshot.calls, target_sc)
    lc = find_best_strike(snapshot.calls, target_lc)
    sp = find_best_strike(snapshot.puts, target_sp)
    lp = find_best_strike(snapshot.puts, target_lp)

    if not all([sc, lc, sp, lp]):
        missing = []
        if not sc: missing.append(f"Short Call ~{target_sc}")
        if not lc: missing.append(f"Long Call ~{target_lc}")
        if not sp: missing.append(f"Short Put ~{target_sp}")
        if not lp: missing.append(f"Long Put ~{target_lp}")
        return {"error": f"No liquid strikes found for: {', '.join(missing)}"}

    call_credit = sc.ltp - lc.ltp
    put_credit = sp.ltp - lp.ltp
    net_credit = call_credit + put_credit

    call_width = lc.strike - sc.strike
    put_width = sp.strike - lp.strike
    max_loss = max(call_width, put_width) - net_credit

    return {
        "short_call": sc,
        "long_call": lc,
        "short_put": sp,
        "long_put": lp,
        "call_credit": round(call_credit, 2),
        "put_credit": round(put_credit, 2),
        "net_credit": round(net_credit, 2),
        "max_loss": round(max_loss, 2),
        "call_width": call_width,
        "put_width": put_width,
        "upper_breakeven": sc.strike + net_credit,
        "lower_breakeven": sp.strike - net_credit,
    }


def print_oi_analysis(snapshot: OptionChainSnapshot, spot: float, num_strikes: int = 8):
    """Print detailed OI analysis around the spot price."""
    atm = round(spot / 50) * 50
    range_start = atm - num_strikes * 50
    range_end = atm + num_strikes * 50

    call_map = {c.strike: c for c in snapshot.calls if range_start <= c.strike <= range_end}
    put_map = {p.strike: p for p in snapshot.puts if range_start <= p.strike <= range_end}

    all_strikes = sorted(set(call_map.keys()) | set(put_map.keys()))

    print(f"\n  {'='*110}")
    print(f"  OI ANALYSIS — Spot: {spot:,.2f} | Expiry: {snapshot.selected_expiry}")
    print(f"  {'='*110}")
    print(f"  {'CALL OI':>12} {'CALL Chg':>10} {'Call LTP':>10} {'Call IV':>8} {'Call Bld':>14}"
          f" | {'Strike':>8} | "
          f"{'Put Bld':<14} {'Put IV':>8} {'Put LTP':>10} {'PUT Chg':>10} {'PUT OI':>12}")
    print(f"  {'-'*110}")

    for strike in all_strikes:
        c = call_map.get(strike)
        p = put_map.get(strike)

        c_oi = f"{c.oi:>12,}" if c else f"{'—':>12}"
        c_chg = f"{c.oi_change:>+10,}" if c else f"{'—':>10}"
        c_ltp = f"₹{c.ltp:>8.1f}" if c else f"{'—':>10}"
        c_iv = f"{c.iv:>7.1f}%" if c and c.iv > 0 else f"{'—':>8}"
        c_bld = f"{c.buildup:>14}" if c else f"{'—':>14}"

        p_oi = f"{p.oi:>12,}" if p else f"{'—':>12}"
        p_chg = f"{p.oi_change:>+10,}" if p else f"{'—':>10}"
        p_ltp = f"₹{p.ltp:>8.1f}" if p else f"{'—':>10}"
        p_iv = f"{p.iv:>7.1f}%" if p and p.iv > 0 else f"{'—':>8}"
        p_bld = f"{p.buildup:<14}" if p else f"{'—':<14}"

        marker = " ◀ ATM" if strike == atm else ""
        print(f"  {c_oi} {c_chg} {c_ltp} {c_iv} {c_bld} | {strike:>8}{marker:6} | "
              f"{p_bld} {p_iv} {p_ltp} {p_chg} {p_oi}")

    print(f"\n  PCR (OI):     {snapshot.pcr_oi:.3f}")
    print(f"  PCR (Volume): {snapshot.pcr_volume:.3f}")
    print(f"  Max Pain:     {snapshot.max_pain:,}")
    print(f"  Total CE OI:  {snapshot.total_call_oi:,}")
    print(f"  Total PE OI:  {snapshot.total_put_oi:,}")

    # Highest OI strikes — support/resistance
    top_call_oi = sorted(snapshot.calls, key=lambda c: c.oi, reverse=True)[:3]
    top_put_oi = sorted(snapshot.puts, key=lambda p: p.oi, reverse=True)[:3]

    print(f"\n  KEY SUPPORT (highest Put OI — writers defend these):")
    for p in top_put_oi:
        print(f"    {p.strike:>8} PE  OI: {p.oi:>12,}  Change: {p.oi_change:>+10,}  [{p.buildup}]")

    print(f"\n  KEY RESISTANCE (highest Call OI — writers defend these):")
    for c in top_call_oi:
        print(f"    {c.strike:>8} CE  OI: {c.oi:>12,}  Change: {c.oi_change:>+10,}  [{c.buildup}]")
