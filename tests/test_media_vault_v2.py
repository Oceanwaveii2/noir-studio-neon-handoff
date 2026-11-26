"""Exercise Vault originals and typed pins over the same loopback routes as Studio."""

import json
import tempfile
import threading
import unittest
from hashlib import sha256
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image

from prose_engine.media_graph import PIN_ROLE_MAP, normalize_pin_role
from story_graph.episode_timeline import TimelineStore
from tools.studio_ui import StudioRequestHandler


class MediaVaultV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'timeline.sqlite'
        store = TimelineStore(path, project_id='vault', universe_id='test')
        store.create_episode('one', 'Vault fixture', 'main', 1)
        store.save('one', 0, script='INT. WORKROOM - DAY\n\nThe clock strikes.\n', source_name='vault-fixture')
        self.scope = {'project': 'vault', 'universe': 'test', 'episode': 'one', 'branch': 'main'}
        self.revision = store.get_episode('one')['head']
        server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
        server.timeline_only = True
        server.timeline_path = path
        server.initial_episode = 'one'
        self.base = f'http://127.0.0.1:{server.server_port}'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def request(self, path, data=None, content_type='application/json'):
        headers = {'Origin': self.base, 'Content-Type': content_type} if data is not None else {}
        with urlopen(Request(self.base + path, data=data, headers=headers), timeout=10) as response:
            return response.status, response.read()

    def command(self, action, **fields):
        return json.loads(self.request('/api/episode-command',
                           json.dumps(self.scope | fields | {'action': action}).encode())[1])

    def upload(self, name, data):
        status, body = self.request('/api/beat-media/upload?' + urlencode(self.scope | {'name': name}),
                                    data, 'application/octet-stream')
        self.assertEqual(status, 201)
        asset = json.loads(body)['asset']
        self.assertEqual(asset['sha256'], sha256(data).hexdigest())
        status, original = self.request('/api/beat-media/original?' + urlencode(self.scope | {'id': asset['id']}))
        self.assertEqual((status, original), (200, data))
        return asset

    def test_typed_role_normalization(self):
        self.assertEqual(set(PIN_ROLE_MAP), {
            'catalyst_trigger', 'relationship_chemistry', 'rhythm_timing', 'personality_mind', 'wardrobe_reference',
        })
        for role, purpose in PIN_ROLE_MAP.items():
            self.assertEqual(normalize_pin_role(role), (purpose, role))
            self.assertEqual(normalize_pin_role(purpose), (purpose, role))
        self.assertEqual(normalize_pin_role('rhythm_timing', 'document'), ('reference', 'rhythm_timing'))

    def test_live_upload_round_trip_and_distinct_roles_on_saved_passage(self):
        status, js = self.request('/assets/v2/media_vault.js')
        self.assertEqual(status, 200)
        self.assertIn(b'uploadMediaFiles', js)
        track = self.command('scene.timeline.open', timeline_revision=self.revision)
        beat = track['scenes'][0]['beats'][0]
        target = {'timeline_revision': self.revision, 'beat': beat['id'],
                  'passage_sha256': beat['passage']['sha256']}

        png = BytesIO()
        Image.new('RGB', (1, 1), 'green').save(png, 'PNG')
        image = self.upload('look.png', png.getvalue())
        script = self.upload('timing.txt', b'The clock strikes.\r\nWait.\n')
        appearance = self.command('scene.media.attach', **target, asset=image['id'],
                                  selector={'x': 0, 'y': 0, 'width': 10000, 'height': 10000},
                                  pin_role='wardrobe_reference')
        self.assertEqual(appearance['segment']['purpose'], 'appearance')
        args = target | {'asset': script['id'], 'selector': {'start': 0, 'end': 8}}
        rhythm = self.command('scene.media.attach', **args, pin_role='rhythm_timing')
        chemistry = self.command('scene.media.attach', **args, pin_role='relationship_chemistry')
        self.assertNotEqual(rhythm['segment']['id'], chemistry['segment']['id'])
        self.assertEqual(self.command('scene.media.attach', **args, pin_role='rhythm_timing')['pin'], rhythm['pin'])
        vault = self.command('scene.media.open', **target)
        self.assertEqual(vault['pin_role_map'], PIN_ROLE_MAP)
        self.assertEqual(len(vault['pins']), 3)
        self.assertEqual({item['pin_role'] for item in vault['segments']},
                         {'wardrobe_reference', 'rhythm_timing', 'relationship_chemistry'})
        self.assertEqual(vault['provider_calls'], 0)
        with self.assertRaises(HTTPError) as error:
            self.command('scene.media.attach', **(args | {'passage_sha256': '0' * 64}), pin_role='rhythm_timing')
        self.assertEqual(error.exception.code, 400)
        self.assertEqual(len(self.command('scene.media.open', **target)['pins']), 3)
