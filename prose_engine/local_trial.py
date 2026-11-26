"""Shared proposal contract for the isolated U7 local generation trial."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import re

from .editorial_service import Edit, preview, revision
from .guards import preserves_facts


SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": ["keep", "replace"]},
        "replacement": {"type": "string"},
    },
    "required": ["operation", "replacement"],
    "additionalProperties": False,
}
SYSTEM = (
    "You are line-editing action narration. Work on the exact selected span only. "
    "Keep the identity, objects, physical action, joke and timing. Do not add dialogue, people, props, "
    "locations or later information. Leave frozen spans unchanged. "
    "Use a single JSON object and no explanation: "
    '{"operation":"replace","replacement":"the new span"} or {"operation":"keep","replacement":""}.'
)
MAX_TOKENS = 128
CONTEXT = 4096
SEED = 70817


@dataclass(frozen=True)
class TrialCase:
    id: str
    split: str
    scene: str
    source: str
    revision: str
    start: int
    end: int
    paragraph_start: int
    paragraph_end: int
    frozen: tuple[tuple[int, int], ...]
    scene_parts: tuple[str, ...]
    scene_part_index: int
    direction: str
    baseline_replacement: str | None
    required: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()

    @property
    def target(self) -> str:
        return self.source[self.start:self.end]

    @property
    def paragraph(self) -> str:
        return self.source[self.paragraph_start:self.paragraph_end]

    def messages(self) -> list[dict[str, str]]:
        locked = any(self.start < b and a < self.end for a, b in self.frozen)
        content = json.dumps({"direction": self.direction, "selected_span": self.target,
                              "paragraph_for_context": self.paragraph, "frozen": locked},
                             ensure_ascii=False, separators=(",", ":"))
        return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def parse_proposal(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or len(raw) > 5000:
        raise ValueError("Expected a bounded JSON reply.")
    value = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(value, dict) or set(value) != {"operation", "replacement"}:
        raise ValueError("Expected operation and replacement only.")
    op, text = value["operation"], value["replacement"]
    if not isinstance(text, str) or op not in ("keep", "replace"):
        raise ValueError("Unknown operation or invalid replacement.")
    if op == "keep" and text != "":
        raise ValueError("Keep requires an empty replacement.")
    if op == "replace" and (not text or text != text.strip() or not text.isprintable() or len(text) > 1000):
        raise ValueError("Replace requires a bounded single-line span.")
    return op, text


def assess(case: TrialCase, raw: str, world, house) -> dict:
    try:
        op, replacement = parse_proposal(raw)
    except (ValueError, TypeError, RecursionError):
        return {"status": "SCHEMA_FAILURE", "schema_ok": False}
    if op == "keep":
        return {"status": "KEEP", "schema_ok": True}
    # Check the owning editor's exact-span and canon gates before any other
    # interpretation of the proposed replacement.
    result = preview(case.source, case.revision,
                     (Edit(case.id, case.start, case.end, case.target, replacement),), case.frozen, world)
    if result.status != "ELIGIBLE_FOR_REVIEW":
        return {"status": result.status, "schema_ok": True}
    if replacement == case.target:
        return {"status": "UNCHANGED_REPLACE", "schema_ok": True}
    if any(replacement.count(ch) > case.target.count(ch) for ch in ('"', '“', '”', '`', '*')):
        return {"status": "BLOCKED_NEW_DIALOGUE_OR_MARKUP", "schema_ok": True}
    # Appending sentence punctuation to an inner phrase would duplicate the
    # preserved punctuation immediately after the edit.
    if case.end < case.paragraph_end and case.source[case.end] in ".,!?;:" and replacement[-1] in ".,!?;:":
        return {"status": "BLOCKED_SPAN_BOUNDARY", "schema_ok": True}
    start = case.start - case.paragraph_start
    end = case.end - case.paragraph_start
    proposed = case.paragraph[:start] + replacement + case.paragraph[end:]
    if not preserves_facts(case.paragraph, proposed)[0]:
        return {"status": "BLOCKED_FACT_LOSS", "schema_ok": True}
    folded = proposed.casefold()
    if any(term.casefold() not in folded for term in case.required) or any(
        re.search(pattern, proposed, re.IGNORECASE) for pattern in case.forbidden
    ):
        return {"status": "BLOCKED_CASE_CONTINUITY", "schema_ok": True}
    before = list(case.scene_parts)
    after = before.copy()
    after[case.scene_part_index] = proposed
    if Counter(house.check_scene(after)) - Counter(house.check_scene(before)):
        return {"status": "BLOCKED_NEW_STAGING_ISSUE", "schema_ok": True}
    return {"status": "ELIGIBLE", "schema_ok": True, "replacement": replacement}


def deterministic(case: TrialCase) -> str:
    return json.dumps({"operation": "replace" if case.baseline_replacement is not None else "keep",
                       "replacement": case.baseline_replacement or ""}, ensure_ascii=False)


def synthetic_case(row: dict) -> TrialCase:
    source, paragraph, target = row["source"], row["paragraph"], row["target"]
    if source.count(paragraph) != 1 or paragraph.count(target) != 1:
        raise ValueError("Smoke anchors must occur once.")
    start = source.index(paragraph)
    anchor = start + paragraph.index(target)
    frozen = []
    for text in row.get("frozen", []):
        if source.count(text) != 1:
            raise ValueError("Frozen anchor must occur once.")
        a = source.index(text)
        frozen.append((a, a + len(text)))
    return TrialCase(row["id"], "smoke", row["scene"], source, revision(source), anchor,
                     anchor + len(target), start, start + len(paragraph), tuple(frozen),
                     (paragraph,), 0, row["direction"], row.get("baseline_replacement"),
                     tuple(row.get("required", ())), tuple(row.get("forbidden", ())))
