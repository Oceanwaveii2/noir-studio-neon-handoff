"""Score ID-only, human-judged held-out retrieval results. No passage content required."""
from __future__ import annotations

import json
import math
import argparse
from pathlib import Path


def score_query(relevance: dict[str, int], ranked: list[str], k: int = 5) -> dict:
    if k <= 0 or not relevance or not any(v > 0 for v in relevance.values()):
        raise ValueError("Each query needs at least one positive relevance judgment and k > 0.")
    if any(not isinstance(key, str) or not key for key in relevance):
        raise ValueError("Passage IDs must be non-empty strings.")
    if any(type(v) is not int or v < 0 or v > 3 for v in relevance.values()):
        raise ValueError("Judgments must be integer grades from 0 to 3.")
    if any(not isinstance(key, str) or not key for key in ranked) or len(ranked) != len(set(ranked)):
        raise ValueError("Ranked IDs must be non-empty and unique.")
    selected = ranked[:k]
    positive = sum(value > 0 for value in relevance.values())
    recall = sum(relevance.get(item, 0) > 0 for item in selected) / positive
    dcg = sum((2 ** relevance.get(item, 0) - 1) / math.log2(i + 2) for i, item in enumerate(selected))
    ideal = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum((2 ** value - 1) / math.log2(i + 2) for i, value in enumerate(ideal))
    return {"recall_at_5": recall, "ndcg_at_5": dcg / idcg}


def evaluate(judgments: dict, runs: dict) -> dict:
    if not judgments or set(judgments) != set(runs):
        raise ValueError("Judgments and run must contain exactly the same non-empty query set.")
    details = {query: score_query(judgments[query], runs[query]) for query in sorted(judgments)}
    count = len(details)
    return {"query_count": count,
            "mean_recall_at_5": sum(v["recall_at_5"] for v in details.values()) / count,
            "mean_ndcg_at_5": sum(v["ndcg_at_5"] for v in details.values()) / count,
            "per_query": details}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("judgments", type=Path)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        judgments = json.loads(args.judgments.read_text(encoding="utf-8"))
        run = json.loads(args.run.read_text(encoding="utf-8"))
        print(json.dumps(evaluate(judgments, run), indent=2))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f"Invalid evaluation: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
