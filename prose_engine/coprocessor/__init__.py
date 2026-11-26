"""
Prose Engine Local Coprocessors.
High-speed, GPU-accelerated local micro-models running on RTX 4080 Super alongside Gemini.
"""

from .guardrail import GuardrailAuditReport, GuardrailCoprocessor
from .harness import CoprocessorPipelineReport, DualEngineHarness
from .micro_generator import DialedCandidate, LocalMicroGenerator
from .reranker import LocalSomaticReranker, RerankResult

__all__ = [
    "LocalSomaticReranker",
    "RerankResult",
    "LocalMicroGenerator",
    "DialedCandidate",
    "GuardrailCoprocessor",
    "GuardrailAuditReport",
    "DualEngineHarness",
    "CoprocessorPipelineReport",
]
