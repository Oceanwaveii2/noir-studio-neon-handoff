"""Report explicit author decisions separately from automated gate outcomes.

Legacy rows without a declared record type and named reviewer remain unclassified.
By default the report is printed; use --output for an explicit destination.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHOR_CHOICES = {"accept", "keep_original", "tie", "reject"}
GATE_CHOICES = {"pass", "fail"}


def rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    result = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected a JSON object")
            result.append(row)
    return result


def wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [round(center - margin, 4), round(center + margin, 4)]


def summarize(decisions: list[dict], proposals: list[dict]) -> dict:
    authors: Counter = Counter()
    gates: Counter = Counter()
    unclassified = 0
    for row in decisions:
        kind = row.get("record_type")
        reviewer = row.get("reviewer")
        choice = row.get("decision")
        if kind == "author_decision" and isinstance(reviewer, str) and reviewer.strip() and choice in AUTHOR_CHOICES:
            authors[choice] += 1
        elif kind == "gate_result" and row.get("result") in GATE_CHOICES:
            gates[row["result"]] += 1
        else:
            unclassified += 1
    total = sum(authors.values())
    return {
        "author": {
            "status": "reviewed" if total else "pending",
            "counts": {k: authors[k] for k in sorted(AUTHOR_CHOICES)},
            "total": total,
            "accept_rate": round(authors["accept"] / total, 4) if total else None,
            "accept_rate_wilson_95": wilson(authors["accept"], total),
        },
        "automatic_gate": {
            "counts": {k: gates[k] for k in sorted(GATE_CHOICES)},
            "total": sum(gates.values()),
        },
        "unclassified_decision_rows": unclassified,
        "proposal_rows": len(proposals),
        "limitations": [
            "Legacy records without an explicit type and named reviewer are not author decisions.",
            "Counts are descriptive; scene-level held-out paired evaluation is not yet run.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, default=ROOT / "eval" / "decisions.jsonl")
    parser.add_argument("--proposals", type=Path, default=ROOT / "eval" / "proposals.jsonl")
    parser.add_argument("--output", type=Path, help="Write report to a new file")
    args = parser.parse_args()
    try:
        report = summarize(rows(args.decisions), rows(args.proposals))
        rendered = json.dumps(report, indent=2)
        if args.output:
            with args.output.open("x", encoding="utf-8") as out:
                out.write(rendered + "\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
