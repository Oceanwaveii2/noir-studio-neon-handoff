"""Recorded beat grouping stays read-only and does not invent beat data."""
import json
import subprocess
import unittest
from tools.studio_ui import HTML_TEMPLATE


class BeatMapTests(unittest.TestCase):
    def test_groups_only_valid_recorded_beats_in_numeric_order(self):
        start = HTML_TEMPLATE.index('function groupedEpisodeBeats(nodes){')
        end = HTML_TEMPLATE.index('function renderBeatMap(){', start)
        function = HTML_TEMPLATE[start:end]
        nodes = [
            {'id': 'b', 'type': 'beat', 'title': 'Second', 'data': {'beat': 2}},
            {'id': 'a', 'type': 'beat', 'title': 'First', 'data': {'beat': 1}},
            {'id': 'c', 'type': 'beat', 'title': 'Another', 'data': {'beat': 1}},
            {'id': 'd', 'type': 'character', 'title': 'Not a beat', 'data': {'beat': 1}},
            {'id': 'e', 'type': 'beat', 'data': {'beat': '3'}},
            {'id': 'f', 'type': 'beat', 'data': {'beat': -1}},
            {'id': 'g', 'type': 'beat', 'data': {'beat': 1000001}},
            None,
        ]
        js = function + '\nprocess.stdout.write(JSON.stringify(groupedEpisodeBeats(' + json.dumps(nodes) + ')));'
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout), [
            {'beat': 1, 'titles': ['First', 'Another']},
            {'beat': 2, 'titles': ['Second']},
        ])

    def test_beat_direction_keeps_existing_node_association(self):
        start = HTML_TEMPLATE.index("document.getElementById('rhythmSave').onclick=")
        end = HTML_TEMPLATE.index("document.getElementById('rhythmUndo').onclick=", start)
        save = HTML_TEMPLATE[start:end]
        self.assertIn('profile.node_id=rhythmState.profile.node_id || null;', save)
        self.assertNotIn("profile.node_id=document.getElementById('rhythmNode')", save)
        self.assertIn('body.beat-workspace .noir-advanced{display:none!important}', HTML_TEMPLATE)


if __name__ == '__main__':
    unittest.main()
