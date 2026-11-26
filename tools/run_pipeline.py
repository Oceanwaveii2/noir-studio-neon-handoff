"""
End-to-End Build Pipeline: Story Graph (System A) -> Prose Engine (System B).
Milestone M-PE7: End-to-End Integration & CI Verification Suite.

Orchestrates the entire decoupled narrative generation pipeline in strict sequence:
  Stage 1: System A - Story Graph (World State, Causal DAG, Epistemic Ledger, Beat Packet Compiler)
  Stage 2: System B - Aesthetic & Element Feature Ledger Extractor (M-PE1)
  Stage 3: System B - Segmented Sub-Corpus Dispatcher & Genre Isolation Gate (M-PE2)
  Stage 4: System B - 4-Tier Deep Scan across 105+ Books (M-PE3)
  Stage 5: System B - Mandatory Farce Joke & Somatic Gag Injector (M-PE4)
  Stage 6: System B - Configurable Dialogue Influence Dial (M-PE5)
  Stage 7: System B - Script-Novel Hybrid Realizer & Anti-AI-ism Linter (M-PE6)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# System A: Story Graph
from story_graph.compiler import BeatPacket, BeatPacketCompiler
from story_graph.dag import BeatSequencer
from story_graph.scenarios.spring_breakup import build_spring_breakup_world
from story_graph.scenarios.spring_breakup_dag import build_spring_breakup_dag
from story_graph.scenarios.spring_breakup_epistemic import build_spring_breakup_epistemic_ledger

# System B: Prose Engine
from prose_engine.prepass.feature_ledger import AestheticFeatureLedger
from prose_engine.dispatcher.router import SubCorpusDispatcher
from prose_engine.deep_scan import DeepScanEngine
from prose_engine.gag_injector import MandatoryGagInjector
from prose_engine.dialogue_dial import CharacterInfluenceSettings, DialogueDialEngine
from prose_engine.hybrid_realizer import ScriptNovelHybridRealizer
from prose_engine.linter import AntiAILinter
from prose_engine.coprocessor.harness import DualEngineHarness


class PipelineRunner:
    """
    Executes the end-to-end compilation pipeline from Story Graph to Script-Novel Hybrid.
    """

    def __init__(
        self,
        out_dir: Optional[Path] = None,
        verbose: bool = True,
        coprocessor_mode: str = "rule_based",
    ):
        self.out_dir = (out_dir or (ROOT / "work" / "americandad")).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.coprocessor_mode = coprocessor_mode
        self.harness = DualEngineHarness(mode=coprocessor_mode, lazy_load=True)

    def log(self, stage: str, message: str) -> None:
        if self.verbose:
            print(f"[{stage}] {message}")

    def run_stage1_story_graph(self) -> Tuple[Path, Path]:
        """
        Stage 1: Execute Story Graph causal DAG, world state fluents, and epistemic ledger,
        then compile beat packets into JSON manifest and lean Screenplay Markdown.
        """
        self.log("STAGE 1", "Initializing World State, Causal DAG, and Epistemic Ledger...")
        world = build_spring_breakup_world()
        dag = build_spring_breakup_dag()
        ledger = build_spring_breakup_epistemic_ledger()

        sequencer = BeatSequencer(dag, world)
        self.log("STAGE 1", "Sequencing beats in topological causal order...")
        while not sequencer.is_finished():
            eligible = sequencer.get_eligible_beats()
            if not eligible:
                raise RuntimeError("Story Graph sequencer stalled: circular or unmet preconditions.")
            sequencer.execute_beat(eligible[0].id)

        self.log("STAGE 1", f"Executed {len(sequencer.execution_log)} story beats.")

        compiler = BeatPacketCompiler(world, ledger)
        packets = compiler.compile_all(sequencer.execution_log)

        manifest_path = self.out_dir / "spring_breakup_beat_manifest.json"
        raw_script_path = self.out_dir / "spring_breakup_raw_script.md"

        compiler.export_manifest(packets, manifest_path)
        compiler.export_raw_script(packets, raw_script_path)

        self.log("STAGE 1", f"Exported beat manifest: {manifest_path}")
        self.log("STAGE 1", f"Exported raw script: {raw_script_path}")
        return manifest_path, raw_script_path

    def run_stage2_feature_ledger(self, beat_manifest_path: Path) -> Path:
        """
        Stage 2: Semantic pre-pass extracting aesthetic, somatic, and domestic features.
        """
        self.log("STAGE 2", "Extracting aesthetic feature ledger from beat packets...")
        manifest_data = json.loads(beat_manifest_path.read_text(encoding="utf-8"))
        ledger_engine = AestheticFeatureLedger()
        profiles = ledger_engine.extract_from_manifest(manifest_data)

        ledger_path = self.out_dir / "spring_breakup_aesthetic_ledger.json"
        ledger_engine.export_ledger_json(profiles, output_path=ledger_path)

        self.log("STAGE 2", f"Extracted {len(profiles)} profiles -> {ledger_path}")
        return ledger_path

    def run_stage3_dispatcher(self, beat_manifest_path: Path) -> Path:
        """
        Stage 3: Sub-Corpus Dispatcher partitioning the 105-book library and enforcing genre isolation.
        """
        self.log("STAGE 3", "Routing beats to authorized sub-corpora and enforcing genre gates...")
        manifest_data = json.loads(beat_manifest_path.read_text(encoding="utf-8"))
        ledger_engine = AestheticFeatureLedger()
        profiles = ledger_engine.extract_from_manifest(manifest_data)

        dispatcher = SubCorpusDispatcher()
        dispatches = dispatcher.dispatch_manifest(profiles)

        # Audit isolation
        for b_id, d in dispatches.items():
            ok, violations = dispatcher.audit_isolation(d)
            if not ok:
                raise RuntimeError(f"Genre isolation failure in beat '{b_id}': {violations}")

        dispatched_path = self.out_dir / "spring_breakup_dispatched_manifest.json"
        data = {
            "version": "1.0",
            "beat_count": len(dispatches),
            "dispatches": {b_id: d.to_dict() for b_id, d in dispatches.items()},
        }
        dispatched_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.log("STAGE 3", f"Dispatched {len(dispatches)} beats with 0% contamination -> {dispatched_path}")
        return dispatched_path

    def run_stage4_deep_scan(self, dispatched_manifest_path: Path) -> Path:
        """
        Stage 4: 4-Tier Deep Scan across 105+ books (Thematic, Visceral, Cadence, Idioms).
        """
        self.log("STAGE 4", "Executing 4-tier deep scan across 105+ books library...")
        deep_scan_engine = DeepScanEngine()
        deep_scan_path = self.out_dir / "spring_breakup_deep_scan_manifest.json"
        deep_scan_engine.scan_manifest(dispatched_manifest_path, output_path=deep_scan_path)

        if self.coprocessor_mode in ("hybrid", "local"):
            self.log("STAGE 4", f"Applying local somatic reranker coprocessor ({self.harness.active_device})...")
            ds_data = json.loads(deep_scan_path.read_text(encoding="utf-8"))
            for b_id, b_info in ds_data.get("deep_scans", {}).items():
                visceral = b_info.get("visceral_somatic", {})
                anchors = visceral.get("somatic_anchors", [])
                if anchors:
                    queries = [f"{b_id} somatic texture bodily action tension"]
                    passages = [{"id": f"a_{i}", "text": a, "weight": 1.0} for i, a in enumerate(anchors)]
                    reranked = self.harness.rerank_somatic_passages(queries, passages, top_k=len(passages))
                    visceral["somatic_anchors"] = [r.text for r in reranked]
                    visceral["reranked_scores"] = [r.effective_score for r in reranked]
            deep_scan_path.write_text(json.dumps(ds_data, indent=2), encoding="utf-8")

        self.log("STAGE 4", f"Deep scan complete across all tiers -> {deep_scan_path}")
        return deep_scan_path

    def run_stage5_gag_injector(self, deep_scan_manifest_path: Path) -> Path:
        """
        Stage 5: Mandatory joke and somatic gag injection enforcing canonical farce mechanics.
        """
        self.log("STAGE 5", "Injecting canonical farce mechanics into deep scan manifest...")
        injector = MandatoryGagInjector()
        gag_path = self.out_dir / "spring_breakup_gag_enriched_manifest.json"
        injector.enrich_manifest(deep_scan_manifest_path, output_path=gag_path)

        self.log("STAGE 5", f"Farce gags enriched -> {gag_path}")
        return gag_path

    def run_stage6_dialogue_dial(
        self,
        gag_manifest_path: Path,
        influence_spec: str = "Francine:0 Rainee:50 Haley:20",
    ) -> Path:
        """
        Stage 6: Configurable dialogue influence dial (0% to 75% or per-character mix).
        """
        self.log("STAGE 6", f"Dialing dialogue with influence settings: '{influence_spec}'...")
        settings = CharacterInfluenceSettings.parse(influence_spec)
        dial_engine = DialogueDialEngine()

        dialed_path = self.out_dir / "spring_breakup_dialed_manifest.json"
        dial_engine.dial_manifest(gag_manifest_path, settings=settings, output_path=dialed_path)

        self.log("STAGE 6", f"Dialogue dialed and validated -> {dialed_path}")
        return dialed_path

    def run_stage7_hybrid_realizer(
        self,
        dialed_manifest_path: Path,
        burstiness_threshold: float = 4.0,
        minimum_gags: int = 3,
    ) -> Path:
        """
        Stage 7: Script-Novel Hybrid Realization & Anti-AI-ism Linting.
        """
        self.log("STAGE 7", "Synthesizing Script-Novel Hybrid manuscript and executing Guardrail Coprocessor...")
        hybrid_path = self.out_dir / "spring_breakup_hybrid_novel.md"
        text, audit_report = self.harness.synthesize_and_verify(
            dialed_manifest_path=dialed_manifest_path,
            output_path=hybrid_path,
            burstiness_threshold=burstiness_threshold,
            minimum_gags=minimum_gags,
        )

        if not audit_report.passed:
            raise RuntimeError(
                f"Guardrail screening failed! AI tells: {len(audit_report.ai_tell_violations)}, "
                f"Burstiness: {audit_report.burstiness_score:.2f} (passed={audit_report.burstiness_passed})"
            )

        gag_report = self.harness.gag_injector.audit_scene(text, minimum_gags=minimum_gags)

        self.log(
            "STAGE 7",
            f"Generated draft written; author review pending ({len(text)} chars, {len(text.split())} words, "
            f"sigma={audit_report.burstiness_score:.2f}, {gag_report.detected_count}/6 gags) -> {hybrid_path}",
        )
        return hybrid_path

    def run_full_pipeline(
        self,
        influence_spec: str = "Francine:0 Rainee:50 Haley:20",
        burstiness_threshold: float = 4.0,
        minimum_gags: int = 3,
    ) -> Dict[str, Path]:
        """
        Executes all 7 stages in end-to-end succession.
        """
        self.log("PIPELINE", "=== STARTING FULL END-TO-END NARRATIVE ENGINE BUILD ===")
        m_beat, m_raw = self.run_stage1_story_graph()
        m_feat = self.run_stage2_feature_ledger(m_beat)
        m_disp = self.run_stage3_dispatcher(m_beat)
        m_deep = self.run_stage4_deep_scan(m_disp)
        m_gag = self.run_stage5_gag_injector(m_deep)
        m_dial = self.run_stage6_dialogue_dial(m_gag, influence_spec=influence_spec)
        m_hybrid = self.run_stage7_hybrid_realizer(
            m_dial,
            burstiness_threshold=burstiness_threshold,
            minimum_gags=minimum_gags,
        )

        self.log("PIPELINE", "=== PIPELINE COMPLETE: ALL 7 STAGES PASSED ===")
        return {
            "beat_manifest": m_beat,
            "raw_script": m_raw,
            "aesthetic_ledger": m_feat,
            "dispatched_manifest": m_disp,
            "deep_scan_manifest": m_deep,
            "gag_enriched_manifest": m_gag,
            "dialed_manifest": m_dial,
            "hybrid_novel": m_hybrid,
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="End-to-End Build Pipeline: Story Graph -> Prose Engine")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "work" / "americandad",
        help="Output directory for generated manifests and scripts",
    )
    parser.add_argument(
        "--character-influence",
        type=str,
        default="Francine:0 Rainee:50 Haley:20",
        help="Dialogue dial setting (single int or 'Francine:0 Rainee:50 Haley:20')",
    )
    parser.add_argument(
        "--burstiness-threshold",
        type=float,
        default=4.0,
        help="Minimum standard deviation for sentence lengths (default: 4.0)",
    )
    parser.add_argument(
        "--min-gags",
        type=int,
        default=3,
        help="Minimum distinct farce mechanics required in manuscript (default: 3)",
    )
    parser.add_argument(
        "--coprocessor",
        type=str,
        default="rule_based",
        choices=["hybrid", "local", "rule_based"],
        help="Coprocessor mode: hybrid (GPU coprocessors + macro realizer), local (GPU pure local), rule_based (CPU)",
    )
    args = parser.parse_args()

    runner = PipelineRunner(out_dir=args.out_dir, verbose=True, coprocessor_mode=args.coprocessor)
    try:
        runner.run_full_pipeline(
            influence_spec=args.character_influence,
            burstiness_threshold=args.burstiness_threshold,
            minimum_gags=args.min_gags,
        )
        return 0
    except Exception as e:
        print(f"\n[ERROR] Pipeline failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
