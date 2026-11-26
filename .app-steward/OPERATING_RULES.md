# Checkpoint-first operating rules

These are custom rules for this user's existing applications, informed by Artcraft's official repository documentation. They do not authorize replacing the application's existing stack, data or instructions.

## Before any meaningful change

Save the last completed action, current task, unfinished action and next exact step. Save/export unsaved buffers and safely pause file writers. Record active agents and actual test results. Capture a verified local checkpoint before reorganizing. If it fails, keep the handoff and stop mutation. No fabricated memory, outputs, tests or approvals.

## Read order

Read the user's current request; the saved original task; existing applicable agent instructions; `.app-steward/policies/project-profile.json`; existing architecture and development records; the current gaps/task; and relevant source files. Existing project-specific requirements take priority over generic layout examples. Surface conflicting requirements instead of deleting one.

## Architecture and code

Keep existing working modules and ecosystem paths unless a reviewed migration justifies the change. Reuse established infrastructure. User-visible operations have explicit input, output, state, error, persistence and undo/cancel contracts. UI and agent adapters call the same core implementation. Separate pure data, operations, persistence/integration, command dispatch and UI responsibilities as appropriate to the real stack. Do not impose Rust, egui, wgpu, WASM, or Artcraft's exact crate names on unrelated projects.

## Files and data

Inventory first. Preserve source assets, provenance, history, external references and licenses. Do not delete, silently merge duplicates, overwrite destinations, reset/clean/stash, change branches, commit, update dependencies, follow symlinks or move nested repositories merely to organize. Keep secrets and recovery snapshots local. Existing database identifiers and schemas do not change with a folder rename. Do not copy live databases as though they were consistent backups.

## Tasks and workers

Use bounded tasks with ownership and acceptance cases. The integrator owns shared registration/manifests. Parallel agents use separate build outputs/runtime ports and never overwrite each other's active work. Record interrupted work durably. Advisory ownership records need enforcement by the actual agent environment; the kit does not control unrelated coding tools.

## Evidence and acceptance

Real checks are the gate. Preserve baseline failures and test floors. Check failure paths, persistence, recovery and visible results, not only menu wiring. Every result records command, revision/fingerprint, output and limitations. Unavailable checks are BLOCKED/UNCONFIGURED. Implemented is not accepted. The kit's graph checker validates declared metadata only; connect actual dependency extraction to CI separately.

## Checkpoint cadence

At session start before organization; before each migration/refactor batch; after a meaningful successful change; before task/agent handoff; before context reduction or shutdown. A fresh checkpoint is required when covered files change. A snapshot of disk cannot preserve unsaved RAM or external services. Do not prune recovery data automatically.

## Completion

Update the gap/task and evidence records, retain the recovery ids, and resume the task saved before the reorganization. Report limitations clearly. Never claim all applications were reorganized because a folder kit was installed.
