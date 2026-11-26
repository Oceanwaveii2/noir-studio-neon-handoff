# Noir Fiction Engine — Full Architectural Breakdown & 5-Pass Wordcraft Compositor Plan

*Extracted to plain Markdown from `NOIR_FULL_BREAKDOWN_AND_COMPOSITOR_PLAN.pdf` (November 18, 2026) so agentic coders can read all constraints reliably without binary PDF parsing.*

---

## 1. Forensic Post-Mortem: Anti-Patterns to Avoid

1. **Reviewer & Audit Bureaucracy Everywhere:** Never require human `reviewer`, `approval`, `review_request`, or `ELIGIBLE_FOR_REVIEW` gates for Import, Cook, Generate, or Apply. Where legacy SQLite tables (`events`, `beat_anchors`) require a `reviewer` column internally, auto-populate `'author-auto'` silently.
2. **Potemkin Delivery (Passing Without Writing):** Never write setup scripts that pre-populate finished dialogue or use `origin: imported` (`scene.bridge.save`) to fake generation tests. Positive generation tests must start from an unwritten placeholder and prove `provider_calls >= 1` with a verified `writer_receipt`.
3. **Disconnected Pilot Islands:** Never add new `fx06.*`, `scene.minds.*`, or scene-specific endpoints to `EpisodeCommands`. Route all generation through `WritingRuns` (`run.selection` / `run.start`) and the 5-Pass Compositor Pipeline.
4. **Split-Brain Runs & Response-Loss Gap:** `AttemptJournal` must persist raw `response_text` and `response_sha256` in SQLite **before** returning from the provider adapter (`session_attempts.py` / `deepseek_session.py`), eliminating the crash window between provider completion and draft commit.
5. **Guardrail Suffocation of the Writer:** Avoid forcing verbatim stage-direction echoing or `<=300` char dialogue-only slots when `conditioner.py` / Beat Slot Realization should realize vivid stage action, reactions, and dialogue in one coordinated director/writer pass per beat group.

---

## 2. Multi-Pass 'Wordcraft Compositor' Architecture

Passes 1–3 (Structure, Graph/Socket Extraction, and Multimodal State Replay) are separate, inspectable deterministic passes. Pass 4 keeps all active speakers in one coordinated director/writer pass per beat group, followed by Pass 5 (`conditioner.py` polish + mechanical byte splice).

| Compositor Pass | Input → Automatic Operation | Durable Output & Socket Contract | LLM Cost |
| :--- | :--- | :--- | :--- |
| **PASS 1 · Wordcraft Structural Ingest** | Formatted text/script (headings, stage notes, speaker cues, narrator blocks) → `cook.py` + `notebook.py prepare_structure`. | Typed Notebook Blocks (`scene-heading`, `stage-direction`, `character`, `narrator`, `cue_prefix`) + Unicode code-point Masks (`100%` hard locks vs `25%` editable). | **0 Calls** (Deterministic) |
| **PASS 2 · World Graph & Empty Sockets** | Typed blocks → `scene_fragments.py` + `form_graph_store.py` auto-extracts beats, locations, and speakers. | Executable `SceneFragment` Beat DAG + Auto-Created Character Junctions & Empty Form/Mind Sockets. Zero external Python setup scripts required. | **0 Calls** (Optional 1 Analyst call on raw video) |
| **PASS 3 · Multimodal Binding & Replay** | Author attaches packages to sockets: Mean Girls → 3 Mind ports; Cutaway → Split/Reunion/Relapse; Fart Media → Timing & Scents; Books → Topic/LUAR/Style. | Compiled Turn & Social Pressure Ledger (`scene_plan.py`): Active forms per beat, Francine–Rainee marriage, full `when->try` cards, pause cues, scent rules. | **0 Calls** (Deterministic Causal Replay) |
| **PASS 4 · Slot-Based Scene Realization** | Turn Ledger + Book Craft Cards → Primary Writer via `WritingRuns` & `AttemptJournal`. | Rough Scene Draft: Writer realizes both vivid stage action/reactions and dialogue per beat slot. Raw response bytes saved atomically in `AttemptJournal` BEFORE validation. | **1 Writer Call** (Capped & Recoverable) |
| **PASS 5 · Prose Engine Polish & Splice** | Rough Draft → Bounded `conditioner.py` pass + mechanical byte splice in `notebook.py`. | Polished Episode Draft: Sharpens comedic pause, cadence, and subtext inside masks, then splices between exact original bytes. | **0–1 Call** (Rough draft kept if skipped) |

---

## 3. Ironclad Guardrails for Receiving Coding Agents

1. **NO REVIEWER OR APPROVAL GATES:** When the author clicks Import, Cook, Generate, or Apply, Noir executes automatically. Auto-populate `'author-auto'` silently where legacy schemas require a reviewer column.
2. **NO MORE STANDALONE AUDIT ESSAYS:** Do not write new `*_AUDIT.md`, `*_TRACE.md`, or `*_REVIEW.md` reports in place of fixing code. Close tasks with working code, automated regression tests, and machine-readable receipts.
3. **NO POTEMKIN SETUP SCRIPTS OR PRE-SEEDED PROSE:** Positive generation tests must prove `provider_calls >= 1` with a verified `writer_receipt`.
4. **NO NEW BESPOKE PILOT ROUTES:** Route all generation through `WritingRuns` (`run.selection` / `run.start`) and the 5-Pass Compositor Pipeline.
5. **ATOMIC RESPONSE RECOVERY:** `AttemptJournal` persists raw `response_text` and `response_sha256` in SQLite before returning from the provider adapter.
6. **PRESERVE THE TEST FLOOR:** Run `py -B tools/ci.py --core` after every change (`>= 572` core baseline tests passing, `5/5` architecture fixtures passing).
