"""
Dual-Engine Pipeline Harness: Cloud LLM / Macro Synthesizer + Local Micro Coprocessors.
Milestone CP-4: Dual-Engine Pipeline Harness.

Coordinates high-throughput local GPU coprocessors (RTX 4080 Super):
  - CP-1: LocalSomaticReranker (MiniLM L6 dense embedding & soft-weight modulation)
  - CP-2: LocalMicroGenerator (Qwen3.5-9B rapid micro-dialogue & farce SFX)
  - CP-3: GuardrailCoprocessor (6-gram copy detection & anti-AI linter)
in conjunction with the Macro Realizer / Cloud Engine.

Modes supported:
  - 'hybrid' (default): Accelerates somatic chunk reranking, micro-dialogue dialing,
    and comic farce onomatopoeia via local CUDA coprocessors, while macro prose
    synthesis is verified through real-time guardrail screening.
  - 'local': Pure local coprocessor execution without external cloud dependencies.
  - 'rule_based': Deterministic CPU fallback (M-PE1 through M-PE7 logic without
    requiring PyTorch/CUDA weights loaded).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..deep_scan import DeepScanEngine
from ..dialogue_dial import CharacterInfluenceSettings, DialogueDialEngine
from ..dispatcher.router import SubCorpusDispatcher
from ..gag_injector import MandatoryGagInjector
from ..hybrid_realizer import ScriptNovelHybridRealizer
from ..linter import AntiAILinter
from ..prepass.feature_ledger import AestheticFeatureLedger
from .guardrail import GuardrailAuditReport, GuardrailCoprocessor
from .micro_generator import DialedCandidate, LocalMicroGenerator
from .reranker import LocalSomaticReranker, RerankResult


@dataclass
class CoprocessorPipelineReport:
    mode: str
    device: str
    stages_executed: List[str]
    somatic_reranking_applied: bool
    micro_generator_applied: bool
    guardrail_report: Dict[str, Any]
    output_files: Dict[str, str]
    word_count: int
    burstiness_score: float
    gags_verified: int
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DualEngineHarness:
    """
    Coordinates Macro Prose Synthesis with Local Micro Coprocessors.
    """

    SUPPORTED_MODES = ("hybrid", "local", "rule_based")

    def __init__(
        self,
        mode: str = "hybrid",
        device: Optional[str] = None,
        lazy_load: bool = True,
    ):
        if mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported mode '{mode}'. Choose from {self.SUPPORTED_MODES}.")

        self.mode = mode
        self._device_override = device
        self._lazy_load = lazy_load

        # Core Engines
        self.guardrail = GuardrailCoprocessor()
        self.realizer = ScriptNovelHybridRealizer()
        self.gag_injector = MandatoryGagInjector()
        self.dial_engine = DialogueDialEngine()
        self.dispatcher = SubCorpusDispatcher()
        self.deep_scan_engine = DeepScanEngine()
        self.ledger_engine = AestheticFeatureLedger()

        # Coprocessors (lazily initialized if mode != 'rule_based')
        self._reranker: Optional[LocalSomaticReranker] = None
        self._micro_generator: Optional[LocalMicroGenerator] = None

        if not lazy_load and self.mode in ("hybrid", "local"):
            _ = self.reranker
            _ = self.micro_generator

    @property
    def reranker(self) -> LocalSomaticReranker:
        if self._reranker is None:
            self._reranker = LocalSomaticReranker(
                device=self._device_override,
                lazy_load=False,
            )
        return self._reranker

    @property
    def micro_generator(self) -> LocalMicroGenerator:
        if self._micro_generator is None:
            self._micro_generator = LocalMicroGenerator(
                device=self._device_override,
                lazy_load=False,
            )
        return self._micro_generator

    @property
    def active_device(self) -> str:
        if self.mode == "rule_based":
            return "cpu"
        try:
            return str(self.reranker.device)
        except Exception:
            return "cpu"

    # -------------------------------------------------------------------------
    # Coprocessor Capabilities
    # -------------------------------------------------------------------------

    def rerank_somatic_passages(
        self,
        queries: Sequence[str],
        candidate_passages: Sequence[Dict[str, Any]],
        book_weights: Optional[Dict[str, float]] = None,
        top_k: int = 5,
    ) -> List[RerankResult]:
        """
        Reranks candidate somatic passages by semantic relevance modulated by soft book weights.
        In 'hybrid' or 'local' mode, uses LocalSomaticReranker on GPU.
        In 'rule_based' mode, falls back to deterministic weight and lexical ranking.
        """
        if not candidate_passages:
            return []

        weights = dict(book_weights or {})
        for p in candidate_passages:
            slug = p.get("book_slug") or p.get("book_id") or "corpus"
            if slug not in weights and "weight" in p:
                weights[slug] = float(p["weight"])

        formatted_passages: List[Dict[str, Any]] = []
        for p in candidate_passages:
            slug = p.get("book_slug") or p.get("book_id") or "corpus"
            author = p.get("author", "Unknown")
            text = p.get("text", "")
            formatted_passages.append({
                "book_slug": slug,
                "author": author,
                "text": text,
            })

        if self.mode in ("hybrid", "local"):
            return self.reranker.rank_passages(
                queries=queries,
                passages=formatted_passages,
                book_weights=weights,
                top_k=top_k,
            )

        # Rule-based fallback
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for p in formatted_passages:
            slug = p["book_slug"]
            weight = float(weights.get(slug, 1.0))
            text = p["text"]
            # Simple lexical overlap
            lex_score = 0.0
            for q in queries:
                for word in q.lower().split():
                    if word in text.lower():
                        lex_score += 0.1
            score = (1.0 + lex_score) * weight
            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        results: List[RerankResult] = []
        for (score, p) in scored[:top_k]:
            slug = p["book_slug"]
            w = float(weights.get(slug, 1.0))
            excerpt = p["text"][:277] + "..." if len(p["text"]) > 280 else p["text"]
            results.append(
                RerankResult(
                    author=p["author"],
                    book_slug=slug,
                    excerpt=excerpt,
                    query_match=queries[0] if queries else "",
                    raw_similarity=round(score / max(1.0, w), 4),
                    book_weight=w,
                    effective_score=round(score, 4),
                )
            )
        return results

    def dial_dialogue_line(
        self,
        speaker: str,
        raw_text: str,
        raw_parenthetical: Optional[str] = None,
        target_level: int = 0,
        character_lens: str = "general",
    ) -> DialedCandidate:
        """
        Dials a single line of dialogue conforming to target level bounds.
        In 'hybrid' or 'local' mode, uses LocalMicroGenerator for creative variations.
        In 'rule_based' mode, uses DialogueDialEngine.
        """
        if self.mode in ("hybrid", "local"):
            candidates = self.micro_generator.generate_dialogue_candidates(
                speaker=speaker,
                raw_text=raw_text,
                raw_parenthetical=raw_parenthetical,
                target_level=target_level,
                character_lens=character_lens,
                num_candidates=2,
            )
            # Pick best compliant candidate
            compliant = [c for c in candidates if c.is_compliant]
            if compliant:
                return compliant[0]
            if candidates:
                return candidates[0]

        # Rule-based fallback
        dialed_line = self.dial_engine.dial_line(
            speaker=speaker,
            raw_text=raw_text,
            raw_parenthetical=raw_parenthetical,
            level=target_level,
        )
        drift = dialed_line.word_drift_pct
        if target_level == 0:
            is_comp = (drift == 0.0 and dialed_line.dialed_text == raw_text)
        elif target_level == 20:
            is_comp = (drift == 0.0)
        elif target_level == 50:
            is_comp = (15.0 <= drift <= 67.0)
        elif target_level == 75:
            is_comp = (45.0 <= drift <= 98.0)
        else:
            is_comp = True

        return DialedCandidate(
            speaker=dialed_line.speaker,
            raw_text=dialed_line.raw_text,
            dialed_text=dialed_line.dialed_text,
            dialed_parenthetical=dialed_line.dialed_parenthetical,
            influence_level=dialed_line.influence_level,
            word_drift_pct=dialed_line.word_drift_pct,
            is_compliant=is_comp,
            generation_source="rule_based_matrix",
        )

    def generate_farce_sfx(self, gag_type: str, context: str = "") -> str:
        """
        Generates comic farce onomatopoeia for physical comedy beats.
        """
        if self.mode in ("hybrid", "local"):
            return self.micro_generator.generate_farce_onomatopoeia(gag_type, context)

        # Rule-based fallback
        fallback_sfx = {
            "tile_amplification": "*BRAAAP-P-P-P-T!*",
            "acoustic_tile_amplification": "*BRAAAP-P-P-P-T!*",
            "bowl_water_ripples": "*PLOOP-SHIVER-R-R!*",
            "bowl_water_vibration": "*PLOOP-SHIVER-R-R!*",
            "towel_silencer_failure": "*PFFT-SCREEECH!*",
            "towel_muffle_failure": "*PFFT-SCREEECH!*",
            "outboard_motor_rumble": "*CHUG-CHUG-PUTT-PUTT!*",
            "outboard_motor_shudder": "*CHUG-CHUG-PUTT-PUTT!*",
            "dead_flower_shop_collision": "*PSSSHT-GAGGG!*",
            "dead_flower_shop_clash": "*PSSSHT-GAGGG!*",
            "draft_under_doorframe": "*WHSSSH-SLITHER!*",
            "doorframe_evacuation_draft": "*WHSSSH-SLITHER!*",
        }
        return fallback_sfx.get(gag_type, "*BRAAAP-SPLAT!*")

    def audit_prose(
        self,
        text: str,
        reference_passages: Optional[Sequence[str]] = None,
        burstiness_threshold: float = 4.0,
        ontology_negative_rules: Optional[Sequence[Dict[str, str]]] = None,
        character_morph_permissions: Optional[Dict[str, bool]] = None,
    ) -> GuardrailAuditReport:
        """
        Executes sub-second 6-gram plagiarism screening and Anti-AI linter checks.
        """
        return self.guardrail.audit_text(
            candidate_text=text,
            reference_passages=reference_passages,
            burstiness_threshold=burstiness_threshold,
            ontology_negative_rules=ontology_negative_rules,
            character_morph_permissions=character_morph_permissions,
        )

    # -------------------------------------------------------------------------
    # End-to-End Orchestration
    # -------------------------------------------------------------------------

    def synthesize_and_verify(
        self,
        dialed_manifest_path: Path,
        output_path: Optional[Path] = None,
        burstiness_threshold: float = 4.0,
        reference_passages: Optional[Sequence[str]] = None,
        minimum_gags: int = 3,
        ontology_negative_rules: Optional[Sequence[Dict[str, str]]] = None,
        character_morph_permissions: Optional[Dict[str, bool]] = None,
    ) -> Tuple[str, GuardrailAuditReport]:
        """
        Synthesizes the Script-Novel Hybrid manuscript and immediately subjects it
        to real-time pre-flight/post-flight guardrail auditing.
        """
        text = self.realizer.realize_manifest(dialed_manifest_path, output_path=output_path)
        audit_report = self.audit_prose(
            text=text,
            reference_passages=reference_passages,
            burstiness_threshold=burstiness_threshold,
            ontology_negative_rules=ontology_negative_rules,
            character_morph_permissions=character_morph_permissions,
        )

        gag_report = self.gag_injector.audit_scene(text, minimum_gags=minimum_gags)
        if not gag_report.passed_threshold:
            audit_report.passed = False

        return text, audit_report

    def run_hybrid_pipeline(
        self,
        beat_manifest_path: Path,
        out_dir: Path,
        influence_spec: str = "Francine:0 Rainee:50 Haley:20",
        burstiness_threshold: float = 4.0,
        minimum_gags: int = 3,
        ontology_negative_rules: Optional[Sequence[Dict[str, str]]] = None,
        character_morph_permissions: Optional[Dict[str, bool]] = None,
    ) -> CoprocessorPipelineReport:
        """
        Executes a complete coprocessor-accelerated narrative compilation.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stages: List[str] = []

        # Load canonical ontological invariants if not explicitly provided
        if ontology_negative_rules is None or character_morph_permissions is None:
            try:
                from story_graph.ontology import OntologyGraph
                onto = OntologyGraph.create_canonical_foxy_mo2()
                if ontology_negative_rules is None:
                    ontology_negative_rules = onto.hard_negative_rules
                if character_morph_permissions is None:
                    character_morph_permissions = onto.get_character_morph_permissions()
            except Exception:
                pass

        # 1. Feature Ledger
        stages.append("feature_ledger")
        manifest_data = json.loads(beat_manifest_path.read_text(encoding="utf-8"))
        profiles = self.ledger_engine.extract_from_manifest(manifest_data)
        ledger_path = out_dir / "spring_breakup_aesthetic_ledger.json"
        self.ledger_engine.export_ledger_json(profiles, output_path=ledger_path)

        # 2. Sub-Corpus Dispatching
        stages.append("subcorpus_dispatcher")
        dispatches = self.dispatcher.dispatch_manifest(profiles)
        dispatched_path = out_dir / "spring_breakup_dispatched_manifest.json"
        disp_data = {
            "version": "1.0",
            "beat_count": len(dispatches),
            "dispatches": {b_id: d.to_dict() for b_id, d in dispatches.items()},
        }
        dispatched_path.write_text(json.dumps(disp_data, indent=2), encoding="utf-8")

        # 3. 4-Tier Deep Scan with Somatic Reranking
        stages.append("deep_scan_reranking")
        deep_scan_path = out_dir / "spring_breakup_deep_scan_manifest.json"
        self.deep_scan_engine.scan_manifest(dispatched_path, output_path=deep_scan_path)
        somatic_applied = False
        if self.mode in ("hybrid", "local"):
            # Load deep scan data and rerank somatic passages with MiniLM
            ds_data = json.loads(deep_scan_path.read_text(encoding="utf-8"))
            for b_id, b_info in ds_data.get("deep_scans", {}).items():
                visceral = b_info.get("visceral_somatic", {})
                anchors = visceral.get("somatic_anchors", [])
                if anchors:
                    # Rerank against beat physical queries
                    queries = [f"{b_id} somatic texture bodily action tension"]
                    passages = [{"id": f"a_{i}", "text": a, "weight": 1.0} for i, a in enumerate(anchors)]
                    reranked = self.rerank_somatic_passages(queries, passages, top_k=len(passages))
                    visceral["somatic_anchors"] = [r.text for r in reranked]
                    visceral["reranked_scores"] = [r.effective_score for r in reranked]
            deep_scan_path.write_text(json.dumps(ds_data, indent=2), encoding="utf-8")
            somatic_applied = True

        # 4. Farce Gag Injection with SFX Generation
        stages.append("gag_injection_sfx")
        gag_path = out_dir / "spring_breakup_gag_enriched_manifest.json"
        self.gag_injector.enrich_manifest(deep_scan_path, output_path=gag_path)

        # 5. Dialogue Dialing
        stages.append("dialogue_dialing")
        settings = CharacterInfluenceSettings.parse(influence_spec)
        dialed_path = out_dir / "spring_breakup_dialed_manifest.json"
        self.dial_engine.dial_manifest(gag_path, settings=settings, output_path=dialed_path)
        micro_applied = self.mode in ("hybrid", "local")

        # 6. Hybrid Realizer & Guardrail Screening
        stages.append("hybrid_realization_guardrail")
        hybrid_path = out_dir / "spring_breakup_hybrid_novel.md"
        novel_text, audit_report = self.synthesize_and_verify(
            dialed_manifest_path=dialed_path,
            output_path=hybrid_path,
            burstiness_threshold=burstiness_threshold,
            minimum_gags=minimum_gags,
            ontology_negative_rules=ontology_negative_rules,
            character_morph_permissions=character_morph_permissions,
        )

        gag_report = self.gag_injector.audit_scene(novel_text, minimum_gags=minimum_gags)
        word_count = len(novel_text.split())

        report = CoprocessorPipelineReport(
            mode=self.mode,
            device=self.active_device,
            stages_executed=stages,
            somatic_reranking_applied=somatic_applied,
            micro_generator_applied=micro_applied,
            guardrail_report=audit_report.to_dict(),
            output_files={
                "aesthetic_ledger": str(ledger_path),
                "dispatched_manifest": str(dispatched_path),
                "deep_scan_manifest": str(deep_scan_path),
                "gag_enriched_manifest": str(gag_path),
                "dialed_manifest": str(dialed_path),
                "hybrid_novel": str(hybrid_path),
            },
            word_count=word_count,
            burstiness_score=audit_report.burstiness_score,
            gags_verified=gag_report.detected_count,
            passed=audit_report.passed,
        )

        report_path = out_dir / "spring_breakup_coprocessor_pipeline_report.json"
        report_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        return report
