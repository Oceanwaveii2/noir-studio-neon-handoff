"""Voice engine: measurement, retrieval, steering, selection, structure, critique, and author lenses."""

from .evaluate import Evaluator, Decision
from .tics import Finding, scan, counts, blacklisted_cliches, BLACKLIST_CLICHES
from .lens import AuthorLens, get_lens, list_lenses, LENSES
from .injection import format_injection_prompt, sample_idioms, sample_rhythm, calculate_borrow_rate, get_lens_bank
from .synthesizer import (
    DeNovoSynthesizer, DialogueLine, DramaticBeat,
    extract_dialogue_skeleton, verify_dialogue_invariant
)

__all__ = [
    "Evaluator", "Decision", "Finding", "scan", "counts",
    "blacklisted_cliches", "BLACKLIST_CLICHES",
    "AuthorLens", "get_lens", "list_lenses", "LENSES",
    "format_injection_prompt", "sample_idioms", "sample_rhythm", "calculate_borrow_rate", "get_lens_bank",
    "DeNovoSynthesizer", "DialogueLine", "DramaticBeat",
    "extract_dialogue_skeleton", "verify_dialogue_invariant"
]
