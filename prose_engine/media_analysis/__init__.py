"""Promoted offline multimodal clip analysis and opt-in evidence sidecar for prose_engine."""
from __future__ import annotations

from .analyzer import (
    ClipExpressiveEnvelope,
    Evidence,
    PauseWindow,
    analyze_clip,
    compare_ocr,
    compare_timed,
    detect_wav_pauses,
    load_evidence,
    resolve_hf_snapshot,
    save_evidence,
)

__all__ = [
    "ClipExpressiveEnvelope",
    "Evidence",
    "PauseWindow",
    "analyze_clip",
    "compare_ocr",
    "compare_timed",
    "detect_wav_pauses",
    "load_evidence",
    "resolve_hf_snapshot",
    "save_evidence",
]
