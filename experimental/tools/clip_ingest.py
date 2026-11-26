"""
Extract the expressive dynamics of a reference clip: timing, escalation density, pauses.

The plot summary of Bridesmaids' bathroom scene is useless to a writer. The clip has rhythm:
where the laughs land, how long the scene holds, where it goes quiet. This tool turns a clip
into that rhythm, as JSON the prompt can use.

    python tools/clip_ingest.py --file references/clips/bridesmaids_bathroom.mp4
    python tools/clip_ingest.py --file clip.mp4 --transcribe

No downloading. You supply files you have the rights to use.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np


def probe(path: Path) -> dict:
    output = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(output.stdout)


def audio_profile(path: Path, rate: int = 8000, window: float = 0.1) -> dict:
    raw = subprocess.run(
        ["ffmpeg", "-v", "quiet", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    size = max(1, int(rate * window))
    frames = len(samples) // size
    rms = np.array(
        [float(np.sqrt(np.mean(samples[i * size:(i + 1) * size] ** 2))) for i in range(frames)]
    )
    if frames == 0:
        return {"windows": 0, "peaks": [], "longest_silence": 0.0}
    threshold = float(rms.mean() + 2 * rms.std())
    peaks = [round(i * window, 2) for i, value in enumerate(rms) if value >= threshold]
    silence = rms < max(0.01, rms.mean() * 0.25)
    longest, run = 0, 0
    for is_silent in silence:
        run = run + 1 if is_silent else 0
        longest = max(longest, run)
    return {
        "windows": frames,
        "peaks": peaks[:60],
        "peak_count": len(peaks),
        "longest_silence": round(longest * window, 2),
        "mean_energy": round(float(rms.mean()), 4),
    }


def transcribe(path: Path) -> list:
    from faster_whisper import WhisperModel

    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path))
    return [
        {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": segment.text.strip()}
        for segment in segments
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--transcribe", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"not found: {path}")
    data = probe(path)
    duration = float(data.get("format", {}).get("duration") or 0.0)
    report = {
        "file": path.name,
        "duration": round(duration, 2),
        "audio": audio_profile(path),
    }
    if args.transcribe:
        report["transcript"] = transcribe(path)
    target = Path(args.out) if args.out else path.with_suffix(".json")
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"duration {report['duration']}s | peaks {report['audio'].get('peak_count', 0)} | "
          f"longest silence {report['audio'].get('longest_silence', 0)}s")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
