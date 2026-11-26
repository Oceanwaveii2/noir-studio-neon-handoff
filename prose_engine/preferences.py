"""
Preference calibration from the engine's own accept/reject decisions.

No model is trained. The tool reads proposals.json files (which record accepted, reason,
original, proposed), computes the overlap and length ratio of every decision, and reports the
range that has actually been accepted. That range is the evidence for tightening or loosening a
strength preset.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Dict, Iterable, List

from .guards import token_overlap


def load_proposals(patterns: Iterable[str]) -> List[Dict]:
    rows: List[Dict] = []
    for pattern in patterns:
        for name in glob.glob(pattern, recursive=True):
            path = Path(name)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                data = data.get("proposals", [])
            for entry in data:
                if not isinstance(entry, dict) or "original" not in entry:
                    continue
                original = entry.get("original") or ""
                proposed = entry.get("proposed") or ""
                rows.append(
                    {
                        "accepted": bool(entry.get("accepted")),
                        "reason": entry.get("reason", ""),
                        "overlap": token_overlap(original, proposed) if proposed else 1.0,
                        "ratio": len(proposed) / max(1, len(original)),
                        "source": str(path),
                    }
                )
    return rows


def summarize(rows: List[Dict]) -> Dict:
    accepted = [row for row in rows if row["accepted"]]
    rejected = [row for row in rows if not row["accepted"]]
    result: Dict = {
        "total": len(rows),
        "accepted": len(accepted),
        "rejected": len(rejected),
    }
    if accepted:
        result["accepted_overlap_max"] = round(max(row["overlap"] for row in accepted), 3)
        result["accepted_overlap_mean"] = round(
            sum(row["overlap"] for row in accepted) / len(accepted), 3
        )
        result["accepted_ratio_range"] = [
            round(min(row["ratio"] for row in accepted), 2),
            round(max(row["ratio"] for row in accepted), 2),
        ]
    if rejected:
        result["rejected_overlap_min"] = round(min(row["overlap"] for row in rejected), 3)
        reasons: Dict[str, int] = {}
        for row in rejected:
            key = row["reason"].split("(")[0].strip()[:60] or "unknown"
            reasons[key] = reasons.get(key, 0) + 1
        result["rejection_reasons"] = dict(sorted(reasons.items(), key=lambda pair: -pair[1]))
    return result


def suggest(summary: Dict) -> Dict:
    """A conservative threshold set derived from what was accepted."""
    suggestion: Dict = {}
    if "accepted_overlap_max" in summary:
        suggestion["max_overlap"] = round(min(0.9, summary["accepted_overlap_max"] + 0.02), 2)
    if "accepted_ratio_range" in summary:
        low, high = summary["accepted_ratio_range"]
        suggestion["ratio"] = [round(max(0.3, low - 0.05), 2), round(min(2.5, high + 0.05), 2)]
    return suggestion
