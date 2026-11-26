"""Run the established fixture baseline without resolving external model weights."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = (
    "tests.test_studio_ui",
    "tests.test_story_graph_dag",
    "tests.test_story_graph_world_state",
    "tests.test_story_graph_epistemic",
    "tests.test_story_graph_compiler",
    "tests.test_u4_context",
    "tests.test_foxy_mo2_dag",
    "tests.test_mo2_execution",
    "tests.test_u4_transaction_audit",
    "tests.test_studio_form_store",
    "tests.test_u5_blind",
    "tests.test_u5_decisions",
    "tests.test_u5_pilot",
    "tests.test_u6_retrieval_metrics",
    "tests.test_u6_retrieval_experiment",
    "tests.test_u7_local_trial",
    "tests.test_primary_sessions",
    "tests.test_reference_policy",
    "tests.test_library_indexes",
    "tests.test_library_integration",
    "tests.test_luar_conditioner",
    "tests.test_luar_calibration",
    "tests.test_nm06_index_audit",
    "tests.test_nm07_09",
    "tests.test_nr01_universe_scope",
    "tests.test_nr02_world_laws",
    "tests.test_nr03_shared_enforcement",
    "tests.test_nr04_scoped_books",
    "tests.test_nr05_character_profiles",
    "tests.test_nr06_beat_rhythm",
    "tests.test_rhythm_integration",
    "tests.test_beat_anchors",
    "tests.test_anchored_groups",
    "tests.test_source_migration",
    "tests.test_processed_reader",
    "tests.test_nr07_drafts",
    "tests.test_nr08_meaning",
    "tests.test_nr09_notebook_ui",
    "tests.test_nr09b_finish",
    "tests.test_nr09d_popup",
    "tests.test_nr09e_timeline",
    "tests.test_nr09e_racing",
    "tests.test_nr09g_workspace",
    "tests.test_nr09j_beat_map",
    "tests.test_nr11_beat_workflow",
    "tests.test_nr09m_protection",
    "tests.test_u8_release",
    "tests.test_u9_evidence",
    "tests.test_u10_timeline",
    "tests.test_u10_timeline_http",
    "tests.test_u10_scoped_pipeline",
    "tests.test_u10_scoped_http",
    "tests.test_u10_scoped_cli",
    "tests.test_u10_session_isolation",
    "tests.test_ontological_graph",
    "tests.test_smith_lore",
    "tests.test_future_heritage",
    "tests.test_book_expansion",
    "tests.test_m1_correction",
    "tests.test_voice_variations",
    "tests.test_naming_no_relapse",
    "tests.test_lossless_preparation",
    "tests.test_source_timing",
    "tests.test_episode_writing_runs",
    "tests.test_episode_intake",
    "tests.test_noir_service",
    "tests.test_fa04_shared_commands",
    "tests.test_editorial_routes",
    "tests.test_fx06_studio",
    "tests.test_scene_fragments",
    "tests.test_scene_override",
    "tests.test_replay_minds",
    "tests.test_mind_inspection",
    "tests.test_scene_clips",
    "tests.test_scene_mind_support",
    "tests.test_fx06_branches",
    "tests.test_fx06_exchange",
    "tests.test_scene_bridge",
    "tests.test_processing_media",
    "tests.test_media_overrides",
    "tests.test_open_gaps_closure",
    "tests.test_canon_corrector",
    "tests.test_mean_girls_spring_tapped_out",
    "tests.test_gemini_driver",
    "tests.test_unified_prose_architecture",
)
MIN_BASELINE_PASSES = 572
MIN_GUARD_PASSES = 5


def pass_count(result: unittest.TestResult) -> int:
    return (
        result.testsRun - len(result.skipped) - len(result.expectedFailures)
        - len(result.failures) - len(result.errors) - len(result.unexpectedSuccesses)
    )


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))

    runner = unittest.TextTestRunner(verbosity=1)
    baseline = runner.run(unittest.defaultTestLoader.loadTestsFromNames(BASELINE))
    guards = runner.run(unittest.defaultTestLoader.loadTestsFromName("tests.test_architecture_check"))
    passes = pass_count(baseline)
    guard_passes = pass_count(guards)
    print(f"Core baseline: {passes}/{baseline.testsRun} passed (floor {MIN_BASELINE_PASSES})")
    print(f"Architecture check fixtures: {guard_passes}/{guards.testsRun} passed (floor {MIN_GUARD_PASSES})")
    ok = baseline.wasSuccessful() and guards.wasSuccessful()
    return int(not (ok and passes >= MIN_BASELINE_PASSES and guard_passes >= MIN_GUARD_PASSES))


if __name__ == "__main__":
    raise SystemExit(main())
