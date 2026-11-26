"""
Evaluate the rule flagger against the author's in-session decisions.

Labels come from books/author_decisions.json:
  cut  -> must be flagged
  keep -> must NOT be flagged (dialogue lines are excluded: the flagger never runs on dialogue)
  direction/canon/decision -> not scored

No AUC, no probability. Precision/recall on a tiny author set, in-sample, stated as such.

    python tools/eval_author_labels.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.conditioner import is_dialogue
from prose_engine.voice.slop import flag

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    decisions = json.loads((ROOT / "books" / "author_decisions.json").read_text(encoding="utf-8"))["decisions"]
    rows = []
    for item in decisions:
        if item["type"] not in ("cut", "keep"):
            continue
        if item.get("dialogue") or is_dialogue(item["text"]):
            continue
        flagged = bool(flag(item["text"]))
        rows.append({"id": item["id"], "label": item["type"], "flagged": flagged})

    tp = sum(1 for row in rows if row["label"] == "cut" and row["flagged"])
    fn = sum(1 for row in rows if row["label"] == "cut" and not row["flagged"])
    fp = sum(1 for row in rows if row["label"] == "keep" and row["flagged"])
    tn = sum(1 for row in rows if row["label"] == "keep" and not row["flagged"])
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    report = {
        "labels": len(rows),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "missed": [row["id"] for row in rows if row["label"] == "cut" and not row["flagged"]],
        "false_alarms": [row["id"] for row in rows if row["label"] == "keep" and row["flagged"]],
        "note": "author decisions from the session; tiny set; in-sample; no AUC",
    }
    target = ROOT / "telemetry" / "author_labels_eval.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
