# Timeline Command, Temporal Lock & Flag-Disconnect Blueprint

## 1. Core Principle
`RENAME`, `DELETE`, and `REORDER` on Timeline episodes are **Commands**, not raw UI edits. Every episode is coupled to:
- **Timeline Order** (`branch_id`, `position`)
- **Accumulative Memory / Canon** (epistemic state & `@law` rules at episode $N$)
- **Causal Graph (`story_graph`)** (`ENABLES`, `FORKS`, `REQUIRES`, `TEMPORAL_LOCK` edges)

## 2. Two-Phase Command Flow
1. **Phase 1 — `preview_timeline_command(cmd)` (Read-Only Dry Run)**
   - Returns an **Impact Report** without mutating state:
     - `temporal_locks`: hard prerequisites that block moving Episode $B$ before Episode $A$.
     - `broken_edges`: causal edges that would invert or dangle.
     - `memory_flags`: epistemic / world-law violations.
     - `affected_branches`: child forks (`G1`, `G2`) anchored to this episode.
2. **Phase 2 — Writer Choice in Confirmation Modal**
   - **Cancel:** Abort; state remains unchanged.
   - **Disconnect Blocking Flags & Proceed:**
     - Turns off / disconnects the blocking nodes & `TEMPORAL_LOCK` / `REQUIRES` edges preventing the transfer.
     - Executes the `RENAME` / `DELETE` / `REORDER` command.
     - Marks affected episodes with `NEEDS_FLAG_REPAIR` so the writer can fix the flag structures afterward.
3. **Atomic Undo / Redo**
   - Every committed command pushes a pre-command snapshot (order + graph edges + flag states) onto the **Undo Stack** and clears Redo.
   - `Timeline Undo` / `Timeline Redo` restores both episode order and disconnected flags atomically.
