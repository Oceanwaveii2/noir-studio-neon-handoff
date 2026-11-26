# Noir Fiction Studio — Complete UI System & Subsystem Representation Mind Map

**Purpose:** Master architectural map of (1) the **entire current Studio v2 UI** (`ui/` + `tools/v2_page.html` + companion routes) and (2) **every backend / emergent simulation / media / prose / canon system** that must be faithfully represented in the UI under our **"Familiar Front, Emergent Back" (DLSS-5 Simulate-Then-Render)** design.

---

## 1. Visual Mind Map (Mermaid)

```mermaid
mindmap
  root((Noir Fiction Studio UI))
    00 Cockpit Shell & VFX
      Top Nav: Home | Word Prep | Compose | Character Graph | Story Graph & Rhythm | Timeline
      Header Controls: Cook, Save Status, SFX, Music, VFX Mode, Engine Drawer
      Left Rail Switcher: Project Episodes vs Raw Text Shelf
      Pop Modals: Starter, Laws, Memory, Timeline
      Motion & Audio: ui/vfx_engine.js, EffectCraft Lottie, Nuke Optical Plates, WebAudio SFX
    01 Home (view=start · intake.js)
      Grand Prix Route Deck (Compose / Switchyard / Beat DAG cards)
      Multimodal Source Desk (Script, DOCX, PDF, Image, Audio/Video drop -> 32 MB)
      3-Stage Ingest Strip: Parse Source -> Link Characters -> Extract Beats
      Episode Launch Config: Title, Branch, Placement, Presets, Gemini/Codex Writer
      Director Inspector: Draft Outline & Synthesis Notes
    02 Word Prep (view=prep · shelf.js)
      Raw Story Vault / Text Shelf (RAW | STAGED | IN GRAPH cards in localStorage)
      Connected Gutter-Node Word Processor (Illuminated Conduit Spine + 7 NOIR_WORD_SCHEMA Node Types)
      Dual View: Visual Gutter Nodes | Raw .noir Markup + Font/Rich Toolbar + Auto-Format
      Precision Data Injection: Inject 0% Lock, Inject 50% Bal, Bind @law:id
      Graph Readiness Telemetry + Live WORLD_LAWS.noir Rule Editor
      Handoff: Send Prepped -> Compose / Character Graph
    03 Compose (view=compose · compose.js)
      Familiar Warm Parchment Editor (#F7F4EC grouped blocks via compose_blocks.js)
      Highlighter Freeze (0% LOCK Verbatim Span Protection)
      4-Tier Uplift / Noise Masking (0% Lock, 25%, 50%, 75%, 100%)
      Inline Speaker Picker + + New Major/Minor Character Spawn & SQLite Bind
      4-Mode Canon Tag Strip: Canon | Non-Canon | Alternate Canon | Time-Travel Canon + Carrier Select
      Split Story Graph Mode (Live Sync Pane + Click-to-Scroll)
      Right Inspector: Stage 1 Weather & Relations Card, Block <-> Character Sync, Canon-Diff / Auto-Fixes
    04 Character Graph (view=graph · char_switchyard.js & graph.js)
      01 Identity -> 02 Form & Branching Forks (Rainee Base -> Big Butt -> Branch A Peter / Branch B 3 Bitches)
      03 Resolved Context + 04 Relationship Node (Asymmetric Stance, Patience Slider, Bridging Direction)
      Mind Port Matrix (Clips, Voice/Persona Ports, Toggle ON/OFF)
      Typed Media Pin Drop Firewall (catalyst_trigger, relationship_chemistry, rhythm_timing, personality_mind)
      Form Interior & Clips Modal + SQLite Character Junction Hydration
      Subtabs: Form Switchyard | Cytoscape Story DAG | Character Junctions List
    05 Story Graph & Timeline (view=timeline · timeline.js & story_graph_canvas.js)
      Tracks: Episode Branching Timeline vs Story Beats Track
      Vertical Beat DAG (G0 / G1 / G2 What-If Forks) + Jump to Compose Block
      Sensory Portals per Beat (Sight / Audio Barrier Flags + Rhythm Clips)
      [GAP] Two-Phase Timeline Impact Dry-Run Modal (Temporal Lock & Broken Edge Guard)
    06 Engine Drawer & Specialty Routes
      Engine Drawer: Prose Lab, World Laws Editor, Analysis Lab (ToM + MAP-Elites), Draft Compare
      Legacy/Specialty Pages: /scene-clips, /beat-media, /scene-fragments, /scene-replay, /scene-minds, /scene-branches, /fx06
      Sim Lab Blueprint: blueprints/simulate_then_render/mockup_simulate_render.html
    Backend Systems Required in UI
      Stage 1 Multi-Agent Blackboard & Sensory Barriers (W_t vs B_t)
      Global Character Graph & Asymmetric Relationships Store
      Causal-Temporal Canon Bridges (Time-Travel / Alternate Canon)
      Unified Content-Addressed Media Vault (Stage A Track Extraction + Stage B Pins)
      138-Book Mighty Prose Engine & PDG Incremental Cache (CACHE_HIT vs RECOMPUTED)
      Episodic Memory & Isolated Multi-DB Resource Bridges
```

---

## 2. Current Live UI Inventory (`ui/` + `tools/`)

| Area | Route / Trigger | Canonical Files | Role & Live State |
|---|---|---|---|
| **Cockpit Shell** | `/v2` (`tools/v2_page.html`) | `ui/app.js`, `ui/store.js`, `ui/api.js`, `ui/shell.css`, `ui/tokens.css` | 6-tab top nav, left project/shelf rail, Engine Drawer, save/cook bar, Racing/Editorial themes. |
| **VFX & Audio** | Theme `racing` + toggles | `ui/vfx_engine.js`, `ui/vfx_overlay.css`, `ui/sound.js`, `ui/assets/vfx/*` | EffectCraft Lottie overlays + Nuke RGBA optical plates (`Overdrive / Balanced / Focus`) + WebAudio SFX/Music. |
| **Home / Source Desk** | `/v2?view=start` | `ui/intake.js`, `ui/intake.css` | Grand Prix 3-card Route Deck, multimodal file drop, 3-step synth bar, episode launch & writer selector. |
| **Word Prep (Pre-Stage)** | `/v2?view=prep` | `ui/shelf.js`, `ui/shelf.css` | Left Raw Story Vault (`Text Shelf`), connected gutter-node editor (`7` schema node types), precision injector, telemetry, `WORLD_LAWS.noir`. |
| **Compose** | `/v2?view=compose` | `ui/compose.js`, `ui/compose.css`, `tools/compose_blocks.js` | Warm parchment prose editor, `0% LOCK` freeze & uplift tiers, inline `+ New Character` spawn, 4-mode Canon strip, split graph, `⚡ Stage 1 Weather` card. |
| **Character Graph** | `/v2?view=graph` | `ui/char_switchyard.js`, `ui/graph.js`, `ui/form-board.js`, `ui/live_graph_bridge.js` | 4-tier branching Form Switchyard, Hybrid Relationships Controller, Typed Media Pin drops, Cytoscape Story DAG, Junctions. |
| **Story Graph & Rhythm** | `/v2?view=story` | `ui/story_graph_canvas.js`, `ui/live_graph_bridge.js` | Houdini L1/L2/L3 Beat DAG (`G0/G1/G2`), between-beat `+ Media` hooks, Sight/Audio portals, rhythm clips. |
| **Timeline** | `/v2?view=timeline` | `ui/timeline.js`, `ui/story_timeline.js`, `ui/beat.js`, `ui/scene_plan.js` | Episode branching lanes with SVG wires, `Timeline Undo/Redo`, `Removed (N)` archive, Beat Inspector. |
| **Active Planning Blueprints** | Read-Only Specs | `blueprints/noir_studio_character_graph_blueprint.html`, `docs/specs/COMPOSITOR_BREAKDOWN.md` | Authoritative specs for Character Graph v2 (Global/Episodic, Super Node socket, Houdini interiors) and 5-Pass Compositor. |
| **Engine Drawer Tabs** | Top-right `Engine` button | `ui/prose.js`, `ui/analysis_lab.js` | Prose generation / Best-of-N / Craft Brief / Book Policy / Canon-Diff (`Pass 0-3`) / World Laws / V7 Analysis Lab (ToM + MAP-Elites). |
| **Specialty HTTP Pages** | `/scene-clips`, `/beat-media`, `/scene-fragments`, `/fx06`, etc. | `tools/*.html`, `tools/studio_ui.py`, `tools/studio_canon_routes.py` | Clip range trimmer & library, beat evidence attachment, replay inspector, FX06 pilot workbench. |

---

## 3. Master Representation Audit: All System Domains vs. UI Coverage

Every backend subsystem in Narrative Engine and how faithfully the UI currently represents it:

| # | Core System / Backend Module | What Exists Under the Hood | Current UI Representation | Target / Missing Gap for Full Simulator |
|---|---|---|---|---|
| **1** | **Stage 1 Emergent Simulation & Blackboard** (`story_graph/simulation/contracts.py`, planned Phase 2 behind `cook.py`) | `AgentIntentProposal` competing intents, `BeatBlackboard` arbitration, sensory room barriers (`W_t` world vs `B_t` witness), blocked law violations | **Partial (Phase 1):** `⚡ Stage 1 Weather & Relations` preview card in `ui/compose.js` + full 70/30 interactive Sim Dock in `blueprints/simulate_then_render/mockup_simulate_render.html` | Live backend Stage 1 simulator endpoint feeding real arbitration traces, competing character intents, and room sight/audio barrier toggles directly into Compose's 30% dock. |
| **2** | **Character Minds, ToM & Variant Relationships** (`story_graph/epistemic.py`, `form_graph_store.py`, `DirectedRelationshipEdge`) | Form-specific asymmetric edges (`Francine ↔ Super Butt` vs `Big Booty Peter` vs `Three Little Bitches`), epistemic per-character knowledge sets, Mean Girls minds | **Live UI Shell:** Branching Switchyard + `04 RELATIONSHIP` node + `Relationships Controller` matrix + inline `+ New Character` spawn | Persist `DirectedRelationshipEdge` matrices in SQLite per `(universe, branch, episode)` and expose live **Epistemic ToM Diff** ("who knows what in this scene"). |
| **3** | **Story DAG, World Laws & Timeline Safety** (`story_graph/dag.py`, `world_laws.py`, `state_compiler.py`, `scene_fragments.py`) | Immutable `@LAW` guards, Pass 0-3 Canon-Diff + Auto-Corrections, causal beat DAG, episode rank unlocks anchored by episode ID | **Live:** World Laws editor, Canon-Diff inspector, Beat DAG, `WORLD_LAWS.noir` panel | **Two-Phase Timeline Command Modal** (preview Temporal Locks & Broken Edges before reordering/deleting episodes, as prototyped in `NOIR_KERNEL_V5_BLUEPRINT`). |
| **4** | **Multimodal Media Vault & Stage A/B Grammar** (`prose_engine/scene_clips.py`, `studio_clip_http.py`, `experimental/evidence_sidecar.py`, `TypedMediaPin`) | SHA-256 clip/audio/image pinning with 4 typed roles (`catalyst_trigger`, `relationship_chemistry`, `rhythm_timing`, `personality_mind`) + Bridging Stage Directions | **Split:** `/scene-clips` + `/beat-media` separate HTML pages + Switchyard Drop Tray & Interior Modal | Unified in-app **📦 Plug-and-Play Media Vault Drawer/Modal** inside Studio v2 with automated Stage A visual/audio/power-shift timelines and cross-node pin reuse. |
| **5** | **138-Book Mighty Prose Engine & Anti-Slop PDG** (`prose_engine/conditioner.py`, `slot_infill.py`, `scoped_pipeline.py`, `guards.py`, `protected_spans.py`) | Offline Craft Briefs (`<=130 tok` zero raw excerpt dumps), LUAR/Styleprint cadence matching, 138 verified / 49 quarantined books, SlopCritic, `0%`–`100%` `UpliftSlotPolicy` | **Live Partial:** Highlight locks (`0%–100%`), Engine Drawer `Prose` / `Book Policy` / `Slop` tools | Live **Houdini-style PDG Node Cache Ribbon** (`CACHE_HIT` vs `RECOMPUTED` per beat/slot), unified `CraftOp` dial controls, and click-to-inspect `CraftBrief` token budgets. |
| **6** | **Causal-Temporal Canon & Multi-DB Memory** (`CausalTemporalBridge`, `universe_scope.py`, `source_migration.py`) | 4 Canon modes (`canon`, `non_canon`, `alternate_canon`, `time_travel_canon` with carrier), chained `ep[0..activeRank]` memory, multi-project isolation | **Live UI Strip:** 4-mode Canon Tag Strip + carrier dropdown in `ui/compose.js`; `Memory` modal in `ui/app.js` | Wire `CanonMode` + `CausalTemporalBridge` persistence into SQLite revisions, and add **4 Cross-DB Resource Bridge** toggles (`castRoots`, `pseudoLoraMinds`, `worldLaws`, `mediaVault`). |
| **7** | **Pre-Staging vs. Manuscript Workflow** (`ui/shelf.js` vs `ui/compose.js`) | `Word Prep` stages raw prose/notes with 7 schema node badges before promoting into live SQLite `Compose` blocks | **Live:** Both tabs exist (`⚡ Word Prep` and `✎ Compose`) | Implement 1-click **"Send Prepped → Compose / Graph"** backend serializer that converts `Word Prep` gutter nodes directly into typed SQLite blocks, `@LAW` binds, and FormGraph nodes. |
