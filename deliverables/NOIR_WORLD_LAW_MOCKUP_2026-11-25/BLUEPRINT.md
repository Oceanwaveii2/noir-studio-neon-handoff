# Sprint 4 · World laws and counterfactual validation blueprint

Open [the interactive mockup](index.html) in a fresh browser profile to start with an empty Main branch. Add a world law such as **vault-access**, with **Open vault** as the action and **Key recovered** as the required world fact. Create a beat that attempts the action. The preview shows the blocking rule and affected beat before any save. Use **Jump to beat** to focus the action, **Stage prerequisite** to preview adding a setup beat, or **Discard edit** to restore the saved view.

## Simulation behavior

| Area | Behavior |
|---|---|
| World state | A typed action checks facts established by earlier valid beats. A fact established by the current beat becomes available afterward. |
| Character knowledge | The observer learns the fact when their evidence channel is open. A closed channel leaves the fact in world state and withholds it from that witness. |
| Validation | The preview replays the whole proposed branch. Findings identify the rule, severity, affected beat and suggested remedy. Earlier edits can invalidate later saved beats. |
| Remediation | **Stage prerequisite** proposes an earlier world fact or open observation for the currently edited beat. Saving commits the prerequisite and the edit together after replay succeeds. |
| Branching | A fork captures the saved prefix through the selected beat. Forking from project start captures an empty prefix. Inherited beats are read-only. Future suffix edits replay only in the selected branch. |

The preview displays the active branch, world facts, and facts known from the selected viewpoint. **View replay payload** shows the structured findings and replay result. Saved laws, branches, and beats persist in browser storage.

## Proposed Studio integration

- Scope a preview to the selected project, universe, branch, and saved revision. The document and graph editors should call the same validator. Return structured findings with stable rule and beat or node IDs, severity, and suggested remediation.
- Resolve the branch from its saved fork point and ordered local transitions. Check world facts and viewpoint knowledge separately. Link every emitted fact or observation to its evidence and channel.
- Commit only the proposed patch that passed replay against the current revision. If the revision changed, recheck the patch. A compound prerequisite and beat edit belongs to one recoverable command.
- Keep scenario-specific starting facts in seed adapters. Use project-scoped generic validators and branch operations. Live acceptance still requires a new empty Studio project and a real endpoint, author edit, saved fork, and deterministic reload.

References include the [Timeline command blueprint](../../blueprints/v7_parallel_analysis/TIMELINE_COMMAND_BLUEPRINT.md) and the [Studio subsystem map](../../docs/UI_SYSTEM_MIND_MAP.md).
