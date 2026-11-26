"""Offline guidance/preview/persistence evidence, not literary acceptance."""
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from story_graph.episode_timeline import TimelineStore
from story_graph.beat_rhythm import BeatRhythmStore, defaults
from story_graph.beat_map import map_episode
from story_graph.world_laws import WorldLawStore
from prose_engine.scoped_pipeline import build_packet
from prose_engine.scoped_service import execute_scoped
from prose_engine.beat_workflow import generate_group, preview_group
from prose_engine.notebook import NotebookStore, DraftStore
from prose_engine.rhythm_guidance import compile_guidance, evidence


class Provider:
    def __init__(self, change=None, text=None):
        self.prompts=[];self.change=change;self.text=text

    def generate_rewrite(self, request, prompt):
        self.prompts.append(prompt)
        if self.change:self.change()
        return self.text if self.text is not None else request.original_text+' She waited.'


class RhythmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.store=TimelineStore(self.root/'timeline.sqlite')
        self.store.create_episode('sample','Sample','main',1)
        self.text='INT. ROOM\r\n\r\nLena turned the brass key.\r\n\r\nRain ticked against the awning.\r\n\r\nShe left her hand on the door.'
        self.store.save('sample',0,script=self.text,source_name='synthetic fixture')
        self.nb=NotebookStore(self.store);n=self.nb.open('sample')
        self.nb.save('sample',n['revision'],1,n['blocks'],25,n['masks'])
        self.drafts=DraftStore(self.nb);self.rhythm=BeatRhythmStore(self.store)
        self.mapping=map_episode(self.store,'sample',1);first=self.mapping['beats'][0]
        self.request={'episode':'sample','beat':0,'revision':1,'start':first['start'],'end':first['end'],
                      'provider':'codex-session','references':'none','scene_function':'scene'}
        self.group={'episode':'sample','revision':1,'project':self.mapping['project_id'],
                    'universe':self.mapping['universe_id'],'branch':'main','source_sha256':self.mapping['source_sha256'],
                    'beats':[b['id'] for b in self.mapping['beats']],'provider':'codex-session',
                    'references':'none','scene_function':'comedy','direction':'Keep the existing actions and let the pauses register.'}

    def save_profile(self, **values):
        current=self.rhythm.open('sample',0)
        return self.rhythm.save('sample',0,1,current['revision'],{**defaults(),**values})

    def preview(self, **values):
        return execute_scoped(self.store,'rhythm-preview',{**self.request,**values})

    def test_preview_neutral_no_books_no_provider_no_drafts_or_prose_changes(self):
        episode=self.store.get_episode('sample');state=self.nb.existing('sample')
        with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('No provider')):
            result=self.preview()
        self.assertEqual(result['status'],'PREVIEW');self.assertFalse(result['generation_started'])
        self.assertEqual(result['provider_calls'],0);self.assertEqual(result['drafts_created'],0)
        self.assertEqual(result['rhythm_guidance']['cues'][0]['source'],'neutral')
        self.assertIsNone(result['rhythm_guidance']['reference_observation'])
        self.assertEqual(self.drafts.list('sample','main'),[])
        self.assertEqual(self.store.get_episode('sample'),episode);self.assertEqual(self.nb.existing('sample'),state)

    def test_same_preview_plan_reaches_prompt_result_and_draft(self):
        self.save_profile(pace='measured',pause='held',cadence='varied',transition='linger',tension_start=1,tension_end=4)
        preview=self.preview();provider=Provider()
        result=execute_scoped(self.store,'generate',{**self.request,'rhythm_plan_id':preview['rhythm_guidance']['id']},provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED')
        self.assertEqual(result['rhythm_guidance'],preview['rhythm_guidance'])
        sent=json.loads(provider.prompts[0].split('RHYTHM CRAFT PLAN ',1)[1].split('\n',1)[1].split('\n\n',1)[0])
        self.assertEqual(sent,preview['rhythm_guidance'])
        draft=self.drafts.open('sample','main',result['draft_id'])
        self.assertEqual(draft['rhythm_guidance'],sent);self.assertEqual(draft['rhythm_evidence'],result['rhythm_evidence'])
        self.assertEqual(draft['rhythm_evidence']['before']['word_count'],5)
        self.assertIn('not a quality score',sent['interpretation'])

    def test_distinct_intents_and_explicit_controls_precede_reference_suggestions(self):
        plans=[self.preview(scene_function=function)['rhythm_guidance'] for function in ('beauty','comedy','transformation')]
        self.assertEqual(len({json.dumps(p['cues']) for p in plans}),3)
        self.save_profile(intent='comedy',pace='slow',pause='held',comedy='setup',cadence='flowing',transition='smooth',author_override='Do not rush the existing action.')
        result=self.preview(scene_function='transformation',direction='Retain the held pause.')
        self.assertEqual(result['rhythm_guidance']['scene_function'],'transformation')
        cues=result['rhythm_guidance']['cues']
        self.assertEqual([c['source'] for c in cues[:5]],['author:pace','author:pause','author:cadence','author:transition','author:comedy'])
        self.assertIn('explicit author direction',result['rhythm_guidance']['precedence'])
        self.assertIn('Retain the held pause.',result['scope']['beat_rhythm']['profile']['author_override'])

    def books(self, short=False):
        from prose_engine.embedding_store import EmbeddingIndex
        root=self.root/'books';root.mkdir()
        (root/'reference_policy.json').write_text(json.dumps({'schema_version':1,'sources':{'allowed':{
            'enabled':True,'permissions':['rank_local','prompt','remote_transfer']}}}),encoding='utf-8')
        (root/'vector_index.joblib').write_bytes(b'synthetic index')
        passage='A short source.' if short else ('A patient character crosses a quiet room while the rain taps at the window. '
            'Another character studies the table and waits for an answer that arrives later.')
        model=SimpleNamespace(encode=lambda texts,**kw:np.ones((len(texts),1),dtype='float32'))
        index=EmbeddingIndex([passage],[{'book':'allowed'}],np.ones((1,1),dtype='float32'),_model=model)
        return root,index,passage

    def test_eligible_reference_cadence_is_bound_without_copying_text_into_plan(self):
        root,index,passage=self.books();provider=Provider()
        with patch('prose_engine.embedding_store.load_index',return_value=index):
            preview=execute_scoped(self.store,'rhythm-preview',{**self.request,'references':'topic'},books_root=root)
            result=execute_scoped(self.store,'generate',{**self.request,'references':'topic','rhythm_plan_id':preview['rhythm_guidance']['id']},books_root=root,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED');plan=result['rhythm_guidance']
        self.assertEqual(plan['reference_observation']['sample_count'],1)
        self.assertEqual(plan['reference_basis'][0]['source_id'],'allowed')
        self.assertEqual(plan['reference_basis'][0]['library']['policy_sha256'],result['reference_receipts'][0]['policy_sha256'])
        self.assertNotIn(passage,json.dumps(plan));self.assertIn(passage,provider.prompts[0])
        self.assertEqual(plan['cues'][-1]['source'],'eligible-reference')
        self.assertIn('craft inspiration',plan['cues'][-1]['instruction'])

    def test_short_excerpts_invent_no_cadence(self):
        root,index,_=self.books(short=True)
        with patch('prose_engine.embedding_store.load_index',return_value=index):
            result=execute_scoped(self.store,'rhythm-preview',{**self.request,'references':'topic'},books_root=root)
        self.assertIsNone(result['rhythm_guidance']['reference_observation'])
        self.assertFalse(any(c['source']=='eligible-reference' for c in result['rhythm_guidance']['cues']))

    def test_plan_drift_blocks_before_draft_or_provider_construction(self):
        preview=self.preview();self.save_profile(pace='fast')
        with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('No provider')):
            with self.assertRaisesRegex(ValueError,'Rhythm plan changed'):
                execute_scoped(self.store,'generate',{**self.request,'rhythm_plan_id':preview['rhythm_guidance']['id']})
        self.assertEqual(self.drafts.list('sample','main'),[])

    def test_group_positions_coordinate_without_later_or_private_text(self):
        self.store.add_event('future','sample',2,'The hidden violet crown arrives at dawn.',status='approved',permitted=True,reviewer='fixture',source_id='fixture')
        self.rhythm.save('sample',4,1,0,{**defaults(),'author_override':'Future rhythm marker only.'})
        provider=Provider();preview=preview_group(self.store,self.group)
        result=generate_group(self.store,{**self.group,'rhythm_plan_id':preview['rhythm_guidance']['id']},provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        self.assertEqual(result['rhythm_guidance'],preview['rhythm_guidance'])
        plans=[p['plan'] for p in result['rhythm_guidance']['passages']]
        self.assertEqual([p['group']['phase'] for p in plans],['entry','development','exit'])
        for index,prompt in enumerate(provider.prompts):
            self.assertIn(f'Passage {index+1} of 3',prompt)
            self.assertNotIn('hidden violet crown',prompt);self.assertNotIn('Future rhythm marker',prompt)
            for later in self.mapping['beats'][index+1:]:self.assertNotIn(later['text'],prompt)
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)
        aggregate=self.drafts.open('sample','main',result['draft_id'])
        self.assertEqual(aggregate['rhythm_guidance'],result['rhythm_guidance'])
        self.assertEqual(len(aggregate['rhythm_evidence']['observations']),3)

    def test_untrusted_request_cannot_supply_group_position_or_later_text(self):
        result=self.preview(rhythm_position={'index':2,'count':3,'text':'Untrusted hidden prose.'})
        self.assertIsNone(result['rhythm_guidance']['group'])
        packet=build_packet(self.store,'sample',0,1,self.request['start'],self.request['end'])
        for position in ({'index':True,'count':3},{'index':0,'count':3},{'index':2,'count':9},{'index':1,'count':2,'text':'no'}):
            with self.assertRaisesRegex(ValueError,'position'):compile_guidance(packet,position=position)

    def test_invalid_group_preview_sends_nothing_and_creates_no_draft(self):
        for beats in ([],self.group['beats'][::-1],[self.group['beats'][0]]*2):
            with self.assertRaises(ValueError):preview_group(self.store,{**self.group,'beats':beats})
        self.assertEqual(self.drafts.list('sample','main'),[])

    def test_group_scope_change_between_calls_stops_before_next_dispatch(self):
        provider=Provider();calls=[]
        def scoped(*args,**kwargs):
            result=execute_scoped(*args,**kwargs)
            if args[1]=='generate':
                calls.append(result);self.save_profile(pace='slow')
            return result
        with patch('prose_engine.beat_workflow.execute_scoped',side_effect=scoped):
            result=generate_group(self.store,self.group,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(len(provider.prompts),1)
        self.assertEqual(len(result['completed']),1);self.assertIn('Scope changed',result['error'])
        self.assertEqual(self.drafts.list('sample','main')[0]['status'],'PROPOSED')

    def test_library_drift_between_calls_stops_even_if_same_excerpts_remain(self):
        root,index,_=self.books();provider=Provider()
        def scoped(*args,**kwargs):
            result=execute_scoped(*args,**kwargs)
            if args[1]=='generate':
                path=root/'reference_policy.json';policy=json.loads(path.read_text())
                policy['sources']['allowed']['permissions'].append('inspect_local');path.write_text(json.dumps(policy))
            return result
        with patch('prose_engine.embedding_store.load_index',return_value=index),patch('prose_engine.beat_workflow.execute_scoped',side_effect=scoped):
            result=generate_group(self.store,{**self.group,'references':'topic'},books_root=root,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PARTIAL');self.assertEqual(len(provider.prompts),1)
        self.assertIn('Rhythm plan changed',result['error']);self.assertEqual(len(result['completed']),1)

    def test_exact_100_skips_dispatch_and_partial_lock_retains_blocked_evidence(self):
        n=self.nb.existing('sample');self.nb.save('sample',n['revision'],1,n['blocks'],100,n['masks'])
        self.save_profile(pace='fast',cadence='staccato');preview=self.preview()
        self.assertTrue(preview['rhythm_guidance']['fully_locked'])
        self.assertEqual([c['source'] for c in preview['rhythm_guidance']['cues']],['exact-protection'])
        with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('No provider')):
            preserved=execute_scoped(self.store,'generate',self.request)
        self.assertTrue(preserved['preserved'])
        self.assertEqual(preserved['provider_calls'],0)
        self.assertEqual(preserved['text'],self.text[self.request['start']:self.request['end']])
        n=self.nb.existing('sample')
        snippet='the brass key'
        a=self.text.index(snippet)
        from prose_engine.notebook import digest
        self.nb.save('sample',n['revision'],1,n['blocks'],25,
                     [{'id':'exact','start':a,'end':a+len(snippet),'value':100,'sha256':digest(snippet)}])
        result=execute_scoped(self.store,'generate',self.request,provider_factory=lambda:Provider(text='Lena touched the door.'))
        self.assertEqual(result['status'],'BLOCKED')
        draft=self.drafts.open('sample','main',result['draft_id'])
        self.assertIsNotNone(draft['text']);self.assertIsNotNone(draft['rhythm_evidence'])
        self.assertEqual(self.store.get_episode('sample')['script'],self.text)

    def test_inflight_change_preserves_stale_candidate_plan_and_observations(self):
        self.save_profile(pace='slow')
        provider=Provider(change=lambda:self.save_profile(pace='fast'))
        with self.assertRaisesRegex(ValueError,'changed during'):
            execute_scoped(self.store,'generate',self.request,provider_factory=lambda:provider)
        draft=self.drafts.list('sample','main')[0]
        self.assertEqual(draft['status'],'STALE');self.assertIsNotNone(draft['text'])
        self.assertIsNotNone(draft['rhythm_guidance']);self.assertIsNotNone(draft['rhythm_evidence'])

    def test_laws_and_future_direction_remain_pre_dispatch_constraints(self):
        self.store.add_event('future','sample',2,'The hidden violet crown arrives at dawn.',status='approved',permitted=True,reviewer='fixture',source_id='fixture')
        provider=Provider()
        with self.assertRaisesRegex(ValueError,'unavailable at this beat'):
            execute_scoped(self.store,'rhythm-preview',{**self.request,'direction':'The hidden violet crown arrives at dawn.'},provider_factory=lambda:provider)
        self.assertEqual(provider.prompts,[])
        self.assertEqual(WorldLawStore(self.store).open()['laws'],[])

    def test_group_guidance_survives_native_backup_apply_and_undo(self):
        from tools.u10_backup import backup
        result=generate_group(self.store,self.group,provider_factory=Provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        original=self.drafts.open('sample','main',result['draft_id'])
        destination=self.root/'restored.sqlite';backup(Path(self.store.path),destination)
        restored=TimelineStore(destination);nb=NotebookStore(restored);drafts=DraftStore(nb)
        self.assertEqual(drafts.open('sample','main',result['draft_id']),original)
        n=nb.existing('sample');used=drafts.use('sample','main',result['draft_id'],n['revision'],1)
        nb.undo('sample',used['revision'],used['timeline_revision'])
        self.assertEqual(restored.get_episode('sample')['script'],self.text)
        self.assertEqual(drafts.open('sample','main',result['draft_id'])['rhythm_guidance'],original['rhythm_guidance'])

    def test_observations_are_numeric_and_advisory_not_similarity_scores(self):
        result=evidence('One. Two longer words.','One unchanged observation.')
        self.assertEqual(result['before']['sentence_count'],2)
        self.assertNotIn('score',result);self.assertIn('does not measure literary quality',result['interpretation'])

    def test_http_preview_uses_shared_path_without_provider_or_draft(self):
        from tools.studio_ui import StudioRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=Path(self.store.path);server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(path,data):
            req=urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(req) as response:return json.load(response)
        try:
            with patch('prose_engine.providers.primary_session.create_scoped_provider',side_effect=AssertionError('Preview must not create a provider')):
                single=post('/api/scoped',{**self.request,'action':'rhythm-preview'})
                group=post('/api/beat-group',{**self.group,'action':'preview'})
            self.assertEqual(single['rhythm_guidance'],self.preview()['rhythm_guidance'])
            self.assertEqual(group['rhythm_guidance'],preview_group(self.store,self.group)['rhythm_guidance'])
            self.assertEqual(self.drafts.list('sample','main'),[])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
