"""Reference clips as prompt material: timing, peaks, pauses — not plot summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Sequence


def load_clips(directory: str | Path = "references/clips") -> Dict[str, dict]:
    root = Path(directory)
    clips: Dict[str, dict] = {}
    if not root.is_dir():
        return clips
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        clips[path.stem] = data
    return clips


def format_clips(names: Sequence[str], directory: str | Path = "references/clips") -> str:
    clips = load_clips(directory)
    lines: List[str] = []
    for name in names:
        data = clips.get(name)
        if not data:
            lines.append(f"- {name}: clip not ingested yet")
            continue
        audio = data.get("audio") or {}
        speech = data.get("speech") or {}
        if audio.get("peak_count"):
            lines.append(
                f"- {name}: {data.get('duration', '?')}s, {audio.get('peak_count')} energy peaks, "
                f"longest silence {audio.get('longest_silence', 0)}s "
                f"(study where the laughs land and how long the scene holds)"
            )
        elif speech:
            lines.append(
                f"- {name}: {speech.get('duration', '?')}s, {speech.get('cues')} speech cues, "
                f"longest gap {speech.get('longest_gap')}s, {speech.get('words_per_min')} wpm "
                f"(study the pace and the silence)"
            )
        else:
            lines.append(f"- {name}: clip ingested without speech timing")
        sound = data.get("sound") or {}
        if sound.get("events"):
            lines.append(
                f"  sound: {sound.get('events')} low-band events, "
                f"silence {sound.get('silence_ratio')} of the clip"
            )
        seeded = data.get("events_seeded") or {}
        if seeded.get("hits"):
            stamps = ", ".join(f"{hit['start']}s (p={hit['confidence']})" for hit in seeded["hits"][:4])
            lines.append(f"  farts: {stamps}")
        events = data.get("events") or {}
        if events.get("hits"):
            first = events["hits"][0]
            lines.append(
                f"  flatulence regions: {len(events['hits'])} "
                f"(e.g. {first['start']}-{first['end']}s)"
            )
        dialogue = data.get("dialogue") or {}
        if dialogue:
            lines.append(
                f"  dialogue: {dialogue.get('speech_seconds')}s speech, "
                f"{dialogue.get('segments')} segments, longest gap {dialogue.get('longest_gap')}s "
                f"(no speaker identity)"
            )
        classification = sound.get("classification") or {}
        if classification.get("body_sound_hits") is not None:
            lines.append(
                f"  body sounds: {classification.get('body_sound_hits')} hits "
                f"(top: {classification.get('top_labels', [['?', 0]])[0][0]})"
            )
        transcript = data.get("transcript") or []
        if transcript:
            first = transcript[0]
            lines.append(f"  opens: \"{first.get('text', '')[:90]}\" at {first.get('start', 0)}s")
    lines = list(dict.fromkeys(lines))
    if not lines:
        return ""
    return "REFERENCE CLIP DYNAMICS (timing, not premise):\n" + "\n".join(lines)
