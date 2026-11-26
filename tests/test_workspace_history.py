"""Project history integration across independent SQLite stores."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore
from story_graph.beat_rhythm import BeatRhythmStore, defaults
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore


class ProjectHistoryTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='noir-project-history-')
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'timeline.sqlite'
        self.timeline = TimelineStore(self.path, project_id='journal', universe_id='test')
        self.timeline.create_episode('ep', 'Episode', 'main', 1)
        self.forms = FormGraphStore(self.timeline.form_graph_path)
        self.commands = EpisodeCommands(self.timeline, form_graph=self.forms)

    def history(self):
        return self.commands.execute('history.open', {})

    def step(self, direction):
        state = self.history()
        return self.commands.execute('history.' + direction,
                                     {'revision': state['revision'], 'tx_id': state['next_' + direction]['tx_id']})

    def add_character(self):
        return self.forms.change({'action': 'add_character', 'revision': 0,
                                  'character_id': 'mara', 'label': 'Mara'}, _history_path=self.path)

    def test_stale_request_and_atomic_form_failure(self):
        before = self.history()
        with patch('story_graph.transaction_audit.record_project_edit', side_effect=RuntimeError('journal failure')):
            with self.assertRaisesRegex(RuntimeError, 'journal failure'):
                self.add_character()
        self.assertEqual(self.history(), before)
        self.assertEqual(self.forms.read()['revision'], 0)
        self.add_character()
        form = self.forms.read()
        current = self.history()
        with self.assertRaisesRegex(ValueError, 'Project history changed'):
            self.commands.execute('history.undo',
                                  {'revision': before['revision'], 'tx_id': before['next_undo']['tx_id']})
        self.assertEqual(self.forms.read(), form)
        self.assertEqual(self.history(), current)
        self.assertEqual(self.step('undo')['changed']['domain'], 'forms')
        self.timeline = TimelineStore(self.path)
        self.forms = FormGraphStore(self.timeline.form_graph_path)
        self.commands = EpisodeCommands(self.timeline, form_graph=self.forms)
        self.assertEqual(self.step('redo')['changed']['domain'], 'forms')
        self.assertIn('mara', self.forms.junctions())

    def test_notebook_and_graph_replay_preserves_protection_and_uses_distinct_revisions(self):
        self.timeline.save('ep', 0, script='The room went quiet.', source_name='source.txt')
        notebook = NotebookStore(self.timeline)
        original = notebook.open('ep')
        graph = {'nodes': [{'id': 'room', 'type': 'scene'}], 'edges': []}
        rev = self.timeline.save('ep', 1, graph=graph, preserve_notebook=True)
        after_graph = notebook.open('ep')
        self.assertFalse(after_graph['stale'])
        notebook.save('ep', after_graph['revision'], rev, original['blocks'], 27, original['masks'])
        self.assertEqual(self.step('undo')['changed']['domain'], 'notebook')
        self.assertEqual(self.timeline.get_episode('ep')['graph'], graph)
        self.assertEqual(notebook.open('ep')['default_protection'], original['default_protection'])
        self.assertEqual(self.step('undo')['changed']['domain'], 'graph')
        self.assertFalse(notebook.open('ep')['stale'])
        self.assertEqual(self.timeline.get_episode('ep')['graph']['nodes'], [])
        self.assertEqual(self.step('redo')['changed']['domain'], 'graph')
        self.assertEqual(self.step('redo')['changed']['domain'], 'notebook')
        saved = notebook.open('ep')
        self.assertEqual(saved['default_protection'], 27)
        self.assertEqual(saved['blocks'], original['blocks'])
        self.assertEqual(saved['masks'], original['masks'])
        self.assertEqual(self.timeline.get_episode('ep')['graph'], graph)

    def test_per_beat_direction_replay(self):
        rhythm = BeatRhythmStore(self.timeline)
        profile = {**defaults(), 'pace': 'slow'}
        rhythm.save('ep', 1, 0, 0, profile)
        self.assertEqual(self.step('undo')['changed']['domain'], 'beat_rhythm')
        self.assertEqual(rhythm.open('ep', 1)['profile'], defaults())
        self.assertEqual(self.step('redo')['changed']['domain'], 'beat_rhythm')
        self.assertEqual(rhythm.open('ep', 1)['profile'], profile)
