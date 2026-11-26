# Narrative Engine (NOIR Studio) — Agent Instructions & Handoff Rulebook

## 1. Mandatory Cold-Start Reading Order (Do This Before Editing Anything)
1. Read `AGENTS.md` (this file), `.app-steward/OPERATING_RULES.md`, `.app-steward/policies/project-profile.json`, and `docs/PROJECT_STEWARDSHIP.md`.
2. Read `docs/UI_SYSTEM_MIND_MAP.md` (canonical 6-tab inventory & subsystem map).
3. Read ONLY the read-only spec for your active milestone:
   - **Character Graph / Global–Episodic / Houdini Interiors / Atomic Undo:** `blueprints/noir_studio_character_graph_blueprint.html`
   - **Timeline Command Guard:** `blueprints/v7_parallel_analysis/TIMELINE_COMMAND_BLUEPRINT.md`
   - **Compose Highlight & Sim Dock:** `blueprints/simulate_then_render/mockup_simulate_render.html`
   - **V7 Parallel Analysis & Code Nodes:** `blueprints/v7_parallel_analysis/V7_AGENT_EXECUTION_SPEC.md` + `V7_DATA_CONTRACTS.json`
   - **5-Pass Wordcraft Compositor & Ironclad Rules:** `docs/specs/COMPOSITOR_BREAKDOWN.md`
4. Inspect the exact target file(s) in `ui/` before proposing a plan + diff preview.

## 2. Quick Commands (Run Verification Before Declaring Done)
- **Install (editable):** `py -B -m pip install -e .`
- **Launch Studio UI:** `py -B tools/studio_ui.py --port 8765` (serves live UI at `http://127.0.0.1:8765/v2`)
- **Core baseline + architecture boundaries:** `py -B tools/ci.py --core`
- **Studio v2 UI unit suite:** `py -B -m unittest tests.test_studio_v2_ui`
- **V7 contract suite:** `py -B blueprints/v7_parallel_analysis/verify_v7_contracts.py`
- **Zero `!important` CSS gate:** `py -B -c "import pathlib; bad=[p.name for p in pathlib.Path('ui').glob('*.css') if '!important' in p.read_text(encoding='utf-8')]; assert not bad, bad; print('CSS_OK')"`
- **Canon check (read-only manuscript):** `py -B tools/check_canon.py`
- **Release verification:** `py -B tools/ci.py`
- *Report `ci.py --core` separately from release CI, real-provider runs, author acceptance, and `check_canon.py`. Keep existing failures and test floors visible (`>= 572` core baseline, `5` architecture fixtures).*

## 3. Source-of-Truth & Authority Map (Zero-Drift Locks)
- **Editable Backend (`story_graph/`, `prose_engine/`, `telemetry/`, `experimental/`, `tools/`, `tests/`):**
  5-layer Python architecture checked statically by `tools/check_architecture.py` (`.app-steward/architecture/modules.json`). `story_graph/` owns state, causal DAGs, world laws, and `simulation/` contracts; `prose_engine/` owns retrieval, guards, and LLM adapters; `tools/` owns `studio_ui.py`, Workbench, and CI.
- **Editable Frontend (`ui/` + `tools/v2_page.html`):** Active Studio v2 JS/CSS (`app.js`, `compose.js`, `char_switchyard.js`, `story_graph_canvas.js`, `timeline.js`, `shelf.js`, `vfx_engine.js`) served with priority by `tools/studio_canon_routes.py`. Edit `ui/` in place — **NEVER rebuild `ui/` from scratch** and **NEVER edit shadowed copies in `tools/assets/v2/`**. Keep `tools/v2_page.html` live (it is the `/v2` entrypoint served by `tools/studio_ui.py`).
- **Shared Data & Build (`books/`, `appearances/`, `references/`, `voice/`, `eval/`, `work/`, `imports/`, `vfx_src/`, `deliverables/NOIR_FX06_*`):** Active corpora, working & migrated SQLite workspaces (`imports/`), VFX build scripts, and FX06 test fixtures.
- **Read-Only Architectural Specs (`blueprints/`, `docs/specs/`):** Authoritative specs & interactive planning mockups (`blueprints/`) defining target architecture, ports, and contracts. **Strictly READ-ONLY during coding sprints.**
- **Quarantined Legacy (`_archive/`, `sketches/`):** Excluded via `.claudeignore` / `.cursorignore` / `.aiignore`. Historical design notes live in `docs/NOVEMBER_LOG.md` and `docs/archive/`.

## 4. Hard Stop Rules
1. **Never import from, run as production, or edit `sketches/`, `_archive/`, or `blueprints/`** when implementing application features unless explicitly asked.
2. **Preserve story vs. prose separation:** Keep `story_graph/` strictly free of imports from `prose_engine/` or `tools/`. Keep frozen dialogue and source provenance intact.
3. **Follow checkpoint-first stewardship:** Before reorganizing or coding, read `.app-steward/OPERATING_RULES.md`, `.app-steward/policies/project-profile.json`, and `docs/PROJECT_STEWARDSHIP.md`, save/verify the latest local checkpoint & baseline, open a bounded task, and update the matching command contract alongside behavior changes. Preserve all existing comments/instructions and surface conflicts rather than overwriting them.
4. **Zero `!important` in UI CSS:** Keep Studio v2 styling (`ui/*.css`) free of `!important` overrides.
5. **Loopback & adapter parity:** Keep UI (`tools/studio_ui.py`) and CLI adapters on the same engine path where implemented; record discrepancies as gaps.
6. **Zero Hard Deletes & Input-Focus Undo Guard:** All node/edge/junction/episode/image removals must be reversible soft-deletes. Global `Ctrl+Z` / `Ctrl+Y` handlers MUST ignore events when focus is inside `<input>`, `<textarea>`, or `[contenteditable]`.
7. **Open-Ended Super Character Socket & Zero Trait Mutation:** Align with `FormLink(kind="super_character")` (`story_graph/character_forms.py`) and keep `mind_payload` open (`schema_mode: "open"`). Swapping form routing updates downstream resolved context only — never mutate internal traits/Minds.
8. **No Reviewer Gates / Potemkin Scripts:** Never add human approval/reviewer sign-off blockers or pre-seeded dialogue setup scripts (see `docs/specs/COMPOSITOR_BREAKDOWN.md`).
