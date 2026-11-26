"""
Corpus typicality per paragraph — a DIAGNOSTIC, not a target.

Similarity to the centroid of ten unrelated books measures typicality/topic, not voice. It is
reported here because it is cheap and stable, and it must never be used as an objective or a
pass/fail (see docs/RETRACTIONS.md).

    python tools/eval_voice.py --file work/americandad/start_scene_annotated.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.conditioner import paragraph_spans
from prose_engine.voice.evaluate import Evaluator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--min-words", type=int, default=8)
    parser.add_argument("--out", default="books/voice_eval.json")
    args = parser.parse_args()

    evaluator = Evaluator(books="books")
    text = Path(args.file).read_text(encoding="utf-8")
    rows = []
    for start, end in paragraph_spans(text):
        chunk = text[start:end].strip()
        if len(chunk.split()) < args.min_words:
            continue
        if chunk.lstrip().startswith(("[", "]", "#")):
            continue
        rows.append(
            {
                "words": len(chunk.split()),
                "corpus_typicality": round(evaluator.similarity(chunk), 4),
                "corpus_typicality_pct": round(evaluator.percentile(chunk), 4),
                "text": chunk[:160],
            }
        )
    if not rows:
        print("no paragraphs")
        return 1
    typicality = [row["corpus_typicality"] for row in rows]
    percentiles = [row["corpus_typicality_pct"] for row in rows]
    report = {
        "file": str(args.file),
        "paragraphs": len(rows),
        "mean_corpus_typicality": round(statistics.mean(typicality), 4),
        "median_corpus_typicality": round(statistics.median(typicality), 4),
        "median_corpus_typicality_pct": round(statistics.median(percentiles), 4),
        "note": "diagnostic only; not a target and not a pass/fail",
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    for row in rows:
        print(f"{row['words']:>4}w  typicality {row['corpus_typicality']:.3f}  pct {row['corpus_typicality_pct']:.3f}")
    print("---")
    print(
        f"paragraphs {report['paragraphs']} | mean typicality {report['mean_corpus_typicality']:.3f} | "
        f"median pct {report['median_corpus_typicality_pct']:.3f}"
    )
    print("diagnostic only — never a target (docs/RETRACTIONS.md)")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
