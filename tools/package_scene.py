"""Build one folder (and zip) with everything related to the Rainee scene."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "rainee_scene_package"


def copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def house_diagram(target: Path) -> None:
    from PIL import Image, ImageDraw

    floors = [("Ground", "ground"), ("Upper", "upper"), ("Basement", "basement")]
    tiles = []
    for title, stem in floors:
        data = json.loads((ROOT / "books" / "ling_house" / f"{stem}.json").read_text(encoding="utf-8"))
        points = [point for room in data.get("rooms", []) for point in room["polygon"]]
        min_x = min(point[0] for point in points); max_x = max(point[0] for point in points)
        min_y = min(point[1] for point in points); max_y = max(point[1] for point in points)
        width, height, pad = 760, 520, 40
        scale = min((width - 2 * pad) / max(1e-6, max_x - min_x), (height - 2 * pad) / max(1e-6, max_y - min_y))
        image = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((pad, 10), title, fill="black")
        for room in data.get("rooms", []):
            xy = [(pad + (x - min_x) * scale, pad + (y - min_y) * scale) for x, y in room["polygon"]]
            draw.polygon(xy, fill=(226, 232, 240), outline=(51, 65, 85))
            cx = sum(point[0] for point in xy) / len(xy)
            cy = sum(point[1] for point in xy) / len(xy)
            draw.text((cx - 4 * len(room["label"]) / 2, cy), room["label"], fill="black")
        for door in data.get("doors", []):
            (x1, y1), (x2, y2) = door
            draw.line(
                [(pad + (x1 - min_x) * scale, pad + (y1 - min_y) * scale),
                 (pad + (x2 - min_x) * scale, pad + (y2 - min_y) * scale)],
                fill=(220, 38, 38), width=3,
            )
        tiles.append(image)
    combined = Image.new("RGB", (tiles[0].width, sum(tile.height for tile in tiles)), "white")
    offset = 0
    for tile in tiles:
        combined.paste(tile, (0, offset))
        offset += tile.height
    target.parent.mkdir(parents=True, exist_ok=True)
    combined.save(target)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)

    # 01 scene
    for name in ("script.md", "script_cleaned.md", "start_scene_corrected.md", "start_scene_deepseek.md",
                 "start_scene_annotated.md", "start_scene_v2.md"):
        copy(ROOT / "work" / "americandad" / name, OUT / "01_scene" / name)
    for name in ("TYPED_DRAFT_with_red.html", "TYPED_DRAFT_with_red.png", "ORIGINAL_SAMPLE_with_notes.md"):
        source = ROOT / "work" / "americandad" / name
        if source.is_file():
            copy(source, OUT / "01_scene" / name)

    # 02 guidelines
    for name in ("world_state.json", "editorial_notes.json", "author_decisions.json", "style_card.json"):
        copy(ROOT / "books" / name, OUT / "02_guidelines" / name)
    copy(ROOT / "docs" / "RETRACTIONS.md", OUT / "02_guidelines" / "RETRACTIONS.md")

    # 03 references
    for path in (ROOT / "references" / "clips").glob("*.json"):
        copy(path, OUT / "03_references" / path.name)
    copy(ROOT / "references" / "clips" / "README.md", OUT / "03_references" / "README.md")
    copy(ROOT / "references" / "clips" / "youtube_sources.md", OUT / "03_references" / "youtube_sources.md")

    # 04 clips: audio -> mp3, subs as-is
    audio_dir = OUT / "04_clips" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for wav in (ROOT / "references" / "clips" / "audio").glob("*.wav"):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "128k", str(audio_dir / (wav.stem + ".mp3"))],
            check=False,
        )
    for vtt in (ROOT / "references" / "clips" / "subs").glob("*.vtt"):
        copy(vtt, OUT / "04_clips" / "subs" / vtt.name)

    # 04 clips: analysis outputs + detection tooling
    analysis = OUT / "04_clips" / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    profile_paths = sorted((ROOT / "references" / "clips").glob("*.json"))
    for path in profile_paths:
        copy(path, analysis / path.name)

    rows = [
        "# Fart and sound capture",
        "",
        "What the pipeline found in each reference clip.",
        "",
        "| Clip | Duration | Speech | Longest gap | wpm | AST body-sound hits | Seeded CLAP | VAD turns |",
        "|---|---:|---:|---:|---:|---|---|---:|",
    ]
    details = []
    for path in profile_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        speech = data.get("speech", {})
        sound = data.get("sound", {})
        classification = sound.get("classification", {}) if isinstance(sound, dict) else {}
        hits = classification.get("hits", []) if isinstance(classification, dict) else []
        seeded_block = data.get("events_seeded", {})
        seeded = seeded_block.get("hits", []) if isinstance(seeded_block, dict) else []
        dialogue = data.get("dialogue", {})
        hit_text = ", ".join(f"{hit['time']}s {hit['label']} {hit['score']:.2f}" for hit in hits) or "none"
        seeded_text = ", ".join(f"{hit['start']}-{hit['end']}s p={hit['confidence']:.2f}" for hit in seeded) or "-"
        rows.append(
            f"| {path.stem} | {speech.get('duration', 0):.1f}s | {speech.get('speech_seconds', 0):.1f}s | "
            f"{speech.get('longest_gap', 0):.1f}s | {speech.get('words_per_min', 0):.0f} | {hit_text} | "
            f"{seeded_text} | {dialogue.get('segments', 0)} |"
        )
        details.append(
            f"## {path.stem}\n\n"
            f"- source: {data.get('source', 'n/a')}\n"
            f"- low-band ratio: {sound.get('low_band_ratio', 'n/a')}; silence: {sound.get('silence_ratio', 'n/a')}\n"
            f"- AST checked {classification.get('events_checked', 0)} events: {classification.get('top_labels', [])}\n"
            f"- event times: {sound.get('event_times', [])[:24]}\n"
        )
    (analysis / "FART_EVENTS.md").write_text("\n".join(rows) + "\n\n" + "\n".join(details), encoding="utf-8")

    tools_dir = OUT / "04_clips" / "tools"
    for name in ("clip_ingest.py", "clip_subs.py", "clip_sound.py", "clip_classify.py", "clip_events.py", "clip_diarize.py"):
        source = ROOT / "experimental" / "tools" / name
        if source.is_file():
            copy(source, tools_dir / name)
    (tools_dir / "PIPELINE.md").write_text(
        """# Fart capture pipeline

| Step | Script | What it does |
|---|---|---|
| 1 | `clip_ingest.py` | yt-dlp + ffmpeg: fetch and convert a clip to mono 16 kHz WAV |
| 2 | `clip_subs.py` | download YouTube VTT subtitles; cue timing, longest gap, wpm |
| 3 | `clip_sound.py` | librosa RMS + spectral flux: candidate sound events, low-band ratio |
| 4 | `clip_classify.py` | AST (`MIT/ast-finetuned-audioset-10-10-0.4593`): top-3 labels per event |
| 5 | `clip_events.py` | CLAP zero-shot `fart / flatulence` versus negatives; seeded window search |
| 6 | `clip_diarize.py` | silero-VAD speech turns; ECAPA embeddings (clustering dropped as unstable) |

Outputs are the JSON profiles in `analysis/`.

The Bridesmaids bathroom clip is the useful one: AST labelled farts at **39.38s (0.888)** and
**41.23s (0.569)**; seeded CLAP windows are **38.88-40.88s (p=0.706)** and **40.73-42.73s (p=0.887)**.
Scary Movie 4: AST found **49.02s Fart 0.76** (and burping at 39.25s).

Limits: no video files (audio only); no Whisper transcript (dialogue timing comes from VTT);
speaker clustering was dropped because it collapsed to one speaker.
""",
        encoding="utf-8",
    )

    # 05 diagrams
    house_diagram(OUT / "05_diagrams" / "smith_house_floors.png")
    copy(ROOT / "docs" / "scene_map.png", OUT / "05_diagrams" / "scene_map.png")
    copy(ROOT / "docs" / "scene_map.html", OUT / "05_diagrams" / "scene_map.html")
    for stem in ("ground", "upper", "basement"):
        copy(ROOT / "books" / "ling_house" / f"{stem}.json", OUT / "05_diagrams" / f"floor_{stem}.json")

    # 06 variations
    copy(ROOT / "work" / "variants" / "INJECTED.md", OUT / "06_variations" / "INJECTED.md")
    for index in (7, 18, 33):
        copy(ROOT / "work" / "variants" / f"beat{index}.json", OUT / "06_variations" / f"beat{index}.json")

    # 07 source: the author's marked PDF and extracted labels
    pdf = Path(r"C:\NOIR_LOCAL\Downloads\Corrections II.pdf")
    if pdf.is_file():
        copy(pdf, OUT / "07_source" / pdf.name)
    copy(ROOT / "books" / "corrections_v2.jsonl", OUT / "07_source" / "corrections_v2.jsonl")

    # 08 reports
    copy(ROOT / "reports" / "SYSTEM_TEST.md", OUT / "08_reports" / "SYSTEM_TEST.md")
    copy(ROOT / "telemetry" / "author_labels_eval.json", OUT / "08_reports" / "author_labels_eval.json")
    copy(ROOT / "telemetry" / "quality_budget.json", OUT / "08_reports" / "quality_budget.json")

    readme = """# Rainee scene package

One folder: the scene, the rules, the references, the clips, the house, the variations, the marked source.

## 01_scene
- `script.md` — **your original sample**, as pasted (before any editing).
- `script_cleaned.md` — earlier cleaned pass.
- `start_scene_corrected.md` — structural correction pass.
- `start_scene_deepseek.md` — draft written through DeepSeek.
- `start_scene_annotated.md` — annotated working text (directions, AVOID lines, canon notes).
- `start_scene_v2.md` — **new main text**: chosen variation takes applied, annotations stripped.

## 02_guidelines
- `world_state.json` — canon rules, impossible things, banned patterns (two mothers, no Stan in the opening, perfume farts).
- `editorial_notes.json` — per-beat direction, AVOID lines, tone references, beat requires/effects.
- `author_decisions.json` — 20 in-session decisions (cut / keep / direction / canon) with reasons.
- `style_card.json` — numeric prose targets (no book text).
- `RETRACTIONS.md` — numbers that are withdrawn; do not quote them as results.

## 03_references
Clip profiles (timings, dialogue gap, wpm, sound events) and `youtube_sources.md`.

## 04_clips
- `audio/*.mp3` — audio extracted from the five reference clips (converted from WAV for size).
- `subs/*.vtt` — subtitle tracks used for dialogue timing.
- `analysis/FART_EVENTS.md` + JSONs — per-clip fart/sound capture: AST labels, CLAP probabilities, VAD turns.
- `tools/` — the six scripts that produced them, with `PIPELINE.md`.

**No video files are included** — the pipeline downloaded audio only. **No Whisper transcript** was
produced: dialogue timing came from the VTT subtitles, and farts/noises were detected with librosa +
CLAP/AST. `faster-whisper` is installed if transcripts are wanted.

## 05_diagrams
- `smith_house_floors.png` — ground / upper / basement with rooms and doors (red).
- `scene_map.png` / `.html` — scene beats, what was cut, what was restored.
- `floor_*.json` — the raw room polygons and door segments.

## 06_variations
`INJECTED.md` — 3 beats × 5 treatments, gate results, chosen takes. `beat*.json` — machine records.

## 07_source
`Corrections II.pdf` — your red-marked source. `corrections_v2.jsonl` — extracted lines with doc_id and op.

## 08_reports
`SYSTEM_TEST.md` — the readable pass/fail report. `author_labels_eval.json`, `quality_budget.json`.

## Not included
- Book texts: excluded by design (no book passages in prompts).
- Video files: not downloaded.
- Real-provider variation: the takes were written in-session; local/API runs are still unmeasured.
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    archive = ROOT / "deliverables" / "rainee_scene_package.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(OUT.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(OUT.parent))

    size = archive.stat().st_size / (1024 * 1024)
    print(f"folder: {OUT}")
    print(f"zip:    {archive} ({size:.1f} MB)")
    print(f"files:  {sum(1 for path in OUT.rglob('*') if path.is_file())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
