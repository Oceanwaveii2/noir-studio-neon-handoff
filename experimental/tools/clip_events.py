"""
P0: CLAP zero-shot event detection over the whole clip.

AST's defect was vocabulary, not accuracy. CLAP scores arbitrary phrases, so "a fart" can be
compared directly against "a bass guitar" and "a person speaking", with a margin.

    python tools/clip_events.py --file references/clips/audio/bridesmaids_bathroom.wav \
        --name bridesmaids_bathroom --merge

Writes `events` into references/clips/<name>.json: contiguous hit intervals with confidence and
the nearest competing label.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import librosa
import numpy as np
import torch
from transformers import ClapModel, ClapProcessor

MODEL = "laion/clap-htsat-unfused"
POSITIVE = ["a fart", "a wet fart", "a loud fart", "flatulence", "a whoopee cushion", "a person passing gas"]
NEGATIVE = [
    "a person speaking", "background music", "a bass guitar", "a subwoofer thump",
    "a door slam", "applause", "laughter", "room tone",
]


def load_audio(path: Path, rate: int = 48000):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run(
            ["ffmpeg", "-v", "quiet", "-y", "-i", str(path), "-ac", "1", "-ar", str(rate), str(wav)],
            check=True,
        )
        samples, sr = librosa.load(str(wav), sr=rate, mono=True)
    return samples, sr


def windows(samples, sr, size=2.0, hop=0.5):
    n = int(size * sr)
    step = int(hop * sr)
    for start in range(0, max(1, len(samples) - n + 1), step):
        yield start, samples[start:start + n]


def merge(intervals, gap=0.6):
    merged = []
    for start, end, conf, label in sorted(intervals):
        if merged and start - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end), max(merged[-1][2], conf), merged[-1][3])
        else:
            merged.append((start, end, conf, label))
    return merged


def _score(model, processor, text_inputs, chunk, sr, device):
    audio = processor(audio=[chunk], sampling_rate=sr, return_tensors="pt").to(device)
    logits = model(**text_inputs, **audio).logits_per_audio[0]
    probs = logits.softmax(dim=-1).cpu().numpy()
    p_pos = float(probs[0] + probs[3])  # "a fart" + "flatulence"
    neg_index = int(np.argmax(probs[len(POSITIVE):]))
    p_neg = float(probs[len(POSITIVE) + neg_index])
    return p_pos, p_neg, NEGATIVE[neg_index]


def classify(samples, sr, threshold=0.55, margin_threshold=0.0, centers=None):
    model = ClapModel.from_pretrained(MODEL)
    processor = ClapProcessor.from_pretrained(MODEL)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    texts = POSITIVE + NEGATIVE
    hits = []
    with torch.no_grad():
        text_inputs = processor(text=texts, return_tensors="pt", padding=True).to(device)
        if centers:
            for center in centers:
                best = None
                for offset in (-0.5, 0.0, 0.5):
                    start = max(0, int((center + offset - 1.0) * sr))
                    chunk = samples[start:int((center + offset + 1.0) * sr)]
                    if chunk.size < sr // 2:
                        continue
                    p_pos, p_neg, label = _score(model, processor, text_inputs, chunk, sr, device)
                    if best is None or p_pos > best[0]:
                        best = (p_pos, p_neg, label, start, chunk.size)
                if best and best[0] >= threshold and best[0] > best[1]:
                    p_pos, _p_neg, label, start, size = best
                    hits.append((start / sr, (start + size) / sr, round(p_pos, 3), label))
            return hits
        for start, chunk in windows(samples, sr):
            if chunk.size < sr // 2:
                continue
            p_pos, p_neg, label = _score(model, processor, text_inputs, chunk, sr, device)
            if p_pos >= threshold and p_pos > p_neg:
                hits.append((start / sr, (start + chunk.size) / sr, round(p_pos, 3), label))
    return merge(hits)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--seed", action="store_true", help="use AST body-sound hits as centers")
    args = parser.parse_args()

    target = Path(args.out) if args.out else Path("references/clips") / f"{args.name}.json"
    data = json.loads(target.read_text(encoding="utf-8")) if (args.merge and target.is_file()) else {}
    samples, sr = load_audio(Path(args.file))
    if args.seed:
        seeds = [hit["time"] for hit in (data.get("sound", {}).get("classification", {}).get("hits") or [])]
        intervals = classify(samples, sr, centers=seeds)
        data["events_seeded"] = {
            "centers": seeds,
            "hits": [
                {"start": round(a, 2), "end": round(b, 2), "confidence": c, "versus": v}
                for a, b, c, v in intervals
            ],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{args.name}: {len(intervals)} seeded events")
        for hit in data["events_seeded"]["hits"]:
            print(f"  {hit['start']}s p={hit['confidence']} (vs {hit['versus']})")
        print(f"written: {target}")
        return 0
    intervals = classify(samples, sr)
    data["events"] = {
        "model": MODEL,
        "positive": POSITIVE,
        "negative": NEGATIVE,
        "hits": [
            {"start": round(a, 2), "end": round(b, 2), "confidence": c, "versus": v}
            for a, b, c, v in intervals
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.name}: {len(intervals)} hit intervals")
    for hit in data["events"]["hits"][:10]:
        print(f"  {hit['start']}-{hit['end']}s p={hit['confidence']} (vs {hit['versus']})")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
