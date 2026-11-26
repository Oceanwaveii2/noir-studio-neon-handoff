"""Occurrence-safe 0/25/50/75/100% slot infill planning and structural seam validation (Epic 4)."""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
import hashlib
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROTECTION_TIERS: Tuple[int, ...] = (0, 25, 50, 75, 100)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
_ANCHOR_RE = re.compile(r"\b(?:[A-Z][a-zA-Z0-9’\-]{2,}|[A-Z]{2,}|\d+(?:\.\d+)?)\b")
_STOPWORDS = frozenset({
    "the", "and", "for", "that", "with", "from", "this", "they", "their", "them",
    "have", "had", "has", "was", "were", "are", "been", "being", "into", "onto",
    "over", "under", "then", "than", "when", "where", "while", "what", "which",
    "who", "whom", "his", "her", "hers", "she", "him", "its", "you", "your",
    "our", "but", "not", "all", "one", "two", "just", "like", "back", "down",
})
_HEADING_CUE = re.compile(r"^\s*(?:#{1,6}\s+\S|(?:INT|EXT|INT/EXT|I/E|SCENE|CHAPTER)\b)", re.I)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_grapheme_boundary(text: str, position: int) -> bool:
    """Reject splits inside CRLF pairs, combining marks, ZWJ sequences, or regional indicators."""
    if position <= 0 or position >= len(text):
        return position in (0, len(text))
    left, right = text[position - 1], text[position]
    if left == "\r" and right == "\n":
        return False
    if unicodedata.category(right).startswith("M") or right == "\u200d" or left == "\u200d":
        return False
    code = ord(right)
    if 0x1F3FB <= code <= 0x1F3FF or 0xE0020 <= code <= 0xE007F:
        return False
    if 0x1F1E6 <= ord(left) <= 0x1F1FF and 0x1F1E6 <= code <= 0x1F1FF:
        return False
    return True


def validate_tier(value: Any) -> int:
    """Validate an infill/protection tier in 0..100."""
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("Slot protection tier must be an integer from 0 to 100")
    return value


@dataclass(frozen=True)
class TierPolicy:
    """Preservation and seam contract for one protection tier."""

    tier: int
    mode: str
    editable: bool
    min_token_retention: float
    preserve_anchors: bool
    allow_rephrase: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "mode": self.mode,
            "editable": self.editable,
            "min_token_retention": self.min_token_retention,
            "preserve_anchors": self.preserve_anchors,
            "allow_rephrase": self.allow_rephrase,
        }


def tier_policy(value: int) -> TierPolicy:
    """Map an integer tier (0, 25, 50, 75, 100 or intermediate 0..100) to its contract."""
    tier = validate_tier(value)
    if tier == 100:
        return TierPolicy(tier=100, mode="verbatim", editable=False, min_token_retention=1.0, preserve_anchors=True, allow_rephrase=False)
    if tier >= 75:
        return TierPolicy(tier=tier, mode="tight_polish", editable=True, min_token_retention=0.60, preserve_anchors=True, allow_rephrase=True)
    if tier >= 50:
        return TierPolicy(tier=tier, mode="balanced_rewrite", editable=True, min_token_retention=0.30, preserve_anchors=True, allow_rephrase=True)
    if tier >= 1:
        return TierPolicy(tier=tier, mode="loose_infill", editable=True, min_token_retention=0.10, preserve_anchors=False, allow_rephrase=True)
    return TierPolicy(tier=0, mode="open_infill", editable=True, min_token_retention=0.0, preserve_anchors=False, allow_rephrase=True)


def occurrence_of(source_text: str, start: int, end: int) -> Tuple[int, int]:
    """Return (0-based occurrence_index, occurrence_total) of source_text[start:end]."""
    sub = source_text[start:end]
    if not sub:
        return 0, 1
    positions: List[int] = []
    pos = 0
    while True:
        idx = source_text.find(sub, pos)
        if idx == -1:
            break
        positions.append(idx)
        pos = idx + 1
    if start not in positions:
        raise ValueError("Slice boundaries do not align with source substring")
    return positions.index(start), len(positions)


def normalize_slot_ranges(
    source_text: str,
    ranges: Iterable[Any] = (),
    *,
    default_tier: int = 0,
    base_offset: int = 0,
) -> List[Tuple[int, int, int]]:
    """Partition [0, len(source_text)] into sorted, coalesced (start, end, tier) ranges."""
    default = validate_tier(default_tier)
    length = len(source_text)
    normalized: List[Tuple[int, int, int]] = []
    for item in ranges:
        if isinstance(item, Mapping):
            raw_a, raw_b, raw_val = item["start"], item["end"], item.get("value", item.get("tier", default))
        else:
            raw_a, raw_b, raw_val = item[0], item[1], item[2]
        if type(raw_a) is not int or type(raw_b) is not int:
            raise ValueError("Slot range offsets must be integers")
        a = raw_a - base_offset if raw_a >= base_offset and raw_b <= base_offset + length else raw_a
        b = raw_b - base_offset if raw_a >= base_offset and raw_b <= base_offset + length else raw_b
        a = max(0, min(length, a))
        b = max(0, min(length, b))
        tier = validate_tier(raw_val)
        if a < b:
            if not safe_grapheme_boundary(source_text, a) or not safe_grapheme_boundary(source_text, b):
                raise ValueError("Slot boundary splits a multi-code-point grapheme")
            normalized.append((a, b, tier))

    if length == 0:
        return []
    bounds = sorted({0, length, *(a for a, _, _ in normalized), *(b for _, b, _ in normalized)})
    out: List[Tuple[int, int, int]] = []
    for a, b in zip(bounds, bounds[1:]):
        if a >= b:
            continue
        tier = max((t for ra, rb, t in normalized if ra < b and a < rb), default=default)
        if out and out[-1][1] == a and out[-1][2] == tier:
            out[-1] = (out[-1][0], b, tier)
        else:
            out.append((a, b, tier))
    return out


@dataclass(frozen=True)
class InfillSlot:
    """One addressed slot (verbatim or editable tier) with exact occurrence coordinates."""

    slot_id: str
    index: int
    start: int
    end: int
    abs_start: int
    abs_end: int
    tier: int
    policy: TierPolicy
    source_text: str
    sha256: str
    occurrence_index: int
    occurrence_total: int
    left_context: str
    right_context: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "abs_start": self.abs_start,
            "abs_end": self.abs_end,
            "tier": self.tier,
            "mode": self.policy.mode,
            "editable": self.policy.editable,
            "sha256": self.sha256,
            "occurrence_index": self.occurrence_index,
            "occurrence_total": self.occurrence_total,
            "source_text": self.source_text,
            "left_context": self.left_context,
            "right_context": self.right_context,
        }


@dataclass(frozen=True)
class SeamFinding:
    """One structural seam or tier-fidelity violation."""

    code: str
    severity: str  # 'error' | 'warning'
    slot_id: Optional[str]
    position: Optional[int]
    message: str
    excerpt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "slot_id": self.slot_id,
            "position": self.position,
            "message": self.message,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class SeamValidationReport:
    """Result of validating filled or edited prose against an InfillPlan."""

    valid: bool
    issues: List[str]
    findings: List[SeamFinding]
    slot_reports: List[Dict[str, Any]] = field(default_factory=list)
    remapped_locks: List[Tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": list(self.issues),
            "findings": [f.to_dict() for f in self.findings],
            "slot_reports": list(self.slot_reports),
            "remapped_locks": [list(pair) for pair in self.remapped_locks],
        }


@dataclass(frozen=True)
class InfillPlan:
    """Partitioned occurrence-safe slot plan for one target span."""

    source_text: str
    base_offset: int
    source_sha256: str
    default_tier: int
    slots: Tuple[InfillSlot, ...]

    def editable_slots(self) -> List[InfillSlot]:
        return [s for s in self.slots if s.policy.editable]

    def locked_slots(self) -> List[InfillSlot]:
        return [s for s in self.slots if not s.policy.editable]

    def resolve_slot_key(self, key: Any) -> InfillSlot:
        """Resolve slot_id str, slot int index, (start, end) tuple, (text, occ_idx) tuple, or unique text."""
        if isinstance(key, int):
            if 0 <= key < len(self.slots):
                return self.slots[key]
            raise ValueError(f"Slot index {key} out of range")
        if isinstance(key, tuple) and len(key) == 2:
            left, right = key
            if type(left) is int and type(right) is int:
                for s in self.slots:
                    if (s.start, s.end) == (left, right) or (s.abs_start, s.abs_end) == (left, right):
                        return s
                raise ValueError(f"No slot matches offsets {key}")
            if isinstance(left, str) and type(right) is int:
                matches = [s for s in self.slots if s.source_text == left and s.occurrence_index == right]
                if len(matches) == 1:
                    return matches[0]
                raise ValueError(f"No slot matches text occurrence ({left!r}, {right})")
        if isinstance(key, str):
            by_id = [s for s in self.slots if s.slot_id == key]
            if len(by_id) == 1:
                return by_id[0]
            by_text = [s for s in self.slots if s.source_text == key]
            if not by_text:
                raise ValueError(f"Unknown slot reference '{key}'")
            if len(by_text) > 1 or by_text[0].occurrence_total > 1:
                raise ValueError(
                    f"Ambiguous duplicate occurrence for slot text {key!r}; target by slot_id, (start, end), or (text, occurrence_index)"
                )
            return by_text[0]
        raise ValueError(f"Unsupported slot reference: {key!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_offset": self.base_offset,
            "source_sha256": self.source_sha256,
            "default_tier": self.default_tier,
            "slot_count": len(self.slots),
            "editable_count": len(self.editable_slots()),
            "locked_count": len(self.locked_slots()),
            "slots": [s.to_dict() for s in self.slots],
        }


def plan_infill_slots(
    source_text: str,
    ranges: Iterable[Any] = (),
    *,
    default_tier: int = 0,
    base_offset: int = 0,
    context_chars: int = 40,
) -> InfillPlan:
    """Compile source_text and protection ranges into an occurrence-safe InfillPlan."""
    if not isinstance(source_text, str):
        raise ValueError("source_text must be a string")
    default = validate_tier(default_tier)
    normalized = normalize_slot_ranges(source_text, ranges, default_tier=default, base_offset=base_offset)
    slots: List[InfillSlot] = []
    for idx, (a, b, tier) in enumerate(normalized):
        chunk = source_text[a:b]
        digest_hex = _sha256(chunk)
        occ_idx, occ_total = occurrence_of(source_text, a, b)
        slot_id = f"slot-{idx}-{digest_hex[:8]}"
        slots.append(
            InfillSlot(
                slot_id=slot_id,
                index=idx,
                start=a,
                end=b,
                abs_start=base_offset + a,
                abs_end=base_offset + b,
                tier=tier,
                policy=tier_policy(tier),
                source_text=chunk,
                sha256=digest_hex,
                occurrence_index=occ_idx,
                occurrence_total=occ_total,
                left_context=source_text[max(0, a - context_chars) : a],
                right_context=source_text[b : min(len(source_text), b + context_chars)],
            )
        )
    return InfillPlan(
        source_text=source_text,
        base_offset=base_offset,
        source_sha256=_sha256(source_text),
        default_tier=default,
        slots=tuple(slots),
    )


def _content_tokens(text: str) -> List[str]:
    return [tok.casefold() for tok in _WORD_RE.findall(text) if tok.casefold() not in _STOPWORDS]


def _extract_anchors(text: str) -> List[str]:
    seen: List[str] = []
    for m in _ANCHOR_RE.finditer(text):
        tok = m.group(0).casefold()
        if tok not in seen and tok not in _STOPWORDS:
            seen.append(tok)
    return seen


def validate_slot_fidelity(
    slot: InfillSlot,
    candidate_segment: str,
    *,
    allow_empty: bool = False,
) -> List[SeamFinding]:
    """Validate a candidate replacement for a single InfillSlot against its TierPolicy."""
    findings: List[SeamFinding] = []
    if not isinstance(candidate_segment, str):
        return [SeamFinding("tier_violation", "error", slot.slot_id, slot.start, "Slot replacement must be text")]

    policy = slot.policy
    if not policy.editable:
        if candidate_segment != slot.source_text:
            findings.append(
                SeamFinding(
                    "tier_violation",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"100% locked slot {slot.slot_id} cannot be altered or deleted",
                    candidate_segment[:60],
                )
            )
        return findings

    if slot.source_text.strip() and not candidate_segment.strip():
        if not allow_empty:
            findings.append(
                SeamFinding(
                    "tier_empty_collapse",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Editable slot {slot.slot_id} ({slot.tier}%) collapsed non-empty text to empty",
                    slot.source_text[:60],
                )
            )
        return findings

    if policy.min_token_retention <= 0.0:
        return findings

    src_tokens = _content_tokens(slot.source_text)
    cand_tokens = set(_content_tokens(candidate_segment))
    if len(src_tokens) >= 4:
        retained = sum(1 for t in src_tokens if t in cand_tokens) / len(src_tokens)
        if retained < policy.min_token_retention:
            findings.append(
                SeamFinding(
                    "tier_violation",
                    "error",
                    slot.slot_id,
                    slot.start,
                    (
                        f"Slot {slot.slot_id} ({slot.tier}% {policy.mode}) retained {retained:.2f} "
                        f"content tokens below required {policy.min_token_retention:.2f}"
                    ),
                    candidate_segment[:80],
                )
            )

    if policy.preserve_anchors:
        anchors = _extract_anchors(slot.source_text)
        cand_lower = candidate_segment.casefold()
        missing = [a for a in anchors if not re.search(rf"(?<!\w){re.escape(a)}(?!\w)", cand_lower)]
        if missing:
            findings.append(
                SeamFinding(
                    "tier_anchor_loss",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Slot {slot.slot_id} ({slot.tier}% {policy.mode}) dropped concrete anchor(s): {', '.join(missing[:4])}",
                    candidate_segment[:80],
                )
            )
    return findings


def _check_boundary_seams(
    slot: InfillSlot,
    left_neighbor: str,
    candidate_segment: str,
    right_neighbor: str,
) -> List[SeamFinding]:
    """Detect word-glue collisions, heading collapse, quote imbalance, and >=5-word seam echoes."""
    findings: List[SeamFinding] = []
    if left_neighbor and candidate_segment:
        lch = left_neighbor[-1]
        rch = candidate_segment[0]
        orig_started_alnum = bool(slot.source_text) and slot.source_text[0].isalnum()
        if lch.isalnum() and rch.isalnum() and not orig_started_alnum:
            findings.append(
                SeamFinding(
                    "seam_word_collision",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Left seam at {slot.slot_id} collides alphanumeric tokens ('{left_neighbor[-12:]}' + '{candidate_segment[:12]}')",
                    left_neighbor[-12:] + candidate_segment[:12],
                )
            )
        if not safe_grapheme_boundary(left_neighbor + candidate_segment, len(left_neighbor)):
            findings.append(
                SeamFinding(
                    "seam_split_grapheme",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Left seam at {slot.slot_id} splits a Unicode grapheme",
                )
            )

    if candidate_segment and right_neighbor:
        lch = candidate_segment[-1]
        rch = right_neighbor[0]
        orig_ended_alnum = bool(slot.source_text) and slot.source_text[-1].isalnum()
        if lch.isalnum() and rch.isalnum() and not orig_ended_alnum:
            findings.append(
                SeamFinding(
                    "seam_word_collision",
                    "error",
                    slot.slot_id,
                    slot.end,
                    f"Right seam at {slot.slot_id} collides alphanumeric tokens ('{candidate_segment[-12:]}' + '{right_neighbor[:12]}')",
                    candidate_segment[-12:] + right_neighbor[:12],
                )
            )
        if not safe_grapheme_boundary(candidate_segment + right_neighbor, len(candidate_segment)):
            findings.append(
                SeamFinding(
                    "seam_split_grapheme",
                    "error",
                    slot.slot_id,
                    slot.end,
                    f"Right seam at {slot.slot_id} splits a Unicode grapheme",
                )
            )

    if right_neighbor and _HEADING_CUE.match(right_neighbor):
        had_nl = slot.source_text.endswith("\n")
        if had_nl and candidate_segment and not candidate_segment.endswith("\n"):
            findings.append(
                SeamFinding(
                    "seam_heading_collapse",
                    "error",
                    slot.slot_id,
                    slot.end,
                    f"Slot {slot.slot_id} collapsed newline separator before scene heading",
                    (candidate_segment[-16:] + right_neighbor[:24]).replace("\n", "\\n"),
                )
            )

    # Check quote & parenthesis parity delta against original slot
    src = slot.source_text
    if candidate_segment != src:
        if (candidate_segment.count('"') % 2) != (src.count('"') % 2):
            findings.append(
                SeamFinding(
                    "seam_quote_imbalance",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Slot {slot.slot_id} introduces unbalanced ASCII double quote across seam",
                )
            )
        src_curly = src.count("“") - src.count("”")
        cand_curly = candidate_segment.count("“") - candidate_segment.count("”")
        if cand_curly != src_curly:
            findings.append(
                SeamFinding(
                    "seam_quote_imbalance",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Slot {slot.slot_id} introduces unbalanced curly quote across seam",
                )
            )
        if (candidate_segment.count("(") - candidate_segment.count(")")) != (src.count("(") - src.count(")")):
            findings.append(
                SeamFinding(
                    "seam_paren_imbalance",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Slot {slot.slot_id} introduces unbalanced parentheses across seam",
                )
            )

    # Check >=5-word verbatim seam echo against neighboring text
    cand_words = [w.casefold() for w in _WORD_RE.findall(candidate_segment)]
    if len(cand_words) >= 5:
        left_words = [w.casefold() for w in _WORD_RE.findall(left_neighbor)]
        right_words = [w.casefold() for w in _WORD_RE.findall(right_neighbor)]
        if len(left_words) >= 5 and cand_words[:5] == left_words[-5:]:
            findings.append(
                SeamFinding(
                    "seam_verbatim_echo",
                    "error",
                    slot.slot_id,
                    slot.start,
                    f"Slot {slot.slot_id} repeats trailing 5 words of left context across seam",
                    " ".join(cand_words[:5]),
                )
            )
        if len(right_words) >= 5 and cand_words[-5:] == right_words[:5]:
            findings.append(
                SeamFinding(
                    "seam_verbatim_echo",
                    "error",
                    slot.slot_id,
                    slot.end,
                    f"Slot {slot.slot_id} repeats leading 5 words of right context across seam",
                    " ".join(cand_words[-5:]),
                )
            )
    return findings


def _align_slots_between_locks(
    plan: InfillPlan,
    assembled_text: str,
    *,
    source_edit: Optional[Tuple[int, int]] = None,
) -> Tuple[Optional[Dict[str, Tuple[int, int]]], List[SeamFinding]]:
    """Align locked 100% slots (and unambiguous editable spans) against assembled_text."""
    locked = plan.locked_slots()
    if assembled_text == plan.source_text:
        return {s.slot_id: (s.start, s.end) for s in plan.slots}, []

    findings: List[SeamFinding] = []
    if source_edit is not None:
        se_start, se_end = source_edit
        new_end = se_end + len(assembled_text) - len(plan.source_text)
        if not (
            0 <= se_start <= se_end <= len(plan.source_text)
            and se_start <= new_end <= len(assembled_text)
            and plan.source_text[:se_start] == assembled_text[:se_start]
            and plan.source_text[se_end:] == assembled_text[new_end:]
        ):
            findings.append(
                SeamFinding(
                    "occurrence_mismatch",
                    "error",
                    None,
                    se_start,
                    "Edit does not match its authorized source occurrence",
                )
            )
            return None, findings

        before_slice = plan.source_text[se_start:se_end]
        after_slice = assembled_text[se_start:new_end]
        mapped: Dict[str, Tuple[int, int]] = {}
        delta = new_end - se_end
        matches = None
        for s in plan.slots:
            if s.end <= se_start:
                mapped[s.slot_id] = (s.start, s.end)
            elif s.start >= se_end:
                mapped[s.slot_id] = (s.start + delta, s.end + delta)
            elif not s.policy.editable:
                if se_start == se_end:
                    findings.append(SeamFinding("protected_split", "error", s.slot_id, s.start, "Insertion splits a 100% locked slot"))
                    return None, findings
                left = max(s.start, se_start)
                right = min(s.end, se_end)
                overlap = plan.source_text[left:right]
                if before_slice.count(overlap) > 1 and after_slice.count(overlap) < before_slice.count(overlap):
                    findings.append(
                        SeamFinding(
                            "occurrence_ambiguity",
                            "error",
                            s.slot_id,
                            s.start,
                            "Edit ambiguously removes a protected occurrence; select the editable range",
                        )
                    )
                    return None, findings
                if matches is None:
                    matches = difflib.SequenceMatcher(a=before_slice, b=after_slice, autojunk=False).get_matching_blocks()
                match = next((m for m in matches if m.a <= left - se_start and right - se_start <= m.a + m.size), None)
                if match is None:
                    findings.append(
                        SeamFinding(
                            "tier_violation",
                            "error",
                            s.slot_id,
                            s.start,
                            f"100% locked slot {s.slot_id} altered or removed inside edit",
                        )
                    )
                    return None, findings
                dest = s.start + match.b - match.a
                if assembled_text[dest : dest + (s.end - s.start)] != s.source_text:
                    findings.append(SeamFinding("tier_violation", "error", s.slot_id, s.start, f"Locked slot {s.slot_id} altered"))
                    return None, findings
                mapped[s.slot_id] = (dest, dest + (s.end - s.start))
            elif len(plan.editable_slots()) == 1 or (se_start <= s.start and s.end <= se_end and sum(
                1 for e in plan.slots if e.start < se_end and se_start < e.end and e.policy.editable
            ) == 1):
                mapped[s.slot_id] = (se_start, new_end)
        return mapped, findings

    # No explicit source_edit: align locked anchors sequentially via exact find
    mapped = {}
    cursor = 0
    for s in locked:
        pos = assembled_text.find(s.source_text, cursor)
        if pos < 0:
            findings.append(
                SeamFinding(
                    "tier_violation",
                    "error",
                    s.slot_id,
                    s.start,
                    f"100% locked slot {s.slot_id} missing, altered, or out of order",
                    s.source_text[:60],
                )
            )
            return None, findings
        # If there are duplicate copies of s.source_text in the document, require count preservation
        src_copies = plan.source_text.count(s.source_text)
        cand_copies = assembled_text.count(s.source_text)
        if src_copies > 1 and cand_copies < src_copies:
            findings.append(
                SeamFinding(
                    "occurrence_ambiguity",
                    "error",
                    s.slot_id,
                    s.start,
                    f"Duplicate locked occurrence '{s.source_text[:30]}' count changed without source_edit disambiguation",
                )
            )
            return None, findings
        mapped[s.slot_id] = (pos, pos + len(s.source_text))
        cursor = pos + len(s.source_text)

    # Align unique editable spans bracketed between consecutive locked anchors
    for idx, s in enumerate(plan.slots):
        if s.slot_id in mapped:
            continue
        prev_locked = next((plan.slots[j] for j in range(idx - 1, -1, -1) if not plan.slots[j].policy.editable), None)
        next_locked = next((plan.slots[j] for j in range(idx + 1, len(plan.slots)) if not plan.slots[j].policy.editable), None)
        span_start = mapped[prev_locked.slot_id][1] if prev_locked else 0
        span_end = mapped[next_locked.slot_id][0] if next_locked else len(assembled_text)
        # Only assign exact editable slice when no adjacent editable slot shares this bracket
        left_is_editable = idx > 0 and plan.slots[idx - 1].policy.editable
        right_is_editable = idx + 1 < len(plan.slots) and plan.slots[idx + 1].policy.editable
        if not left_is_editable and not right_is_editable:
            mapped[s.slot_id] = (span_start, span_end)
    return mapped, findings


def validate_infill_seams(
    plan: InfillPlan,
    assembled_text: str,
    *,
    source_edit: Optional[Tuple[int, int]] = None,
    slot_segments: Optional[Mapping[str, str]] = None,
    enforce_tier_fidelity: bool = True,
    allow_empty: bool = False,
) -> SeamValidationReport:
    """Validate protection tiers, duplicate-occurrence integrity, and structural boundary seams."""
    if not isinstance(assembled_text, str) or not assembled_text.strip():
        finding = SeamFinding("empty_output", "error", None, 0, "Output is empty")
        return SeamValidationReport(valid=False, issues=[finding.message], findings=[finding])

    findings: List[SeamFinding] = []
    slot_reports: List[Dict[str, Any]] = []
    mapped, align_findings = _align_slots_between_locks(plan, assembled_text, source_edit=source_edit)
    findings.extend(align_findings)

    remapped_locks: List[Tuple[int, int]] = []
    if mapped is not None:
        for s in plan.locked_slots():
            if s.slot_id in mapped:
                remapped_locks.append(mapped[s.slot_id])

        for idx, s in enumerate(plan.slots):
            cand_seg: Optional[str] = None
            left_nb = s.left_context
            right_nb = s.right_context
            if slot_segments is not None and s.slot_id in slot_segments:
                cand_seg = slot_segments[s.slot_id]
            elif s.slot_id in mapped:
                a, b = mapped[s.slot_id]
                cand_seg = assembled_text[a:b]
                left_nb = assembled_text[max(0, a - 40) : a]
                right_nb = assembled_text[b : min(len(assembled_text), b + 40)]

            if cand_seg is None:
                continue

            seam_hits = _check_boundary_seams(s, left_nb, cand_seg, right_nb) if cand_seg != s.source_text else []
            tier_hits: List[SeamFinding] = []
            if enforce_tier_fidelity and (cand_seg != s.source_text or not s.policy.editable):
                effective_allow_empty = allow_empty or (source_edit is not None and cand_seg == "")
                tier_hits = validate_slot_fidelity(s, cand_seg, allow_empty=effective_allow_empty)

            findings.extend(seam_hits)
            findings.extend(tier_hits)
            slot_reports.append({
                "slot_id": s.slot_id,
                "tier": s.tier,
                "changed": cand_seg != s.source_text,
                "issues": [f.code for f in (*seam_hits, *tier_hits)],
            })

    issues = [f.message for f in findings]
    return SeamValidationReport(
        valid=len(findings) == 0,
        issues=issues,
        findings=findings,
        slot_reports=slot_reports,
        remapped_locks=remapped_locks,
    )


def apply_slot_fills(
    plan: InfillPlan,
    fills: Mapping[Any, str] | Sequence[Tuple[Any, str]],
    *,
    validate: bool = True,
    enforce_tier_fidelity: bool = True,
    allow_empty: bool = False,
) -> Dict[str, Any]:
    """Apply occurrence-safe fills to an InfillPlan, splice cleanly, and run seam/tier validation."""
    pairs = list(fills.items()) if isinstance(fills, Mapping) else list(fills)
    if not pairs:
        report = validate_infill_seams(plan, plan.source_text, enforce_tier_fidelity=enforce_tier_fidelity)
        return {
            "text": plan.source_text,
            "source_edit": (0, 0),
            "candidate_bounds": (0, 0),
            "applied_slots": [],
            "validation": report.to_dict(),
        }

    resolved: Dict[str, str] = {}
    for ref, replacement in pairs:
        if not isinstance(replacement, str):
            raise ValueError("Slot fill replacement must be a string")
        slot = plan.resolve_slot_key(ref)
        if slot.slot_id in resolved:
            raise ValueError(f"Duplicate fill target for slot {slot.slot_id}")
        if not slot.policy.editable and replacement != slot.source_text:
            raise ValueError(f"100% locked slot {slot.slot_id} cannot be edited")
        resolved[slot.slot_id] = replacement

    pieces: List[str] = []
    slot_segments: Dict[str, str] = {}
    cand_bounds_by_slot: Dict[str, Tuple[int, int]] = {}
    cursor = 0
    for slot in plan.slots:
        seg = resolved.get(slot.slot_id, slot.source_text)
        pieces.append(seg)
        slot_segments[slot.slot_id] = seg
        cand_bounds_by_slot[slot.slot_id] = (cursor, cursor + len(seg))
        cursor += len(seg)

    assembled = "".join(pieces)
    edited = [s for s in plan.slots if s.slot_id in resolved and resolved[s.slot_id] != s.source_text]
    if edited:
        source_edit = (edited[0].start, edited[-1].end)
        cand_bounds = (cand_bounds_by_slot[edited[0].slot_id][0], cand_bounds_by_slot[edited[-1].slot_id][1])
    else:
        source_edit = (0, 0)
        cand_bounds = (0, 0)

    report = validate_infill_seams(
        plan,
        assembled,
        source_edit=source_edit if edited else None,
        slot_segments=slot_segments,
        enforce_tier_fidelity=enforce_tier_fidelity,
        allow_empty=allow_empty,
    )
    if validate and not report.valid:
        raise ValueError("; ".join(report.issues))

    return {
        "text": assembled,
        "source_edit": source_edit,
        "candidate_bounds": cand_bounds,
        "applied_slots": [s.slot_id for s in edited],
        "validation": report.to_dict(),
    }
