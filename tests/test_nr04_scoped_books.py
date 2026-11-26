import json
import os
import subprocess
import sys
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
from story_graph.episode_timeline import TimelineStore
from prose_engine.embedding_store import EmbeddingIndex
from prose_engine.notebook import DraftStore, NotebookStore
from prose_engine.scoped_references import ReferenceUnavailable, select_references
from prose_engine.scoped_service import execute_scoped
from tools.studio_ui import StudioRequestHandler


class Provider:
    def __init__(self,text='A dim room.',on_call=None): self.calls=0;self.prompts=[];self.text=text;self.on_call=on_call
    def generate_rewrite(self,request,prompt):
        self.calls+=1;self.prompts.append(prompt)
        if self.on_call: self.on_call()
        return self.text


class ScopedBooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.books=self.root/'books';self.books.mkdir()
        self.store=TimelineStore(self.root/'timeline.sqlite');self.store.add_starter_cards()
        self.store.save('spring-break',0,script='A quiet room.',source_name='fixture')
        self.store.add_event('future','tapped-out',1,'The hidden glitter secret arrives.',status='approved',permitted=True,reviewer='author',source_id='fixture')
        self.req={'episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,
                  'provider':'codex-session','references':'topic','scene_function':'comedy'}
        self.texts=['An eligible passage with a quiet distinctive rhythm.',
                    'An off passage must never appear in any ranking.',
                    'An unknown passage must never appear in any ranking.',
                    'A local only passage must not reach a remote session.',
                    'A future story entry must not reach any ranking.',
                    'A sibling branch entry must not reach any ranking.',
                    'The hidden glitter secret arrives.']
        self.meta=[{'book':name} for name in ('allowed','off','unknown','local','future','sibling','hidden')]
        self.meta[4]['episode']='future';self.meta[5]['branch']='sibling'
        self.policy={'schema_version':1,'sources':{
            name:{'enabled':True,'permissions':['rank_local','prompt','remote_transfer']}
            for name in ('allowed','off','future','sibling','hidden')}}
        self.policy['sources']['local']={'enabled':True,'permissions':['rank_local','prompt']}
        self.write_policy()
        (self.books/'influence.json').write_text(json.dumps({'books':{'off':0}}),encoding='utf-8')
        (self.books/'vector_index.joblib').write_bytes(b'synthetic index')
        model=SimpleNamespace(encode=lambda texts,**kwargs: np.ones((len(texts),len(self.texts)),dtype='float32'))
        self.index=EmbeddingIndex(self.texts,self.meta,np.eye(len(self.texts),dtype='float32'),_model=model)

    def write_policy(self): (self.books/'reference_policy.json').write_text(json.dumps(self.policy),encoding='utf-8')

    def test_only_eligible_reaches_ranker_prompt_and_text_free_receipt(self):
        from prose_engine.embedding_store import EmbeddingIndex
        provider=Provider();seen=[];original=EmbeddingIndex.query
        def observe(index,text,*args,**kwargs):
            seen.append((list(index.texts),text));return original(index,text,*args,**kwargs)
        with patch('prose_engine.embedding_store.load_index',return_value=self.index),patch.object(EmbeddingIndex,'query',observe):
            result=execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
            again=execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED');self.assertEqual(provider.calls,2)
        self.assertEqual(seen[0][0],[self.texts[0]]);self.assertIn('comedic timing',seen[0][1])
        self.assertIn(self.texts[0],provider.prompts[0]);self.assertNotIn('hidden glitter secret',provider.prompts[0])
        for text in self.texts[1:]: self.assertNotIn(text,provider.prompts[0])
        receipt=result['reference_receipts'][0]
        self.assertEqual(receipt['source_id'],'allowed');self.assertEqual(receipt['passage_id'],again['reference_receipts'][0]['passage_id'])
        self.assertNotIn(self.texts[0],json.dumps(result))
        stored=DraftStore(NotebookStore(self.store)).open('spring-break','main',result['draft_id'])
        self.assertEqual(stored['reference_receipts'],result['reference_receipts'])
        self.assertNotIn(self.texts[0],json.dumps(stored))

    def test_missing_policy_explicit_no_book_and_copy_guard(self):
        (self.books/'reference_policy.json').unlink();provider=Provider()
        with self.assertRaises(ReferenceUnavailable) as error:
            execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(error.exception.state,'unconfigured');self.assertEqual(provider.calls,0)
        no_books=execute_scoped(self.store,'generate',{**self.req,'references':'none'},books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(no_books['book_status']['state'],'disabled')
        self.assertIn('SCENE FUNCTION: comedy',provider.prompts[-1])
        self.write_policy();copier=Provider(self.texts[0])
        with patch('prose_engine.embedding_store.load_index',return_value=self.index):
            result=execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:copier)
        self.assertEqual(result['status'],'PROPOSED')

    def test_policy_change_during_provider_marks_draft_stale(self):
        def change():
            self.policy['sources']['allowed']['enabled']=False;self.write_policy()
        provider=Provider(on_call=change)
        with patch('prose_engine.embedding_store.load_index',return_value=self.index):
            with self.assertRaises(ReferenceUnavailable) as error:
                execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(error.exception.state,'stale')
        self.assertEqual(DraftStore(NotebookStore(self.store)).list('spring-break','main')[-1]['status'],'STALE')

    def test_policy_change_before_dispatch_makes_zero_provider_calls(self):
        provider=Provider()
        def factory():
            self.policy['sources']['allowed']['enabled']=False;self.write_policy();return provider
        with patch('prose_engine.embedding_store.load_index',return_value=self.index):
            with self.assertRaises(ReferenceUnavailable) as error:
                execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=factory)
        self.assertEqual(error.exception.state,'stale');self.assertEqual(provider.calls,0)
        self.assertEqual(DraftStore(NotebookStore(self.store)).list('spring-break','main')[-1]['status'],'STALE')

    def test_no_eligible_sources_stop_and_export_contains_no_excerpts(self):
        for entry in self.policy['sources'].values(): entry['enabled']=False
        self.write_policy();provider=Provider()
        with patch('prose_engine.embedding_store.load_index',return_value=self.index):
            with self.assertRaises(ReferenceUnavailable) as error:
                execute_scoped(self.store,'generate',self.req,books_root=self.books,provider_factory=lambda:provider)
        self.assertEqual(error.exception.state,'no_eligible');self.assertEqual(provider.calls,0)
        exported=execute_scoped(self.store,'export',self.req,books_root=self.books)
        for text in self.texts: self.assertNotIn(text,json.dumps(exported))

    def test_independent_library_paths_work_outside_project_directory(self):
        other=self.root/'other';other.mkdir()
        (other/'reference_policy.json').write_text(json.dumps(self.policy),encoding='utf-8')
        (other/'vector_index.joblib').write_bytes(b'other index')
        from prose_engine.scoped_pipeline import build_packet
        packet=build_packet(self.store,'spring-break',1,1,0,13)
        start=Path.cwd()
        try:
            os.chdir(self.root)
            with patch('prose_engine.embedding_store.load_index',return_value=self.index):
                first=select_references(packet,root=self.books,provider='codex-session')
                second=select_references(packet,root=other,provider='codex-session')
        finally: os.chdir(start)
        self.assertNotEqual(first['receipts'][0]['index_sha256'],second['receipts'][0]['index_sha256'])

    def test_real_synthetic_indexes_from_an_unrelated_working_directory(self):
        from prose_engine.vector_store import VectorIndex
        root_a=self.root/'library-a';root_b=self.root/'library-b'
        chunks=[{'book':name,'title':name,'text':text} for name,text in [
            ('allowed','quiet room bright silver room comic laughter'),
            ('off','quiet room secret window quiet laughter'),
            ('other','quiet room chairs quiet music laughter')]]
        for root in (root_a,root_b):
            root.mkdir();VectorIndex.build(chunks,dim=2).save(root/'vector_index.joblib')
            (root/'reference_policy.json').write_text(json.dumps(self.policy),encoding='utf-8')
            (root/'influence.json').write_text(json.dumps({'books':{'off':0}}),encoding='utf-8')
        code=('import json,sys; from story_graph.episode_timeline import TimelineStore; '
              'from prose_engine.scoped_pipeline import build_packet; '
              'from prose_engine.scoped_references import select_references; '
              'p=build_packet(TimelineStore(sys.argv[1]),"spring-break",1,1,0,13); '
              'print(json.dumps([[r["source_id"] for r in select_references(p,root=x,provider="codex-session")["receipts"]] for x in sys.argv[2:]]))')
        env=dict(os.environ);env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
        run=subprocess.run([sys.executable,'-B','-c',code,str(self.root/'timeline.sqlite'),str(root_a),str(root_b)],
                           cwd=self.root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout),[['allowed'],['allowed']])

    def test_studio_source_settings_do_not_generate_and_preserve_unclassified(self):
        (self.books/'reference_policy.json').unlink()
        (self.books/'manifest.json').write_text(json.dumps({'books':[{'slug':'allowed'},{'slug':'unknown'}]}),encoding='utf-8')
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=self.root/'timeline.sqlite';server.timeline_only=True;server.books_dir=self.books
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base+'/api/book-policy') as response: initial=json.load(response)
            with urllib.request.urlopen(base+'/api/book-status?backend=none&provider=codex-session') as response:
                self.assertEqual(json.load(response)['state'],'disabled')
            with urllib.request.urlopen(base+'/api/book-status?backend=topic&provider=codex-session') as response:
                self.assertEqual(json.load(response)['state'],'unconfigured')
            self.assertFalse((self.books/'reference_policy.json').exists());self.assertFalse(initial['sources'][0]['configured'])
            body={'source':'allowed','enabled':True,'permissions':['rank_local','prompt','remote_transfer'],'revision':initial['revision']}
            request=urllib.request.Request(base+'/api/book-policy',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response: saved=json.load(response)
            sources={x['id']:x for x in saved['sources']}
            self.assertTrue(sources['allowed']['configured']);self.assertFalse(sources['unknown']['configured'])
            self.assertEqual(list(json.loads((self.books/'reference_policy.json').read_text())['sources']),['allowed'])
            stale=urllib.request.Request(base+'/api/book-policy',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
            with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(stale)
            self.assertEqual(error.exception.code,400)
        finally: server.shutdown();server.server_close();thread.join()

    def test_studio_scoped_generation_receives_only_eligible_books(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.root/'timeline.sqlite';server.timeline_only=True;server.books_dir=self.books
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        provider=Provider()
        request=urllib.request.Request(base+'/api/scoped',data=json.dumps({**self.req,'action':'generate'}).encode(),
                                       headers={'Content-Type':'application/json','Origin':base})
        try:
            with patch('prose_engine.embedding_store.load_index',return_value=self.index), \
                 patch('prose_engine.providers.primary_session.create_scoped_provider',return_value=provider):
                with urllib.request.urlopen(request) as response: result=json.load(response)
            self.assertEqual(result['book_status']['state'],'ready')
            self.assertEqual(provider.calls,1);self.assertIn(self.texts[0],provider.prompts[0])
            self.assertNotIn(self.texts[1],provider.prompts[0])
            self.assertNotIn(self.texts[0],json.dumps(result))
        finally: server.shutdown();server.server_close();thread.join()


if __name__=='__main__': unittest.main()
