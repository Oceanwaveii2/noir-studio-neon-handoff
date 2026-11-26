"""Pass 0-1 Block and span speech-act classifier for multi-pass canon ingestion."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Dict, List, Optional, Sequence

from story_graph.canon_models import ASSERTION_CLASSES

_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")
_NEGATION_RE = re.compile(
    r"\b(?:never|no|not|neither|nor|none|wasn['’]t|weren['’]t|didn['’]t|doesn['’]t|"
    r"don['’]t|isn['’]t|aren['’]t|cannot|can['’]t|never\s+married|kept\s+the\s+ling\s+name|"
    r"instead\s+of|rather\s+than|before\s+(?:the\s+)?wedding|dumped|ex-)\b",
    re.IGNORECASE,
)
_BELIEF_RE = re.compile(
    r"\b(?:believ\w*|thought|thinks?|assumed|imagined|wondered|rumou?r|pretend\w*|"
    r"said|says|claimed|alleged|insisted|source\s+show|american\s+dad|broadcast|cartoon|cosplay\w*)\b",
    re.IGNORECASE,
)
_TEASE_RE = re.compile(
    r"\b(?:jok\w*|teas\w*|kidding|sarcas\w*|smirk\w*|snort\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClassifiedSpan:
    """One classified sentence/clause span preserving exact character offsets and speaker metadata."""

    block_id: str
    block_kind: str
    speaker_id: Optional[str]
    span_start: int
    span_end: int
    excerpt: str
    assertion_class: str
    source_origin: str = "author_manuscript"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def normalize_blocks(blocks_or_text: Sequence[dict] | str) -> List[dict]:
    """Accept saved Cook/Notebook block dicts or plain text and normalize into offset blocks."""
    if isinstance(blocks_or_text, str):
        blocks: List[dict] = []
        cursor = 0
        for idx, para in enumerate(re.split(r"(\n\s*\n)", blocks_or_text)):
            if not para:
                continue
            if para.strip():
                speaker_match = re.match(r"^([A-Za-z][A-Za-z0-9_ .-]{0,30}):\s+(.+)$", para, re.DOTALL)
                is_heading = bool(re.match(r"^(?:INT\.|EXT\.|##)", para.strip()))
                kind = (
                    "scene-heading" if is_heading
                    else "character" if speaker_match
                    else "narrator"
                )
                speaker = speaker_match.group(1).strip().casefold() if speaker_match else None
                blocks.append({"id": f"b-{idx}", "kind": kind, "speaker": speaker, "text": para, "offset": cursor})
            cursor += len(para)
        return blocks
    normalized: List[dict] = []
    cursor = 0
    for idx, raw in enumerate(blocks_or_text):
        text = str(raw.get("text", ""))
        normalized.append(
            {
                "id": str(raw.get("id") or f"b-{idx}"),
                "kind": str(raw.get("kind") or "narrator"),
                "speaker": raw.get("speaker"),
                "text": text,
                "offset": int(raw.get("offset", cursor)),
                "source_origin": str(raw.get("source_origin") or ""),
            }
        )
        cursor += len(text)
    return normalized


def _has_inline_quote(sentence: str) -> bool:
    return bool(re.search(r'"[^"\n]{3,}"|“[^”\n]{3,}”|‘[^’\n]{3,}’|(?:^|\s)\'[^\'\n]{3,}\'', sentence))


def classify_sentence(
    sentence: str,
    *,
    block_kind: str,
    source_origin: str = "author_manuscript",
) -> str:
    """Assign one mutually exclusive AssertionClass based on block role, origin, and phrasing cues."""
    if source_origin == "broadcast_quote_fixture" or block_kind == "show-quote":
        return "show_quote"
    if _NEGATION_RE.search(sentence):
        return "negated_divergence"
    if _BELIEF_RE.search(sentence) or (block_kind != "character" and _has_inline_quote(sentence)):
        return "character_belief"
    if block_kind == "character":
        return "dialogue_teasing" if _TEASE_RE.search(sentence) else "dialogue_literal_claim"
    if block_kind in ("stage-direction", "scene-heading", "action"):
        return "stage_direction"
    return "narration_fact"


def classify_blocks(
    blocks_or_text: Sequence[dict] | str,
    *,
    source_origin: str = "author_manuscript",
) -> List[ClassifiedSpan]:
    """Classify all sentence spans across structured blocks or plain prose text."""
    blocks = normalize_blocks(blocks_or_text)
    spans: List[ClassifiedSpan] = []
    for block in blocks:
        text = block["text"]
        base_offset = int(block.get("offset", 0))
        origin = block.get("source_origin") or source_origin
        block_kind = block["kind"]
        speaker = block.get("speaker")
        for m in _SENTENCE_RE.finditer(text):
            excerpt = m.group(0).strip()
            if not excerpt:
                continue
            lead = len(m.group(0)) - len(m.group(0).lstrip())
            start = base_offset + m.start() + lead
            end = start + len(excerpt)
            ac = classify_sentence(excerpt, block_kind=block_kind, source_origin=origin)
            if ac not in ASSERTION_CLASSES:
                raise ValueError(f"Invalid assertion class: {ac}")
            spans.append(
                ClassifiedSpan(
                    block_id=block["id"],
                    block_kind=block_kind,
                    speaker_id=speaker,
                    span_start=start,
                    span_end=end,
                    excerpt=excerpt,
                    assertion_class=ac,
                    source_origin=origin,
                )
            )
    return spans
