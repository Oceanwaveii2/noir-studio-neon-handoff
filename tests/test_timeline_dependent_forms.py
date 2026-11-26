"""Verify chronological form gating across episode positions and time_travel_override."""
from __future__ import annotations

import unittest

from story_graph.character_forms import AFM_JUNCTIONS


class TimelineDependentFormsTests(unittest.TestCase):
    def _project_all(self, episode_pos: int, time_travel_override: bool = False):
        out = {}
        for cid, junction in AFM_JUNCTIONS.items():
            all_ids = [f.id for f in junction.forms]
            proj = junction.project(
                approved=all_ids,
                planning=True,
                episode_pos=episode_pos,
                time_travel_override=time_travel_override,
            )
            out[cid] = {row['id']: row['status'] for row in proj['forms']}
        return out

    def test_pre_spring_break_locks_all_future_transformations(self):
        state = self._project_all(episode_pos=0)
        self.assertEqual(state['rainee']['peter_griffin_celestial_variant'], 'locked_future')
        self.assertEqual(state['francine']['nurse_pamela_franny_anderson'], 'locked_future')
        self.assertEqual(state['haley']['awakened_haley_fox'], 'locked_future')
        self.assertEqual(state['stella']['big_tiddy_steve_stella'], 'locked_future')

    def test_spring_break_unlocks_rainee_and_francine_but_locks_hot_scoomp_haley(self):
        state = self._project_all(episode_pos=10)
        self.assertEqual(state['rainee']['peter_griffin_celestial_variant'], 'available')
        self.assertEqual(state['francine']['nurse_pamela_franny_anderson'], 'available')
        self.assertEqual(state['haley']['awakened_haley_fox'], 'locked_future')
        self.assertEqual(state['stella']['big_tiddy_steve_stella'], 'locked_future')

    def test_hot_scoomp_unlocks_awakened_haley_fox(self):
        state = self._project_all(episode_pos=20)
        self.assertEqual(state['haley']['awakened_haley_fox'], 'available')
        self.assertEqual(state['stella']['big_tiddy_steve_stella'], 'locked_future')

    def test_time_travel_override_unlocks_future_forms_at_pos_zero(self):
        state = self._project_all(episode_pos=0, time_travel_override=True)
        self.assertEqual(state['rainee']['peter_griffin_celestial_variant'], 'time_travel_unlocked')
        self.assertEqual(state['haley']['awakened_haley_fox'], 'time_travel_unlocked')


if __name__ == '__main__':
    unittest.main()
