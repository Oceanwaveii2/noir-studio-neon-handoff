# Prose Engine — a script doctor's bench

A local, inference-only bench for a comedy screenplay. It is **not** a voice cloner.

Loop: AI-written or partly human draft → engine flags tells → proposes **cuts first**, then span
replacements → enforces canon and spatial continuity → for a beat the author has given a
**DIRECTION**, offers N distinct takes → the author accepts or rejects → every decision is logged.

Success is **author accept rate and post-accept edit distance**. Corpus scores are diagnostics and
must never be targets (`docs/RETRACTIONS.md`).

The active **Codex or Gemini session** is the primary renderer for the story. Downloaded local
models are optional coprocessors: they can propose small edits or variations for the session to
consider. The [U7 experiment](docs/U7_LOCAL_MODEL_RESULTS.md) measures that local role.

## Quickstart

```powershell
python -m unittest discover -s tests -t .                 # 234 tests, no GPU/network

python -m prose_engine condition --file scene.md --out out/run --provider edits --edits drafts.json --apply
python -m prose_engine voice slop    --file scene.md      # rule-based tell flags, no score
python -m prose_engine voice vary    --file scene.md --para 7 --direction "make it worse for her" --provider edits --edits drafts.json
python -m prose_engine voice world   --file scene.md      # canon
python -m prose_engine voice spatial --file scene.md      # rooms, staging, reachability
python -m prose_engine voice ledger  --file scene.md      # beat order and fluents
python tools/workbench.py --file scene.md --provider edits --edits drafts.json
python tools/ci.py                                        # tests + bench + quality budget + manifest
```

Dialogue is **frozen by default** (comedy dialogue is the joke); pass `--allow-dialogue` to opt in.
Book passages never enter prompts; `--allow-book-references` is an explicit override.
Fusion, steering, logit rules, clip/audio tools and the Venice/Gemini providers live in
`experimental/` and are not part of the core loop.

## Layout

```
prose_engine/
  prose_engine/            the package
    diagnostics.py         paragraph metrics + warnings
    style_engine.py        StyleProfile + built-in profiles
    prompt_assembler.py    builds the rewrite prompt
    invariant_gate.py      candidate validation (protected spans, props, epistemic bounds)
    conditioner.py         paragraph planning / application
    corpus.py              book loading, measurements, derived profiles, passages
    cli.py                 command line
    providers/             mock, gemini, venice
  books/
    manifest.json          titles, authors, pages, word counts
    text/*.txt             10 extracted books
    passages.json          selected reference passages
  tools/
    extract_books.py       PDF -> books/text (PyMuPDF)
    build_package.py       copies modules out of narrative_composer (maintenance)
  examples/sample_chapter.md
  tests/
  out/                     generated reports
```

## Quick start

Python 3.11+ and `pydantic` 2.x; `httpx` for the remote providers. `pymupdf` is only needed to
re-extract books.

```powershell
python -m prose_engine books
python -m prose_engine corpus index --out out/corpus_index.json
python -m prose_engine corpus profile --out out/corpus_profile.json
python -m prose_engine corpus passages --count 8
python -m prose_engine diagnose --file examples/sample_chapter.md
python -m prose_engine condition --file examples/sample_chapter.md --out out/sample --provider mock --limit 2 --apply
```

`mock` is offline and deliberately poor — it exists for pipeline tests. For an explicit CLI
generation experiment, choose `--provider venice` or `--provider gemini`.

## Corpus

Ten books, **873,145 words**, extracted from PDF:

| Book | Words |
|---|---:|
| Fool | 81,305 |
| Gentlemen Prefer Blondes | 42,714 |
| Luster | 67,855 |
| No One Is Talking About This | 41,248 |
| Pulp Fiction | 35,091 |
| Star | 90,696 |
| The Love Machine | 177,480 |
| The World Is Full of Divorced Women | 89,100 |
| Valley of the Dolls | 162,951 |
| We Are Never Meeting in Real Life | 84,705 |

Three other PDFs (`sample-miami`, `sample-shihatsu-densha`, `sample-vision`) are single-page
image specimens with no text layer; they are listed in the manifest with zero words and skipped.

Regenerate (needs the source PDFs):

```powershell
python tools/extract_books.py --pdf-dir "D:\path\to\01_Test_PDFs" --out books
```

**Copyright:** the books are third-party material, extracted for local style analysis. Do not
redistribute them.

## Derived style profile

`corpus profile` measures each book and returns a `StyleProfile` JSON:

- **Cadence**: paragraph-level burstiness (mean 15.67 across the corpus) is recorded, but the
  *target* is clamped to 3.5–8.0 — a corpus that varies 10–24 is a human range, and using it as
  a prompt target encourages choppy prose.
- **Sensory vocabulary**: the most frequent lexicon terms across the books become the profile's
  `sensory_preferences`.
- **Dialogue density**: 25.4% of corpus words are spoken; recorded as a voice principle.

Use it with `--profile-file out/corpus_profile.json`.

## Providers and keys

`--provider mock | venice | gemini`.

Keys resolve in this order:

1. explicit `api_key` argument (library use),
2. `VENICE_API_KEY` / `GEMINI_API_KEY` environment variable,
3. `local_secrets.json` at the project root: `{"venice_api_key": "..."}`.

`local_secrets.json` is gitignored and **is present in this checkout** so the engine can be
tested end to end. Treat it as a live credential and rotate it when done.

## Semantic drive: the vector index

The books are not decoration. `corpus vectors` chunks all ten books into **8,262 passages** and
embeds them with a real sentence-transformer model — **all-MiniLM-L6-v2, 384 dimensions** —
L2-normalised, stored in `books/vector_index.joblib` (**13.8 MB**, gitignored, rebuildable).

```powershell
pip install sentence-transformers           # one-time; the model downloads on first build
python -m prose_engine corpus vectors --books books --backend transformer
python -m prose_engine reference --file draft.md --flagged -k 2
```

First build downloads the model (~90 MB) and encodes 8,262 passages in about 2.5 minutes on CPU.
`--backend lsa` builds the older TF-IDF + SVD index (256 dims, 103 MB) when the model is not
available; both are searched with the same cosine interface.

A conditioning run uses the index automatically:

- **retrieval** — every flagged paragraph gets its 3 nearest passages by cosine similarity;
- **prompt** — those passages are placed in the prompt's reference section for a model;
- **voice score** — each paragraph and rewrite is scored by mean top-k cosine against the
  corpus; a rewrite that drops similarity by more than 0.10 is rejected as off-voice;
- **report** — `voice_before` / `voice_after` and the per-paragraph scores are written to
  `report.json` and shown in `review.html`.

Retrieval is semantic, not keyword: on the Foxy Mom script, *"the sedan sits low and patient,
like a dog"* retrieved a door/street passage about a car, the kitchen action retrieved a
kitchen scene, and the car gurgle retrieved a passage set in a car.

### Variants: let the corpus choose

The engine does not have to accept the first rewrite. Write several candidates per paragraph,
and ariants scores each against the vector index, keeps the highest-scoring valid one, and
records the ranking:

`powershell
python -m prose_engine variants --file work/foxy/variants.json --books books --out work/foxy/selected.json
python -m prose_engine condition --file draft.md --provider edits --edits work/foxy/selected.json --apply
`

Example from the Foxy Mom script (six paragraphs, three variants each):

| Paragraph | Best variant | Voice |
|---|---|---:|
| overnight bag / zipper | v2 | 0.530 |
| sedan / dog | v2 | 0.494 |
| Rainee-Peter / lawn chair | v2 | 0.482 |
| arm around waist | v1 | 0.471 |
| wind chime / hose | v2 | 0.447 |
| car gurgle / seatbelt | v1 | 0.410 |

Every candidate is also checked for length ratio, new filter words, and emotion labels; a
variant that fails those is skipped even if it scores higher. Result on the three scripts:

| Script | voice before | hand-picked edit | corpus-ranked variants |
|---|---:|---:|---:|
| Combined | 0.427 | 0.447 | **0.472** |
| Opening | 0.435 | 0.474 | **0.501** |
| Scenes 2–3 | 0.421 | 0.433 | **0.458** |

## How a conditioning run works

1. Split the document into paragraphs (blank-line separated) and diagnose each.
2. Skip paragraphs shorter than 80 or longer than 6000 characters.
3. For each flagged paragraph: build a `ProseRewriteRequest`, assemble the prompt (diagnostics +
   profile + optional reference passages), call the provider.
4. Validate the candidate:
   - invariant gate (protected spans / props / epistemic bounds),
   - length ratio 0.5–2.2,
   - no new filter words or emotion labels,
   - not unchanged, no stray wrapping quotes.
5. Write `proposals.json` + `review.html`; with `--apply`, replace accepted paragraphs by
   character offset into `conditioned.md` and record before/after metrics in `report.json`.

## Local model (offline generation)

Candidate rewrites can be generated on this machine, so the loop needs no API:

`powershell
pip install torch --index-url https://download.pytorch.org/whl/cu126   # GPU build
pip install transformers accelerate
python -m prose_engine generate-variants --file draft.md --out variants.json --provider local --count 3
python -m prose_engine variants --file variants.json --books books --out selected.json
python -m prose_engine condition --file draft.md --provider edits --edits selected.json --apply
`

Model: Qwen/Qwen2.5-1.5B-Instruct (downloaded once, ~3 GB). On an RTX 4080 SUPER it runs at
~14 tokens/s steady state; CPU-only torch is ~1.9 tokens/s, so the CUDA build matters. After the
download the whole loop runs with HF_HUB_OFFLINE=1 set — verified.

Larger models run in 4-bit by default (PROSE_LOCAL_4BIT=0 forces fp16):

`powershell
python -m prose_engine generate-variants --file draft.md --out variants.json 
  --provider local --model Qwen/Qwen3.5-9B --count 3
`

7B in NF4 needs ~5.5 GB of VRAM, so it fits comfortably on a 16 GB card and follows the length
constraint better than the 1.5B model.

The model is a candidate generator, not an authority: its rewrites go through the same guards
(1-3 sentences, a hard word budget, length ratio, filter/label regression, quote balance) and the
vector index picks the best. Ranking applies a length penalty, because raw embedding similarity
rewards padding: a 5x expansion scores higher than the original even though it is worse prose.

## Style guide (from the writing-samples method)

The strongest lever is not the model, it is a style guide built from real samples: examples
plus a sentence-level analysis of them.

`powershell
python -m prose_engine style guide --samples draft.md --out out/style_guide.json
python -m prose_engine variants --file variants.json --books books --style-guide out/style_guide.json --out selected.json
`

The guide records mean sentence length and variation, short/long/fragment percentages, sentence
openings, punctuation habits, simile and sensory density, plus exemplar passages. Ranking adds a
style-fit term (0.25 weight); generation puts the guide in the prompt. Strategies are generated
per paragraph (image, action, understatement, rhythm) and every candidate is checked for fact
preservation (names, numbers, props, quoted lines) before it can be selected.

## Who writes the candidates

DeepSeek (this assistant) writes them in-session and the engine ranks/applies them; that is
cheaper than local inference and measurably better than the 1.5B/7B models on detail retention.
The local providers remain available (--provider local|deepseek) but are optional.

Candidates are generated per strategy (image / action / understatement / rhythm) with concrete
pattern constraints, a retrieved pattern exemplar, the house style guide, and the fact rules.
Ranking weights novelty (1 - token overlap with the original) at 0.15 and rejects near-copies
(overlap > 0.82); the length floor is 0.4 so terse strategies can qualify.

Trade-off: novelty and corpus voice pull against each other. Terser re-conceptions score lower
on voice (0.45 vs 0.49) but are genuinely different sentences instead of paraphrase.

## Document-level tells

Paragraph diagnostics cannot see rhythm that lives between lines, so a separate pass checks the
whole document:

```powershell
python -m prose_engine tells --file ../node_engine/docs/00_combined_conditioned.md
```

| Rule | Fires on |
|---|---|
| `BEAT_DIRECTION` / `BEAT_OVERUSE` | explicit `Beat.` stage directions (more than four = warning) |
| `DENIAL_PLUS_BEAT` | a bare denial ("Absolutely not.") answered by `Beat.` |
| `TRIPLET_REPEAT` | "Okay. Okay. Okay." style repetition |
| `CLIPPED_RUN` | three or more consecutive lines of four words or fewer |
| `SIMILE_DENSITY` | more than 8 "like a / as if" constructions per 1,000 words |

These are the patterns that make a draft read as machine-written even when every sentence is
clean. Rewrites are not automatic: the engine reports them, then `apply-fixes` (or a model) can
replace the offending node.

## Limitations

- **The sensory lexicon is ~100 terms.** Good prose that uses sensory words outside it (e.g.
  "rain", "tin roof") is flagged as a "Sensory deficit". The diagnostic is a net, not a judge.
- **Cadence is paragraph-local.** Whole-book burstiness (10–24) is not comparable to the
  rewrite target; only sampled paragraph cadence feeds the profile.
- **No scene or character memory.** Unlike the Narrative Composer, this engine rewrites
  paragraph by paragraph; it cannot enforce cross-paragraph continuity, who knows what, or
  prop state. (The invariant gate supports those checks if a caller supplies the data, but the
  standalone CLI does not build it.)
- **PDF extraction is approximate.** Multi-column layouts and running heads can reorder text;
  the manifest records page and word counts so drift is visible.
- **`mock` is deliberately poor.** It exercises the pipeline; it is not a prose model.

---

## Per-book influence (levels)

Every reference book has a level that controls its share of retrieved passages, **independent of
how many words it contributes**. Stored in `books/influence.json`.

| Level | Weight | Meaning |
|---|---:|---|
| `off` | 0 | excluded from retrieval |
| `whisper` | 0.25 | rare |
| `normal` | 1 | default |
| `strong` | 2 | twice a normal book's share |
| `dominant` | 4 | four times |

```powershell
python -m prose_engine influence show
python -m prose_engine influence set valley_of_the_dolls_jacqueline_susann strong
python -m prose_engine influence set sample_vision_by_nastka_drabot off
python -m prose_engine influence mode balanced   # fair share by level (default)
python -m prose_engine influence mode volume     # score × weight, size still counts
```

`balanced` uses repeated fair-share selection: with ten books at `normal`, a six-passage
reference set comes from six different books. `volume` reproduces the old size-proportional
behaviour, tunable per book.

## Rewrite strength

condition --strength controls how far the rewrite is allowed to move from the original:

| Preset | References | Max overlap | Length | Directive |
|---|---:|---:|---|---|
| light | 2 | 0.85 | 0.5–1.5× | smallest change that clears the flag |
| standard | 4 | 0.70 | 0.4–2.0× | rewrite in place |
| 
ebuild | 6 | 0.45 | 0.6–1.8× | write the beat anew; paraphrase is failure |

`powershell
python -m prose_engine condition --file draft.md --out out/run --provider edits \
  --edits edits.json --strength rebuild --references 6 --apply
`


ebuild rejects a candidate whose word overlap with the original exceeds 0.45 — a polished
paraphrase fails, and the model must rebuild from the facts and the reference passages. Six
references (one per book, under influence mode balanced) push the books harder; set a book to
strong or dominant if it should dominate the voice.

## Contrastive exemplars and preference calibration

**Contrastive exemplars** — `rebuild` (and `--contrastive`) appends AI-voice negatives to the
prompt, matched to the paragraph's warnings: the simile pileup shows the simile failure, the
filter-word paragraph shows filter verbs. The bank lives in
`prose_engine/data/ai_voice_negatives.json`; the model is told DO NOT IMITATE and why.

**Preference calibration** — every conditioning run writes `proposals.json` with accepted/rejected
decisions. `prose_engine preferences` reads them and reports the overlap and length ranges that
were actually accepted, plus a suggested preset:

```powershell
python -m prose_engine preferences
# decisions: 235 (197 accepted, 38 rejected)
# accepted_overlap_max: 0.862
# suggested preset: {"max_overlap": 0.88, "ratio": [0.37, 2.14]}
```

That is evidence, not a model: it tells you whether a preset is stricter than your own decisions.
Use it to tune `strength.py` deliberately rather than by feel.

## Style distance and the voice card

Cosine similarity says "about the same thing"; it does not say "sounds like the same writer".
`styleprint` measures 83 stylometric features over the ten books — function-word rates,
punctuation per 1,000 characters, sentence-length distribution, dialogue share, contraction
rate — and stores the corpus mean/SD in `books/styleprint.json`.

```powershell
python -m prose_engine.styleprint build --books books
python -m prose_engine.styleprint show --file draft.md --books books
```

Per-feature z-scores are capped at ±3 so one noisy rate in a short paragraph cannot dominate.
Across the ten books the distance to the corpus centroid runs 0.62–1.99; anything well above
that is drifting.

`tools/voice_card.py` writes `books/voice_card.md` — the measured habits as instructions:

> sentence length: mean 11.2 words; 37% under 7 words; 7% over 25 · dialogue: 29% of words in
> quotes · 10 commas / 1,000 chars · 26 contractions / 1,000 words · openers: So, The, But, He…

`condition` puts that card in the prompt and records `style_before` / `style_after` per proposal.
A rewrite more than **0.75** further from the corpus than the original is rejected as off-voice;
small drift is allowed, because a paragraph is not a novel.

## Voice engine

Eleven inference-side tools for pushing the output toward the books, built per
`docs/PLAN_VOICE_ENGINE.md`.

```powershell
python -m prose_engine voice eval --file draft.md          # similarity + percentile + tics
python -m prose_engine voice tics --file draft.md          # measured tells
python -m prose_engine voice report                        # acceptance ledger
python -m prose_engine condition --file draft.md --out out/run --strength rebuild `
  --references 6 --retrieval style --apply                 # style-retrieved references
python -m prose_engine voice rewrite --file paragraph.md --provider local `
  --candidates 4 --out out/rewrite.md                      # retrieve, sample, select, critique
```

- `voice/evaluate.py` — corpus similarity and percentile, decision ledger
- `voice/tics.py` — participial tails, excess lexicon, negative parallelism, filter words, beat cues
- `voice/retrieve.py` — stylometric style index (8,262 passages), `StyleDrive`
- `voice/style_vector.py` — contrast-pair direction + forward hook, `tools/calibrate_steering.py`
- `voice/best_of_n.py` — sample N, score, accept only on a margin
- `voice/logit_rules.py` — `BannedPhraseProcessor` (comparisons)
- `voice/scene.py`, `bible.py`, `epistemic.py` — scene contract, typed bible, knowledge ledger
- `voice/critique.py` — one external-feedback revision
- `voice/pipeline.py` — orchestration

## Environment (this machine)

- `HF_HOME=H:\NOIR_LOCAL\hf` — model cache lives off the system drive; Qwen3.5-9B (18 GB) and
  all-MiniLM-L6-v2 are there. Old C: cache keeps only the art/whisper models.
- CUDA 12.6 toolkit; `causal-conv1d 1.7.0` built, `triton-windows 3.9`, `flash-linear-attention 0.6.0`
  (needed for Qwen3.5's hybrid layers; without them generation is ~100× slower).
- Rebuilding `causal-conv1d` needs `vcvars64.bat` + `DISTUTILS_USE_SDK=1` + `CUDA_HOME`.

## Appearance canon (image → constraints)

An appearance image is not a prop; it becomes a schema the story must respect.

```powershell
python tools/build_appearance.py --image images/rainee_peter.png --entity rainee
python -m prose_engine voice appearance show --file appearances/rainee.json
python -m prose_engine voice appearance check --text-file draft.md --appearance appearances/rainee.json
```

The schema (`appearances/<entity>.json`) holds:

- `immutable_base_traits` — may be altered by a transformation, never erased
- `state_deltas` — per-state traits (`pre_transformation`, `peter`, …)
- `forbidden_claims` — phrases the prose may never use
- `palette`, `silhouette`, `notes`
- `image` + `image_sha256` — the canon is pinned to the exact file

`tools/build_appearance.py` reads the image with Qwen3.5 (image-text-to-text) and writes the JSON;
you review it, and from then on the gates read the JSON, never the pixels. `appearances/rainee.json`
is a placeholder schema until the reference image lands.

## Two modes: correction and variation

The workbench has a mode switch:

- **Correction** — keep the passage, remove the AI tells, apply the direction as a note. Dialogue
  is corrected too unless you mark it keep (brief) or pass --freeze-dialogue; human lines are
  protected, AI-written ones are fair game.
- **Variation** — correction plus the variation engine: three treatments of the same passage
  (nanite malfunction, staged, curse), guided by the direction box under that passage. For text
  that is AI from the start.

```powershell
# correction: light edits, dialogue frozen
python -m prose_engine condition --file scene.md --out out/fix --provider local `
  --strength light --freeze-dialogue --apply

# variation: four treatments of the same beat
python tools/variations_demo.py
```

`voice/variations.py` drives variation by **treatments** (nanite malfunction, wish gone wrong,
curse, medical, dream, staged, inheritance), one draft each, with cross-variant overlap filtering
and tell scoring. Resampling one prompt does not vary the text: measured pairwise overlap of
three samples was 0.62–0.86.

## Per-passage strength (the DLSS knob)

A strength map assigns each paragraph 0–1:

| Band | Mode | Effect |
|---|---|---|
| 0.00–0.15 | frozen | never touched |
| 0.15–0.45 | light | copy-edit, keep sentences |
| 0.45–0.75 | standard | rewrite in place |
| 0.75–1.00 | rebuild | write from the facts |

```json
{"default": 0.6,
 "rules": [{"selector": "range:0-4", "strength": 0.0},
           {"selector": "contains:dialogue", "strength": 0.15},
           {"selector": "index:7", "strength": 1.0}]}
```

```powershell
python -m prose_engine condition --file scene.md --out out/run --provider local `
  --strength-map map.json --freeze-file frozen.txt --apply
```

Frozen spans are exact strings that must survive verbatim; `missing_frozen` rejects a rewrite
that drops or alters one. `--freeze-dialogue` freezes every dialogue paragraph automatically.

## Chunking

The workbench does not split on blank lines. oice/chunking.py groups a screenplay properly:
a cue + its parentheticals + its dialogue lines are one block labelled by character; the scene
heading joins only the first action paragraph; later action paragraphs stay separate; short
lines merge into their neighbour. On the combined script this is 123 blocks instead of 261.

## Slop score is uncalibrated

ooks/slop_eval.json records the only honest number: a page-grouped held-out split of the single
corrections PDF. Read it before trusting a score:

`powershell
python tools/eval_slop.py        # writes books/slop_eval.json
python -m prose_engine voice slop --file scene.md
`

The CLI prints the calibration line first. A single correction document cannot give a
document-level split, and the harness says so.

## Timeline Studio

Run `python tools/studio_ui.py` and open the local address it prints. Choose a timeline episode to compose in separate script blocks. Use `python -m prose_engine scoped --help` for the same timeline operations from the command line. See [U10](docs/PROJECT_TIMELINE_U10.md) and the [UI/UX design report](docs/UI_UX_DESIGN_REPORT.md).

## Standalone Workbench

A local, stdlib-only server: the original text stays visible, paragraph by paragraph, with a
strength slider and a Rewrite button. The original file is never modified; accepted rewrites go
to a conditioned copy.

`powershell
python tools/workbench.py --file scene.md --provider local --port 8765
# or offline, against prepared edits:
python tools/workbench.py --file scene.md --provider edits --edits edits.json
`

Open http://127.0.0.1:8765. Each paragraph shows its original text, a strength slider
(0 = frozen, 1 = rebuild), and the rewrite with its reject reasons. **Save conditioned copy**
writes out/workbench/conditioned.md plus decisions.json.

## Local CI and the pre-commit hook

`powershell
python tools/install_hooks.py   # installs hooks/pre-commit into .git/hooks
python tools/ci.py              # verify (tests + evidence) -> bench (budgets) -> manifest
`

The hook runs the same CI before every commit and blocks it on failure. Bypass once with
git commit --no-verify. The hook is stored in hooks/ so a fresh clone can reinstall it.

## Tests

```powershell
python -m unittest discover -s tests -t .
```

## Provenance

Extracted from `narrative_composer/prose/` at commit `6bb671a` of the Narrative Composer. The
screenplay-specific bridge (`composer_bridge.py`, which depended on the AST/scene models) is
intentionally not included: this engine works on paragraphs, and the CLI is the integration
point.
