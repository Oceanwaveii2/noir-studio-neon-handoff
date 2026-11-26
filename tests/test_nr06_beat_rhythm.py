import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from story_graph.beat_rhythm import BeatRhythmStore, defaults
from story_graph.episode_timeline import TimelineStore
from story_graph.epistemic import viewpoint_diff
from story_graph.world_laws import WorldLawStore
from prose_engine.embedding_store import EmbeddingIndex
from prose_engine.notebook import DraftStore, NotebookStore
from prose_engine.scoped_pipeline import build_packet, prompt_for
from prose_engine.scoped_service import execute_scoped
from tools.studio_ui import StudioRequestHandler


class Provider:
    def __init__(self,on_call=None):self.prompts=[];self.on_call=on_call
    def generate_rewrite(self,request,prompt):
        self.prompts.append(prompt)
        if self.on_call:self.on_call()
        return 'A quiet room.'


class BeatRhythmTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'timeline.sqlite'
        self.store=TimelineStore(self.path);self.store.add_starter_cards()
        for episode in ('spring-break','hot-scoomp','tapped-out'):
            self.store.save(episode,0,script='A quiet room.',source_name='fixture')
        self.rhythm=BeatRhythmStore(self.store)
        self.req={'episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,'provider':'codex-session'}

    def test_act_structure_reopens_authored_targets_and_guards_stale_writes(self):
        rhythm = BeatRhythmStore(self.store)
        structure = rhythm.open_structure('spring-break', 1)
        passage = structure['selected']
        point = {'marker': 'A-plot reversal', 'tension': 4, 'duration_ms': 1500, 'pace': 'fast',
                 'direction': 'Hold on the clock.', 'sight': True, 'audio': False}
        saved = rhythm.save_structure('spring-break', 1, structure['revision'], 'episodic_comedy',
                                      beat_id=passage, point=point, viewpoint='roger')
        self.assertEqual(saved['epistemic']['channels'], {'sight': True, 'audio': False})
        self.assertEqual(rhythm.open_structure('spring-break', 1)['points'][0]['marker'], 'A-plot reversal')
        with self.assertRaisesRegex(ValueError, 'changed'):
            rhythm.save_structure('spring-break', 1, structure['revision'], 'custom')
        self.assertEqual(self.store.get_episode('spring-break')['script'], 'A quiet room.')

    def test_epistemic_diff_uses_witness_scope_and_closed_channel(self):
        rows = [
            {'id': 'public', 'beat': 0, 'content': 'The clock stopped.', 'viewpoint': None},
            {'id': 'sight', 'beat': 1, 'content': 'A light flashes.', 'viewpoint': 'roger', 'sensory_channel': 'sight'},
            {'id': 'audio', 'beat': 1, 'content': 'The latch clicks.', 'viewpoint': 'roger', 'sensory_channel': 'audio'},
            {'id': 'other', 'beat': 1, 'content': 'A key is hidden.', 'viewpoint': 'stella'},
        ]
        diff = viewpoint_diff(rows, 'roger', audio=False)
        self.assertEqual([row['id'] for row in diff['known']], ['public', 'sight'])
        self.assertEqual([row['id'] for row in diff['withheld']], ['audio', 'other'])

    def profile(self,**values):return {**defaults(),**values}
    def save(self,beat,profile,revision=0,episode='spring-break',head=1):
        return self.rhythm.save(episode,beat,head,revision,profile)

    def test_beat_undo_redo_survives_reopen(self):
        saved=self.save(1,self.profile(pace='slow'))
        undone=self.rhythm.undo('spring-break',1,1,saved['revision'])
        self.assertEqual(undone['profile'],defaults())
        again=BeatRhythmStore(TimelineStore(self.path)).redo('spring-break',1,1,undone['revision'])
        self.assertEqual(again['profile']['pace'],'slow')
        with self.assertRaises(ValueError):self.rhythm.redo('spring-break',1,1,undone['revision'])

    def test_unset_is_neutral_and_invalid_data_does_not_create_storage(self):
        self.assertEqual(self.rhythm.open('spring-break',1)['status'],'unset')
        with self.assertRaisesRegex(ValueError,'Invalid beat pace'):
            self.save(1,self.profile(pace='impossible'))
        with self.assertRaisesRegex(ValueError,'Tension'):
            self.save(1,self.profile(tension_start=9))
        with self.store._connect() as c:
            self.assertFalse(c.execute("SELECT 1 FROM sqlite_master WHERE name='beat_rhythm_heads'").fetchone())

    def test_three_scene_functions_change_guidance_not_world_or_masks(self):
        laws=WorldLawStore(self.store).open();episode=self.store.get_episode('spring-break')
        self.save(1,self.profile(intent='beauty',pace='slow',pause='held',cadence='flowing',author_override='Let the preparation breathe.'))
        self.save(2,self.profile(intent='comedy',pace='fast',tension_start=1,tension_end=4,comedy='escalation',cadence='punchy'))
        self.save(3,self.profile(intent='transformation',pace='measured',tension_start=4,tension_end=2,transition='linger'))
        providers=[]
        for beat in (1,2,3):
            p=Provider();providers.append(p)
            result=execute_scoped(self.store,'generate',{**self.req,'beat':beat,'protected_ranges':[[2,7]]},provider_factory=lambda:p)
            self.assertEqual(result['status'],'PROPOSED');self.assertEqual(result['book_status']['state'],'disabled')
            draft=DraftStore(NotebookStore(self.store)).open('spring-break','main',result['draft_id'])
            self.assertEqual(draft['rhythm_revision'],1);self.assertEqual(draft['rhythm_profile_id'],f'spring-break:{beat}')
            self.assertEqual(draft['protected_ranges'],[[2,7]])
            self.assertIn('Haley',p.prompts[0]);self.assertIn('quiet',p.prompts[0])
        self.assertIn('SCENE FUNCTION: beauty',providers[0].prompts[0]);self.assertIn('Let the preparation breathe',providers[0].prompts[0])
        self.assertIn('"comedy": "escalation"',providers[1].prompts[0])
        self.assertIn('SCENE FUNCTION: transformation',providers[2].prompts[0])
        override=Provider();execute_scoped(self.store,'generate',{**self.req,'scene_function':'tension'},provider_factory=lambda:override)
        self.assertIn('SCENE FUNCTION: tension',override.prompts[0]);self.assertIn('overrides the beat intent',override.prompts[0])
        self.assertEqual(WorldLawStore(self.store).open(),laws)
        self.assertEqual(self.store.get_episode('spring-break'),episode)

    def test_selected_beat_only_and_sibling_branch_are_isolated(self):
        self.save(3,self.profile(author_override='Later rhythm marker.',pace='fast'))
        early=build_packet(self.store,'spring-break',1,1,0,13)
        self.assertEqual(early.beat_rhythm['status'],'unset');self.assertNotIn('Later rhythm marker',prompt_for(early))
        self.store.fork('sibling','main','spring-break',1)
        self.store.create_episode('sibling-episode','Sibling','sibling',0)
        self.store.save('sibling-episode',0,script='A quiet room.',source_name='fixture')
        sibling=build_packet(self.store,'sibling-episode',3,1,0,13)
        self.assertEqual(sibling.beat_rhythm['status'],'unset');self.assertNotIn('Later rhythm marker',prompt_for(sibling))

    def test_future_information_or_law_conflict_in_override_is_rejected(self):
        self.store.add_event('future','tapped-out',1,'The hidden future secret appears.',status='approved',permitted=True,source_id='fixture',reviewer='author')
        self.save(1,self.profile(author_override='The hidden future secret appears.'))
        provider=Provider()
        with self.assertRaisesRegex(ValueError,'unavailable at this beat'):
            execute_scoped(self.store,'generate',self.req,provider_factory=lambda:provider)
        self.assertEqual(provider.prompts,[])
        self.save(1,self.profile(author_override='Haley has a father.'),1)
        with self.assertRaisesRegex(ValueError,'world law'):
            execute_scoped(self.store,'generate',self.req,provider_factory=lambda:provider)
        self.assertEqual(provider.prompts,[])

    def test_graph_link_revision_undo_and_invalid_binding(self):
        graph={'nodes':[{'id':'beat-1','type':'beat','data':{'beat':1}}],'edges':[]}
        head=self.store.save('spring-break',1,graph=graph)
        saved=self.save(1,self.profile(node_id='beat-1',pace='slow'),head=head)
        self.assertEqual(saved['revision'],1);self.assertEqual(self.store.get_episode('spring-break')['head'],head)
        with self.assertRaisesRegex(ValueError,'Stale'):
            self.save(1,self.profile(),0,head=head)
        with self.assertRaisesRegex(ValueError,'another beat'):
            self.save(2,self.profile(node_id='beat-1'),head=head)
        restored=self.rhythm.undo('spring-break',1,head,1)
        self.assertEqual(restored['revision'],2);self.assertEqual(restored['profile'],defaults())
        with self.assertRaisesRegex(ValueError,'Stale'):
            self.rhythm.undo('spring-break',1,head,1)

    def test_missing_linked_graph_node_fails_closed(self):
        graph={'nodes':[{'id':'beat-1','type':'beat','data':{'beat':1}}],'edges':[]}
        head=self.store.save('spring-break',1,graph=graph)
        self.save(1,self.profile(node_id='beat-1',pace='slow'),head=head)
        head=self.store.save('spring-break',head,graph={'nodes':[],'edges':[]})
        provider=Provider()
        with self.assertRaisesRegex(ValueError,'graph node is missing'):
            execute_scoped(self.store,'generate',{**self.req,'revision':head},provider_factory=lambda:provider)
        self.assertEqual(provider.prompts,[])

    def test_selected_beat_change_blocks_draft_but_another_beat_does_not(self):
        self.save(1,self.profile(pace='slow'))
        book=NotebookStore(self.store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
        result=execute_scoped(self.store,'generate',self.req,provider_factory=Provider)
        self.save(2,self.profile(pace='fast'))
        applied=execute_scoped(self.store,'apply-draft',{**self.req,'draft':result['draft_id'],'notebook_revision':1})
        self.assertEqual(applied['status'],'APPLIED')
        # A second isolated episode tests the same-beat stale failure.
        other='hot-scoomp';state=book.open(other);book.save(other,0,1,state['blocks'],25,[])
        self.save(1,self.profile(pace='slow'),episode=other)
        req={**self.req,'episode':other}
        draft=execute_scoped(self.store,'generate',req,provider_factory=Provider)
        self.save(1,self.profile(pace='fast'),1,episode=other)
        with self.assertRaisesRegex(ValueError,'beat direction'):
            execute_scoped(self.store,'apply-draft',{**req,'draft':draft['draft_id'],'notebook_revision':1})

    def test_inflight_rhythm_change_marks_draft_stale(self):
        self.save(1,self.profile(pace='slow'))
        def change():self.save(1,self.profile(pace='fast'),1)
        with self.assertRaisesRegex(ValueError,'changed during'):
            execute_scoped(self.store,'generate',self.req,provider_factory=lambda:Provider(change))
        self.assertEqual(DraftStore(NotebookStore(self.store)).list('spring-break','main')[-1]['status'],'STALE')

    def test_future_beat_change_does_not_change_current_generation(self):
        self.save(1,self.profile(pace='slow'))
        def change_future():self.save(5,self.profile(pace='fast',author_override='Later beat only.'))
        provider=Provider(change_future)
        result=execute_scoped(self.store,'generate',self.req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED')
        self.assertNotIn('Later beat only',provider.prompts[0])

    def test_eligible_references_supply_bounded_observations_and_receipts(self):
        self.save(1,self.profile(intent='comedy',comedy='setup'))
        books=self.root/'books';books.mkdir()
        (books/'reference_policy.json').write_text(json.dumps({'schema_version':1,'sources':{'allowed':{'enabled':True,'permissions':['rank_local','prompt','remote_transfer']}}}),encoding='utf-8')
        (books/'vector_index.joblib').write_bytes(b'index')
        excerpt=('A patient character crosses the quiet room while the rain taps at the window. '
                 'A second character pauses, studies the table, and waits for an answer that arrives much later.')
        model=SimpleNamespace(encode=lambda texts,**kw:np.ones((len(texts),1),dtype='float32'))
        index=EmbeddingIndex([excerpt],[{'book':'allowed'}],np.ones((1,1),dtype='float32'),_model=model)
        provider=Provider()
        with patch('prose_engine.embedding_store.load_index',return_value=index):
            result=execute_scoped(self.store,'generate',{**self.req,'references':'topic'},books_root=books,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED');self.assertEqual(result['reference_features']['sample_count'],1)
        self.assertIn('descriptive only',result['reference_features']['interpretation'])
        self.assertIn('REFERENCE CADENCE OBSERVATION',provider.prompts[0]);self.assertIn('SCENE FUNCTION: comedy',provider.prompts[0])
        draft=DraftStore(NotebookStore(self.store)).open('spring-break','main',result['draft_id'])
        self.assertEqual(draft['reference_features'],result['reference_features']);self.assertEqual(draft['reference_receipts'][0]['source_id'],'allowed')
        self.assertNotIn(excerpt,json.dumps(draft))

    def test_studio_beat_controls_save_and_undo_without_provider(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=self.path;server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        def post(body):
            request=urllib.request.Request(base+'/api/beat-rhythm',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            with patch('prose_engine.providers.primary_session.create_scoped_provider') as provider:
                self.assertEqual(post({'action':'open','episode':'spring-break','beat':1})['status'],'unset')
                saved=post({'action':'save','episode':'spring-break','beat':1,'timeline_revision':1,'revision':0,'profile':self.profile(pace='slow')})
                self.assertEqual(saved['revision'],1)
                undone=post({'action':'undo','episode':'spring-break','beat':1,'timeline_revision':1,'revision':1})
                self.assertEqual(undone['profile'],defaults());provider.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join()


class EdgeNeighborRhythmTests(unittest.TestCase):
    def test_edge_neighbors_on_open_packet_and_compile_guidance(self):
        import tempfile
        from pathlib import Path
        from story_graph.episode_timeline import TimelineStore
        from story_graph.beat_rhythm import BeatRhythmStore, defaults
        from prose_engine.notebook import NotebookStore
        from prose_engine.scoped_pipeline import build_packet
        from prose_engine.rhythm_guidance import compile_guidance

        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(Path(tmp) / 'timeline.sqlite')
            store.create_episode('ep', 'Episode', 'main', 1)
            graph = {
                'nodes': [
                    {'id': 'n0', 'type': 'beat', 'title': 'Beat Zero', 'data': {'beat': 0}},
                    {'id': 'n1', 'type': 'beat', 'title': 'Beat One', 'data': {'beat': 1}},
                    {'id': 'n2', 'type': 'beat', 'title': 'Beat Two', 'data': {'beat': 2}},
                ],
                'edges': [
                    {'from': 'n0', 'to': 'n1', 'fromPort': 'setup'},
                    {'from': 'n1', 'to': 'n2', 'fromPort': 'payoff'},
                ],
            }
            script = 'INT. ROOM\r\n\r\nLena checked the brass lock on the desk.\r\n\r\nWait for beat two.'
            rev = store.save('ep', 0, graph=graph, script=script, source_name='ep.txt')
            start = script.index('Lena')
            end = script.index('desk.') + len('desk.')

            rhythm = BeatRhythmStore(store)
            unset_open = rhythm.open('ep', 1)
            self.assertEqual(unset_open['status'], 'unset')
            self.assertEqual(unset_open['edge_neighbors'], {'incoming': [], 'outgoing': []})

            packet_unset = build_packet(store, 'ep', 1, rev, start, end)
            self.assertEqual(packet_unset.beat_rhythm['edge_neighbors'], {'incoming': [], 'outgoing': []})
            plan_unset = compile_guidance(packet_unset)
            self.assertFalse(any(c['source'] == 'author:edge-transition' for c in plan_unset['cues']))

            rhythm.save('ep', 1, rev, 0, {**defaults(), 'node_id': 'n1', 'pace': 'slow'})
            configured_open = rhythm.open('ep', 1)
            self.assertEqual(configured_open['status'], 'configured')
            expected_neighbors = {
                'incoming': [{'node_id': 'n0', 'beat': 0, 'title': 'Beat Zero', 'port': 'setup'}],
                'outgoing': [{'node_id': 'n2', 'beat': 2, 'title': 'Beat Two', 'port': 'payoff'}],
            }
            self.assertEqual(configured_open['edge_neighbors'], expected_neighbors)

            packet = build_packet(store, 'ep', 1, rev, start, end)
            self.assertEqual(packet.beat_rhythm['edge_neighbors'], expected_neighbors)
            plan = compile_guidance(packet)
            edge_cues = [c for c in plan['cues'] if c['source'] == 'author:edge-transition']
            self.assertEqual(len(edge_cues), 1)
            self.assertIn('beat 0', edge_cues[0]['instruction'])
            self.assertIn('beat 2', edge_cues[0]['instruction'])

            nb = NotebookStore(store)
            state = nb.open('ep')
            nb.save('ep', state['revision'], rev, state['blocks'], 100, state['masks'])
            locked_packet = build_packet(store, 'ep', 1, rev, start, end)
            locked_plan = compile_guidance(locked_packet)
            self.assertTrue(locked_plan['fully_locked'])
            self.assertEqual([c['source'] for c in locked_plan['cues']], ['exact-protection'])


if __name__=='__main__':unittest.main()
