"""
Sound-event profile for a reference clip: the farts, thumps and gaps Whisper cannot hear.

Whisper transcribes speech; it will not label a fart. This tool measures the audio instead:

  - low-band bursts (40-250 Hz) — body sounds, thumps, rumble
  - onsets — how many events, and when
  - silence ratio — how much air the scene leaves

    python tools/clip_sound.py --file references/clips/bridesmaids_bathroom.mp4
    python tools/clip_sound.py --file clip.mp4 --out references/clips/NAME.json --merge

`--merge` folds the sound block into an existing clip JSON (speech profile) instead of replacing it.
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


def extract_wav(path: Path, target: Path, rate: int = 16000) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "quiet", "-y", "-i", str(path), "-ac", "1", "-ar", str(rate), str(target)],
        check=True,
    )
    return target


def profile(path: Path, rate: int = 16000) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        wav = extract_wav(path, Path(tmp) / "audio.wav", rate)
        samples, sr = librosa.load(str(wav), sr=rate, mono=True)
    if samples.size == 0:
        return {"events": 0, "event_times": [], "silence_ratio": 1.0}

    duration = len(samples) / sr
    stft = np.abs(librosa.stft(samples, n_fft=1024, hop_length=256))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    low = stft[(freqs >= 40) & (freqs <= 250)].mean(axis=0)
    high = stft[freqs > 2000].mean(axis=0)
    times = librosa.frames_to_time(np.arange(low.size), sr=sr, hop_length=256)

    threshold = float(max(np.percentile(low, 85), low.mean() + 0.5 * low.std()))
    active = low >= threshold
    events = []
    start = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            events.append((start, index))
            start = None
    if start is not None:
        events.append((start, active.size))
    merged = []
    for begin, end in events:
        if merged and begin - merged[-1][1] < 15:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((begin, end))
    events = merged

    rms = librosa.feature.rms(y=samples, hop_length=256)[0]
    silence_ratio = float(np.mean(rms < max(0.005, rms.mean() * 0.2)))

    return {
        "duration": round(duration, 2),
        "events": len(events),
        "event_times": [round(float(times[a]), 2) for a, _ in events][:40],
        "event_durations": [round(float(times[min(b, times.size - 1)] - times[a]), 2) for a, b in events][:40],
        "low_band_ratio": round(float(low.mean() / (high.mean() + 1e-9)), 2),
        "silence_ratio": round(silence_ratio, 3),
        "mean_rms": round(float(rms.mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"not found: {path}")
    name = args.name or path.stem
    block = profile(path)
    target = Path(args.out) if args.out else Path("references/clips") / f"{name}.json"
    if args.merge and target.is_file():
        data = json.loads(target.read_text(encoding="utf-8"))
    else:
        data = {"file": name}
    data["sound"] = block
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{name}: {block['events']} low-band events, silence {block['silence_ratio']}")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
