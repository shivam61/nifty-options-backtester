"""
News sentiment scorer for market analysis.
Uses keyword-based NLP to score financial news headlines.

This module provides:
1. Keyword-based sentiment scoring of financial headlines
2. Geopolitical risk scoring
3. Macro event classification
4. Historical sentiment tracking via price-action proxies
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


NEGATIVE_KEYWORDS = {
    # Geopolitical — high impact
    "war": -3, "strike": -2, "attack": -3, "bomb": -3, "missile": -2,
    "invasion": -3, "conflict": -2, "escalation": -2, "sanctions": -2,
    "nuclear": -3, "military": -1, "troops": -1, "ceasefire rejected": -2,
    "deadline": -1, "ultimatum": -2, "threat": -1, "retaliation": -2,

    # Economic negative
    "recession": -3, "stagflation": -2, "inflation surge": -2, "rate hike": -1,
    "downgrade": -2, "default": -3, "crash": -2, "collapse": -3,
    "sell-off": -2, "selloff": -2, "plunge": -2, "tumble": -2,
    "bear market": -2, "correction": -1, "slump": -2,

    # India specific
    "fii selling": -2, "fpi outflow": -2, "rupee fall": -1, "rupee weak": -1,
    "oil spike": -2, "crude surge": -2, "trade deficit": -1,

    # Market structure
    "margin call": -2, "liquidity crisis": -3, "circuit breaker": -2,
    "halt": -1, "volatility spike": -1,
}

POSITIVE_KEYWORDS = {
    # Geopolitical — resolution
    "ceasefire": 3, "peace": 2, "deal": 2, "agreement": 2,
    "truce": 2, "de-escalation": 2, "diplomatic": 1, "resolution": 2,
    "withdraw": 1, "treaty": 2,

    # Economic positive
    "rate cut": 2, "stimulus": 2, "growth": 1, "recovery": 2,
    "rally": 1, "surge": 1, "boom": 1, "upgrade": 2,
    "bull market": 2, "all-time high": 1, "breakout": 1,

    # India specific
    "fii buying": 2, "fpi inflow": 2, "rupee strong": 1, "rupee gain": 1,
    "reform": 1, "budget positive": 1, "rbi dovish": 2,
    "monsoon normal": 1, "gdp growth": 1,

    # Market structure
    "liquidity": 1, "stability": 1, "confidence": 1,
}

MACRO_EVENT_PATTERNS = {
    "rbi_policy": ["rbi", "monetary policy", "repo rate", "mpc"],
    "us_fed": ["fed", "fomc", "powell", "federal reserve", "rate decision"],
    "oil_crisis": ["oil", "crude", "opec", "strait of hormuz", "oil price"],
    "geopolitical": ["war", "iran", "china", "russia", "conflict", "military"],
    "earnings": ["earnings", "quarterly results", "profit", "revenue"],
    "election": ["election", "vote", "poll", "government"],
    "trade_war": ["tariff", "trade war", "trade deal", "sanctions"],
}


@dataclass
class SentimentScore:
    score: float           # -1.0 to +1.0
    magnitude: float       # 0.0 to 1.0 (strength)
    category: str          # "geopolitical", "economic", "market", "neutral"
    key_factors: list[str]
    risk_events: list[str]


def score_headline(headline: str) -> SentimentScore:
    """Score a single news headline."""
    text = headline.lower()
    total_score = 0
    factors = []
    events = []

    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if keyword in text:
            total_score += weight
            factors.append(f"{keyword} ({weight})")

    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword in text:
            total_score += weight
            factors.append(f"{keyword} (+{weight})")

    for event_type, patterns in MACRO_EVENT_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                events.append(event_type)
                break

    max_possible = 10
    normalized = max(-1.0, min(1.0, total_score / max_possible))
    magnitude = min(1.0, abs(total_score) / max_possible)

    if any(e in events for e in ["geopolitical", "trade_war"]):
        category = "geopolitical"
    elif any(e in events for e in ["rbi_policy", "us_fed", "oil_crisis"]):
        category = "economic"
    elif factors:
        category = "market"
    else:
        category = "neutral"

    return SentimentScore(
        score=normalized,
        magnitude=magnitude,
        category=category,
        key_factors=factors[:5],
        risk_events=list(set(events)),
    )


def score_headlines(headlines: list[str]) -> SentimentScore:
    """Score multiple headlines and aggregate."""
    if not headlines:
        return SentimentScore(0, 0, "neutral", [], [])

    scores = [score_headline(h) for h in headlines]
    avg_score = np.mean([s.score for s in scores])
    max_magnitude = max(s.magnitude for s in scores)

    all_factors = []
    all_events = []
    for s in scores:
        all_factors.extend(s.key_factors)
        all_events.extend(s.risk_events)

    categories = [s.category for s in scores if s.category != "neutral"]
    category = max(set(categories), key=categories.count) if categories else "neutral"

    return SentimentScore(
        score=round(avg_score, 3),
        magnitude=round(max_magnitude, 3),
        category=category,
        key_factors=list(set(all_factors))[:8],
        risk_events=list(set(all_events)),
    )


def compute_price_action_sentiment(data: pd.DataFrame) -> pd.Series:
    """
    Derive a sentiment proxy from price action when news data isn't available.
    Uses cross-asset signals as a proxy for market sentiment.

    High sentiment = markets calm, risk-on
    Low sentiment = markets stressed, risk-off
    """
    sentiment = pd.Series(0.0, index=data.index)

    # Component 1: VIX level relative to mean (inverted — low VIX = positive sentiment)
    if "vix" in data.columns:
        vix = data["vix"].fillna(15)
        vix_mean = vix.rolling(50, min_periods=10).mean()
        vix_component = -(vix - vix_mean) / vix_mean.replace(0, 1)
        sentiment += vix_component.fillna(0) * 0.3

    # Component 2: Nifty momentum (positive returns = positive sentiment)
    if "nifty_return_5d" in data.columns:
        sentiment += data["nifty_return_5d"].fillna(0).clip(-0.05, 0.05) * 4.0 * 0.2

    # Component 3: Crude oil stress (rising crude = negative for India)
    if "crude_change_5d" in data.columns:
        sentiment -= data["crude_change_5d"].fillna(0).clip(-0.1, 0.1) * 2.0 * 0.15

    # Component 4: Rupee stress (weakening rupee = negative)
    if "usdinr_change_5d" in data.columns:
        sentiment -= data["usdinr_change_5d"].fillna(0).clip(-0.03, 0.03) * 5.0 * 0.1

    # Component 5: US VIX correlation (global risk)
    if "us_vix_change_5d" in data.columns:
        sentiment -= data["us_vix_change_5d"].fillna(0).clip(-0.3, 0.3) * 0.5 * 0.1

    # Component 6: Gold as safe haven signal (rising gold = fear)
    if "gold_change_5d" in data.columns:
        sentiment -= data["gold_change_5d"].fillna(0).clip(-0.05, 0.05) * 2.0 * 0.1

    # Component 7: S&P 500 alignment (global equity mood)
    if "sp500_return_5d" in data.columns:
        sentiment += data["sp500_return_5d"].fillna(0).clip(-0.05, 0.05) * 2.0 * 0.05

    return sentiment.clip(-1.0, 1.0)


def compute_geopolitical_risk_index(data: pd.DataFrame) -> pd.Series:
    """
    Compute a geopolitical risk proxy from market data.
    Spikes in crude + gold + VIX + rupee weakness simultaneously = geopolitical event.
    """
    risk = pd.Series(0.0, index=data.index)

    if "crude_change_5d" in data.columns:
        crude_stress = data["crude_change_5d"].fillna(0).clip(0, 0.2) * 5
        risk += crude_stress * 0.3

    if "gold_change_5d" in data.columns:
        gold_stress = data["gold_change_5d"].fillna(0).clip(0, 0.1) * 10
        risk += gold_stress * 0.2

    if "vix_change_5d" in data.columns:
        vix_stress = data["vix_change_5d"].fillna(0).clip(0, 0.5) * 2
        risk += vix_stress * 0.3

    if "usdinr_change_5d" in data.columns:
        inr_stress = data["usdinr_change_5d"].fillna(0).clip(0, 0.03) * 33
        risk += inr_stress * 0.2

    return risk.clip(0, 1.0)
