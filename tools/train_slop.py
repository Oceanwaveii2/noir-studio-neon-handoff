"""Train the slop model from books/corrections.jsonl and report separation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.voice.slop import SlopModel, train


def clean_rows(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        text = entry["text"].strip()
        if len(text) < 25:
            continue
        if text.startswith("•") or "AI made" in text or "Horrible writing" in text:
            continue
        rows.append({"label": entry["label"], "text": text})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corrections", default="books/corrections.jsonl")
    parser.add_argument("--out", default="books/slop_model.json")
    args = parser.parse_args()

    rows = clean_rows(Path(args.corrections))
    bad = [row for row in rows if row["label"] == "bad"]
    neutral = [row for row in rows if row["label"] == "neutral"]
    print(f"bad: {len(bad)} | neutral: {len(neutral)}")

    model = train(rows)
    model.save(args.out)
    bad_scores = sorted(model.score(row["text"]) for row in bad)
    neutral_scores = sorted(model.score(row["text"]) for row in neutral)
    print(f"bad mean: {sum(bad_scores)/len(bad_scores):.1f} | neutral mean: {sum(neutral_scores)/len(neutral_scores):.1f}")
    print(f"bad range: {bad_scores[0]:.0f}-{bad_scores[-1]:.0f} | neutral range: {neutral_scores[0]:.0f}-{neutral_scores[-1]:.0f}")
    print(f"written: {args.out}")

    print("\n=== highest-scoring neutral lines (false alarms) ===")
    for row in sorted(neutral, key=lambda item: -model.score(item["text"]))[:4]:
        print(f"  {model.score(row['text']):.0f} {row['text'][:90]}")
    print("\n=== lowest-scoring bad lines (misses) ===")
    for row in sorted(bad, key=lambda item: model.score(item["text"]))[:4]:
        print(f"  {model.score(row['text']):.0f} {row['text'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
