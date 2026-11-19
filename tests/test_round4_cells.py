"""Round 4 declared cells (docs/preregistration_round4.md, Section 2): round-3 specs renamed G_<id>, no other change.

Synthetic only: no archive, no network.
"""

import dataclasses

import pytest

from backtester.candidates import ROUND3_CELL_IDS, ROUND4_CELL_IDS, CandidateSpec, get_round3_cell, get_round4_cell


def test_round4_ids_exact():
    assert ROUND4_CELL_IDS == ("G_M1", "G_M2", "G_M3", "G_S1", "G_T1", "G_R1", "G_W1")
    assert tuple(c[2:] for c in ROUND4_CELL_IDS) == ROUND3_CELL_IDS


@pytest.mark.parametrize("cid", ROUND4_CELL_IDS)
def test_every_field_equals_round3_except_cell_id(cid):
    r4, r3 = get_round4_cell(cid), get_round3_cell(cid[2:])
    assert isinstance(r4, CandidateSpec) and r4.cell_id == cid and r3.cell_id == cid[2:]
    for f in dataclasses.fields(CandidateSpec):
        if f.name == "cell_id":
            continue
        assert getattr(r4, f.name) == getattr(r3, f.name), f.name
    assert dataclasses.replace(r4, cell_id=r3.cell_id) == r3


@pytest.mark.parametrize("cid", ROUND4_CELL_IDS)
def test_gate_is_not_part_of_spec(cid):
    names = {f.name for f in dataclasses.fields(CandidateSpec)}
    assert not any("exit" in n or "ml_" in n for n in names)   # term_structure_gate is a round-3 rule, not the exit gate


@pytest.mark.parametrize("bad", ["M1", "G_M4", "G_C1", "", "g_m1", "E1"])
def test_unknown_id_raises(bad):
    with pytest.raises(KeyError):
        get_round4_cell(bad)


def test_round3_cells_untouched():
    assert get_round3_cell("M1").cell_id == "M1"
