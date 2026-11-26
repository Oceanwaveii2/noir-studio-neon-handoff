"""Local fixtures only: no external model or primary-session dispatch."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
from prose_engine.embedding_store import EmbeddingIndex
from prose_engine.voice.luar import LuarIndex
from prose_engine.voice.retrieve import StyleIndex
from prose_engine.notebook import NotebookStore, DraftStore
from prose_engine.scoped_service import execute_scoped
from prose_engine.scoped_references import ReferenceUnavailable
from prose_engine.beat_workflow import generate_group
from prose_engine.reference_service import prepare_retrieval
from story_graph.episode_timeline import TimelineStore
from story_graph.beat_map import map_episode
from tools.studio_ui import StudioRequestHandler


class Provider:
    def __init__(self, callback=None): self.prompts=[]; self.callback=callback
    def generate_rewrite(self, request, prompt):
        self.prompts.append(prompt)
        if self.callback: self.callback()
        return request.original_text + ' The lamp flickered.'


class LibraryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.books=self.root/'books'; self.books.mkdir()
        (self.books/'text').mkdir()
        self.passage='A measured reference sentence moves across the page. Another pause lets the reader catch up before the next turn arrives.'
        self.suspect='A false attributed scene that must never enter a prompt.'
        self.write('manifest.json',{'books':[{'slug':'allowed','title':'Reviewed fixture edition','author':'Fixture Author'}, {'slug':'suspect','title':'Wrong book'}]})
        for name,text in [('allowed',self.passage),('suspect',self.suspect)]:
            (self.books/'text'/f'{name}.txt').write_text(text,encoding='utf-8')
        self.write('reference_policy.json',{'schema_version':1,'sources':{
            s:{'enabled':True,'permissions':['rank_local','inspect_local','prompt','remote_transfer']} for s in ('allowed','suspect')}})
        self.write('influence.json',{'books':{}})
        self.write('library_quality.json',{'schema_version':1,'excluded':{'suspect':'Mislabelled original retained for history.'}})
        meta=[{'book':s} for s in ('allowed','suspect')]
        vectors=np.ones((2,1),dtype='float32')
        self.model=SimpleNamespace(encode=lambda texts,**kwargs:np.ones((len(texts),1),dtype='float32'))
        self.topic=EmbeddingIndex([self.passage,self.suspect],meta,vectors,_model=self.model)
        self.topic.save(self.books/'vector_index.joblib')
        self.luar=LuarIndex(vectors,[self.passage,self.suspect],meta); self.luar.save(self.books/'luar_index.joblib')
        self.style=StyleIndex(vectors,[self.passage,self.suspect],meta,encode=lambda text:np.ones(1)); self.style.save(self.books/'style_index.joblib')
        self.store=TimelineStore(self.root/'timeline.sqlite'); self.store.create_episode('fixture','Fixture','main',1)
        self.text='INT. ROOM\n\nA quiet arrival.\n\nA second moment.'
        self.store.save('fixture',0,script=self.text,source_name='isolated-fixture')
        self.nb=NotebookStore(self.store); n=self.nb.open('fixture')
        self.nb.save('fixture',n['revision'],1,n['blocks'],25,n['masks'])
        self.req={'episode':'fixture','revision':1,'beat':0,'start':11,'end':27,
                  'provider':'codex-session','references':'topic','scene_function':'comedy'}

    def write(self,name,value): (self.books/name).write_text(json.dumps(value),encoding='utf-8')

    def test_all_three_legacy_views_exclude_retired_sources_before_scoring(self):
        with patch('prose_engine.embedding_store.load_index',return_value=self.topic), \
             patch('prose_engine.voice.luar.LuarIndex.load',return_value=self.luar), \
             patch('prose_engine.voice.luar.LuarEncoder',return_value=self.model), \
             patch('prose_engine.voice.retrieve.StyleIndex.load',return_value=self.style):
            for backend in ('topic','luar','style'):
                setup=prepare_retrieval(self.books,backend,'codex-session')
                self.assertEqual(setup.state,'ready',setup.message)
                self.assertEqual(setup.drive.index.texts,[self.passage])
                hits=setup.drive.retrieve_passages('fixture','quiet',influence=setup.influence)
                self.assertEqual([h.text for h in hits],[self.passage])
        self.assertEqual(len(self.topic.texts),2)
        self.assertTrue(json.loads((self.books/'reference_policy.json').read_text())['sources']['suspect']['enabled'])

    def test_scoped_prompt_and_draft_keep_metadata_cadence_and_no_excerpt_export(self):
        provider=Provider()
        with patch('prose_engine.embedding_store.load_index',return_value=self.topic):
            result=execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        self.assertIn(self.passage,provider.prompts[0]); self.assertNotIn(self.suspect,provider.prompts[0])
        self.assertIn('Reviewed fixture edition',provider.prompts[0])
        self.assertIn('ELIGIBLE BOOK SOURCE RECEIPTS',provider.prompts[0])
        self.assertIn('REFERENCE CADENCE OBSERVATION',provider.prompts[0])
        receipt=result['reference_receipts'][0]
        self.assertEqual(receipt['source_author'],'Fixture Author')
        self.assertEqual(receipt['excerpt_sha256'],hashlib.sha256(self.passage.encode()).hexdigest())
        self.assertEqual(len(receipt['quality_sha256']),64)
        stored=DraftStore(self.nb).open('fixture','main',result['draft_id'])
        self.assertEqual(stored['reference_receipts'],result['reference_receipts'])
        self.assertEqual(stored['reference_features'],result['reference_features'])
        self.assertNotIn(self.passage,json.dumps(stored)); self.assertEqual(self.store.get_episode('fixture')['script'],self.text)

    def test_quality_drift_during_generation_retains_stale_draft(self):
        provider=Provider(lambda:self.write('library_quality.json',{'schema_version':1,'excluded':{'allowed':'Later review'}}))
        with patch('prose_engine.embedding_store.load_index',return_value=self.topic):
            with self.assertRaises(ReferenceUnavailable):
                execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(len(provider.prompts),1)
        self.assertEqual(DraftStore(self.nb).list('fixture','main')[-1]['status'],'STALE')
        self.assertEqual(self.store.get_episode('fixture')['script'],self.text)

    def test_cadence_delivery_omits_book_words_and_allows_craft_without_copy_block(self):
        source=self.passage
        calls=[]
        class Copies:
            def generate_rewrite(self, request, prompt):
                calls.append(prompt)
                return request.original_text + ' ' + source
        request={**self.req,'reference_delivery':'cadence'}
        with patch('prose_engine.embedding_store.load_index',return_value=self.topic):
            preview=execute_scoped(self.store,'rhythm-preview',request,books_root=self.books)
            result=execute_scoped(self.store,'generate',{**request,'rhythm_plan_id':preview['rhythm_guidance']['id']},
                                  books_root=self.books,provider_factory=Copies)
        self.assertEqual(len(calls),1)
        self.assertIn('content-free-cadence-v1',calls[0])
        self.assertNotIn(source,calls[0])
        self.assertNotIn('Reviewed fixture edition',calls[0])
        self.assertEqual(result['status'],'PROPOSED')
        self.assertEqual(result['reference_receipts'][0]['source_id'],'allowed')

    def test_group_retains_each_child_cadence_and_recoverable_receipts(self):
        mapped=map_episode(self.store,'fixture',1); provider=Provider()
        request={**self.req,'project':mapped['project_id'],'universe':mapped['universe_id'],'branch':'main',
                 'source_sha256':mapped['source_sha256'],'beats':[b['id'] for b in mapped['beats']]}
        with patch('prose_engine.embedding_store.load_index',return_value=self.topic):
            result=generate_group(self.store,request,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED',result)
        self.assertEqual(len(provider.prompts),2)
        stored=DraftStore(self.nb).open('fixture','main',result['draft_id'])
        self.assertEqual(stored['reference_features']['scope'],'consecutive-beat-group')
        self.assertEqual(len(stored['reference_features']['observations']),2)
        self.assertEqual(stored['reference_features'],result['reference_features'])
        self.assertNotIn(self.passage,json.dumps(stored))

    def test_http_readiness_and_quality_controls_construct_no_encoder(self):
        before={p.name:p.read_bytes() for p in self.books.iterdir() if p.is_file()}
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.root/'timeline.sqlite'; server.timeline_only=True; server.books_dir=self.books
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            with patch('prose_engine.reference_service.prepare_retrieval',side_effect=AssertionError('GET must not prepare an encoder')), \
                 patch('prose_engine.voice.luar.LuarEncoder',side_effect=AssertionError('GET inference')):
                for backend in ('topic','luar','style'):
                    with urllib.request.urlopen(base+'/api/book-status?backend='+backend+'&provider=codex-session') as response: data=json.load(response)
                    self.assertEqual(data['state'],'incomplete')
                    self.assertEqual(set(data['indexes']),{'topic','luar','style'})
                    self.assertFalse(data['generation_started']); self.assertEqual(data['quality_quarantined'],1)
                with urllib.request.urlopen(base+'/api/book-policy') as response: sources=json.load(response)['sources']
                self.assertEqual(next(s for s in sources if s['id']=='suspect')['quality_exclusion'],'Mislabelled original retained for history.')
        finally: server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.books.iterdir() if p.is_file()})

    def test_cli_inspection_selects_active_path_and_bad_pointer_never_falls_back(self):
        from prose_engine.cli import cmd_reference
        source=self.root/'query.txt'; source.write_text('An original fixture query.',encoding='utf-8')
        args=SimpleNamespace(books=str(self.books),file=str(source),paragraph=None,flagged=False,k=1)
        selected=self.books/'selected-topic.joblib'; selected.write_bytes(b'fixture-selected')
        with patch('prose_engine.library_indexes.index_path',return_value=selected), \
             patch('prose_engine.cli.load_index',return_value=self.topic) as loader:
            cmd_reference(args)
            loader.assert_called_once_with(selected)
        self.write('library_active.json',{'schema_version':1,'directory':'../not-a-release','hashes':{}})
        with self.assertRaises(ValueError): cmd_reference(args)

    def test_evaluator_centroid_uses_only_eligible_quality_checked_rows(self):
        from prose_engine.voice.evaluate import Evaluator
        evaluator=Evaluator(books=self.books)
        self.assertEqual(evaluator.unit.shape,(1,1))
        self.assertTrue(np.allclose(evaluator.centroid,[1.]))
        policy=json.loads((self.books/'reference_policy.json').read_text())
        policy['sources']['allowed']['enabled']=False; self.write('reference_policy.json',policy)
        with self.assertRaises(ValueError): Evaluator(books=self.books)


if __name__=='__main__': unittest.main()
