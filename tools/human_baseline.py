"""
Held-out human baseline for prose diagnostics.

Split the ten books: five to build the style card, five held out. Score every paragraph of the
held-out five on the contamination-free diagnostics, report p10 / median / p90. This replaces the
retracted "human floor".

    python tools/human_baseline.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.voice.diagnostics_suite import analyze

ROOT = Path(__file__).resolve().parents[1]


def paragraphs(path: Path):
    return [part.strip() for part in path.read_text(encoding="utf-8", errors="ignore").split("\n\n") if len(part.split()) >= 25]


def main() -> int:
    files = sorted((ROOT / "books" / "text").glob("*.txt"))
    files = [path for path in files if path.stat().st_size > 1000]
    if len(files) < 6:
        print(f"NOT RUN: need at least 6 book texts, found {len(files)}")
        return 1
    held_out = files[5:]
    rows = []
    for path in held_out:
        for paragraph in paragraphs(path):
            result = analyze(paragraph)
            rows.append(
                {
                    "book": path.stem,
                    "tic": result["findings"]["tic"]["rate_per_1000"],
                    "filter": result["findings"]["filter"]["rate_per_1000"],
                    "simile": result["findings"]["simile"]["rate_per_1000"],
                    "participial": result["findings"]["participial"]["rate_per_1000"],
                    "cliche": result["findings"]["cliche"]["rate_per_1000"],
                    "repetition": result["findings"]["repetition"]["rate_per_1000"],
                    "mean_sentence": result["mean_sentence"],
                    "sd_sentence": result["sd_sentence"],
                    "dialogue_ratio": result["dialogue_ratio"],
                    "specificity": result["specificity_per_100"],
                }
            )

    def band(values):
        values = sorted(values)
        if not values:
            return {"p10": None, "median": None, "p90": None}
        def pick(q):
            index = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
            return round(values[index], 2)
        return {"p10": pick(0.1), "median": pick(0.5), "p90": pick(0.9)}

    metrics = [key for key in rows[0] if key != "book"] if rows else []
    report = {
        "held_out_books": [path.stem for path in held_out],
        "paragraphs": len(rows),
        "metrics": {key: band([row[key] for row in rows]) for key in metrics},
    }
    target = ROOT / "telemetry" / "books" / "human_baseline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
