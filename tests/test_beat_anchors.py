"""Offline, explicit author assertions; never automatic timing inference."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from story_graph.episode_timeline import TimelineStore
from story_graph.beat_map import map_episode
from story_graph.beat_anchors import BeatAnchorStore
from prose_engine.scoped_pipeline import build_packet
from prose_engine.scoped_service import execute_scoped
from prose_engine.notebook import NotebookStore, DraftStore


class AnchorFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=TimelineStore(Path(self.tmp.name)/'timeline.sqlite')
        self.store.create_episode('sample','Sample','main',1)
        self.text='INT. ROOM\r\n\r\nLena turned the brass key.\r\n\r\nThe violet crown glowed at dawn.'
        self.store.save('sample',0,script=self.text,source_name='synthetic fixture')
        self.store.add_event('early','sample',1,'The brass door is open.',status='approved',permitted=True,reviewer='author',source_id='fixture')
        self.store.add_event('late','sample',5,'The violet crown glowed at dawn.',status='approved',permitted=True,reviewer='author',source_id='fixture')
        self.anchors=BeatAnchorStore(self.store);self.nb=NotebookStore(self.store)
        n=self.nb.open('sample');self.nb.save('sample',n['revision'],1,n['blocks'],25,n['masks'])
        self.drafts=DraftStore(self.nb)

    def mapping(self,viewpoint=None):
        return map_episode(self.store,'sample',self.store.get_episode('sample')['head'],viewpoint=viewpoint)

    def request(self,index=0,viewpoint=None):
        m=self.mapping(viewpoint)
        return {'episode':'sample','revision':m['revision'],'project':m['project_id'],'universe':m['universe_id'],
                'branch':m['branch'],'source_sha256':m['source_sha256'],'passage':m['beats'][index]['id'],
                'expected_token':m['anchor_token'],'viewpoint':viewpoint,'reviewer':'fixture author','event':'early'}

    def bind(self,index=0,event='early',viewpoint=None):
        return self.anchors.change('bind',{**self.request(index,viewpoint),'event':event})


class BeatAnchorTests(AnchorFixture):
    def test_map_and_open_are_read_only_and_do_not_create_anchor_tables(self):
        before=self.store.get_episode('sample');self.anchors.open('sample',1)
        with self.store._connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='passage_anchor_revisions'").fetchone())
        self.assertEqual(before,self.store.get_episode('sample'))

    def test_bind_is_explicit_revisioned_and_never_edits_canon_or_prose(self):
        before=self.store.get_episode('sample');events=self.store.episode_events('sample');n=self.nb.existing('sample')
        self.bind();p=self.mapping()['beats'][0]
        self.assertEqual((p['scope_beat'],p['timing']),(1,'reviewed'))
        self.assertEqual(before,self.store.get_episode('sample'));self.assertEqual(events,self.store.episode_events('sample'))
        self.assertEqual(n,self.nb.existing('sample'));self.assertEqual(self.drafts.list('sample','main'),[])
        self.assertTrue(p['anchor']['id'].startswith('anchor-'))

    def test_invalid_evidence_does_not_create_storage(self):
        self.store.add_event('draft','sample',2,'A draft only.')
        self.store.add_event('denied','sample',2,'Not permitted.',status='approved',reviewer='author',source_id='fixture')
        for event in ('missing','draft','denied'):
            with self.assertRaisesRegex(ValueError,'approved'):
                self.bind(event=event)
        with self.store._connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='passage_anchor_revisions'").fetchone())

    def test_wrong_scope_and_stale_token_fail_before_writes(self):
        request=self.request();self.bind()
        for changes in ({},{'project':'another'},{'universe':'another'},{'branch':'sibling'},{'source_sha256':'wrong'}):
            with self.assertRaises(ValueError):self.anchors.change('bind',{**request,**changes})
        with self.store._connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM passage_anchor_revisions').fetchone()[0],1)

    def test_private_evidence_and_sibling_branch_are_not_timing(self):
        self.store.add_event('private','sample',3,'A private character recollection.',status='approved',permitted=True,viewpoint='lena',reviewer='author',source_id='fixture')
        self.assertNotIn('private',[e['id'] for e in self.anchors.open('sample',1)['events']])
        with self.assertRaises(ValueError):self.bind(event='private')
        self.bind(event='private',viewpoint='lena')
        self.assertEqual(self.mapping()['beats'][0]['scope_beat'],0)
        self.assertEqual(self.mapping('lena')['beats'][0]['scope_beat'],3)
        self.assertEqual(self.mapping('other')['beats'][0]['scope_beat'],0)
        self.store.fork('sibling','main','sample',1);self.store.create_episode('other','Other','sibling',0)
        self.store.save('other',0,script='Sibling text.',source_name='fixture')
        self.store.add_event('sibling-event','other',1,'Sibling only.',status='approved',permitted=True,reviewer='author',source_id='fixture')
        with self.assertRaises(ValueError):self.bind(event='sibling-event')

    def test_unique_unchanged_text_keeps_identity_but_requires_explicit_rebind(self):
        self.bind();old=self.mapping()['beats'][0]['anchor']['id']
        self.nb.edit_text('sample',self.nb.existing('sample')['revision'],1,0,0,'A new arrival.\r\n\r\n')
        p=self.mapping()['beats'][1]
        self.assertEqual(p['anchor']['id'],old);self.assertEqual((p['timing'],p['scope_beat']),('stale',0))
        self.bind(index=1);p=self.mapping()['beats'][1]
        self.assertEqual(p['anchor']['id'],old);self.assertEqual(p['scope_beat'],1)
        self.assertEqual(p['anchor']['revision'],2)

    def test_graph_or_event_evidence_drift_is_stale(self):
        self.bind()
        with self.store._connect() as c:c.execute("UPDATE events SET content='Revised brass door evidence.' WHERE id='early'")
        self.assertEqual(self.mapping()['beats'][0]['timing'],'stale');self.bind()
        self.store.save('sample',1,graph={'nodes':[{'id':'one','type':'beat','data':{'beat':1}}],'edges':[]})
        self.assertEqual(self.mapping()['beats'][0]['timing'],'stale')

    def test_duplicate_text_never_inherits_cutoff(self):
        self.bind();self.nb.edit_text('sample',self.nb.existing('sample')['revision'],1,len(self.text),len(self.text),'\r\n\r\nLena turned the brass key.')
        passages=[p for p in self.mapping()['beats'] if p['text']=='Lena turned the brass key.']
        self.assertTrue(all(p['timing']=='ambiguous' and p['scope_beat']==0 for p in passages))
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.bind()

    def test_unbind_and_undo_append_history_without_changing_episode(self):
        self.bind();ident=self.mapping()['beats'][0]['anchor']['id']
        self.anchors.change('unbind',self.request());self.assertEqual(self.mapping()['beats'][0]['scope_beat'],0)
        self.anchors.change('undo',self.request());self.assertEqual(self.mapping()['beats'][0]['scope_beat'],1)
        self.assertEqual(self.mapping()['beats'][0]['anchor']['id'],ident)
        with self.store._connect() as c:
            self.assertEqual([r[0] for r in c.execute('SELECT revision FROM passage_anchor_revisions ORDER BY revision')],[1,2,3])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_undo_cannot_refresh_stale_evidence_implicitly(self):
        self.bind();self.anchors.change('unbind',self.request())
        with self.store._connect() as c:c.execute("UPDATE events SET reviewer='different reviewer' WHERE id='early'")
        with self.assertRaisesRegex(ValueError,'evidence is stale'):self.anchors.change('undo',self.request())

    def test_packet_binding_cannot_be_bypassed_with_a_later_cutoff_or_partial_span(self):
        self.bind();p=self.mapping()['beats'][0]
        packet=build_packet(self.store,'sample',1,1,p['start'],p['end'],passage_anchor=p['anchor'])
        self.assertEqual(packet.passage_anchor,p['anchor']);self.assertEqual([e['id'] for e in packet.events],['early'])
        for start,end,beat in ((p['start'],p['end'],5),(p['start']+1,p['end'],1),(p['start'],len(self.text),5)):
            with self.assertRaises(ValueError):build_packet(self.store,'sample',beat,1,start,end)

    def test_stale_receipt_rejected_before_provider_and_old_receipt_stays_saved(self):
        self.bind();p=self.mapping()['beats'][0]
        request={'episode':'sample','revision':1,'beat':1,'start':p['start'],'end':p['end'],'passage_anchor':p['anchor'],
                 'provider':'codex-session','references':'none'}
        self.bind(event='late')
        with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('No dispatch')):
            with self.assertRaises(ValueError):execute_scoped(self.store,'generate',request)
        self.assertEqual(self.drafts.list('sample','main'),[])

    def test_http_shared_anchor_path_no_provider_and_origin_is_required(self):
        from tools.studio_ui import StudioRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=Path(self.store.path);server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        def post(req,origin=base):
            request=urllib.request.Request(base+'/api/beat-anchors',data=json.dumps(req).encode(),headers={'Content-Type':'application/json','Origin':origin})
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('No provider')):
                opened=post({**self.request(),'action':'open'});self.assertEqual(opened['mapping'],self.mapping())
                bound=post({**self.request(),'action':'bind'});self.assertEqual(bound['mapping']['beats'][0]['scope_beat'],1)
                post({**self.request(),'action':'unbind'});post({**self.request(),'action':'undo'})
            with self.assertRaises(urllib.error.HTTPError) as error:post({**self.request(),'action':'bind'},'http://not-this-studio')
            self.assertEqual(error.exception.code,403)
            self.assertEqual(self.drafts.list('sample','main'),[])
        finally:server.shutdown();server.server_close();thread.join()


class SceneAnchorInferenceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from story_graph.episode_timeline import TimelineStore
        from story_graph.beat_anchors import BeatAnchorStore

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TimelineStore(Path(self.tmp.name) / 'timeline.sqlite', project_id='proj-step3', universe_id='univ-step3')
        self.store.create_episode('ep', 'Episode', 'main', 1)
        script = (
            'INT. DINER - NIGHT\r\n\r\n'
            'First passage in diner.\r\n\r\n'
            'Second passage in diner.\r\n\r\n'
            'Third passage in diner.\r\n\r\n'
            'INT. ALLEY - NIGHT\r\n\r\n'
            'Alley passage one.'
        )
        self.revision = self.store.save('ep', 0, {'nodes': [], 'edges': []}, script, 'ep.txt')
        self.store.add_event('ev1', 'ep', 1, 'First approved event.', status='approved', permitted=True, viewpoint=None, source_id='src-1', reviewer='author')
        self.store.add_event('ev2', 'ep', 3, 'Third approved event.', status='approved', permitted=True, viewpoint=None, source_id='src-2', reviewer='author')
        self.anchors = BeatAnchorStore(self.store)

    def _scope_req(self, mapping, **extra):
        return {
            'project': mapping['project_id'],
            'universe': mapping['universe_id'],
            'branch': mapping['branch'],
            'episode': mapping['episode'],
            'revision': mapping['revision'],
            'source_sha256': mapping['source_sha256'],
            'expected_token': mapping['anchor_token'],
            'reviewer': 'author',
            **extra,
        }

    def test_scene_inferred_beat_and_summary_counts_preserve_unverified_scope(self):
        opened = self.anchors.open('ep', self.revision)
        m0 = opened['mapping']
        self.assertEqual([s['reviewed_count'] for s in m0['scenes']], [0, 0])
        self.assertEqual([s['unverified_count'] for s in m0['scenes']], [3, 1])
        self.assertEqual([s['inferred_beat_range'] for s in m0['scenes']], [[0, 0], [0, 0]])
        for beat in m0['beats']:
            self.assertEqual(beat['scope_beat'], 0)
            self.assertEqual(beat['timing'], 'unverified')
            self.assertEqual(beat['scene_inferred_beat'], 0)
            self.assertIsNone(beat['scene_inferred_event'])

        bound1 = self.anchors.change('bind', self._scope_req(m0, passage=m0['beats'][0]['id'], event='ev1'))
        m1 = bound1['mapping']
        self.assertEqual(m1['beats'][0]['scope_beat'], 1)
        self.assertEqual(m1['beats'][0]['timing'], 'reviewed')
        self.assertEqual(m1['beats'][0]['scene_inferred_beat'], 1)
        self.assertEqual(m1['beats'][0]['scene_inferred_event'], 'ev1')
        # Subsequent unverified passages in the same scene stay unverified/0 while carrying lower-bound hints
        for idx in (1, 2):
            self.assertEqual(m1['beats'][idx]['scope_beat'], 0)
            self.assertEqual(m1['beats'][idx]['timing'], 'unverified')
            self.assertEqual(m1['beats'][idx]['scene_inferred_beat'], 1)
            self.assertEqual(m1['beats'][idx]['scene_inferred_event'], 'ev1')
        # Scene 2 must stay completely isolated
        self.assertEqual(m1['beats'][3]['scene_inferred_beat'], 0)
        self.assertIsNone(m1['beats'][3]['scene_inferred_event'])
        self.assertEqual(m1['scenes'][0]['reviewed_count'], 1)
        self.assertEqual(m1['scenes'][0]['unverified_count'], 2)
        self.assertEqual(m1['scenes'][0]['inferred_beat_range'], [1, 1])

        bound2 = self.anchors.change('bind', self._scope_req(m1, passage=m1['beats'][2]['id'], event='ev2'))
        m2 = bound2['mapping']
        self.assertEqual(m2['beats'][1]['scope_beat'], 0)
        self.assertEqual(m2['beats'][1]['scene_inferred_beat'], 1)
        self.assertEqual(m2['beats'][2]['scope_beat'], 3)
        self.assertEqual(m2['scenes'][0]['reviewed_count'], 2)
        self.assertEqual(m2['scenes'][0]['unverified_count'], 1)
        self.assertEqual(m2['scenes'][0]['inferred_beat_range'], [1, 3])

    def test_bind_scene_propagates_preceding_and_explicit_event_via_store_and_http(self):
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from pathlib import Path
        from unittest.mock import patch
        from tools.studio_ui import StudioRequestHandler

        opened = self.anchors.open('ep', self.revision)
        m0 = opened['mapping']
        bound = self.anchors.change('bind', self._scope_req(m0, passage=m0['beats'][0]['id'], event='ev1'))
        m1 = bound['mapping']

        propagated = self.anchors.change('bind_scene', self._scope_req(m1, scene='scene-1'))
        self.assertEqual(propagated['bound_count'], 2)
        mp = propagated['mapping']
        self.assertEqual([b['scope_beat'] for b in mp['beats'][:3]], [1, 1, 1])
        self.assertEqual([b['timing'] for b in mp['beats'][:3]], ['reviewed', 'reviewed', 'reviewed'])
        self.assertEqual(mp['beats'][3]['scope_beat'], 0)
        self.assertEqual(mp['beats'][3]['timing'], 'unverified')

        server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
        server.timeline_path = Path(self.store.path)
        server.timeline_only = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)

        def post(payload):
            req = urllib.request.Request(
                base + '/api/beat-anchors',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'Origin': base},
            )
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)

        try:
            with patch('prose_engine.providers.primary_session.create_scoped_provider', side_effect=AssertionError('No provider')):
                http_open = post({'action': 'open', 'episode': 'ep', 'revision': self.revision})
                hm = http_open['mapping']
                scene2_bind = post(self._scope_req(hm, action='bind_scene', scene='scene-2', event='ev2'))
                self.assertEqual(scene2_bind['bound_count'], 1)
                self.assertEqual(scene2_bind['mapping']['beats'][3]['scope_beat'], 3)
                self.assertEqual(scene2_bind['mapping']['beats'][3]['timing'], 'reviewed')
                with self.assertRaises(urllib.error.HTTPError) as err:
                    post(self._scope_req(scene2_bind['mapping'], action='bind_scene', scene='scene-2', event='ev2'))
                self.assertEqual(err.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_anchor_undo_and_redo_via_store_and_http(self):
        import json
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from pathlib import Path
        from unittest.mock import patch
        from tools.studio_ui import StudioRequestHandler

        opened = self.anchors.open('ep', self.revision)
        m0 = opened['mapping']
        p0 = m0['beats'][0]['id']
        bound = self.anchors.change('bind', self._scope_req(m0, passage=p0, event='ev1'))
        m1 = bound['mapping']
        self.assertEqual(m1['beats'][0]['scope_beat'], 1)

        with self.assertRaisesRegex(ValueError, 'Nothing to redo'):
            self.anchors.change('redo', self._scope_req(m1, passage=p0))

        undone = self.anchors.change('undo', self._scope_req(m1, passage=p0))
        self.assertEqual(undone['mapping']['beats'][0]['timing'], 'unbound')
        self.assertEqual(undone['mapping']['beats'][0]['scope_beat'], 0)

        redone = self.anchors.change('redo', self._scope_req(undone['mapping'], passage=p0))
        self.assertEqual(redone['mapping']['beats'][0]['timing'], 'reviewed')
        self.assertEqual(redone['mapping']['beats'][0]['scope_beat'], 1)

        server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
        server.timeline_path = Path(self.store.path)
        server.timeline_only = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)

        def post(payload):
            req = urllib.request.Request(
                base + '/api/beat-anchors',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'Origin': base},
            )
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)

        try:
            with patch('prose_engine.providers.primary_session.create_scoped_provider', side_effect=AssertionError('No provider')):
                h_open = post({'action': 'open', 'episode': 'ep', 'revision': self.revision})['mapping']
                h_undo = post(self._scope_req(h_open, action='undo', passage=p0))
                self.assertEqual(h_undo['mapping']['beats'][0]['timing'], 'unbound')
                h_redo = post(self._scope_req(h_undo['mapping'], action='redo', passage=p0))
                self.assertEqual(h_redo['mapping']['beats'][0]['scope_beat'], 1)
                self.assertEqual(self.store.get_episode('ep')['head'], self.revision)

                # Active beat anchor blocks unapproving referenced event; after undo, unapproving blocks redo
                with self.assertRaisesRegex(ValueError, 'Unbind passage beat anchors'):
                    self.store.unreview_event('ep', 'ev1', 'Author')
                h_undo2 = post(self._scope_req(h_redo['mapping'], action='undo', passage=p0))
                self.store.unreview_event('ep', 'ev1', 'Author')
                with self.assertRaises(urllib.error.HTTPError) as err:
                    post(self._scope_req(h_undo2['mapping'], action='redo', passage=p0))
                self.assertEqual(err.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__=='__main__':unittest.main()
