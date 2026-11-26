"""
Classify the low-band events in a reference clip with an AudioSet model.

The burst detector finds low-frequency events; this says which ones are actually body sounds
(AudioSet has a Fart class) versus music, thumps or dialogue.

    python tools/clip_classify.py --file references/clips/audio/bridesmaids_bathroom.wav \
        --name bridesmaids_bathroom --merge
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import librosa
import numpy as np
import torch
from transformers import pipeline

MODEL = "MIT/ast-finetuned-audioset-10-10-0.4593"
TARGETS = ("fart", "flatulence", "burp", "gargling", "stomach rumble", "belch")


def load_audio(path: Path, rate: int = 16000):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        import subprocess

        subprocess.run(
            ["ffmpeg", "-v", "quiet", "-y", "-i", str(path), "-ac", "1", "-ar", str(rate), str(wav)],
            check=True,
        )
        samples, sr = librosa.load(str(wav), sr=rate, mono=True)
    return samples, sr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--window", type=float, default=1.0)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    target = Path(args.out) if args.out else Path("references/clips") / f"{args.name}.json"
    data = json.loads(target.read_text(encoding="utf-8")) if (args.merge and target.is_file()) else {}
    events = (data.get("sound") or {}).get("event_times") or []
    samples, sr = load_audio(Path(args.file))
    classifier = pipeline(
        "audio-classification",
        model=MODEL,
        device=0 if torch.cuda.is_available() else -1,
    )

    labels: Counter = Counter()
    hits = []
    for moment in events:
        start = max(0, int((moment - args.window / 2) * sr))
        end = min(len(samples), start + int(args.window * sr))
        window = samples[start:end]
        if window.size < sr // 4:
            continue
        predictions = classifier(window, top_k=3)
        labels[predictions[0]["label"]] += 1
        for candidate in predictions:
            if any(term in candidate["label"].lower() for term in TARGETS):
                hits.append(
                    {"time": moment, "label": candidate["label"], "score": round(candidate["score"], 3)}
                )
                break

    data.setdefault("sound", {})["classification"] = {
        "events_checked": len(events),
        "body_sound_hits": len(hits),
        "hits": hits[:40],
        "top_labels": labels.most_common(10),
    }
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.name}: {len(hits)} body-sound hits / {len(events)} events")
    print("top labels:", labels.most_common(5))
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
