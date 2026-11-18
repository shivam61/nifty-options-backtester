"""Candidate families A and B, as pre-registered in docs/preregistration_candidates.md (Sections 2-5).

A  put credit spread (PCS_A_*): sell 1 PE at K_s, buy 1 PE at K_s - W. Gate 16.0 <= VIX_S < 25.0.
B  long strangle (LS_B_*):      buy 1 CE and 1 PE, no short legs. Gate VIX_S < 13.0.

This module holds the specification and pure helpers only (cells, windows, strike targets, expiry
selection, skip reasons, harness projection). The simulation itself runs inside
backtester.chain_engine.ChainBacktest when ChainConfig.candidate is set.

Conventions (all from the pre-registration):
  signal day S    weekly expiry day; VIX read at S close
  fill day F      next session after S; strikes and prices at F EOD settle
  DTE             calendar days from F to the target expiry (as elsewhere in the chain engine)
  sigma_T         spot_F * (VIX_S / 100) * sqrt(DTE / 252)
  strike rule     target = spot_F -/+ k * sigma_T, snapped to the nearest listed strike (engine _snap)
  weekly window   DTE in [3, 8]
  monthly window  monthly expiry with DTE in [15, 28], closest to 21 (B only)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

import numpy as np
import pandas as pd

PCS = "put_credit_spread"
LS = "long_strangle"
CALL_CREDIT_SPREAD = "call_credit_spread"   # step 0: short CE at spot + k sigma_T, long CE W above it
IRON_CONDOR = "iron_condor"                 # step 0: PCS and CCS together, equal wings W (defined max loss)
# Round 3 (Section 4 item 4): one spread, chosen at fill from NIFTY close_S vs SMA(close up to S): PCS if above, else CCS.
TREND_SPREAD = "trend_spread"

CREDIT_STRUCTURES = (PCS, CALL_CREDIT_SPREAD, IRON_CONDOR, TREND_SPREAD)
KNOWN_STRUCTURES = CREDIT_STRUCTURES + (LS,)
CADENCES = ("weekly", "monthly")
STRIKE_BASIS_FILL_CLOSE = "fill_close"
STRIKE_BASIS_SIGNAL_CLOSE = "signal_close"
STRIKE_BASES = (STRIKE_BASIS_FILL_CLOSE, STRIKE_BASIS_SIGNAL_CLOSE)
MAX_LOSS_BASIS_SETTLE = "settle"
MAX_LOSS_BASIS_FILL_PLUS_FEES = "fill_plus_fees"
MAX_LOSS_BASES = (MAX_LOSS_BASIS_SETTLE, MAX_LOSS_BASIS_FILL_PLUS_FEES)

WEEKLY_DTE_WINDOW = (3, 8)
MONTHLY_DTE_WINDOW = (15, 28)
MONTHLY_DTE_TARGET = 21
TRADING_DAYS_PER_YEAR = 252
RV_WINDOW = 20   # round 2 (Section 3): RV20 uses the last 20 close-to-close log returns

# Skip reasons specific to the candidate path. Counted in ChainBacktest.skips.
# "expiry_after_end" is not named in the pre-registration. A trade whose expiry falls after the window end
# cannot settle inside the window, so it is not opened. This interpretation is flagged in the report.
# "entry_filter" is the opt-in ChainConfig.candidate_entry_filter hook (default: no filter, never counted).
# "zero_contract_leg" is opt-in ChainConfig.skip_zero_contract_legs (round 2, Section 11.1): any entry leg with
# 0 contracts traded on the fill day skips the whole trade. Default off, never counted.
CANDIDATE_SKIP_REASONS = (
    "vix_out_of_band", "position_open", "no_expiry_in_window", "expiry_after_end", "no_listed_strike",
    "no_price", "missing_data", "invalid_structure", "non_positive_credit", "invalid_max_loss",
    "sizing_zero", "kill_switch", "entry_filter", "zero_contract_leg",
)

# Phase windows (pre-registration Section 7). The holdout end is set at the time of the look.
PHASE_WINDOWS = {
    "train": (date(2019, 2, 11), date(2021, 12, 31)),
    "test": (date(2022, 1, 1), date(2023, 12, 31)),
    "holdout": (date(2024, 1, 1), None),
}


@dataclass(frozen=True)
class CandidateSpec:
    cell_id: str
    family: str               # "A", "B", or a later round's label (C, D, E, ...)
    structure: str            # PCS, LS, CALL_CREDIT_SPREAD or IRON_CONDOR
    k: float                  # strike distance in sigma_T units
    width: Optional[float]    # credit structures and wings: long-wing width W in index points; LS: None
    cadence: str              # "weekly" or "monthly" (monthly is declared for B only)
    vix_lo: float             # gate: inclusive lower bound
    vix_hi: float             # gate: exclusive upper bound
    # Exit rules (step 0, opt-in). Checked on each session's EOD settle marks while the trade is open.
    # profit_target_pct: close when mark-to-market gain >= this percent of the entry credit (50.0 = 50%).
    # stop_loss_x: close when mark-to-market loss >= this multiple of the entry credit (2.0 = 2x credit).
    # None (default) holds to expiry. Credit structures only.
    profit_target_pct: Optional[float] = None
    stop_loss_x: Optional[float] = None
    # Round 2 (Section 3): entry only when VIX_S - RV20_S >= rv20_gap_min (vol points). RV20 uses NIFTY closes up
    # to and including S. None (default) applies no realised-vol gate. Enforced by the chain engine.
    rv20_gap_min: Optional[float] = None
    # Round 3 (opt-in; all None/False leaves every output unchanged). Entry filters read data dated on or before S only.
    # spike_level / spike_drop_pct (Section 4 item 2): pass only if max VIX over the 20 sessions up to and including S
    # is >= spike_level AND VIX_S <= (1 - spike_drop_pct) x that max. Set together.
    spike_level: Optional[float] = None
    spike_drop_pct: Optional[float] = None
    # term_structure_gate (Section 4 item 3): pass only if the ATM-straddle implied-move proxy of the nearest weekly
    # expiry is <= that of the nearest monthly expiry (contango), both read from the archive settles on S.
    term_structure_gate: bool = False
    # trend_sma_days (TREND_SPREAD only, Section 4 item 4): SMA window of NIFTY closes up to and including S.
    trend_sma_days: Optional[int] = None
    # monthly_signal (cadence='monthly' only, round 3 Section 4 item 1): signal ON the monthly expiry day, then fill the
    # next session and target the monthly expiry. False keeps the round-1 family B meaning of cadence='monthly':
    # signal on every weekly expiry day, target the monthly expiry (LS_B_*_mo, pre-registered, unchanged).
    monthly_signal: bool = False
    # strike_basis (audit fix 1, opt-in): which NIFTY close sizes sigma_T and the strike targets. 'fill_close' (default)
    # uses the F-day close (historical). 'signal_close' uses the S-day close, known at entry. Legs are still priced at
    # F settle and DTE / expiry selection is still taken from F.
    strike_basis: str = STRIKE_BASIS_FILL_CLOSE
    # max_loss_basis (audit fix 2, opt-in, credit structures only): 'settle' (default) keeps W - net credit on the F
    # settle basis. 'fill_plus_fees' uses W - net credit at the fill price (after entry slippage) plus round-trip fees
    # (see fill_basis_max_loss_unit). Used for sizing and for max_loss_rs. Debit structures are unaffected.
    max_loss_basis: str = MAX_LOSS_BASIS_SETTLE

    def __post_init__(self) -> None:
        if self.strike_basis not in STRIKE_BASES:
            raise ValueError(f"strike_basis must be one of {STRIKE_BASES}")
        if self.max_loss_basis not in MAX_LOSS_BASES:
            raise ValueError(f"max_loss_basis must be one of {MAX_LOSS_BASES}")
        if self.max_loss_basis != MAX_LOSS_BASIS_SETTLE and self.structure not in CREDIT_STRUCTURES:
            raise ValueError("max_loss_basis other than 'settle' applies to credit structures only")
        if self.rv20_gap_min is not None and not math.isfinite(self.rv20_gap_min):
            raise ValueError("rv20_gap_min must be finite (vol points)")
        if self.structure not in KNOWN_STRUCTURES:
            raise ValueError(f"unknown structure {self.structure!r}")
        if self.cadence not in CADENCES:
            raise ValueError(f"cadence must be one of {CADENCES}")
        if not (math.isfinite(self.k) and self.k > 0):
            raise ValueError("k must be a positive finite multiple of sigma_T")
        if self.structure in CREDIT_STRUCTURES and not (
                self.width is not None and math.isfinite(self.width) and self.width > 0):
            raise ValueError("credit structures need a positive finite width (index points)")
        if (self.spike_level is None) != (self.spike_drop_pct is None):
            raise ValueError("spike_level and spike_drop_pct must be set together")
        if self.spike_level is not None:
            if not (math.isfinite(self.spike_level) and self.spike_level > 0):
                raise ValueError("spike_level must be a positive finite VIX level")
            if not (math.isfinite(self.spike_drop_pct) and 0.0 < self.spike_drop_pct < 1.0):
                raise ValueError("spike_drop_pct must be a fraction in (0, 1)")
        if self.structure == TREND_SPREAD:
            if self.trend_sma_days is None or self.trend_sma_days < 2:
                raise ValueError("TREND_SPREAD needs trend_sma_days >= 2")
        elif self.trend_sma_days is not None:
            raise ValueError("trend_sma_days applies to TREND_SPREAD only")
        if self.monthly_signal and self.cadence != "monthly":
            raise ValueError("monthly_signal applies to cadence='monthly' only")
        if self.profit_target_pct is not None or self.stop_loss_x is not None:
            if self.structure not in CREDIT_STRUCTURES:
                raise ValueError("exit rules (profit target / stop loss) apply to credit structures only")
        if self.profit_target_pct is not None and not (math.isfinite(self.profit_target_pct) and self.profit_target_pct > 0):
            raise ValueError("profit_target_pct must be a positive percent of entry credit")
        if self.stop_loss_x is not None and not (math.isfinite(self.stop_loss_x) and self.stop_loss_x > 0):
            raise ValueError("stop_loss_x must be a positive multiple of entry credit")

    def vix_in_band(self, vix: float) -> bool:
        """Half-open band [vix_lo, vix_hi). A missing VIX is never in band."""
        if vix is None or not math.isfinite(vix):
            return False
        return self.vix_lo <= vix < self.vix_hi


_A_CELLS = [
    CandidateSpec(f"PCS_A_k{int(round(k * 10)):02d}_w{int(w)}", "A", PCS, k, float(w), "weekly", 16.0, 25.0)
    for k in (0.9, 1.1, 1.3) for w in (200, 300)
]
_B_CELLS = [
    CandidateSpec("LS_B_k09_wk", "B", LS, 0.9, None, "weekly", -math.inf, 13.0),
    CandidateSpec("LS_B_k09_mo", "B", LS, 0.9, None, "monthly", -math.inf, 13.0),
    CandidateSpec("LS_B_k13_wk", "B", LS, 1.3, None, "weekly", -math.inf, 13.0),
    CandidateSpec("LS_B_k13_mo", "B", LS, 1.3, None, "monthly", -math.inf, 13.0),
]
FAMILY_CELLS = {"A": tuple(_A_CELLS), "B": tuple(_B_CELLS)}
CELLS = {c.cell_id: c for c in _A_CELLS + _B_CELLS}


# Round 2 (docs/preregistration_round2.md Section 3): declared grid, no other values. Width W = 300 index points,
# put/call offset k = 1.0 sigma_T. Signal on weekly expiry day, VIX read at S, fill at F settle, DTE window [3, 8].
# Family F (combination) is not declared: it is built only after train, and is never run by the round-2 runner.
ROUND2_CELLS = {c.cell_id: c for c in (
    CandidateSpec("C1", "C", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, profit_target_pct=50.0, stop_loss_x=2.0),
    CandidateSpec("C2", "C", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, profit_target_pct=75.0, stop_loss_x=1.5),
    CandidateSpec("D1", "D", IRON_CONDOR, 1.0, 300.0, "weekly", 16.0, 25.0, profit_target_pct=50.0, stop_loss_x=2.0),
    CandidateSpec("D2", "D", IRON_CONDOR, 1.0, 300.0, "weekly", 16.0, 25.0),
    CandidateSpec("E1", "E", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, rv20_gap_min=2.0),
    CandidateSpec("E2", "E", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, rv20_gap_min=4.0),
)}
ROUND2_CELL_IDS = tuple(ROUND2_CELLS)


# Round 3 (docs/preregistration_round3.md, Section 3 table): declared grid, no other values. Hold to expiry (no
# profit target or stop), strikes from the S close (strike_basis='signal_close'), max loss on the fill basis plus fees.
# Monthly cells (M1-M3) signal ON the monthly expiry day (monthly_signal=True) and target the monthly expiry, DTE [15, 28].
# Weekly cells sign on weekly expiry days, DTE [3, 8]. Expiry brokerage and zero-contract skips are runner settings.
_R3_COMMON = dict(strike_basis=STRIKE_BASIS_SIGNAL_CLOSE, max_loss_basis=MAX_LOSS_BASIS_FILL_PLUS_FEES)
ROUND3_CELLS = {c.cell_id: c for c in (
    # M1 | IC (hedged) | monthly | 1.0 | 400 | [13, 25) | none
    CandidateSpec("M1", "M", IRON_CONDOR, 1.0, 400.0, "monthly", 13.0, 25.0, monthly_signal=True, **_R3_COMMON),
    # M2 | IC (hedged) | monthly | 1.3 | 400 | [13, 25) | none
    CandidateSpec("M2", "M", IRON_CONDOR, 1.3, 400.0, "monthly", 13.0, 25.0, monthly_signal=True, **_R3_COMMON),
    # M3 | PCS | monthly | 1.0 | 400 | [13, 25) | none
    CandidateSpec("M3", "M", PCS, 1.0, 400.0, "monthly", 13.0, 25.0, monthly_signal=True, **_R3_COMMON),
    # S1 | PCS | weekly | 1.0 | 300 | [13, 35) | post-spike: max VIX over last 20 sessions through S >= 25 and VIX_S <= 0.80 x that max
    CandidateSpec("S1", "S", PCS, 1.0, 300.0, "weekly", 13.0, 35.0, spike_level=25.0, spike_drop_pct=0.20, **_R3_COMMON),
    # T1 | PCS | weekly | 1.0 | 300 | [13, 25) | term-structure: weekly ATM straddle implied-move proxy <= monthly proxy at S close
    CandidateSpec("T1", "T", PCS, 1.0, 300.0, "weekly", 13.0, 25.0, term_structure_gate=True, **_R3_COMMON),
    # R1 | trend-selected PCS/CCS | weekly | 1.0 | 300 | [13, 25) | PCS if NIFTY close_S > SMA50 through S, else CCS
    CandidateSpec("R1", "R", TREND_SPREAD, 1.0, 300.0, "weekly", 13.0, 25.0, trend_sma_days=50, **_R3_COMMON),
    # W1 | IC (hedged) | weekly | 1.5 | 400 | [16, 25) | none
    CandidateSpec("W1", "W", IRON_CONDOR, 1.5, 400.0, "weekly", 16.0, 25.0, **_R3_COMMON),
)}
ROUND3_CELL_IDS = tuple(ROUND3_CELLS)


def get_round3_cell(cell_id: str) -> CandidateSpec:
    if cell_id not in ROUND3_CELLS:
        raise KeyError(f"unknown round-3 cell {cell_id!r}; declared: {list(ROUND3_CELL_IDS)}")
    return ROUND3_CELLS[cell_id]


def get_round2_cell(cell_id: str) -> CandidateSpec:
    if cell_id not in ROUND2_CELLS:
        raise KeyError(f"unknown round-2 cell {cell_id!r}; declared: {list(ROUND2_CELL_IDS)}")
    return ROUND2_CELLS[cell_id]


def get_cell(cell_id: str) -> CandidateSpec:
    if cell_id not in CELLS:
        raise KeyError(f"unknown candidate cell {cell_id!r}; declared: {sorted(CELLS)}")
    return CELLS[cell_id]


def rv20_annualised(closes: pd.Series, signal_day) -> float:
    """RV20 in vol points: sample stdev of the last 20 close-to-close log returns of NIFTY x sqrt(252) x 100.

    `closes` is indexed by date. Only closes up to and including `signal_day` are read (no look-ahead). NaN when
    fewer than 21 closes exist up to that day, or when any close in the window is missing or non-positive.
    """
    s = closes.loc[:pd.Timestamp(signal_day)]
    if len(s) < RV_WINDOW + 1:
        return float("nan")
    tail = s.iloc[-(RV_WINDOW + 1):].to_numpy(dtype=float)
    if not np.all(np.isfinite(tail)) or np.any(tail <= 0):
        return float("nan")
    rets = np.diff(np.log(tail))
    return float(np.std(rets, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)


def rv20_gap_filter(closes: pd.Series, gap_min: float) -> Callable:
    """candidate_entry_filter for ChainConfig: called with the signal-day market row (row.name is the date).

    Returns True when VIX_S - RV20_S >= gap_min, False when below, and None when RV20 is undefined (the engine
    counts None as 'missing_data').
    """
    def _filter(row) -> Optional[bool]:
        rv = rv20_annualised(closes, pd.Timestamp(row.name).date())
        if not math.isfinite(rv):
            return None
        return bool(float(row["vix"]) - rv >= gap_min)
    return _filter


def all_of(filters: list) -> Callable:
    """Combine entry filters with AND. Any definite False wins (skip 'entry_filter'); otherwise any None makes the
    combined result None (skip 'missing_data'); otherwise True. An empty list passes."""
    def _filter(row):
        undefined = False
        for f in filters:
            r = f(row)
            if r is None:
                undefined = True
            elif not r:
                return False
        return None if undefined else True
    return _filter


SPIKE_WINDOW = 20   # round 3 (Section 4 item 2): sessions up to and including S


def post_spike_decision(vix: pd.Series, sig, spike_level: float, drop_pct: float) -> Optional[bool]:
    """Post-spike rule on the VIX closes indexed by date. Reads only values dated <= sig.

    max(last SPIKE_WINDOW closes up to and including sig) >= spike_level AND VIX_sig <= (1 - drop_pct) x that max.
    None when fewer than SPIKE_WINDOW closes exist up to sig or any of them is missing.
    """
    s = vix.loc[:pd.Timestamp(sig)]
    tail = s.iloc[-SPIKE_WINDOW:].to_numpy(dtype=float)
    if len(tail) < SPIKE_WINDOW or not np.all(np.isfinite(tail)):
        return None
    mx = float(tail.max())
    vix_s = float(tail[-1])
    return bool(mx >= spike_level and vix_s <= (1.0 - drop_pct) * mx)


def post_spike_filter(vix: pd.Series, spike_level: float, drop_pct: float) -> Callable:
    """candidate_entry_filter: called with the signal-day market row (row.name is the date)."""
    def _filter(row) -> Optional[bool]:
        return post_spike_decision(vix, pd.Timestamp(row.name).date(), spike_level, drop_pct)
    return _filter


def trend_structure(closes: pd.Series, sig, sma_days: int) -> Optional[str]:
    """TREND_SPREAD structure choice (round 3, Section 4 item 4), decided on S data only.

    PCS when close_S > SMA(sma_days) of the closes up to and including S, otherwise CCS (ties go to CCS).
    None when fewer than sma_days closes exist up to S or any of them is missing.
    """
    s = closes.loc[:pd.Timestamp(sig)].iloc[-sma_days:].to_numpy(dtype=float)
    if len(s) < sma_days or not np.all(np.isfinite(s)):
        return None
    return PCS if s[-1] > float(s.mean()) else CALL_CREDIT_SPREAD


def _straddle_chain_settles(chain: pd.DataFrame) -> pd.DataFrame:
    """Usable settles on a day: positive settle and contracts > 0 (0-contract settles are excluded)."""
    if chain is None or len(chain) == 0:
        return pd.DataFrame(columns=["strike", "opt", "settle"])
    ok = (chain["settle"] > 0) & (chain["contracts"] > 0) & np.isfinite(chain["settle"].astype(float))
    return chain.loc[ok, ["strike", "opt", "settle"]]


def straddle_implied_move(chain: pd.DataFrame, spot: float, dte: int) -> Optional[float]:
    """Model-free ATM straddle implied-move proxy: (CE + PE at the ATM strike) / (spot x sqrt(DTE / 365)).

    ATM strike = the strike with both CE and PE usable settles that minimises |CE - PE| (ties: lower strike).
    None when there is no such pair or the inputs are not positive finite.
    """
    if not (spot is not None and math.isfinite(spot) and spot > 0) or dte is None or dte <= 0:
        return None
    u = _straddle_chain_settles(chain)
    if u.empty:
        return None
    ce = u[u["opt"] == "CE"].groupby("strike")["settle"].first()
    pe = u[u["opt"] == "PE"].groupby("strike")["settle"].first()
    both = ce.index.intersection(pe.index)
    if len(both) == 0:
        return None
    diff = (ce.loc[both] - pe.loc[both]).abs()
    atm = float(diff[diff == diff.min()].index.min())
    straddle = float(ce.loc[atm] + pe.loc[atm])
    return straddle / (float(spot) * math.sqrt(dte / 365.0))


def term_structure_pass(arch, sig, spot: float) -> Optional[bool]:
    """Round 3, Section 4 item 3: True when the nearest weekly expiry's straddle proxy <= the nearest monthly's.

    Reads only the archive on day sig (its expiry index and its chains). Expiries after sig only; the expiry
    falling on sig itself is never used (its rows are intrinsic). Weekly = nearest listed expiry after sig that
    is not a monthly expiry; monthly = nearest monthly expiry after sig (monthly_expiries on sig). None when either
    is missing or has no ATM pair.
    """
    listed_all = listed_expiries(arch, sig)
    monthly = set(monthly_expiries(listed_all, sig))
    after = [e for e in listed_all if e > sig]
    weekly_c = [e for e in after if e not in monthly]
    monthly_c = [e for e in after if e in monthly]
    if not weekly_c or not monthly_c:
        return None
    w, m = min(weekly_c), min(monthly_c)
    pw = straddle_implied_move(arch.chain(sig, w), spot, (w - sig).days)
    pm = straddle_implied_move(arch.chain(sig, m), spot, (m - sig).days)
    if pw is None or pm is None:
        return None
    return bool(pw <= pm)


def term_structure_filter(arch) -> Callable:
    """candidate_entry_filter for the term-structure gate; row is the signal-day market row."""
    def _filter(row) -> Optional[bool]:
        spot = float(row["nifty_close"])
        return term_structure_pass(arch, pd.Timestamp(row.name).date(), spot)
    return _filter


def is_monthly_signal_day(arch, day: date) -> bool:
    """True when day is the monthly expiry (last listed expiry of its calendar month) of the archive on that day."""
    listed = listed_expiries(arch, day)
    return day in monthly_expiries(listed, day)


def sigma_T(spot_f: float, vix_s: float, dte: int) -> float:
    """Period vol in index points: spot_F x (VIX_S / 100) x sqrt(DTE / 252). DTE in calendar days from F."""
    return spot_f * (vix_s / 100.0) * math.sqrt(dte / TRADING_DAYS_PER_YEAR)


def target_strikes(spec: CandidateSpec, spot_f: float, vix_s: float, dte: int) -> dict:
    """Unsnapped strike targets. PCS: {'PE'}; CCS: {'CE'}; IC and LS: {'CE', 'PE'}. Snapping is the engine's job."""
    s = sigma_T(spot_f, vix_s, dte)
    if spec.structure == PCS:
        return {"PE": spot_f - spec.k * s}
    if spec.structure == CALL_CREDIT_SPREAD:
        return {"CE": spot_f + spec.k * s}
    return {"CE": spot_f + spec.k * s, "PE": spot_f - spec.k * s}


def listed_expiries(arch, day: date) -> list:
    """Every expiry the archive lists on `day` (any DTE), ascending.

    Reads NseFoArchive's per-day expiry index. NseFoArchive.weekly_expiries stops at 14 days, which
    is shorter than the monthly window, so the full index is needed here.
    """
    index = getattr(arch, "_expiries_by_day", None)
    if index is None:
        raise RuntimeError("archive does not expose its per-day expiry index")
    return sorted(index.get(day, []))


def monthly_expiries(listed: list, day: date) -> list:
    """Monthly expiries among `listed` (expiries on or after `day`).

    The monthly expiry of a calendar month is the last listed expiry in that month. Earlier weekly
    expiries in the same month are not monthly.
    """
    last: dict = {}
    for e in listed:
        if e < day:
            continue
        key = (e.year, e.month)
        if key not in last or e > last[key]:
            last[key] = e
    return sorted(last.values())


def pick_expiry(spec: CandidateSpec, listed: list, day: date) -> tuple:
    """Target expiry for fill day `day`: (expiry, dte), or (None, None) when no expiry is in window.

    weekly : earliest listed expiry with DTE in [3, 8].
    monthly: monthly expiry with DTE in [15, 28], closest to 21 (ties: earlier expiry).
    """
    if spec.cadence == "weekly":
        lo, hi = WEEKLY_DTE_WINDOW
        cands = [e for e in listed if e >= day and lo <= (e - day).days <= hi]
        if not cands:
            return None, None
        e = min(cands)
        return e, (e - day).days
    lo, hi = MONTHLY_DTE_WINDOW
    cands = [e for e in monthly_expiries(listed, day) if lo <= (e - day).days <= hi]
    if not cands:
        return None, None
    e = min(cands, key=lambda x: (abs((x - day).days - MONTHLY_DTE_TARGET), x))
    return e, (e - day).days


def fill_basis_max_loss_unit(width: float, credit_fill_unit: float, round_trip_fee_rs: float, qty: int) -> float:
    """Audit fix 2 (max_loss_basis='fill_plus_fees'): max loss per unit = W - net credit at the fill price (after entry
    slippage) + round-trip fees spread over the traded quantity. round_trip_fee_rs is a Rs total for qty units; it must
    be a conservative bound (see the chain engine: entry order fees, mirrored exit order fees, STT on exercise)."""
    return width - credit_fill_unit + round_trip_fee_rs / qty


def pcs_max_loss_per_unit(width: float, credit_settle_unit: float) -> float:
    """A: max loss per unit = W - net credit, credit on the F EOD settle basis (pre-registration Section 3)."""
    return width - credit_settle_unit


def ls_debit_per_unit(premium_fill_unit: float, entry_fee_rs: float, qty: int) -> float:
    """B: debit paid per unit = CE + PE premium at F (settle plus entry slippage) plus entry fees spread
    over the traded quantity. This is the max loss per unit. It never uses the 5x credit fallback."""
    return premium_fill_unit + entry_fee_rs / qty


def harness_record(rec: dict) -> dict:
    """Project one closed candidate trade onto the strategy_eval normalised columns.

    Only normalised columns are written. There is no 'pnl_per_lot' key, so strategy_eval's adapter
    auto-detection reads the file as the normalised schema. The chain adapter would instead recompute
    max loss from the legs, which the pre-registration does not allow for B.
    """
    return {
        "strategy": rec["strategy"],
        "entry_date": rec["fill_date"],
        "exit_date": rec["exit_date"],
        "expiry": rec["expiry"],
        "lots": rec["lots"],
        "credit_rs": rec["credit_rs"],
        "max_loss_rs": rec["max_loss_rs"],
        "pnl_gross_rs": rec["gross_fill_rs"],
        "cost_rs": rec["fee_rs"],
        "pnl_net_rs": rec["pnl"],
        "exit_reason": rec["exit_reason"],
        "entry_vix": rec["entry_vix"],
        "hedge_cost_rs": 0.0,
        "slippage_rs": rec["entry_pen_rs"] + rec["close_slip_rs"],
        "base_haircut_pct": 0.0,
        "pricing_source": "chain",
        "family": rec["family"],
        "cadence": rec["cadence"],
        "signal_date": rec["signal_date"],
        "legs": rec["legs"],
    }
