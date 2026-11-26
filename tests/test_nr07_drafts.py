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
from prose_engine.embedding_store import EmbeddingIndex
from prose_engine.notebook import DraftStore, NotebookStore, digest, joined
from prose_engine.scoped_pipeline import build_packet, generate_recorded
from prose_engine.scoped_references import ReferenceUnavailable
from prose_engine.scoped_service import execute_scoped
from story_graph.beat_rhythm import BeatRhythmStore, defaults
from story_graph.episode_timeline import TimelineStore


class FakeProvider:
    def __init__(self, text='A quiet hall.', on_call=None):
        self.text=text; self.on_call=on_call; self.calls=0; self.prompts=[]; self.requests=[]
    def generate_rewrite(self, request, prompt):
        self.calls+=1; self.prompts.append(prompt); self.requests.append(request)
        if self.on_call: self.on_call()
        return self.text


class ScopedDraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.path=self.root/'timeline.sqlite'
        self.store=TimelineStore(self.path); self.store.add_starter_cards()
        for episode in ('spring-break','tapped-out'):
            self.store.save(episode,0,script='A quiet room.',source_name=episode+'.txt')
        self.store.add_event('haley-awakening','hot-scoomp',0,'Haley awakens.',status='approved',permitted=True,source_id='fixture',reviewer='author')
        self.store.add_event('future-only','tapped-out',3,'A future secret red lantern.',status='approved',permitted=True,source_id='fixture',reviewer='author')
        self.book=NotebookStore(self.store)
        for episode in ('spring-break','tapped-out'):
            state=self.book.open(episode)
            mask={'id':'quiet','start':2,'end':7,'value':100,'hard':True,'sha256':digest('quiet')}
            self.book.save(episode,0,1,state['blocks'],25,[mask])
        self.drafts=DraftStore(self.book)

    def request(self,episode='spring-break',**extra):
        return {'episode':episode,'beat':1,'revision':1,'start':0,'end':13,'provider':'codex-session',**extra}

    def test_two_versions_per_episode_and_inspectable_context(self):
        BeatRhythmStore(self.store).save('spring-break',1,1,0,{**defaults(),'pace':'slow','comedy':'delay'})
        ids={}; providers=[]
        for episode in ('spring-break','tapped-out'):
            ids[episode]=[]
            for ending in ('hall','garden'):
                provider=FakeProvider('A quiet '+ending+'.');providers.append(provider)
                result=execute_scoped(self.store,'generate',self.request(episode),provider_factory=lambda:provider)
                ids[episode].append(result['draft_id'])
        again=DraftStore(NotebookStore(TimelineStore(self.path)))
        for episode in ids:
            records=again.list(episode,'main');self.assertEqual(len(records),2)
            self.assertEqual([x['id'] for x in records],ids[episode])
            record=records[0]; context=record['writing_context']
            self.assertEqual(context['episode'],episode); self.assertEqual(context['start'],0);self.assertEqual(context['end'],13)
            self.assertEqual(context['protection_values'],[[0,2,25],[2,7,100],[7,13,25]])
            self.assertTrue(context['world_laws']);self.assertIn('characters',context);self.assertIn('events',context)
            self.assertEqual(record['request_budget']['max_provider_calls'],1)
            self.assertEqual(record['provider'],'codex-session')
        self.assertNotIn('future secret red lantern',json.dumps(again.open('spring-break','main',ids['spring-break'][0])))
        self.assertNotIn('future secret red lantern',providers[0].prompts[0])
        self.assertEqual(again.open('spring-break','main',ids['spring-break'][0])['writing_context']['beat_rhythm']['profile']['pace'],'slow')
        before=sum(p.calls for p in providers)
        again.favorite('spring-break','main',ids['spring-break'][0],True)
        self.assertIn('garden',again.compare('spring-break','main',*ids['spring-break']))
        with self.assertRaises(ValueError):again.open('tapped-out','main',ids['spring-break'][0])
        with self.assertRaises(ValueError):again.list('spring-break','different-branch')
        self.assertEqual(sum(p.calls for p in providers),before)
        from tools.u10_backup import backup
        copy_path=self.root/'recovered-timeline.sqlite'
        self.assertEqual(backup(self.path,copy_path)['status'],'PASS')
        restored=DraftStore(NotebookStore(TimelineStore(copy_path)))
        for episode in ids:
            self.assertEqual([x['id'] for x in restored.list(episode,'main')],ids[episode])
            self.assertEqual(restored.open(episode,'main',ids[episode][0])['writing_context']['episode'],episode)

    def test_partial_apply_and_undo_keep_lock(self):
        p=FakeProvider(); result=execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:p)
        draft=self.drafts.open('spring-break','main',result['draft_id'])
        used=self.drafts.use('spring-break','main',draft['id'],1,1,source_start=8,source_end=12,candidate_start=8,candidate_end=12)
        self.assertEqual(joined(used['blocks']),'A quiet hall.')
        restored=self.book.undo('spring-break',used['revision'],used['timeline_revision'])
        self.assertEqual(joined(restored['blocks']),'A quiet room.')

    def test_apply_keeps_the_first_duplicate_at_its_exact_occurrence(self):
        ep = 'duplicate'
        self.store.create_episode(ep, 'Duplicate', 'main', 8)
        self.store.save(ep, 0, script='Hold. Hold.', source_name='duplicate.txt')
        state = self.book.open(ep)
        lock = dict(id='first', start=0, end=5, value=100, sha256=digest('Hold.'))
        state = self.book.save(ep, state['revision'], 1, state['blocks'], 25, [lock])
        packet = build_packet(self.store, ep, 0, 1, 0, 11)
        draft = self.drafts.start(packet, 'fixture', proposal={'text':'Hold.'})
        args = (ep, 'main', draft, state['revision'], 1)
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.drafts.use(*args, source_start=0, source_end=6, candidate_start=0, candidate_end=0)
        with self.assertRaisesRegex(ValueError, 'occurrence'):
            self.drafts.use(*args)
        used = self.drafts.use(*args, source_start=5, source_end=11, candidate_start=0, candidate_end=0)
        book = NotebookStore(TimelineStore(self.path))
        restored = book.undo(ep, used['revision'], used['timeline_revision'])
        redone = book.redo(ep, restored['revision'], restored['timeline_revision'])
        self.assertEqual([joined(x['blocks']) for x in (used,restored,redone)], ['Hold.', 'Hold. Hold.', 'Hold.'])
        self.assertTrue(all(x['masks']==[lock] for x in (used,restored,redone)))

    def test_sibling_branch_drafts_are_independent(self):
        self.store.fork('alternate','main','spring-break',1)
        self.store.create_episode('alternate-story','Alternate story','alternate',0)
        self.store.save('alternate-story',0,script='A quiet room.',source_name='alternate.txt')
        state=self.book.open('alternate-story');self.book.save('alternate-story',0,1,state['blocks'],25,[])
        writer = FakeProvider()
        primary = execute_scoped(self.store, 'generate', self.request(request_id='same-selection'),
                                 provider_factory=lambda: writer)['draft_id']
        sibling = execute_scoped(self.store, 'generate', self.request('alternate-story', branch='alternate',
                                 request_id='same-selection'), provider_factory=lambda: writer)['draft_id']
        first, second = writer.requests
        self.assertEqual(first.original_text, second.original_text)
        self.assertNotEqual(first.request_id, second.request_id)
        self.assertNotEqual(first.target_span_id, second.target_span_id)
        self.assertEqual(self.drafts.open('spring-break','main',primary)['provider_request_id'], first.request_id)
        self.assertEqual(self.drafts.open('alternate-story','alternate',sibling)['provider_request_id'], second.request_id)
        self.assertEqual([x['id'] for x in self.drafts.list('spring-break','main')],[primary])
        self.assertEqual([x['id'] for x in self.drafts.list('alternate-story','alternate')],[sibling])
        with self.assertRaises(ValueError):self.drafts.open('alternate-story','alternate',primary)

    def test_full_episode_range_crosses_blocks_and_is_recoverable(self):
        self.store.create_episode('multi','Multi block','main',40)
        text='One small room.\n\nAnother small room.'
        self.store.save('multi',0,script=text,source_name='multi.txt')
        state=self.book.open('multi');self.book.save('multi',0,1,state['blocks'],25,[])
        provider=FakeProvider('One quiet room.\n\nAnother bright room.')
        result=execute_scoped(self.store,'generate',self.request('multi',start=0,end=len(text)),provider_factory=lambda:provider)
        draft=self.drafts.open('multi','main',result['draft_id'])
        self.assertEqual(draft['source_text'],text);self.assertIn(text,provider.prompts[0])
        used=self.drafts.use('multi','main',draft['id'],1,1)
        self.assertEqual(joined(used['blocks']),provider.text)
        self.assertEqual(joined(self.book.undo('multi',used['revision'],used['timeline_revision'])['blocks']),text)

    def test_successful_session_journal_is_linked_to_draft(self):
        from prose_engine.providers.primary_session import PrimarySessionProvider
        provider=PrimarySessionProvider('codex',session_handler=lambda prompt:'A quiet hall.',
                   ledger=self.root/'usage.jsonl',max_calls=1,recovery_scope='test-episode')
        result=execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:provider)
        record=self.drafts.open('spring-break','main',result['draft_id'])
        self.assertEqual(record['attempt_id'],provider.last_attempt_id)
        self.assertEqual(record['provider_job_id'],provider.job_id)
        self.assertEqual(record['request_budget']['max_provider_calls'],1)
        attempts=provider.attempts.list_attempts()
        self.assertEqual(attempts[0]['id'],record['attempt_id']);self.assertEqual(attempts[0]['state'],'completed')

    def test_zero_budget_records_no_send(self):
        from prose_engine.providers.primary_session import PrimarySessionProvider
        from prose_engine.providers.deepseek import BudgetExceeded
        calls=[]
        provider=PrimarySessionProvider('codex',session_handler=lambda prompt:calls.append(prompt),
                   ledger=self.root/'usage.jsonl',max_calls=0,recovery_scope='test-episode')
        with self.assertRaises(BudgetExceeded):
            execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:provider)
        record=self.drafts.list('spring-break','main')[-1]
        self.assertEqual(record['status'],'FAILED');self.assertEqual(record['request_budget']['max_provider_calls'],0)
        self.assertIsNone(record['attempt_id']);self.assertEqual(calls,[])

    def test_unknown_session_blocks_repeat_after_restart(self):
        from prose_engine.providers.primary_session import PrimarySessionProvider
        from prose_engine.providers.session_attempts import SessionAttemptError
        calls=[]
        def lost(prompt):calls.append(prompt);raise TimeoutError('connection lost')
        def factory():return PrimarySessionProvider('codex',session_handler=lost,ledger=self.root/'usage.jsonl',max_calls=1,recovery_scope='test-episode')
        with self.assertRaises(SessionAttemptError):execute_scoped(self.store,'generate',self.request(),provider_factory=factory)
        first=self.drafts.list('spring-break','main')[-1]
        self.assertEqual(first['status'],'UNKNOWN');self.assertTrue(first['attempt_id'])
        reopened=TimelineStore(self.path)
        with self.assertRaises(SessionAttemptError):execute_scoped(reopened,'generate',self.request(),provider_factory=factory)
        records=DraftStore(NotebookStore(reopened)).list('spring-break','main')
        self.assertEqual(records[-1]['status'],'UNKNOWN');self.assertEqual(records[-1]['attempt_id'],first['attempt_id'])
        self.assertEqual(len(calls),1)

    def test_keyed_selection_recovers_both_lost_reply_outcomes(self):
        from prose_engine.providers.primary_session import PrimarySessionProvider
        from prose_engine.providers.session_attempts import SessionAttemptError
        for lost in (False, True):
            with self.subTest(lost=lost):
                calls = []
                def handler(prompt):
                    calls.append(prompt)
                    if lost:
                        raise TimeoutError('reply lost after dispatch')
                    return 'A quiet hall.'

                writer = PrimarySessionProvider('codex', session_handler=handler, max_calls=1,
                    ledger=self.root/f'usage-{lost}.jsonl')
                request = self.request(request_id=f'lost-reply-{lost}')
                if lost:
                    with self.assertRaises(SessionAttemptError):
                        execute_scoped(self.store, 'generate', request, provider_factory=lambda: writer)
                else:
                    # Simulate a client losing the committed response.
                    execute_scoped(self.store, 'generate', request, provider_factory=lambda: writer)
                original = self.drafts.list('spring-break','main')[-1]
                reopened = TimelineStore(self.path)
                result = execute_scoped(reopened, 'generate', request,
                    provider_factory=lambda: self.fail('A replay constructed a writer'))
                self.assertTrue(result['replayed'])
                self.assertEqual(result['draft_id'], original['id'])
                self.assertEqual(result['status'], 'UNKNOWN' if lost else 'PROPOSED')
                self.assertEqual(result['text'], None if lost else 'A quiet hall.')
                self.assertEqual(result['attempt_id'], writer.last_attempt_id)
                self.assertEqual(result['provider_request_id'], original['provider_request_id'])
                self.assertEqual(result['provider_calls'], 0)
                self.assertEqual(len(writer.attempts.list_attempts()), 1)
                self.assertEqual(len(calls), 1)

    def test_studio_opens_context_and_compares_without_generation(self):
        from tools.studio_ui import StudioRequestHandler
        provider=FakeProvider()
        first=execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:provider)['draft_id']
        second=execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:provider)['draft_id']
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.path;server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(data):
            request=urllib.request.Request(base+'/api/drafts',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            scope={'episode':'spring-break','branch':'main'}
            record=post({**scope,'action':'open','draft':first})
            self.assertEqual(record['writing_context']['episode'],'spring-break')
            post({**scope,'action':'favorite','draft':first,'value':True})
            post({**scope,'action':'compare','first':first,'second':second})
            self.assertEqual(provider.calls,2)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_unknown_started_missing_provider_and_stale_candidate_survive_restart(self):
        packet=build_packet(self.store,'spring-break',1,1,0,13)
        started=self.drafts.start(packet,'fixture')
        def missing(): raise ValueError('not connected')
        with self.assertRaises(ValueError):generate_recorded(self.store,packet,'fixture',missing,lambda:packet)
        class Unknown:
            def generate_rewrite(self,request,prompt):raise TimeoutError('unknown result')
        with self.assertRaises(TimeoutError):generate_recorded(self.store,packet,'fixture',Unknown,lambda:packet)
        provider=FakeProvider(on_call=lambda:self.store.add_event('midcall','spring-break',0,'A new fact.',status='draft'))
        with self.assertRaises(ValueError):
            generate_recorded(self.store,packet,'fixture',lambda:provider,lambda:build_packet(self.store,'spring-break',1,1,0,13))
        records=DraftStore(NotebookStore(TimelineStore(self.path))).list('spring-break','main')
        self.assertEqual([r['status'] for r in records],['STARTED','FAILED','UNKNOWN','STALE'])
        self.assertEqual(records[0]['id'],started);self.assertEqual(records[-1]['text'],'A quiet hall.')
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')
        with self.assertRaises(ValueError):self.drafts.use('spring-break','main',records[-1]['id'],1,1)

    def test_blocked_candidate_is_preserved_but_not_applied(self):
        p=FakeProvider('A noisy hall.')
        result=execute_scoped(self.store,'generate',self.request(),provider_factory=lambda:p)
        self.assertEqual(result['status'],'BLOCKED');self.assertNotIn('_candidate',result)
        record=self.drafts.open('spring-break','main',result['draft_id'])
        self.assertEqual(record['text'],'A noisy hall.')
        with self.assertRaisesRegex(ValueError,'completed proposal'):self.drafts.use('spring-break','main',record['id'],1,1)

    def test_changed_mask_blocks_old_draft(self):
        ident=execute_scoped(self.store,'generate',self.request(),provider_factory=FakeProvider)['draft_id']
        state=self.book.open('spring-break');self.book.save('spring-break',1,1,state['blocks'],50,state['masks'])
        with self.assertRaisesRegex(ValueError,'mask revision'):self.drafts.use('spring-break','main',ident,2,1)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_changed_law_blocks_old_draft(self):
        from story_graph.world_laws import WorldLawStore
        ident=execute_scoped(self.store,'generate',self.request(),provider_factory=FakeProvider)['draft_id']
        laws=WorldLawStore(self.store);current=laws.open();laws.save(current['revision'],current['laws'])
        with self.assertRaises(ValueError):self.drafts.use('spring-break','main',ident,1,1)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_changed_graph_blocks_old_draft(self):
        ident=execute_scoped(self.store,'generate',self.request(),provider_factory=FakeProvider)['draft_id']
        self.store.save('spring-break',1,graph={'nodes':[{'id':'x','type':'beat','data':{'beat':1}}],'edges':[]})
        with self.assertRaises(ValueError):self.drafts.use('spring-break','main',ident,1,2)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_book_settings_are_rechecked_on_apply(self):
        books=self.root/'books';books.mkdir()
        policy={'schema_version':1,'sources':{'allowed':{'enabled':True,'permissions':['rank_local','prompt','remote_transfer']}}}
        policy_file=books/'reference_policy.json';policy_file.write_text(json.dumps(policy),encoding='utf-8')
        (books/'vector_index.joblib').write_bytes(b'synthetic')
        text='A small eligible reference passage about light in a room.'
        index=EmbeddingIndex([text],[{'book':'allowed'}],np.ones((1,1),dtype='float32'),_model=SimpleNamespace(encode=lambda texts,**kwargs:np.ones((len(texts),1),dtype='float32')))
        provider=FakeProvider()
        with patch('prose_engine.embedding_store.load_index',return_value=index):
            result=execute_scoped(self.store,'generate',self.request(references='topic'),books_root=books,provider_factory=lambda:provider)
        record=self.drafts.open('spring-break','main',result['draft_id'])
        self.assertNotIn(text,json.dumps(record));self.assertEqual(record['reference_receipts'][0]['source_id'],'allowed')
        policy['sources']['allowed']['enabled']=False;policy_file.write_text(json.dumps(policy),encoding='utf-8')
        with self.assertRaises(ReferenceUnavailable):self.drafts.use('spring-break','main',record['id'],1,1,books_root=books)
        with self.assertRaises(ReferenceUnavailable):execute_scoped(self.store,'apply-draft',self.request(draft=record['id'],notebook_revision=1),books_root=books)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')
        policy['sources']['allowed']['enabled']=True;policy_file.write_text(json.dumps(policy),encoding='utf-8')
        from prose_engine import scoped_references
        check=scoped_references.verify_draft_binding; calls=[]
        def revoke_during_apply(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:
                policy['sources']['allowed']['enabled']=False;policy_file.write_text(json.dumps(policy),encoding='utf-8')
            return check(*args,**kwargs)
        with patch.object(scoped_references,'verify_draft_binding',side_effect=revoke_during_apply):
            with self.assertRaises(ReferenceUnavailable):self.drafts.use('spring-break','main',record['id'],1,1,books_root=books)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')
        policy['sources']['allowed']['enabled']=True;policy_file.write_text(json.dumps(policy),encoding='utf-8')
        used=self.drafts.use('spring-break','main',record['id'],1,1,books_root=books)
        self.assertEqual(joined(used['blocks']),'A quiet hall.')

    def test_versioned_book_binding_recovers_after_relocation(self):
        from prose_engine.scoped_references import draft_binding, verify_draft_binding

        original = self.root / 'books-original'
        relocated = self.root / 'books-relocated'
        published = {name: digest(name) for name in
                     ('policy', 'influence', 'quality', 'index', 'catalog', 'release', 'encoder', 'style_model')}
        binding = draft_binding({'backend': 'style', 'root': original, 'fingerprint': published})
        with patch('prose_engine.scoped_references.fingerprint', return_value=published) as current:
            verify_draft_binding(binding, relocated)
            current.assert_called_once_with(relocated.resolve(), 'style')
            for key in published:
                with self.subTest(changed=key):
                    current.return_value = published | {key: digest('different')}
                    with self.assertRaises(ReferenceUnavailable):
                        verify_draft_binding(binding, relocated)

        legacy = published | {'release': 'missing', 'encoder': 'legacy-unverified'}
        binding = draft_binding({'backend': 'style', 'root': original, 'fingerprint': legacy})
        with patch('prose_engine.scoped_references.fingerprint', return_value=legacy):
            verify_draft_binding(binding, original)
            with self.assertRaises(ReferenceUnavailable):
                verify_draft_binding(binding, relocated)

    def test_saved_book_binding_reports_an_unavailable_local_encoder(self):
        from prose_engine.scoped_references import draft_binding, verify_draft_binding

        books = self.root / 'books'
        binding = draft_binding({'backend': 'luar', 'root': books, 'fingerprint': {'encoder': digest('encoder')}})
        with patch('prose_engine.scoped_references.fingerprint', side_effect=FileNotFoundError('encoder snapshot')):
            with self.assertRaises(ReferenceUnavailable) as error:
                verify_draft_binding(binding, books)
        self.assertEqual(error.exception.state, 'unavailable')

    def test_draft_favorite_toggle_undo_redo_and_http(self):
        first=execute_scoped(self.store,'generate',self.request(),provider_factory=FakeProvider)['draft_id']
        second=execute_scoped(self.store,'generate',self.request(),provider_factory=FakeProvider)['draft_id']

        starred=self.drafts.favorite('spring-break','main',first)
        self.assertTrue(starred['favorite'])
        self.assertTrue(starred['can_undo_favorite'])
        self.assertFalse(starred['can_redo_favorite'])
        self.assertEqual(starred['favorite_revision'],1)

        with self.assertRaisesRegex(ValueError,'changed'):
            self.drafts.favorite('spring-break','main',first,expected_favorite=False)
        with self.assertRaisesRegex(ValueError,'changed'):
            self.drafts.undo_favorite('spring-break','main',expected_revision=0)

        starred_second=self.drafts.favorite('spring-break','main',second,True,expected_revision=1)
        self.assertTrue(starred_second['favorite'])

        undone1=self.drafts.undo_favorite('spring-break','main',expected_revision=2)
        self.assertEqual(undone1['id'],second); self.assertFalse(undone1['favorite'])
        self.assertTrue(undone1['can_undo_favorite'] and undone1['can_redo_favorite'])

        undone2=self.drafts.undo_favorite('spring-break','main')
        self.assertEqual(undone2['id'],first); self.assertFalse(undone2['favorite'])
        with self.assertRaisesRegex(ValueError,'No favorite change to undo'):
            self.drafts.undo_favorite('spring-break','main')

        redone=self.drafts.redo_favorite('spring-break','main')
        self.assertEqual(redone['id'],first); self.assertTrue(redone['favorite'])
        # A new favorite toggle clears the redo stack while keeping episode script intact.
        toggled_off=self.drafts.favorite('spring-break','main',first,expected_favorite=True)
        self.assertFalse(toggled_off['favorite']); self.assertFalse(toggled_off['can_redo_favorite'])
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from tools.studio_ui import StudioRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.path; server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def post(payload):
            req=urllib.request.Request(base+'/api/drafts',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(req) as resp: return json.load(resp)
        try:
            listed=post({'episode':'spring-break','branch':'main','action':'list'})
            self.assertIn('favorite_history',listed)
            fav_res=post({'episode':'spring-break','branch':'main','action':'favorite','draft':first,'value':True,'expected_revision':listed['favorite_history']['favorite_revision']})
            self.assertTrue(fav_res['favorite'])
            undo_res=post({'episode':'spring-break','branch':'main','action':'undo-favorite','expected_revision':fav_res['favorite_history']['favorite_revision']})
            self.assertFalse(undo_res['favorite'])
            redo_res=post({'episode':'spring-break','branch':'main','action':'redo-favorite','expected_revision':undo_res['favorite_history']['favorite_revision']})
            self.assertTrue(redo_res['favorite'])
            with self.assertRaises(urllib.error.HTTPError) as err:
                post({'episode':'spring-break','branch':'main','action':'undo-favorite','expected_revision':0})
            self.assertEqual(err.exception.code,400)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
