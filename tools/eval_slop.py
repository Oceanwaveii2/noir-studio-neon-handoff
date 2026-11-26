"""
Held-out evaluation for the slop scorer (M0).

Every quality number the repo printed before this was in-sample. This harness:

  - splits by *document group*, never by line (no leakage)
  - reports TPR at a fixed 5% FPR, AUC, precision/recall, and per-length buckets
  - labels the result weak when there is only one correction document

    python tools/eval_slop.py
    python tools/eval_slop.py --corrections books/corrections.jsonl --out books/slop_eval.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from prose_engine.voice.slop import SlopModel, train

WORD = re.compile(r"[A-Za-z']+")
META = ("AI made", "Horrible writing")


def load_rows(paths):
    rows = []
    sources = set()
    for path in paths:
        path = Path(path)
        sources.add(path.name)
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            text = entry["text"].strip()
            if len(text) < 25 or text.startswith("\u2022") or any(marker in text for marker in META):
                continue
            rows.append(
                {
                    "text": text,
                    "label": entry["label"],
                    "group": f"{path.name}:{entry.get('page', 0)}",
                }
            )
    return rows, sources


def split_groups(rows, test_fraction=0.25, seed=7):
    groups = sorted({row["group"] for row in rows})
    rng = random.Random(seed)
    rng.shuffle(groups)
    count = max(1, round(len(groups) * test_fraction))
    if len(groups) > 1:
        count = min(count, len(groups) - 1)
    test_groups = set(groups[:count])
    train = [row for row in rows if row["group"] not in test_groups]
    test = [row for row in rows if row["group"] in test_groups]
    return train, test


def auc(positives, negatives):
    positive = [float(value) for value in positives]
    negative = [float(value) for value in negatives]
    if not positive or not negative:
        return float("nan")
    greater = sum(1 for p in positive for n in negative if p > n)
    equal = sum(1 for p in positive for n in negative if p == n)
    return (greater + 0.5 * equal) / (len(positive) * len(negative))


def tpr_at_fpr(positives, negatives, fpr=0.05):
    if not positives or not negatives:
        return float("nan"), float("nan"), float("nan")
    ordered = sorted((float(value) for value in negatives), reverse=True)
    allowed = int(math.floor(fpr * len(ordered)))
    threshold = ordered[min(allowed, len(ordered) - 1)] + 1e-6
    tpr = float(np.mean(np.asarray(positives) >= threshold))
    actual = float(np.mean(np.asarray(negatives) >= threshold))
    return tpr, actual, threshold


def bucket(rows, scores):
    buckets = {"short (<12w)": ([], []), "medium (12-25w)": ([], []), "long (>25w)": ([], [])}
    for row, score in zip(rows, scores):
        words = len(WORD.findall(row["text"]))
        key = "short (<12w)" if words < 12 else ("medium (12-25w)" if words <= 25 else "long (>25w)")
        buckets[key][0 if row["label"] == "bad" else 1].append(score)
    return buckets


def evaluate(train_rows, test_rows, model_factory=SlopModel) -> dict:
    model = model_factory(train_rows) if model_factory is not SlopModel else train(train_rows)
    scores = [model.score(row["text"]) for row in test_rows]
    positives = [score for row, score in zip(test_rows, scores) if row["label"] == "bad"]
    negatives = [score for row, score in zip(test_rows, scores) if row["label"] == "neutral"]
    tpr, fpr, threshold = tpr_at_fpr(positives, negatives)
    # precision/recall at the same operating point
    predicted = [score >= threshold for score in scores]
    labels = [row["label"] == "bad" for row in test_rows]
    true_positive = sum(1 for p, l in zip(predicted, labels) if p and l)
    precision = true_positive / max(1, sum(predicted))
    recall = true_positive / max(1, sum(labels))
    buckets = {}
    for key, (bad, good) in bucket(test_rows, scores).items():
        if not bad and not good:
            continue
        buckets[key] = {
            "bad": len(bad),
            "neutral": len(good),
            "mean_bad": round(float(np.mean(bad)), 1) if bad else None,
            "mean_neutral": round(float(np.mean(good)), 1) if good else None,
        }
    return {
        "train": len(train_rows),
        "test": len(test_rows),
        "positives": len(positives),
        "negatives": len(negatives),
        "auc": round(auc(positives, negatives), 3),
        "tpr_at_5pct_fpr": round(tpr, 3) if not math.isnan(tpr) else None,
        "actual_fpr": round(fpr, 3) if not math.isnan(fpr) else None,
        "threshold": round(threshold, 1) if not math.isnan(threshold) else None,
        "precision_at_threshold": round(precision, 3),
        "recall_at_threshold": round(recall, 3),
        "buckets": buckets,
        "weak_evidence": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corrections", default="books/corrections.jsonl")
    parser.add_argument("--out", default="books/slop_eval.json")
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    paths = [Path(args.corrections)]
    rows, sources = load_rows(paths)
    if not rows:
        print("no rows")
        return 1
    train_rows, test_rows = split_groups(rows, args.test_fraction, args.seed)
    positives = sum(1 for row in test_rows if row["label"] == "bad")
    negatives = sum(1 for row in test_rows if row["label"] == "neutral")
    if positives < 30 or negatives < 30:
        report = {
            "verdict": "INSUFFICIENT LABELS",
            "positives": positives,
            "negatives": negatives,
            "train": len(train_rows),
            "test": len(test_rows),
            "note": "AUC is not reported below 30 positives and 30 negatives per fold.",
        }
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"INSUFFICIENT LABELS (n+={positives}, n-={negatives}); no AUC reported")
        print(f"written: {args.out}")
        return 0
    report = evaluate(train_rows, test_rows)
    report["sources"] = sorted(sources)
    report["weak_evidence"] = (
        "single correction document: the split is page-grouped, not document-grouped"
        if len(sources) < 2
        else None
    )
    report["label"] = "uncalibrated" if (report["tpr_at_5pct_fpr"] is None or report["tpr_at_5pct_fpr"] < 0.7) else "usable"

    print(f"train {report['train']} | test {report['test']} | bad {report['positives']} / neutral {report['negatives']}")
    print(f"AUC {report['auc']} | TPR@5%FPR {report['tpr_at_5pct_fpr']} | actual FPR {report['actual_fpr']} | threshold {report['threshold']}")
    print(f"precision {report['precision_at_threshold']} | recall {report['recall_at_threshold']}")
    for key, value in report["buckets"].items():
        print(f"  {key}: bad {value['bad']} (mean {value['mean_bad']}) | neutral {value['neutral']} (mean {value['mean_neutral']})")
    if report["weak_evidence"]:
        print("NOTE:", report["weak_evidence"])
    print("verdict:", report["label"])

    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
