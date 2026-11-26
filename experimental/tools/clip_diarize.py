"""
Dialogue rhythm for a reference clip: speech, turns and pauses — no speaker identity.

Speaker diarization turned out to be unreliable without a gated model (pyannote). Rather than ship
fake labels, this reports only what VAD can defend:

  - speech seconds and speech ratio
  - segment count (turn-ish units) and mean turn length
  - longest gap and mean gap

    python tools/clip_diarize.py --file references/clips/audio/bridesmaids_bathroom.wav \
        --name bridesmaids_bathroom --merge
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
from silero_vad import get_speech_timestamps, load_silero_vad


def load_audio(path: Path, rate: int = 16000):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        subprocess.run(
            ["ffmpeg", "-v", "quiet", "-y", "-i", str(path), "-ac", "1", "-ar", str(rate), str(wav)],
            check=True,
        )
        samples, sr = librosa.load(str(wav), sr=rate, mono=True)
    return torch.from_numpy(samples), sr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    target = Path(args.out) if args.out else Path("references/clips") / f"{args.name}.json"
    data = json.loads(target.read_text(encoding="utf-8")) if (args.merge and target.is_file()) else {}
    waveform, sr = load_audio(Path(args.file))

    vad = load_silero_vad()
    segments = get_speech_timestamps(waveform, vad, sampling_rate=sr, return_seconds=True)
    speech_seconds = sum(segment["end"] - segment["start"] for segment in segments)
    gaps = [
        segments[index + 1]["start"] - segments[index]["end"]
        for index in range(len(segments) - 1)
    ]
    duration = float(waveform.numel()) / sr
    report = {
        "provider": "silero-vad",
        "estimated": False,
        "segments": len(segments),
        "speech_seconds": round(speech_seconds, 2),
        "speech_ratio": round(speech_seconds / max(1e-6, duration), 3),
        "longest_gap": round(max(gaps), 2) if gaps else 0.0,
        "mean_gap": round(float(np.mean(gaps)), 2) if gaps else 0.0,
        "mean_turn": round(speech_seconds / max(1, len(segments)), 2),
    }
    data["dialogue"] = report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{args.name}: {report}")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
