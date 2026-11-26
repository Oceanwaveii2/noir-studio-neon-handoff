# Coding and verification workflow

This project applies the attached Application Steward kit to the existing Python narrative app. The kit is already installed; the project adds its own boundaries, command contracts, test floor, task scope and evidence. The kit's Artcraft source policy governs the kit's design references. It does not require adopting Artcraft's stack or replace the project's separate [upgrade research](research/ADVANCED_UPGRADE_RESEARCH_PLAN_2026-11-08.md).

## Before changing code

1. Read [AGENTS.md](../AGENTS.md), the [operating rules](../.app-steward/OPERATING_RULES.md), the [Fiction Engine profile](../.app-steward/policies/project-profile.json), and the latest local handoff. Record the last completed action, unfinished work, exact next step and actual baseline. Verify the relevant files against a complete recovery checkpoint before changing them; take a fresh checkpoint if the covered paths drift or a migration is planned.
2. Choose one outcome from the [gap register](../.app-steward/tasks/gaps.json). Copy the [task template](../.app-steward/tasks/task-template.json) to a task-specific file. Name an implementation owner, set owned and forbidden paths, identify the reviewer role, and write acceptance cases for the normal path and applicable failure, persistence, recovery and cancellation paths. One integrator owns shared registration. Do not infer acceptance from a role assignment.
3. Check the [module map](../.app-steward/architecture/modules.json) and [behavior registry](../.app-steward/behavior/commands.json). Keep story state and typed transitions in `story_graph`; keep candidate generation and validation in `prose_engine`. Keep Studio, Workbench and automation at the boundary. When routes differ today, capture the difference in the contract and a gap; do not document intended parity as working behavior.

## What to run

| Check | Command | What it establishes |
|---|---|---|
| Core, no external model resolution | `python -B tools/ci.py --core` | Actual Python import boundaries with a floor of 542 passing core fixtures and five passing architecture fixtures. The suite uses a local Studio test server on port 8795 and temporary fixtures, including temporary proposal telemetry. It requires the core dependencies and loopback. |
| Kit's declared graph | `python -B _APP_STEWARD/code/steward.py --root . validate-architecture` | Checks module paths and declared layer direction. The separate CI check parses real Python imports, including function-local static imports, within the five declared top-level directories. It does not prove runtime dependencies or track dynamic imports. |
| Current master canon | `python -B tools/check_canon.py` | Read-only manuscript check. The existing frozen conflict still exits 1; it needs a scoped author decision. It is not covered by passing fixture tests. |
| Release | `python -B tools/ci.py` | Bounded full verification, local benchmark, quality, hybrid and manifest stages. Model downloads are disabled by default; opt into the model benchmark with `--models`. Run in an isolated copy because release stages write reports and may write a manifest. See [U8 release and recovery](U8_RELEASE_RECOVERY.md). |

The kit's migration runner requires its own exact reviewed commands; that list remains empty. The commands above are project entry points and can be run directly. File moves and layout changes still require a separate reviewed migration. No external service or model is required for the core fixture command; model checks, data transfer and media analysis retain their separate project permissions.

The import check rejects reverse imports. NE-008 was addressed by passing editorial cliché
findings into telemetry, rather than importing the editorial layer from telemetry.

## Close a task with evidence

Record the exact command and exit, the working-tree fingerprint or affected file hashes, visible behavior where relevant, unresolved failures and the next step. Do not overwrite historical receipts or treat a passing fixture, hardcoded demo count or LLM score as author acceptance. Save detailed logs and snapshots locally. Keep scoped verification separate from [release and author acceptance](ACCEPTANCE.md).

This integration changed development tooling and project records. It did not consolidate editorial routes, change Studio behavior, touch manuscripts, move folders, or alter quality thresholds. The next behavior change is the [NE-001](../.app-steward/tasks/gaps.json) three-beat pilot for protected dialogue, continuity and direction-led variation.
