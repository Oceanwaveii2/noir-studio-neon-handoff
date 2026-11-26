"""Keep the shared evidence receipt scope independent of writer state."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from prose_engine import evidence_exchange as exchange
from prose_engine.notebook import NotebookStore
from prose_engine.service_daemon import open_exchange_ticket, write_ticket
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_fragments import encoded


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = TimelineStore(self.root/'timeline.sqlite')
        self.store.create_episode('episode', 'Test episode', 'main', 1)
        info = self.store.scope()
        self.branch = {'project': info['project_id'], 'universe': info['universe_id'], 'episode': 'episode',
                       'branch': 'main', 'scope_revision': info['scope_revision']}
        NotebookStore(self.store)
        self.keys = self.branch | {'result': 'fork-result'}
        self.target = {'form': 'second', 'mind': 'form-data:test-2'}
        self.clip = {'id': 'clip', 'sha256': 'a'*64, 'duration_us': 10_000}
        self.catalog = {'clip': self.clip, 'draft': 'existing', 'visual': None,
                        'evidence': [
                            self.sample('fusion', [1_000, 2_000], exchange.TIMING_PAIR[0], 'sampled_boundary'),
                            self.sample('hold', [3_000, 5_000], exchange.TIMING_PAIR[1], 'sampled_extent')]}
        self.record = {'world_sha256': 'b'*64, 'timeline_revision': 0, 'law_revision': 0,
                       'terminal_event': 'split', 'exact_dialogue': {'sha256': 'c'*64}}
        self.frame = {'state': {'root': 'lead', 'manifestations': [{'id': 'second', 'mind': self.target['mind']}]}}
        self.source_sha = 'd'*64
        patcher = patch.object(exchange.branches, 'resolve',
                               side_effect=lambda *args: (self.record, self.source_sha, self.frame, 'protected private text'))
        patcher.start()
        self.addCleanup(patcher.stop)
        draft = {'id': 'existing', 'project_id': self.branch['project'], 'universe_id': self.branch['universe'],
                 'provider': 'codex-session', 'text': 'private draft',
                 'writing_context': {'continuation': {'binding': {'result': self.keys['result'], 'sha256': self.source_sha},
                                                      'lineage': {'world_sha256': self.record['world_sha256']}}}}
        with self.store._connect() as c:
            c.execute('INSERT INTO episode_drafts(id,episode,branch,status,payload) VALUES(?,?,?,?,?)',
                      ('existing', 'episode', 'main', 'PROPOSED', encoded(draft)))
        self.link = SimpleNamespace(kind='digital_mind', node_id=self.target['mind'])
        self.junctions = {'lead': SimpleNamespace(forms=[SimpleNamespace(id='second', link=self.link)])}

    @staticmethod
    def sample(ident, extent, obs, method):
        return {'id': ident, 'range_us': extent, 'observation': obs, 'method': method,
                'actor_identity': None, 'speaker_identity': None}

    def call(self, action, **extra):
        return exchange.execute(self.store, 'scene.exchange.'+action, self.keys | extra, junctions=lambda: self.junctions)

    def stage(self):
        exchange.install_catalog(self.store, self.branch, self.keys['result'], self.catalog)
        offer = self.call('offer', request_id='offer')
        return {'request_id': 'first', 'offer': offer['receipt']['id'], 'offer_sha256': offer['sha256'],
                'source_job': {'id': 'mining:job:'+'a'*16, 'sha256': 'a'*64}, 'target': self.target,
                'cue': 'hold_after_change', 'evidence': ['fusion', 'hold'], 'visual': None}

    def test_retry_opens_exact_ack_even_after_source_stales(self):
        payload = self.stage()
        reply = self.call('submit', **payload)
        self.assertEqual(reply['state'], 'SAVED')
        self.assertEqual(reply['receipt']['card']['observed_hold_us'], 2_000)
        self.assertNotIn('private', encoded(reply))
        with patch.object(exchange.branches, 'resolve', side_effect=ValueError('Stale branch replay')):
            self.assertEqual(self.call('submit', **payload), reply | {'state': 'REPLAYED'})
            self.assertEqual(self.call('receipt', receipt=reply['receipt']['id']), reply | {'state': 'OPENED'})
            with self.assertRaisesRegex(ValueError, 'Stale branch replay'):
                self.call('submit', **(payload | {'request_id': 'second'}))
        self.assertEqual(len(self.call('list')['receipts']), 2)
        with self.assertRaisesRegex(ValueError, 'different data'):
            self.call('submit', **(payload | {'evidence': ['fusion', 'other']}))

    def test_different_mind_and_unregistered_evidence_never_enter_receipt_log(self):
        payload = self.stage()
        with self.assertRaisesRegex(ValueError, 'registered transition'):
            self.call('submit', **(payload | {'evidence': ['fusion', 'caption']}))
        with self.assertRaisesRegex(ValueError, 'active in this saved result'):
            self.call('submit', **(payload | {'target': {'form': 'second', 'mind': 'other'}}))
        self.link.node_id = 'different-active-mind'
        with self.assertRaisesRegex(ValueError, 'link is missing or changed'):
            self.call('submit', **payload)
        self.assertEqual([row['kind'] for row in self.call('list')['receipts']], ['offer'])

    def test_clock_validity_and_catalog_immutability(self):
        catalog = deepcopy(self.catalog)
        catalog['evidence'][0]['range_us'] = [9_000, 11_000]
        with self.assertRaisesRegex(ValueError, 'fit its exact source'):
            exchange.install_catalog(self.store, self.branch, self.keys['result'], catalog)
        self.stage()
        catalog['evidence'][0]['range_us'] = [500, 950]
        with self.assertRaisesRegex(ValueError, 'different evidence catalog'):
            exchange.install_catalog(self.store, self.branch, self.keys['result'], catalog)
        with self.assertRaises(LookupError):
            self.call('list', branch='other')

    def test_ticket_reconnect_and_copy_binding(self):
        path = self.root/'private.json'
        base = {'protocol': 1, 'url': 'http://127.0.0.1:8790', 'workspace': 'a'*64}
        scoped = open_exchange_ticket(path, base, 'fork-result')
        write_ticket(path, scoped)
        self.assertEqual(open_exchange_ticket(path, base, 'fork-result'), scoped)
        with self.assertRaisesRegex(ValueError, 'different service'):
            open_exchange_ticket(path, base | {'workspace': 'b'*64}, 'fork-result')
        with self.assertRaisesRegex(ValueError, 'different service'):
            open_exchange_ticket(path, base, 'sibling')

    def test_appearance_preserves_legacy_receipts_and_exact_image_region(self):
        old = self.stage()
        old_reply = self.call('submit', **old)
        image = {'id':'portrait', 'sha256':'e'*64, 'width':800, 'height':1200}
        item = {'id':'coat', 'region':[2000,3000,7000,6000], 'field':'wardrobe', 'observation':'An orange raincoat.'}
        catalog = {'schema_version':1, 'image':image,'evidence':[item]}
        stamp = exchange.install_appearance(self.store, self.branch, self.keys['result'], catalog)
        self.assertEqual(self.call('submit', **old), old_reply | {'state':'REPLAYED'})
        terms = {'protocol':2,'purpose':'appearance'}
        offer = self.call('offer', request_id='portrait-offer', **terms)
        source_job = {'id':'mining:job:'+'e'*16, 'sha256':image['sha256']}
        payload = terms | {'request_id':'appearance', 'offer':offer['receipt']['id'],'offer_sha256':offer['sha256'],
            'source_job':source_job, 'target':self.target,'cue':'observe_appearance','evidence':['coat'],'visual':'portrait'}
        self.assertEqual(stamp,offer['receipt']['appearance_sha256'])
        with self.assertRaisesRegex(ValueError,'offered evidence protocol'):
            self.call('submit', **{k:v for k,v in payload.items() if k not in terms})
        with self.assertRaisesRegex(ValueError,'offered image'):
            self.call('submit', **(payload|{'source_job':old['source_job']}))
        with self.assertRaisesRegex(ValueError,'registered appearance'):
            self.call('submit', **(payload|{'visual':None}))
        result = self.call('submit', **payload)
        self.assertEqual(result['receipt']['card']['visual']['region'],item['region'])
        self.assertEqual(result['receipt']['card']['use'],'appearance_only')
        self.assertFalse(result['receipt']['writes_canon'])
        self.assertEqual(self.call('submit', **payload), result | {'state':'REPLAYED'})
