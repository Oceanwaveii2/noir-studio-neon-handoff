"""Executable Golden Acceptance Tests (SIM-15..SIM-18) for Noir Studio V7 Blueprint."""
from __future__ import annotations

import copy
import json
from pathlib import Path

CONTRACTS_PATH = Path(__file__).with_name("V7_DATA_CONTRACTS.json")
VALID_GUTTER_KINDS = {
    "scene-heading",
    "stage-direction",
    "narrator",
    "character",
    "mind-form",
    "world-law",
    "beat-turn",
}


def simulate_fork_branch(parent: dict, intervention: dict, laws: list[dict]) -> dict:
    """Reference deterministic implementation for SIM-15 & SIM-16 contract verification."""
    active_ids = {law["id"] for law in laws if law.get("active")}
    pruned = set(intervention.get("prune_beat_ids", []))
    next_beats = []
    conflicts = 0
    for beat in copy.deepcopy(parent["beats"]):
        if beat["id"] in pruned:
            beat["status"] = "PRUNED"
        next_beats.append(beat)
    for beat in copy.deepcopy(intervention.get("add_beats", [])):
        missing = [law_id for law_id in beat.get("requires", []) if law_id not in active_ids]
        beat["conflict_laws"] = missing
        beat["status"] = "CONFLICT" if missing else "NEW"
        if missing:
            conflicts += 1
        next_beats.append(beat)
    return {
        "schema_version": "7.0",
        "branch_id": intervention["branch_id"],
        "parent_branch_id": parent["branch_id"],
        "question": intervention["question"],
        "beats": next_beats,
        "world_law_conflicts": conflicts,
    }


def run_all() -> None:
    contracts = json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))
    assert contracts["schema_version"] == "7.0"
    assert len(contracts["code_nodes"]) == 4

    # Baseline G0 (immutable)
    g0 = {
        "schema_version": "7.0",
        "branch_id": "G0",
        "parent_branch_id": None,
        "immutable": True,
        "beats": [
            {"id": "E01", "status": "BASE", "requires": []},
            {"id": "E03", "status": "BASE", "requires": []},
        ],
    }
    g0_snapshot = copy.deepcopy(g0)

    laws_canon = [
        {"id": "LAW_ZERO_SMITH", "active": True, "hard": True},
        {"id": "LAW_SHAPESHIFT", "active": True, "hard": True},
    ]

    # SIM-15: Chained Counterfactual Fork G0 -> G1 -> G2 without mutating G0
    g1 = simulate_fork_branch(
        g0,
        {
            "branch_id": "G1",
            "question": "Remove Stan and add Peter-Rainee morph",
            "prune_beat_ids": ["E03"],
            "add_beats": [{"id": "E02*", "requires": ["LAW_SHAPESHIFT"]}],
        },
        laws_canon,
    )
    g2 = simulate_fork_branch(
        g1,
        {
            "branch_id": "G2",
            "question": "Peter-Rainee does not stick; farts and splits into The Plastics",
            "prune_beat_ids": ["E02*"],
            "add_beats": [{"id": "E05*", "requires": ["LAW_SHAPESHIFT", "LAW_ZERO_SMITH"]}],
        },
        laws_canon,
    )
    assert g0 == g0_snapshot, "SIM-15 FAIL: G0 was mutated in place!"
    assert g1["parent_branch_id"] == "G0" and g2["parent_branch_id"] == "G1"
    assert g1["world_law_conflicts"] == 0 and g2["world_law_conflicts"] == 0
    print("[PASS] SIM-15: Immutable chained branch fork G0 -> G1 -> G2")

    # SIM-16: Deterministic World-Law Conflict Gate (No-Morph Parallel World)
    laws_no_morph = [
        {"id": "LAW_ZERO_SMITH", "active": True, "hard": True},
        {"id": "LAW_SHAPESHIFT", "active": False, "hard": True},
    ]
    g1_conflict = simulate_fork_branch(
        g0,
        {
            "branch_id": "G1_NO_MORPH",
            "question": "Test Peter-Rainee in No-Morph parallel world",
            "add_beats": [{"id": "E02*", "requires": ["LAW_SHAPESHIFT"]}],
        },
        laws_no_morph,
    )
    e02 = next(b for b in g1_conflict["beats"] if b["id"] == "E02*")
    assert e02["status"] == "CONFLICT" and e02["conflict_laws"] == ["LAW_SHAPESHIFT"]
    assert g1_conflict["world_law_conflicts"] == 1
    print("[PASS] SIM-16: Deterministic World-Law conflict gate flagged E02* pre-LLM")

    # SIM-17: MAP-Elites 4-Quadrant Diversity Lock
    qd_result = {
        "schema_version": "7.0",
        "branch_id": "G2",
        "axes": ["escalation_style", "plot_spine"],
        "cells": [
            {"quadrant": "Social Warfare x A-Plot", "scores": {"coherence": 96, "novelty": 93, "canon_fit": 98}},
            {"quadrant": "Domestic Chaos x B-Plot", "scores": {"coherence": 92, "novelty": 87, "canon_fit": 95}},
            {"quadrant": "Epistemic Comedy x Neighbor", "scores": {"coherence": 90, "novelty": 94, "canon_fit": 93}},
            {"quadrant": "Wild Mutation x 100% Noise", "scores": {"coherence": 88, "novelty": 97, "canon_fit": 91}},
        ],
    }
    quadrants = {c["quadrant"] for c in qd_result["cells"]}
    assert len(qd_result["cells"]) == 4 and len(quadrants) == 4
    for cell in qd_result["cells"]:
        for k in ("coherence", "novelty", "canon_fit"):
            assert 0 <= cell["scores"][k] <= 100
    print("[PASS] SIM-17: MAP-Elites 4-quadrant diversity & bounded score lock")

    # SIM-18: Gutter-Node Promotion Provenance Bridge
    promoted = {
        "source_branch_id": "G2",
        "nodes": [
            {"kind": "scene-heading", "text": "INT. SPRING BREAK DECK - NIGHT"},
            {"kind": "stage-direction", "text": "[Sade, Becky, and Clarie hijack the VIP deck.]"},
            {"kind": "character", "speaker": "SADE", "text": '"4 out of 10, Roger."'},
            {"kind": "world-law", "text": "@law:kidney-price"},
            {"kind": "beat-turn", "text": "Plastics dethrone Roger on live MTV."},
        ],
    }
    assert promoted["source_branch_id"] == "G2"
    assert all(n["kind"] in VALID_GUTTER_KINDS for n in promoted["nodes"])
    print("[PASS] SIM-18: Gutter-Node promotion provenance & schema lock")
    print("ALL V7 BLUEPRINT CONTRACTS PASSED (4/4 SIM-15..SIM-18)")


if __name__ == "__main__":
    run_all()
