"""Round 3 declared cells (docs/preregistration_round3.md, Section 3 table and Section 7 item 1).

Field-by-field checks against the frozen doc table. The table text is parsed from the doc itself, so a drift
between code and doc fails here. Synthetic only: no archive, no network, no run.
"""

import re
from pathlib import Path

import pytest

from backtester.candidates import (
    CALL_CREDIT_SPREAD, IRON_CONDOR, MAX_LOSS_BASIS_FILL_PLUS_FEES, PCS, ROUND2_CELLS, STRIKE_BASIS_SIGNAL_CLOSE,
    TREND_SPREAD, CandidateSpec, CELLS, get_round3_cell, ROUND3_CELL_IDS, ROUND3_CELLS,
)

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "preregistration_round3.md"

STRUCTURE_BY_DOC = {"IC (hedged)": IRON_CONDOR, "PCS": PCS, "trend-selected PCS/CCS": TREND_SPREAD}
ROUND3_IDS = ("M1", "M2", "M3", "S1", "T1", "R1", "W1")

# Extra rule per Section 3 table, copied verbatim from the doc row as a comment, then encoded as fields.
EXTRA_RULE = {
    # M1 | ... | none
    "M1": dict(),
    # M2 | ... | none
    "M2": dict(),
    # M3 | ... | none
    "M3": dict(),
    # S1 | ... | post-spike: max VIX over last 20 sessions through S >= 25 and VIX_S <= 0.80 x that max
    "S1": dict(spike_level=25.0, spike_drop_pct=0.20),
    # T1 | ... | term-structure: weekly ATM straddle implied-move proxy <= monthly proxy at S close
    "T1": dict(term_structure_gate=True),
    # R1 | ... | PCS if NIFTY close_S > SMA50 through S, else CCS
    "R1": dict(trend_sma_days=50),
    # W1 | ... | none
    "W1": dict(),
}


def _doc_rows() -> dict:
    rows = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([MSTRW]\d)\s*\|(.*)\|\s*$", line)
        if m:
            cells = [c.strip() for c in m.group(2).split("|")]
            rows[m.group(1)] = cells
    return rows


def _parse_band(text: str) -> tuple:
    m = re.fullmatch(r"\[(\d+(?:\.\d+)?),\s*(\d+(?:\.\d+)?)\)", text)
    assert m, f"unparseable VIX gate {text!r}"
    return float(m.group(1)), float(m.group(2))


def test_round3_declares_exactly_the_seven_doc_cells():
    assert ROUND3_CELL_IDS == ROUND3_IDS
    assert set(_doc_rows()) == set(ROUND3_IDS)
    assert set(ROUND3_CELLS) == set(ROUND3_IDS)


def test_round3_cells_are_disjoint_from_round1_and_round2():
    assert not set(ROUND3_CELLS) & (set(CELLS) | set(ROUND2_CELLS))


def test_unknown_round3_cell_is_refused_and_f_is_not_declared():
    for bad in ("F1", "M4", "C1", "S2", "PCS_A_k09_w200"):
        with pytest.raises(KeyError):
            get_round3_cell(bad)


@pytest.mark.parametrize("cell_id", ROUND3_IDS)
def test_cell_matches_doc_table_row(cell_id):
    row = _doc_rows()[cell_id]
    structure_txt, cadence, k, width, gate, _extra = row
    c = get_round3_cell(cell_id)
    assert isinstance(c, CandidateSpec)
    assert c.cell_id == cell_id
    assert c.structure == STRUCTURE_BY_DOC[structure_txt], structure_txt
    assert c.cadence == cadence
    assert c.k == float(k)
    assert c.width == float(width)
    assert (c.vix_lo, c.vix_hi) == _parse_band(gate)


@pytest.mark.parametrize("cell_id", ROUND3_IDS)
def test_cell_extra_rules_match_doc_and_encoded_table(cell_id):
    c = get_round3_cell(cell_id)
    expect = EXTRA_RULE[cell_id]
    assert c.spike_level == expect.get("spike_level")
    assert c.spike_drop_pct == expect.get("spike_drop_pct")
    assert c.term_structure_gate is expect.get("term_structure_gate", False)
    assert c.trend_sma_days == expect.get("trend_sma_days")
    # the doc row's last column must describe the rule encoded here
    extra_txt = _doc_rows()[cell_id][5].lower()
    if cell_id == "S1":
        assert "max vix over last 20 sessions" in extra_txt and "0.80" in extra_txt and "25" in extra_txt
    elif cell_id == "T1":
        assert "term-structure" in extra_txt
    elif cell_id == "R1":
        assert "sma50" in extra_txt.replace(" ", "")
    else:
        assert extra_txt == "none"


@pytest.mark.parametrize("cell_id", ROUND3_IDS)
def test_cell_common_settings_are_hold_to_expiry_and_frozen_bases(cell_id):
    c = get_round3_cell(cell_id)
    assert c.profit_target_pct is None and c.stop_loss_x is None and c.rv20_gap_min is None
    assert c.strike_basis == STRIKE_BASIS_SIGNAL_CLOSE
    assert c.max_loss_basis == MAX_LOSS_BASIS_FILL_PLUS_FEES


@pytest.mark.parametrize("cell_id", ROUND3_IDS)
def test_cadence_and_monthly_signal_flag(cell_id):
    c = get_round3_cell(cell_id)
    if c.cadence == "monthly":
        assert c.monthly_signal is True
    else:
        assert c.monthly_signal is False


def test_monthly_cells_are_m1_m2_m3_only_and_weekly_cells_are_the_rest():
    monthly = {c for c in ROUND3_IDS if get_round3_cell(c).cadence == "monthly"}
    assert monthly == {"M1", "M2", "M3"}


def test_wide_weekly_condor_and_cell_families():
    w1 = get_round3_cell("W1")
    assert w1.structure == IRON_CONDOR and w1.k == 1.5 and w1.width == 400.0 and w1.cadence == "weekly"
    assert (w1.vix_lo, w1.vix_hi) == (16.0, 25.0)
    assert get_round3_cell("M2").k == 1.3
    assert get_round3_cell("S1").vix_hi == 35.0
    assert get_round3_cell("R1").structure == TREND_SPREAD
    assert CALL_CREDIT_SPREAD not in {get_round3_cell(c).structure for c in ROUND3_IDS}
