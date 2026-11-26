# Sprint 3 · Media source sockets UI blueprint

Open [the interactive mockup](index.html) in a browser. Try a sample or select a fixture outcome and drop an image, audio clip, video, or document. Inspect its job, choose a socket, and use **View input payload** to see the resulting scene-input preview.

## Behavior in the mockup

| State | What the author sees and can do |
|---|---|
| Queued | The vault shows the source and its current attempt. Duplicate bytes reopen the existing source even if the filename differs. |
| Processing | The vault shows work in progress. A reload requeues an interrupted simulated job. |
| Ready | Bind the source to the beat anchor, character node, or style-reference slot. The scene input includes the typed socket, SHA-256, and fixture signal. |
| Partial | The inspector shows an unavailable extractor warning. The author can bind the metadata, then retry against the same source. A missing signal is represented as null. |
| Failed | The inspector shows the processing error and a retry. The source becomes bindable after recovery. |

SHA-256 is computed from the actual file bytes in the browser. The mockup stores filenames, sizes, types, hashes, job states, and bindings in browser storage. Extraction and the scene-input assembly are simulated. Unbind removes the link to the scene and retains the source in the vault.

## Proposed Studio integration

- Give Intake, Media Vault, Analysis Lab, and Shelf the same workspace-scoped asset and job identity. Deduplicate by SHA-256 inside the workspace. A worker owns each processing attempt and publishes its status after the state is saved.
- Persist source metadata independently of extractor results. Store extractor availability and failure codes alongside any usable output. Retry the same job with a new attempt. A late result from an earlier attempt cannot supersede the active attempt.
- Bind the asset and its evidence revision to a typed target in the selected episode and branch. Beat timing, character evidence, and style references retain distinct roles. Pass metadata-only references through with explicit availability, leaving unavailable signals empty.
- Resolve those bindings in Scene Plan and show the evidence the compiler actually used. The live verification gate still requires a real intake request, persisted worker results, and a scene compilation after reload.

The [Studio subsystem map](../../docs/UI_SYSTEM_MIND_MAP.md) describes the media surfaces. This mockup uses the same Night Station fixture as the [five-pass compositor simulation](../NOIR_5_PASS_STREAM_MOCKUP_2026-11-25/index.html).
