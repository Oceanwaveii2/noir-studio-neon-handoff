"""The ordinary Mind view uses exact scoped evidence without creating authoring state."""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prose_engine.episode_commands import EpisodeCommands
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_fragments import SceneFragmentError


class MindInspectionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'timeline.sqlite'
        self.timeline = TimelineStore(self.path)
        self.timeline.add_starter_cards()
        self.timeline.save('spring-break', 0, script='A shutter rattles.', source_name='fixture.txt')
        self.timeline.save('hot-scoomp', 0, script='The station closes.', source_name='fixture.txt')
        self.timeline.fork('alternate', 'main', 'spring-break', 0)
        self.timeline.create_episode('alternate-scene', 'Alternate scene', 'alternate', 1)
        self.timeline.save('alternate-scene', 0, script='The lamp flickers.', source_name='fixture.txt')
        for ident, episode, beat, viewpoint in [('public', 'spring-break', 0, None),
                ('haley-only', 'spring-break', 0, 'haley'), ('future', 'hot-scoomp', 0, None),
                ('later-beat', 'spring-break', 1, None), ('other-branch', 'alternate-scene', 0, None)]:
            self.timeline.add_event(ident, episode, beat, ident, status='approved', permitted=True,
                                    viewpoint=viewpoint, source_id='fixture', reviewer='fixture')
        identity = self.timeline.scope()
        self.args = {'project': identity['project_id'], 'universe': identity['universe_id'],
                     'episode': 'spring-break', 'branch': 'main', 'timeline_revision': 1}
        self.commands = EpisodeCommands(self.timeline, provider_factory=lambda: self.fail('Inspector called a writer'))

    def inspect(self, **changes):
        return self.commands.execute('mind.inspect', self.args | changes)

    def test_uninitialized_workspace_reads_only_scoped_facts(self):
        before = sha256(self.path.read_bytes()).hexdigest()
        narrator = self.inspect(character='haley')
        self.assertEqual(narrator['beat']['text'], 'A shutter rattles.')
        self.assertEqual(narrator['beat']['cutoff'], 0)
        self.assertEqual(narrator['selected']['status'], 'in_scope')
        self.assertEqual([e['id'] for e in narrator['visible_events']], ['public'])
        haley = self.inspect(character='haley', viewpoint='haley', turn=narrator['beat']['id'])
        self.assertEqual({e['id'] for e in haley['visible_events']}, {'public', 'haley-only'})
        rainee = self.inspect(character='rainee', viewpoint='rainee', turn=narrator['beat']['id'])
        self.assertEqual([e['id'] for e in rainee['visible_events']], ['public'])
        self.assertEqual(rainee['provider_calls'], 0)
        self.assertEqual(before, sha256(self.path.read_bytes()).hexdigest())

    def test_branches_beats_and_explicit_preview(self):
        preview = self.inspect(character='rainee', form='peter_griffin_celestial_variant')
        self.assertEqual(preview['selected']['status'], 'planning_only')
        self.assertEqual(preview['actors']['rainee']['form'], 'rainee')
        self.assertFalse(preview['selected']['knowledge'])
        self.assertIsNone(preview['selected']['card'])
        with self.assertRaisesRegex(SceneFragmentError, 'saved branch'):
            self.inspect(branch='alternate')
        with self.assertRaisesRegex(SceneFragmentError, 'current saved revision'):
            self.inspect(timeline_revision=2)
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            self.inspect(turn='foreign-passage')
