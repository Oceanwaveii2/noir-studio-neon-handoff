"""Milestone 0 regression tests for expand mode, full-text workflow detection, and normalized cliche scoring."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from prose_engine.gemini_driver import _detect_intake_workflow
from prose_engine.rhythm_guidance import compile_guidance
from prose_engine.voice.slop_critic import SlopCritic


class Milestone0Tests(unittest.TestCase):
    def test_expand_mode_suppresses_anti_expansion_control_cues(self):
        packet = SimpleNamespace(
            beat_rhythm={'status': 'configured', 'profile': {'pace': 'slow', 'comedy': 'setup'}},
            start=0,
            end=50,
            protected=(),
            target='Haley rolled her eyes at the kitchen table.',
            context=None,
            character_store_token='tok',
            world_law_revision=1,
            episode='spring-break',
            beat=1,
            branch='main',
            viewpoint=None,
            revision=1,
            target_sha256='abc',
            hidden_phrases=(),
            protection_revision=1,
            public=lambda: {},
        )
        plan = compile_guidance(packet, scene_function='comedy', craft_mode='expand')
        joined = ' '.join(c['instruction'] for c in plan['cues']).lower()
        self.assertNotIn('do not add events to make the passage longer', joined)
        self.assertNotIn('without adding a new gag', joined)
        self.assertIn('expand & enrich unlocked prose', joined)

    def test_detect_intake_workflow_scans_past_3000_chars(self):
        prefix = 'A' * 3500
        text = prefix + '\nRainee Sade and Rainee Becky arrive.'
        self.assertEqual(_detect_intake_workflow('', text, 'auto'), 'spring-alternate')

    def test_slop_critic_normalizes_cliche_penalty_by_length(self):
        critic = SlopCritic(require_burstiness=False, max_slop_score=100.0)
        critic.slop_model = None
        short_text = 'She crossed the room and opened the window.'
        long_text = ' '.join([short_text] * 120)
        with patch('prose_engine.voice.slop_critic.blacklisted_cliches', return_value=['mock_cliche']):
            short_res = critic.critique(short_text)
            long_res = critic.critique(long_text)
        self.assertLess(long_res.slop_score, short_res.slop_score)


if __name__ == '__main__':
    unittest.main()
