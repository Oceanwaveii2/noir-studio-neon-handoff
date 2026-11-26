# Experimental

Parked, not deleted. Nothing here is imported by the core engine, the CLI, the tests, or CI.

| Path | What it is | Why parked |
|---|---|---|
| `voice/fusion.py` | 3 drafts + synthesis against a rubric | never passed the tell/copy gates; superseded by author-anchored takes |
| `providers/venice.py` | Venice AI adapter | external provider, off by default |
| `providers/gemini_flash.py` | Gemini API + session transport | external provider, off by default |
| `tools/clip_*.py` | clip ingestion, subtitle timing, sound events, CLAP/AST, VAD rhythm | reference-clip research; no book text, no core dependency |
| `tools/calibrate_steering*.py` | layer/alpha steering sweep | calibration gain did not transfer to the benchmark |
| `tools/fuse_demo.py`, `bnb_probe.py`, `local_7b_probe*.py` | one-off probes | research leftovers |
| `tools/inspect_candidates.py` | shows copied drafts next to sources | copy-detector evidence tool |
| `tests/test_voice_fusion.py` | fusion contracts | moves with fusion |

`voice/style_vector.py` and `voice/logit_rules.py` stay in the core package because the optional
local provider imports them; they are not exposed in the core CLI.

## Reviving something

1. Move it back next to its package/tool location.
2. Add its tests back under `tests/`.
3. Run `python tools/ci.py`.
4. Do not re-add it to a default path: opt-in only.
