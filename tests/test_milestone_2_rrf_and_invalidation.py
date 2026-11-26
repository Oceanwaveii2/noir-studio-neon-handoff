"""Milestone 2 tests: Reciprocal Rank Fusion (RRF) & Source-Change Invalidation."""
from __future__ import annotations

import unittest

from prose_engine.scoped_references import rrf_fuse_hits
from story_graph.state_compiler import (
    evaluate_stale_decisions,
    upstream_dependency_fingerprint,
)


class Milestone2Tests(unittest.TestCase):
    def test_rrf_prefers_multi_backend_consensus_and_craft_tag_match(self):
        bundles = {
            'style': {
                'texts': ('Solo style hit.', 'Consensus comedy hit.'),
                'receipts': [
                    {'passage_id': 'p_solo_style', 'craft_tags': ['literary_satire_classic']},
                    {'passage_id': 'p_consensus', 'craft_tags': ['slapstick_timing', 'fart_gross_out']},
                ],
            },
            'luar': {
                'texts': ('Solo luar hit.', 'Consensus comedy hit.'),
                'receipts': [
                    {'passage_id': 'p_solo_luar', 'craft_tags': ['noir_mystery_pulp']},
                    {'passage_id': 'p_consensus', 'craft_tags': ['slapstick_timing', 'fart_gross_out']},
                ],
            },
            'topic': {
                'texts': ('Consensus comedy hit.',),
                'receipts': [
                    {'passage_id': 'p_consensus', 'craft_tags': ['slapstick_timing', 'fart_gross_out']},
                ],
            },
        }
        texts, receipts = rrf_fuse_hits(bundles, scene_function='comedy', k=60, limit=3)
        self.assertEqual(receipts[0]['passage_id'], 'p_consensus')
        self.assertEqual(receipts[0]['matched_backends'], ['style', 'luar', 'topic'])
        self.assertGreater(receipts[0]['rrf_score'], receipts[1]['rrf_score'])
        self.assertEqual(len(texts), 3)

    def test_source_change_invalidation_flags_stale_downstream_decisions(self):
        v1 = {'law_revision': 1, 'form_hash': 'h1', 'media_revision': 1, 'episode_pos': 10}
        v2 = {'law_revision': 2, 'form_hash': 'h1', 'media_revision': 3, 'episode_pos': 10}
        decisions = [
            {'id': 'beat_1', 'upstream_versions': dict(v1)},
            {'id': 'beat_2', 'upstream_versions': dict(v2)},
        ]
        checked = evaluate_stale_decisions(decisions, v2)
        self.assertTrue(checked[0]['needs_review'])
        self.assertEqual(checked[0]['stale_reasons'], ['world_laws_changed', 'media_override_changed'])
        self.assertFalse(checked[1]['needs_review'])
        self.assertEqual(checked[1]['stale_reasons'], [])
        self.assertNotEqual(
            upstream_dependency_fingerprint(**v1),
            upstream_dependency_fingerprint(**v2),
        )


if __name__ == '__main__':
    unittest.main()
