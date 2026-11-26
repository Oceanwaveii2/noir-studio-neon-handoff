# NOIR Studio · Sprint 5 handoff for Neon

Open the [standalone golden-path mockup](index.html). The [completed workflow screenshot](completed-workflow.png) shows a draft applied to the alternate branch. The [browser receipt](qa.json) contains the eight checks and the final scene evidence. The [verification script](verify_mockup.py) starts in a fresh Edge browser context. Run it with `py -B verify_mockup.py --receipt qa-replay.json` from this folder using a Python environment with Playwright and Microsoft Edge installed.

## Verified in the simulation

1. Create an empty project. Choose a text source, watch it become ready, and bind it as rhythm evidence. The browser computes SHA-256 on the selected bytes.
2. Add two characters, an alternate form, and a directed relationship.
3. Define a world law and attempt a violating beat. The preview identifies the rule and blocks the save.
4. Establish the prerequisite and fork from the saved setup beat. Save a different fact on each branch and confirm their separation.
5. Watch the five Cook passes and apply the fixture draft. The receipt preserves the source hash, alternate form, relationship, law, and active branch. The test compares the exact UTF-8 bytes of the protected dialogue and verifies that the writable passage changed.
6. Undo the draft and alternate beat across panels. Reload, redo both edits, and reload again. Confirm the saved draft, pass history, and branch evidence. The browser test also checks that text input retains its own Undo shortcut.

Edge passed all eight recorded checks with zero page or console errors and zero HTTP or WebSocket requests. The test opened a local HTML file.

## Readiness evidence for scoring

Baseline percentages come from [Neon’s prior scorecard](../../READINESS_SCORECARD_2026-11-25.md). They are shown in backend / UI parity / live connectivity order. A new production score requires evidence from the live application.

| Pillar | Prior Neon baseline | Sprint 5 mockup evidence | Production evidence still needed |
|---|---|---|---|
| Deterministic World and Counterfactuals | 86 / 88 / 84 | Pre-save rule finding and isolated fork replay | Generic Studio routes, real validator findings, and reload in a fresh Studio project |
| Multiversal Character, Form and Mind | 86 / 88 / 82 | Alternate form and directed relationship included in the fixture receipt | Persistent live graph, Mind resolution, and scene-brief round-trip |
| Multimodal Source Sockets | 84 / 88 / 82 | Real local fingerprint and simulated readiness, binding, and scene-input receipt | Worker extraction, persisted source sockets, and live scene compilation |
| Maestro AI and Five-Pass Compositor | 90 / 88 / 82 | Ten ordered fixture events, exact bytes and saved draft | Live pass stream, real writer receipt, API-routed quality-budget and slop tests |
| Director Cockpit, Audio and Undo | 82 / 94 / 86 | Cross-panel Undo/Redo, persisted replay, desktop and mobile layouts | Sprint 1 production evidence is linked in the scorecard. This mockup has no audio qualification. |

The standalone dependency check verifies that the HTML declares no external scripts, transport calls, or legacy runtime imports. The production API contract and architecture gates belong to the live repository. The fixture draft checks demonstrate exact preservation and visible change, and do not establish the live prose quality threshold.

Related design artifacts include the [Sprint 2 compositor blueprint](../NOIR_5_PASS_STREAM_MOCKUP_2026-11-25/BLUEPRINT.md), [Sprint 3 source socket blueprint](../NOIR_MEDIA_SOCKETS_MOCKUP_2026-11-25/BLUEPRINT.md), and [Sprint 4 counterfactual blueprint](../NOIR_WORLD_LAW_MOCKUP_2026-11-25/BLUEPRINT.md).
