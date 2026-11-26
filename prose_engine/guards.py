"""
Fact preservation: a rewrite may not drop names, numbers, props, or quoted dialogue.

This is the guard that makes bolder rewrites safe to accept. It is deliberately conservative on
what counts as a "fact": proper names, numbers, ALL-CAPS tokens (screenplay props/cues), and
quoted spans of three or more characters.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

_STOP_NAMES = {
    "The", "A", "An", "She", "He", "It", "They", "We", "You", "I", "His", "Her", "Their",
    "This", "That", "These", "Those", "But", "And", "Then", "When", "While", "After", "Before",
    "Meanwhile", "Later", "Now", "Outside", "Inside", "Above", "Below", "Somewhere", "Nothing",
    "Everyone", "Nobody", "Something", "Yes", "No", "Okay", "Beat", "CUT", "FADE", "INT", "EXT",
    "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
}

_COMMON_CAPS = {
    "Under", "Over", "In", "On", "At", "From", "With", "Without", "Across", "Beside",
    "Behind", "Between", "Among", "Around", "Through", "Down", "Up", "Off", "Past",
    "Near", "Against", "Toward", "Towards", "During", "Because", "If", "So", "Yet",
    "Still", "Even", "Only", "Just", "Like", "As", "Once", "Before", "After",
    "Since", "Until", "Despite", "Except", "Inside", "Outside", "Above", "Below",
    "When", "Where", "What", "Who", "Why", "How", "There", "Here", "Every", "Each",
    "Both", "Either", "Neither", "Another", "Other", "Such", "Same", "More", "Most",
    "Less", "Least", "Many", "Much", "Few", "Several", "All", "Any", "Some", "None",
    "Not", "Never", "Always", "Sometimes", "Often", "Again", "Already", "Almost",
    "Also", "Though", "Although", "Unless", "Whether", "Into", "Onto", "Upon", "Beneath", "Beside",
}

_NAME = re.compile(r"\b([A-Z][a-z]{2,})\b")
_ALL_CAPS = re.compile(r"\b([A-Z]{2,}(?:[ -][A-Z]{2,})*)\b")
_NUMBER = re.compile(r"\b(\d+(?:[.,]\d+)?)\b")
_QUOTED = re.compile(r"[\"\u201c]([^\"\u201d]{3,})[\"\u201d]")

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
}

_CANON_PROPS = {
    "pink dress", "pearls", "red lipstick", "tupperware", "tupperware containers",
    "bandage dress", "red dress", "vanity stool", "stool", "platform boots", "heels",
    "candy cane",
}


def _normalize_numbers(text: str) -> List[str]:
    norm_text = _norm(text).lower()
    nums = set(_NUMBER.findall(text))
    for word in re.findall(r"\b[a-z]+\b", norm_text):
        if word in _NUMBER_WORDS:
            nums.add(_NUMBER_WORDS[word])
    return sorted(nums)


def facts(text: str) -> Dict[str, List[str]]:
    names = sorted({m for m in _NAME.findall(text) if m not in _STOP_NAMES})
    caps = sorted({m for m in _ALL_CAPS.findall(text) if m not in {"INT", "EXT", "O", "S", "V"}})
    numbers = _normalize_numbers(text)
    quotes = sorted({q.strip() for q in _QUOTED.findall(text) if q.strip()})
    return {"names": names, "caps": caps, "numbers": numbers, "quotes": quotes}


def fact_list(text: str) -> List[str]:
    """Flat list of the facts a rewrite must keep (names, caps, numbers, quotes)."""
    found = facts(text)
    items: List[str] = []
    for key in ("names", "caps", "numbers"):
        items.extend(found[key])
    items.extend(found["quotes"])
    return sorted(set(items))


def missing_facts(original: str, candidate: str, keep=None) -> List[str]:
    """Returns the facts present in the original but absent from the candidate."""
    before = facts(original)
    after = facts(candidate)
    missing: List[str] = []
    for key in ("names", "caps", "numbers"):
        missing.extend(item for item in before[key] if item not in after[key])
    for quote in before["quotes"]:
        if quote not in candidate:
            missing.append(f'"{quote}"')

    # Prop and visual descriptor preservation (finding F18)
    props_to_check = set(keep) if keep else _CANON_PROPS
    orig_lower = _norm(original).lower()
    cand_lower = _norm(candidate).lower()
    for prop in sorted(props_to_check):
        prop_norm = _norm(prop).lower()
        if prop_norm in orig_lower and prop_norm not in cand_lower:
            missing.append(prop)
    return missing


def preserves_facts(original: str, candidate: str, keep=None) -> Tuple[bool, List[str]]:
    missing = missing_facts(original, candidate, keep=keep)
    return (not missing, missing)


def introduced_entities(original: str, candidate: str, allowed=()) -> List[str]:
    """Proper names in the candidate that were not in the original and are not in the cast.

    The correction mode must never invent a character, place or organisation. This is the
    presence check's other half: preserves_facts stops losses, this stops additions.
    """
    before = set(_NAME.findall(original)) | set(_ALL_CAPS.findall(original))
    allowed_lower = {item.lower() for item in allowed}
    found = []
    for match in _NAME.finditer(candidate):
        word = match.group(1)
        if word in before or word.lower() in allowed_lower or word in _STOP_NAMES or word in _COMMON_CAPS:
            continue
        found.append(word)
    return sorted(set(found))


def _norm(text: str) -> str:
    return (
        text.replace("\u2019", "'").replace("\u2018", "'")
        .replace("\u2014", " ").replace("\u2013", " ")
    )


def reference_copies(candidate: str, references, n: int = 6):
    """Verbatim n-grams shared with the retrieved book passages (borrowing check)."""
    if not references:
        return []
    def grams(text):
        words = re.findall(r"[a-z']+", _norm(text).lower())
        return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}
    candidate_grams = grams(candidate)
    found = set()
    for reference in references:
        found |= candidate_grams & grams(reference)
    return sorted(found)


SPEECH_VERBS = r"(?:said|says|laughed|laughes|replied|asked|whispered|yelled|shouted|muttered|smiled|nodded|shrugged|sighed)"


def load_cast() -> set[str]:
    try:
        from .paths import books
        path = books("world_state.json")
        if path.is_file():
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            cast = set(data.get("characters", {}).keys())
            for char_data in data.get("characters", {}).values():
                cast.update(char_data.get("aliases", []))
            if cast:
                return cast
    except Exception:
        pass
    return {"Rainee", "Francine", "Haley", "Roger", "Steve"}


CAST = {"Rainee", "Francine", "Haley", "Stella", "Roger", "Steve", "Jeff", "Holly", "Barry", "Snot", "Toshi"}


def personification_issues(candidate: str, cast=None):
    """An object cannot speak or act like a person: catch 'Tupperware laughed'."""
    effective_cast = load_cast() if cast is None else cast
    issues = []
    for match in re.finditer(rf"\b([A-Z][a-z]+)\s+{SPEECH_VERBS}\b", candidate):
        word = match.group(1)
        if word not in effective_cast and word not in _STOP_NAMES and word not in _COMMON_CAPS:
            issues.append(f"{word} is treated as a person")
    return issues


_STOP = {"the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "with", "was", "were", "is", "are", "it", "that", "this", "he", "she", "they", "his", "her", "their", "as", "by", "from"}


def _content_shingles(text: str, n: int = 4):
    words = [word for word in re.findall(r"[a-z']+", text.lower()) if word not in _STOP]
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _name_normalized(text: str, n: int = 8):
    normalized = re.sub(r"\b[A-Z][a-z]{2,}\b", "<NAME>", text)
    words = re.findall(r"[a-z']+|<NAME>", normalized.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def copy_issues(candidate: str, references, ngram: int = 5):
    """Copy detector v2: exact n-grams, content 4-grams, name-swapped 8-grams, shingle Jaccard, content Jaccard."""
    issues = []
    if not references:
        return issues
    if reference_copies(candidate, references, ngram):
        issues.append(f"verbatim {ngram}-gram")
    elif ngram != 6 and reference_copies(candidate, references, 6):
        issues.append("verbatim 6-gram")
    candidate_content = _content_shingles(candidate)
    for reference in references:
        if candidate_content & _content_shingles(reference):
            issues.append("content 4-gram")
            break
    candidate_norm = _name_normalized(candidate)
    for reference in references:
        if candidate_norm & _name_normalized(reference):
            issues.append("name-swapped 8-gram")
            break
    candidate_shingles = _content_shingles(candidate, 5)
    for reference in references:
        other = _content_shingles(reference, 5)
        if candidate_shingles and other:
            jaccard = len(candidate_shingles & other) / len(candidate_shingles | other)
            if jaccard >= 0.5:
                issues.append(f"shingle Jaccard {jaccard:.2f}")
                break
    for reference in references:
        overlap = token_overlap(reference, candidate)
        if overlap >= 0.45:
            issues.append(f"reference token overlap {overlap:.2f}")
            break
    return sorted(set(issues))


def token_overlap(original: str, candidate: str) -> float:
    """Jaccard overlap of content words; 1.0 means the candidate is a near-copy."""
    import re

    def words(text: str) -> set:
        return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 2}

    before = words(original)
    after = words(candidate)
    if not before or not after:
        return 0.0
    return len(before & after) / len(before | after)
