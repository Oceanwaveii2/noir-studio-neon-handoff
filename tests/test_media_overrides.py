"""A media link changes only its exact eligible writer selection."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import wave

from prose_engine import media_graph, media_overrides
from prose_engine.episode_commands import EpisodeCommands
from prose_engine.scoped_groups import guard
from prose_engine.scoped_pipeline import build_packet, prompt_for
from story_graph.episode_timeline import TimelineStore


def forbidden(*args):
    raise AssertionError('An offline override action dispatched a writer')


class MediaOverrideTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = TimelineStore(Path(temp.name) / 'timeline.sqlite', project_id='p', universe_id='u')
        self.cmd = EpisodeCommands(self.store, provider_factory=forbidden, provider_resolver=forbidden)
        self.scope = {'project': 'p', 'universe': 'u', 'episode': 'one', 'branch': 'main'}
        self.text = 'INT. KITCHEN - DAY\n\nThe kettle rattles.\n\nThe lights flicker.\n'
        self.store.create_episode('one', 'One', 'main', 1)
        self.store.save('one', 0, script=self.text, source_name='media-override-fixture')
        self.rev = self.store.get_episode('one')['head']
        r = self.execute('scene.fragment.import', timeline_revision=self.rev, selection={'start': 0, 'end': len(self.text)})
        self.fragment = r['fragment']['id']
        track = self.execute('scene.timeline.open', timeline_revision=self.rev, fragment=self.fragment)
        self.rows = track['scenes'][0]['beats']
        raw = BytesIO()
        with wave.open(raw, 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(bytes(16000))
        self.asset = media_graph.upload(self.store, self.scope | {'name': 'take.wav'},
                                        BytesIO(raw.getvalue()), len(raw.getvalue()))['asset']

    def execute(self, command, **fields):
        return self.cmd.execute(command, self.scope | fields)

    def packet(self, row=None):
        span = (row or self.rows[0])['passage']
        return build_packet(self.store, 'one', 0, self.rev, span['start'], span['end'],
                            project_id='p', universe_id='u', branch='main')

    def link(self, purpose, observation=''):
        return self.execute('scene.media.attach', timeline_revision=self.rev, fragment=self.fragment,
                            beat=self.rows[0]['id'], passage_sha256=self.rows[0]['passage']['sha256'],
                            asset=self.asset['id'], selector={'start': 0, 'end': 1000}, purpose=purpose,
                            observation=observation)['pin']['id']

    def test_exact_direction_is_bounded_and_guarded_until_cleared(self):
        before = self.packet()
        other = prompt_for(self.packet(self.rows[-1]))
        observation = 'Let the listener register the interruption before the reply.'
        pin = self.link('timing', observation)
        args = {'pin': pin, 'direction': 'Borrow the pause before the reply'}
        measured = [{'start_ms': 230, 'end_ms': 470, 'duration_ms': 240}]
        with patch('prose_engine.media_signal.interior_pauses', return_value=measured):
            planned = self.execute('scene.media.override.preview', **args)
            self.assertEqual(planned['status'], 'READY', planned)
            args.update(plan=planned['override']['id'], previous=planned['previous'])
            saved = self.execute('scene.media.override.apply', **args)
            self.assertEqual(self.execute('scene.media.override.apply', **args), saved)
        guided = self.packet()
        self.assertEqual(list(guided.media_guidance), [saved['override']])
        self.assertEqual(saved['override']['evidence']['observation'], observation)
        self.assertIn('"reference_pause_ms":240', prompt_for(guided))
        self.assertIn(observation, prompt_for(guided))
        self.assertEqual(prompt_for(self.packet(self.rows[-1])), other)
        with self.store._connect() as c, self.assertRaisesRegex(ValueError, 'Media directions changed'):
            guard(self.store, c, (before,))
        opened = self.execute('scene.media.open', timeline_revision=self.rev, fragment=self.fragment,
                              beat=self.rows[0]['id'], passage_sha256=self.rows[0]['passage']['sha256'])
        self.assertEqual(opened['overrides'], [saved['override']])
        self.execute('scene.media.override.clear', override=saved['override']['id'])
        self.assertEqual(prompt_for(self.packet()), prompt_for(before))
        with self.assertRaisesRegex(ValueError, 'media directions are stale'):
            media_overrides.verify_draft(self.packet(), {'writing_context': guided.public()})
        self.assertEqual(planned['provider_calls'], 0)

    def test_two_pauses_require_a_more_exact_direction(self):
        pin = self.link('timing')
        quiet = [{'start_ms': 100, 'end_ms': 300, 'duration_ms': 200},
                 {'start_ms': 400, 'end_ms': 570, 'duration_ms': 170}]
        with patch('prose_engine.media_signal.interior_pauses', return_value=quiet):
            answer = self.execute('scene.media.override.preview', pin=pin, direction='Use the pause')
            self.assertEqual(answer['status'], 'UNRESOLVED')
            self.assertIn('Several quiet intervals', answer['reason'])
            result = self.execute('scene.media.override.preview', pin=pin, direction='Use the longest pause')
            self.assertEqual(result['override']['evidence']['quiet_interval'], quiet[0])

    def test_preview_only_reference_cannot_become_writer_guidance(self):
        from story_graph.scene_fragments import SceneFragmentStore

        SceneFragmentStore(self.store).register_evidence(self.scope, [{
            'id': 'audition', 'label': 'Ambiguous sound', 'asset': self.asset['id'], 'sha256': self.asset['sha256'],
            'selector': {'kind': 'clip', 'clock': 'file_pts', 'track': 'audio-0', 'unit': 'ms', 'start': 0, 'end': 1000},
            'use': 'preview'}])
        pin = self.link('timing')
        with patch('prose_engine.media_signal.interior_pauses') as pauses:
            result = self.execute('scene.media.override.preview', pin=pin, direction='Use the longest pause')
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIn('preview only', result['reason'])
        pauses.assert_not_called()

    def test_source_role_and_gender_require_observation(self):
        intent = media_overrides._intent('Use the woman’s sound for Rainee 2')
        segment = {'selector': {'start': 0, 'end': 1000}, 'observation': 'Someone laughs at an offscreen sound.'}
        with self.assertRaisesRegex(ValueError, 'emitter is unconfirmed'):
            media_overrides._evidence(None, segment, intent)
        segment['observation'] = 'Speaker: Casey. Presentation: woman. Observation: A clipped reply.'
        with self.assertRaisesRegex(ValueError, 'emitter is unconfirmed'):
            media_overrides._evidence(None, segment, intent)
        segment['observation'] = 'Emitter: Riley. Presentation: woman. Observation: A short audible accent.'
        self.assertEqual(media_overrides._evidence(None, segment, intent)['subject'], 'Riley')
