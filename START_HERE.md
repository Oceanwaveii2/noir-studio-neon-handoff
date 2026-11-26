# NOIR Studio download · November 25, 2026

## Open the mockups

Open [Sprint 5 · Fresh-project workflow](deliverables/NOIR_GOLDEN_PATH_MOCKUP_2026-11-25/index.html) in a browser, then read the [Neon handoff](deliverables/NOIR_GOLDEN_PATH_MOCKUP_2026-11-25/NEON_HANDOFF.md).
The package also includes the complete [Sprint 2](deliverables/NOIR_5_PASS_STREAM_MOCKUP_2026-11-25/index.html), [Sprint 3](deliverables/NOIR_MEDIA_SOCKETS_MOCKUP_2026-11-25/index.html), and [Sprint 4](deliverables/NOIR_WORLD_LAW_MOCKUP_2026-11-25/index.html) mockup folders and the blueprint source tree.

## Run the Studio source snapshot

Clone or download the repository. From its root folder, install the dependencies with `py -m pip install -e .` if needed. Run `py -B START_STUDIO.py` and open [the demo](http://127.0.0.1:8788/v2?episode=night-station). The launcher creates an isolated sample workspace in `.noir-demo`. The mockups run directly from HTML and require no Python installation.

The app source is the current H checkout with working-tree changes. Its base Git revision is `6bb6a28e5a5cabea2de238839ec48512db18aec6`. Member hashes describe the packaged bytes. The standalone Sprint 2–5 evidence is separate from live application readiness.

## Size and scope

The package includes active Studio code, UI assets, source tests, blueprints, mockups, and 52 selected book texts. The books are a small reading sample. Book indexes, model weights, raw clips and audio stems, prior builds, credentials, private manuscripts, and the live project database are outside this repository. Library retrieval and legacy manuscript fixtures may require separately configured inputs. No provider is invoked by the launcher.


## Public edition

This edition omits reference-derived audio and private or rights-unclear design references. The audio manifest is empty and the sound UI is outside this public verification. Local development paths in the packaged copy were generalized. The app code, blueprints, mockups, and test evidence are included for review. The [book list](books/SAMPLE_BOOKS.md) links each source and the full notices remain inside the text files.
