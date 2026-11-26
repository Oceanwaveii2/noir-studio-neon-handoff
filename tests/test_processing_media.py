"""Scoped media reuse and durable processing receipts through episode commands."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
import unittest

from PIL import Image

from prose_engine import media_graph, processing
from prose_engine.episode_commands import EpisodeCommands
from story_graph.episode_timeline import TimelineStore
from telemetry.processing_jobs import LEASE_SECONDS, read


def forbidden(*args):
    raise AssertionError('This workflow has no story-provider dispatch')


class ProcessingMediaTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = TimelineStore(Path(temp.name) / 'timeline.sqlite', project_id='p', universe_id='u')
        self.cmd = EpisodeCommands(self.store, provider_factory=forbidden, provider_resolver=forbidden)
        self.scope = {'project': 'p', 'universe': 'u', 'episode': 'one', 'branch': 'main'}
        self.store.create_episode('one', 'First', 'main', 1)

    def target(self, scope, text):
        episode = scope['episode']
        self.store.save(episode, 0, script=text, source_name='media-anchor-fixture')
        fields = scope | {'timeline_revision': self.store.get_episode(episode)['head']}
        reply = self.cmd.execute('scene.fragment.import', fields | {'selection': {'start': 0, 'end': len(text)}})
        fields['fragment'] = reply['fragment']['id']
        view = self.cmd.execute('scene.timeline.open', fields)
        beat = view['scenes'][0]['beats'][-1]
        return fields | {'beat': beat['id'], 'passage_sha256': beat['passage']['sha256']}, fields

    def upload(self, name, data):
        return media_graph.upload(self.store, self.scope | {'name': name}, BytesIO(data), len(data))

    def test_media_segment_reuses_same_original_on_exact_independent_beats(self):
        target, track = self.target(self.scope, 'INT. KITCHEN - DAY\n\nThe kettle shakes.\n')
        self.store.create_episode('two', 'Second', 'main', 2)
        sibling, sibling_track = self.target(self.scope | {'episode': 'two'}, 'EXT. CAR - DAY\n\nThe door opens.\n')
        original = 'Take one 🎬.\r\nKeep the pause.\n'.encode('utf-8')
        uploaded = self.upload('timing.fountain', original)
        asset = uploaded['asset']
        self.assertEqual(asset['sha256'], sha256(original).hexdigest())
        self.assertEqual(media_graph.original(self.store, self.scope | {'id': asset['id']})[1].read_bytes(), original)
        first = self.cmd.execute('scene.media.attach', target | {
            'asset': asset['id'], 'selector': {'start': 9, 'end': 10}, 'purpose': 'reference',
        })
        self.assertFalse(self.cmd.execute('scene.media.open', sibling)['pins'])
        with self.assertRaisesRegex(ValueError, 'exact passage'):
            self.cmd.execute('scene.media.attach', sibling | {'segment': first['segment']['id'],
                                   'passage_sha256': target['passage_sha256']})
        second = self.cmd.execute('scene.media.attach', sibling | {'segment': first['segment']['id']})
        self.assertEqual(first['segment'], second['segment'])
        self.assertNotEqual(first['pin']['id'], second['pin']['id'])
        for args, item in ((track, first), (sibling_track, second)):
            view = self.cmd.execute('scene.timeline.open', args)
            projections = [link for scene in view['scenes'] for beat in scene['beats'] for link in beat.get('media', [])]
            self.assertEqual([link['pin'] for link in projections], [item['pin']['id']])
            self.assertEqual(view['provider_calls'], 0)

    def test_image_analysis_is_saved_and_failed_upload_keeps_receipt(self):
        image = BytesIO()
        Image.new('RGB', (24, 16)).save(image, 'PNG')
        first = self.upload('region.png', image.getvalue())
        second = self.upload('same-bytes.png', image.getvalue())
        self.assertEqual(first['asset'], second['asset'])
        self.assertEqual(first['asset']['analysis']['width'], 24)
        with self.assertRaisesRegex(ValueError, 'complete PCM WAV'):
            self.upload('incomplete.wav', b'RIFFx')
        reopened = EpisodeCommands(TimelineStore(self.store.path), provider_factory=forbidden)
        response = reopened.execute('processing.open', self.scope)
        failed, reused, imported = response['jobs']
        self.assertEqual([failed['status'], reused['status'], imported['status']], ['FAILED', 'COMPLETED', 'COMPLETED'])
        self.assertEqual([part['status'] for part in failed['steps']], ['COMPLETED', 'FAILED', 'SKIPPED'])
        self.assertEqual([part['status'] for part in reused['steps']], ['COMPLETED', 'SKIPPED', 'SKIPPED'])
        self.assertEqual(imported['outputs']['asset'], first['asset']['id'])
        self.assertEqual(response['provider_calls'], 0)

    def test_interrupted_receipt_keeps_completed_parts_without_a_running_spinner(self):
        with processing.begin(self.store, self.scope, 'media-import', 'Abandoned analysis', {}) as job:
            with job.step('receive') as out:
                out['bytes'] = 123
            with job.step('analysis'):
                active, = self.cmd.execute('processing.open', self.scope | {'job': job.data['id']})['jobs']
                self.assertEqual(active['steps'][1]['status'], 'RUNNING')
                with self.store._connect() as c:
                    stalled, = read(c, job.data['scope'], job.data['id'], now=time() + LEASE_SECONDS + 1)
                self.assertEqual(stalled['status'], 'UNKNOWN')
                self.assertEqual([part['status'] for part in stalled['steps']], ['COMPLETED', 'UNKNOWN', 'SKIPPED'])
                self.assertEqual(stalled['steps'][0]['outputs'], {'bytes': 123})

    def test_scene_and_form_links_do_not_pin_other_beats_or_other_forms(self):
        _, track = self.target(self.scope, 'INT. KITCHEN - DAY\n\nThe kettle shakes.\n')
        scene = self.cmd.execute('scene.timeline.open', track)['scenes'][0]
        uploaded = self.upload('reference.txt', b'Wait for the kettle.')
        args = {'asset': uploaded['asset']['id'], 'selector': {'start': 0, 'end': 8}, 'purpose': 'reference'}
        linked = self.cmd.execute('scene.media.attach', track | args | {
            'scene': scene['id'], 'scene_sha256': scene['passages_sha256'],
        })
        rebuilt = self.cmd.execute('scene.timeline.open', track)['scenes'][0]
        self.assertEqual(rebuilt['media'][0]['pin'], linked['pin']['id'])
        self.assertTrue(all('media' not in beat for beat in rebuilt['beats']))
        rainee = self.scope | {'character': 'rainee', 'form': 'rainee'}
        form_pin = self.cmd.execute('scene.media.attach', rainee | {'segment': linked['segment']['id']})
        self.assertEqual(self.cmd.execute('scene.media.open', rainee)['pins'], [form_pin['pin']])
        sibling = self.scope | {'character': 'rainee', 'form': 'peter_griffin_celestial_variant'}
        self.assertFalse(self.cmd.execute('scene.media.open', sibling)['pins'])
