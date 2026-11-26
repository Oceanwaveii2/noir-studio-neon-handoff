# Noir Studio V7 — Agent-Proof Execution Spec (Astra / Claude / Codex)

> **Purpose:** Zero-ambiguity implementation contract for building the **V7 Parallel Analysis & Counterfactual Recompute System** on top of Noir Fiction Studio without breaking existing architecture, Story-vs-Prose separation, or test floors.

---

## 1. Explicit `DO NOT BUILD` / Anti-Patterns (Hard Bans)
1. **Do NOT mutate `G0` (or any parent branch) in place.** Every What-If question MUST create a new immutable `branch_id` with `parent_branch_id`.
2. **Do NOT generate prose inside `story_graph/`.** `story_graph/` outputs typed JSON beats, edges, and validation statuses ONLY. Prose stays strictly inside `prose_engine/`.
3. **Do NOT hardcode character lore or episode facts inside prompts.** Always read active laws from `universe_laws_v2` / `WORLD_LAWS.noir`.
4. **Do NOT collapse MAP-Elites candidates into a single "best" reply.** `CN-3` MUST return 4 distinct behavioral quadrant bins.
5. **Do NOT refactor unrelated files outside the active Code Node's Ownership Fence.**

---

## 2. Strict Module Ownership Fence (One Code Node Per Task)

| Code Node | Allowed Files (Edit / Create) | Forbidden Files (DO NOT TOUCH) | Verification Gate |
| :--- | :--- | :--- | :--- |
| **CN-1 · Media Ingest** | `tools/media_ingest.py`, `tests/test_media_ingest.py` | `prose_engine/*`, `story_graph/*`, `tools/studio_ui.py`, `ui/*` | `SIM-15` + `ci.py --core` |
| **CN-2 · Counterfactual Engine** | `story_graph/counterfactual.py`, `tests/test_counterfactual.py` | `prose_engine/*`, `tools/studio_ui.py`, `ui/*` | `SIM-15`, `SIM-16` + `ci.py --core` |
| **CN-3 · MAP-Elites Brainstorm** | `story_graph/qd_brainstorm.py`, `tests/test_qd_brainstorm.py` | `prose_engine/*`, `tools/studio_ui.py`, `ui/*` | `SIM-17` + `ci.py --core` |
| **CN-4 · Analysis Lab UI Bridge** | `ui/analysis_lab.js`, `ui/analysis_lab.css`, `ui/app.js`, `tools/studio_canon_routes.py` | `prose_engine/*`, `story_graph/*` | `SIM-18` + `test_studio_v2_ui` + `ci.py --core` |

---

## 3. 1-to-1 Code Node Contracts

### `CN-1` — `tools/media_ingest.py`
- **Function Signature:** `ingest_media_to_baseline_graph(media_path: Path, srt_path: Path | None = None) -> dict`
- **Input Dict:** `{"media_path": "str (mp4/mkv/srt/pdf/docx/txt)", "srt_path": "str | None"}`
- **Return Dict (`BaselineGraphPacket`):**
  ```json
  {
    "schema_version": "7.0",
    "branch_id": "G0",
    "parent_branch_id": null,
    "immutable": true,
    "source_sha256": "hex",
    "scenes": [{"id": "E01", "start_ms": 0, "speakers": ["FRANCINE"], "text": "..."}],
    "causal_edges": [{"from": "E01", "to": "E02", "kind": "ENABLES"}]
  }
  ```

### `CN-2` — `story_graph/counterfactual.py`
- **Function Signature:** `fork_counterfactual_branch(parent_branch: dict, intervention: dict, active_world_laws: list[dict]) -> dict`
- **Input Dict:**
  - `parent_branch`: Immutable `BaselineGraphPacket` or prior `BranchRecomputeResult`
  - `intervention`: `{"question": "str", "branch_id": "G1", "add_beats": [...], "prune_beat_ids": [...]}`
  - `active_world_laws`: `[{"id": "LAW_SHAPESHIFT", "active": true, "hard": true}]`
- **Return Dict (`BranchRecomputeResult`):**
  ```json
  {
    "schema_version": "7.0",
    "branch_id": "G1",
    "parent_branch_id": "G0",
    "question": "...",
    "beats": [{"id": "E02*", "status": "NEW|PRUNED|CONFLICT|BASE", "requires": ["LAW_SHAPESHIFT"], "conflict_laws": []}],
    "world_law_conflicts": 0
  }
  ```
- **Deterministic Pre-LLM Rule:** Any beat whose `requires` contains a law with `active == False` MUST be marked `status == "CONFLICT"` before any LLM call.

### `CN-3` — `story_graph/qd_brainstorm.py`
- **Function Signature:** `generate_map_elites_grid(branch: dict, epistemic_states: list[dict], axes: tuple[str, str] = ("escalation_style", "plot_spine")) -> dict`
- **Return Dict (`MapElitesGridResult`):**
  ```json
  {
    "schema_version": "7.0",
    "branch_id": "G2",
    "axes": ["escalation_style", "plot_spine"],
    "cells": [
      {"quadrant": "Social Warfare x A-Plot", "title": "...", "pitch": "...", "scores": {"coherence": 96, "novelty": 93, "canon_fit": 98}}
    ]
  }
  ```
- **Diversity Lock:** `len(cells) == 4` and all 4 `quadrant` labels MUST be unique.

### `CN-4` — `ui/analysis_lab.js` → `ui/shelf.js`
- **Function Signature:** `promoteCandidateToPrepNodes(candidate, branchId, activeLawIds)`
- **Return Array (`GutterNodePromotionPacket`):** Array of typed Word Prep Connected Gutter-Nodes (`scene-heading`, `stage-direction`, `character`, `world-law`, `beat-turn`) with `source_branch_id` provenance preserved.

---

## 4. Golden Executable Acceptance Tests (`SIM-15..SIM-18`)
Run `py -B blueprints/v7_parallel_analysis/verify_v7_contracts.py` after every milestone:
- **`SIM-15` (Immutable Branch Chain):** `G0 -> G1 -> G2` produces distinct `branch_id` / `parent_branch_id` and leaves `G0` byte-for-byte unchanged.
- **`SIM-16` (Deterministic World-Law Conflict Gate):** Disabling `LAW_SHAPESHIFT` on `G1` flags `E02*` as `status == "CONFLICT"` with `conflict_laws == ["LAW_SHAPESHIFT"]` and zero LLM calls.
- **`SIM-17` (MAP-Elites Diversity Lock):** Returns exactly 4 unique quadrants with numeric scores in `[0, 100]`.
- **`SIM-18` (Gutter-Node Provenance Bridge):** Promoted candidate preserves `source_branch_id`, active `@law` references, and valid Word Prep node kinds.

---

## 5. Mandatory Verification Floor (Every PR / Milestone)
```powershell
py -B blueprints/v7_parallel_analysis/verify_v7_contracts.py
py -B -m unittest tests.test_studio_v2_ui
py -B tools/ci.py --core
```
- **Core CI Floor:** `>=572` core baseline tests passing, `5/5` architecture fixtures passing, `0` illegal package import edges.
- **Studio UI Floor:** `7/7` passing in `tests.test_studio_v2_ui`.

---

## 6. Bounded Milestone Prompts (Feed One Task at a Time to Astra / Claude)
1. **Task 1 (`CN-1`):** *"Implement ONLY `CN-1` (`tools/media_ingest.py` + `tests/test_media_ingest.py`) per `blueprints/v7_parallel_analysis/V7_AGENT_EXECUTION_SPEC.md` and `V7_DATA_CONTRACTS.json`. Do not touch files outside the `CN-1` Ownership Fence. Run `verify_v7_contracts.py` and `tools/ci.py --core`."*
2. **Task 2 (`CN-2`):** *"Implement ONLY `CN-2` (`story_graph/counterfactual.py` + `tests/test_counterfactual.py`) passing `SIM-15` and `SIM-16`. Do not touch `prose_engine/` or `ui/`."*
3. **Task 3 (`CN-3`):** *"Implement ONLY `CN-3` (`story_graph/qd_brainstorm.py` + `tests/test_qd_brainstorm.py`) passing `SIM-17`."*
4. **Task 4 (`CN-4`):** *"Implement ONLY `CN-4` (`ui/analysis_lab.js`, `ui/analysis_lab.css`, route registration) passing `SIM-18` and `tests.test_studio_v2_ui`."*
