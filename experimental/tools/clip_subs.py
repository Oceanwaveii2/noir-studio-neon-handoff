"""
Turn an auto-subtitle track into the scene's timing profile — no video download.

    python tools/clip_subs.py --vtt references/clips/subs/PP9l4LP0WPI.en.vtt \
        --name bridesmaids_bathroom --source https://www.youtube.com/watch?v=PP9l4LP0WPI

Writes references/clips/<name>.json with speech timing: cue count, speech seconds, longest gap,
words per minute, and the transcript. That is the expressive skeleton (where it runs, where it
holds) even when audio analysis is unavailable.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})")
TAG = re.compile(r"<[^>]+>")


def _seconds(hours, minutes, seconds, millis) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_vtt(text: str):
    cues = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        match = TIME.match(lines[index].strip())
        if not match:
            index += 1
            continue
        start = _seconds(*match.groups()[:4])
        end = _seconds(*match.groups()[4:])
        index += 1
        body = []
        while index < len(lines) and lines[index].strip():
            cleaned = TAG.sub("", lines[index]).strip()
            if cleaned:
                body.append(cleaned)
            index += 1
        words = " ".join(body).strip()
        if words and (not cues or cues[-1]["text"] != words):
            cues.append({"start": round(start, 2), "end": round(end, 2), "text": words})
    return cues


def profile(cues) -> dict:
    if not cues:
        return {"cues": 0, "duration": 0.0, "speech_seconds": 0.0, "longest_gap": 0.0, "words_per_min": 0.0}
    intervals = sorted((cue["start"], cue["end"]) for cue in cues)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    speech = sum(end - start for start, end in merged)
    duration = merged[-1][1]
    longest = max((merged[i + 1][0] - merged[i][1] for i in range(len(merged) - 1)), default=0.0)
    words = sum(len(cue["text"].split()) for cue in cues)
    return {
        "cues": len(cues),
        "duration": round(duration, 2),
        "speech_seconds": round(speech, 2),
        "longest_gap": round(longest, 2),
        "words_per_min": round(words / max(1e-6, speech) * 60, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vtt", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--out-dir", default="references/clips")
    args = parser.parse_args()

    cues = parse_vtt(Path(args.vtt).read_text(encoding="utf-8"))
    data = {
        "file": args.name,
        "source": args.source,
        "speech": profile(cues),
        "transcript": cues,
    }
    target = Path(args.out_dir) / f"{args.name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.name}: {data['speech']}")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
