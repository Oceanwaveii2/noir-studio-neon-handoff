"""
Imagery retention: word overlap cannot see that "popcorn popping in a bowl" is the same image
as "pop like popcorn". This module extracts comparison vehicles and detects reuse.
"""

from __future__ import annotations

import re
from typing import Set

_COMPARISON = re.compile(
    r"\b(?:like|resembling|looked like|looks like|felt like)\b\s+((?:(?!\b(?:like|resembling)\b)[^,.;!?]){1,40})",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")

# Words that are too common to prove a comparison was reused.
_GENERIC = {
    "the", "and", "her", "his", "its", "their", "with", "that", "this", "into", "from",
    "over", "under", "through", "against", "skin", "air", "room", "body", "face", "hand",
    "hands", "arms", "shoulders", "hips", "torso", "couch", "dress", "sound", "note",
    "something", "someone", "thing", "little", "whole", "own", "more", "very", "then",
    "when", "while", "about", "down", "up", "out", "off", "onto", "toward", "towards",
    "shoulder", "shoulders", "collarbone", "collarbones", "spine", "jaw", "mouth",
    "cheek", "cheeks", "rear", "neck", "throat", "chest", "stomach", "eye", "eyes",
    "hair", "tail", "vein", "veins", "dress", "couch", "pillow", "pillows", "seam",
    "seams", "arm", "arms", "leg", "legs", "thigh", "thighs", "hip", "hips", "back",
    "they", "them", "their", "she", "he", "him", "it", "its", "you", "we", "i",
    "re", "ve", "ll", "s", "until", "when", "while", "then", "like",
}


def _stem(word: str) -> str:
    word = word.lower().strip("'-")
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def vehicles(text: str) -> Set[str]:
    """Content words inside comparison phrases ('like X', 'as if X', 'resembling X')."""
    found: Set[str] = set()
    for match in _COMPARISON.finditer(text):
        tail = re.split(r"\b(?:and|but|then|when|while|until|that|which|so)\b", match.group(1))[0]
        for word in _WORD.findall(tail)[:3]:
            if word.lower().endswith("ing"):  # participles are motion, not imagery
                continue
            stem = _stem(word)
            if len(stem) >= 4 and stem not in _GENERIC:
                found.add(stem)
    return found


def retained(original: str, candidate: str) -> Set[str]:
    """Original comparison vehicles that still appear anywhere in the candidate."""
    candidate_words = {_stem(word) for word in _WORD.findall(candidate)}
    return {stem for stem in vehicles(original) if stem in candidate_words}


def mask(text: str) -> str:
    """Replaces comparison phrases with a placeholder so they cannot be copied."""
    return _COMPARISON.sub(" [image removed]", text)
