# Five-pass compositor UI blueprint

Open [the interactive mockup](index.html) and choose a scenario. The page runs from a local file and uses fixture text, scores, and stream events.

The dark controls show run state and the selected pass. The parchment panel keeps the saved passage, exact dialogue, and draft visible. The event panel shows the arrival order and lets the author tell a disconnected stream from a failed writer.

| Pass | What the UI shows | Evidence the app would need |
|---|---|---|
| 1. Structure and protection | Saved blocks and exact dialogue locks | Notebook revision, passage bounds, and protection revision |
| 2. World graph and sockets | Resolved cast, forms, and scene graph | Saved node and socket references |
| 3. Bindings and replay | Bound cues, timing, and replay inputs | Preparation receipt and the references actually used |
| 4. Passage realization | Writer progress followed by the rough draft | Run ID, attempt ID, and a durable writer receipt |
| 5. Polish and byte checks | Checked draft, score delta, and exact-dialogue result | Saved draft ID and recorded diagnostics |

## Simulated scenarios

- **Complete run** shows the running and completed state for each pass. The checked draft becomes available to apply to the preview after the fifth pass.
- **Stream disconnect** keeps the run identity and its event history. Reconnecting recovers the writer result without a second writer start.
- **Writer fails once** exposes an explicit retry after a definite failure. The three completed preparation passes stay visible.
- **Fully protected passage** shows why realization and polish were skipped. The saved passage remains visible.

## Future integration

Use one scoped run identity and ordered, replayable events. Each event carries its sequence, pass, state, and a short human-readable detail. On reconnect, replay after the last received sequence and deduplicate against the current run. Connection loss does not establish whether the writer failed. If the outcome is uncertain, recover the existing attempt before offering another send. Enable applying a draft only after its saved receipt and protection checks are available. The mockup applies changes to its own page state.

The pass names and boundaries follow the [compositor specification](../../docs/specs/COMPOSITOR_BREAKDOWN.md). The dark controls and parchment preview follow the [Simulate-Then-Render mockup](../../blueprints/simulate_then_render/mockup_simulate_render.html).
