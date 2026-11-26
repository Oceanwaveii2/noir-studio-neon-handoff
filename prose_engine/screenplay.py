"""
Document-level tells for screenplay prose.

Paragraph diagnostics see one block at a time, so they miss rhythm patterns that live between
lines: a bare denial answered by "Beat.", triplet repetitions, runs of clipped lines, simile
density. These are the tells that make a draft read as machine-written even when every
individual sentence is clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

_BEAT = re.compile(
    r"^(?:\(\s*beat\s*\)|beat(?:\.|$)|a beat(?:\.|$))",
    re.IGNORECASE,
)
_BARE_DENIAL = re.compile(
    r"^(?:absolutely not|no|nope|never|not a chance|no way|absolutely not\.)$", re.IGNORECASE
)
_TRIPLET = re.compile(r"^([A-Za-z']+)[.!?]\s+\1[.!?]\s+\1[.!?]$", re.IGNORECASE)
_SIMILE = re.compile(r"\b(?:like a|like an|as if|as though|like the)\b", re.IGNORECASE)
_CUE = re.compile(r"^[A-Z0-9 .'\-]+$")


@dataclass
class Tell:
    rule: str
    index: int
    severity: str
    message: str
    evidence: str = ""

    def to_dict(self) -> Dict:
        return {
            "rule": self.rule,
            "index": self.index,
            "severity": self.severity,
            "message": self.message,
            "evidence": self.evidence,
        }


def _is_cue(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and bool(_CUE.match(stripped)) and len(stripped.split()) <= 4


def _short_line(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(stripped)
        and len(stripped.split()) <= 4
        and stripped[0].isupper()
        and not _is_cue(stripped)
        and not stripped.startswith(("INT.", "EXT."))
    )


def analyze_document(paragraphs: Sequence[str]) -> List[Tell]:
    """Returns document-level tells with paragraph indices."""
    tells: List[Tell] = []
    stripped = [paragraph.strip() for paragraph in paragraphs]

    beats = [index for index, text in enumerate(stripped) if _BEAT.match(text)]
    for index in beats:
        tells.append(Tell("BEAT_DIRECTION", index, "info", "Explicit 'Beat.' stage direction."))
    if len(beats) > 4:
        tells.append(
            Tell(
                "BEAT_OVERUSE",
                beats[0],
                "warning",
                f"'Beat.' used {len(beats)} times; consider replacing most with physical action.",
            )
        )

    for index, text in enumerate(stripped):
        if not _BARE_DENIAL.match(text):
            continue
        nxt = stripped[index + 1] if index + 1 < len(stripped) else ""
        if _BEAT.match(nxt):
            tells.append(
                Tell(
                    "DENIAL_PLUS_BEAT",
                    index,
                    "warning",
                    f"Bare denial ('{text}') answered by 'Beat.' — a stock rhythm.",
                )
            )

    for index, text in enumerate(stripped):
        if _TRIPLET.match(text):
            tells.append(Tell("TRIPLET_REPEAT", index, "warning", f"Triplet repetition: '{text}'."))

    run_start = None
    run_length = 0
    for index, text in enumerate(stripped):
        if _short_line(text):
            if run_start is None:
                run_start = index
            run_length += 1
        else:
            if run_length >= 3 and run_start is not None:
                tells.append(
                    Tell(
                        "CLIPPED_RUN",
                        run_start,
                        "warning",
                        f"{run_length} consecutive lines of four words or fewer — staccato AI rhythm.",
                    )
                )
            run_start, run_length = None, 0
    if run_length >= 3 and run_start is not None:
        tells.append(
            Tell(
                "CLIPPED_RUN",
                run_start,
                "warning",
                f"{run_length} consecutive lines of four words or fewer — staccato AI rhythm.",
            )
        )

    words = sum(len(text.split()) for text in stripped) or 1
    similes = sum(len(_SIMILE.findall(text)) for text in stripped)
    density = similes * 1000 / words
    if density > 8.0:
        tells.append(
            Tell(
                "SIMILE_DENSITY",
                0,
                "warning",
                f"{similes} similes in {words:,} words ({density:.1f}/1k); sound-alike 'like a…' rhythm.",
            )
        )

    return tells


def summarize(tells: Sequence[Tell]) -> Dict:
    by_rule: Dict[str, int] = {}
    for tell in tells:
        by_rule[tell.rule] = by_rule.get(tell.rule, 0) + 1
    return {
        "total": len(tells),
        "warnings": sum(1 for tell in tells if tell.severity == "warning"),
        "by_rule": dict(sorted(by_rule.items(), key=lambda item: -item[1])),
    }
