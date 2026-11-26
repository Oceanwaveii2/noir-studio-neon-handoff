"""
Standalone prose conditioning engine.

Extracted from the Narrative Composer's `narrative_composer.prose` package so it can run
without the screenplay compiler: diagnostics, style profiles, prompt assembly, the invariant
gate, providers, and a reference-book corpus for style grounding.
"""

from .approved_edits import ApprovedEditPair, ApprovedEditsStore
from .conditioner import (
    Proposal,
    apply_proposals,
    paragraph_spans,
    plan_conditioning,
    run_conditioning,
    text_metrics,
)
from .corpus import (
    Book,
    book_stats,
    corpus_index,
    derive_style_profile,
    load_corpus,
    load_passages,
    reference_passages,
    save_passages,
)
from .diagnostics import ProseDiagnosticsAnalyzer
from .invariant_gate import InvariantGate
from .models import (
    ProseDiagnosticReport,
    ProseRewriteProposal,
    ProseRewriteRequest,
    SpanCategory,
)
from .prompt_assembler import PromptAssembler
from .protected_spans import ProtectedSpanProtector
from .providers import create_prose_provider
from .semantic_drive import ReferencePassage, SemanticDrive
from .style_engine import (
    HOT_SCOOMP_TV14,
    NOIR_DETECTIVE,
    STANDARD_DRAMATIC,
    StyleProfile,
    StyleProfileRepository,
)

__version__ = "0.1.0"

__all__ = [
    "ApprovedEditPair",
    "ApprovedEditsStore",
    "Book",
    "HOT_SCOOMP_TV14",
    "InvariantGate",
    "NOIR_DETECTIVE",
    "Proposal",
    "ProseDiagnosticReport",
    "ProseDiagnosticsAnalyzer",
    "ProseRewriteProposal",
    "ProseRewriteRequest",
    "PromptAssembler",
    "ProtectedSpanProtector",
    "ReferencePassage",
    "STANDARD_DRAMATIC",
    "SemanticDrive",
    "SpanCategory",
    "StyleProfile",
    "StyleProfileRepository",
    "apply_proposals",
    "book_stats",
    "corpus_index",
    "create_prose_provider",
    "derive_style_profile",
    "load_corpus",
    "load_passages",
    "paragraph_spans",
    "plan_conditioning",
    "reference_passages",
    "run_conditioning",
    "save_passages",
    "text_metrics",
]
