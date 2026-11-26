import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from tools.studio_ui import StudioRequestHandler

class TimelineHttpTests(unittest.TestCase):
    def test_episode_import_and_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
            server.timeline_path=Path(tmp)/'timeline.sqlite'
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def post(data,origin=None):
                req=urllib.request.Request(base+'/api/timeline',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':origin or base})
                with urllib.request.urlopen(req) as response: return json.load(response)
            try:
                with urllib.request.urlopen(base+'/timeline') as r: self.assertIn('open this episode in studio',r.read().decode().lower())
                post({'action':'starters'})
                data=post({'action':'open','id':'tapped-out'})['episode']
                post({'action':'save','id':'tapped-out','expected_revision':data['head'],'graph':{'nodes':[{'id':'scene'}],'edges':[]},'script':'INT. KITCHEN','source_name':'scene.fountain'})
                saved=post({'action':'open','id':'tapped-out'})['episode']
                self.assertEqual(saved['script'],'INT. KITCHEN'); self.assertEqual(saved['graph']['nodes'][0]['id'],'scene')
                self.assertEqual(post({'action':'open','id':'spring-break'})['episode']['script'],'')
                with urllib.request.urlopen(base+'/api/state?episode=tapped-out') as r: state=json.load(r)
                self.assertEqual(state['blocks'][0]['text'],'INT. KITCHEN')
                self.assertEqual(state['nodes'][0]['id'],'scene')
                self.assertTrue(state['prerequisites'])
                post({'action':'event','event':'haley-awakening','episode':'hot-scoomp','beat':1,'content':'future awakening'})
                with urllib.request.urlopen(base+'/api/episode-context?episode=tapped-out&beat=2') as r: self.assertEqual(json.load(r)['events'],[])
                with self.assertRaises(urllib.error.HTTPError):
                    post({'action':'review_event','episode':'hot-scoomp','event':'haley-awakening','reviewer':'test','source_id':'fixture','permitted':False})
                post({'action':'review_event','episode':'hot-scoomp','event':'haley-awakening','reviewer':'test','source_id':'fixture','permitted':True})
                with urllib.request.urlopen(base+'/api/episode-context?episode=spring-break&beat=999') as r: self.assertEqual(json.load(r)['events'],[])
                with urllib.request.urlopen(base+'/api/episode-context?episode=tapped-out&beat=0') as r: self.assertEqual(json.load(r)['events'][0]['content'],'future awakening')
                post({'action':'fork','branch':'mini','parent':'main','episode':'hot-scoomp','beat':2})
                post({'action':'create','id':'side','title':'Side story','branch':'mini','position':1})
                self.assertEqual(post({'action':'open','id':'side'})['episode']['branch'],'mini')
                with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(base+'/api/state?episode=missing')
                with self.assertRaises(urllib.error.HTTPError) as e: post({'action':'starters'},'http://evil.invalid')
                self.assertEqual(e.exception.code,403)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_http_undo_redo_events_forms_branches_rejoin_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
            server.timeline_path=Path(tmp)/'timeline.sqlite'
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def post(data):
                req=urllib.request.Request(base+'/api/timeline',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':base})
                with urllib.request.urlopen(req) as response: return json.load(response)
            try:
                post({'action':'starters'})
                post({'action':'fork','branch':'temp-branch','parent':'main','episode':'hot-scoomp','beat':2})
                branches=post({'action':'unfork','branch':'temp-branch'})['branches']
                self.assertNotIn('temp-branch',[b['id'] for b in branches])

                post({'action':'fork','branch':'mini','parent':'main','episode':'hot-scoomp','beat':2})
                post({'action':'create','id':'side','title':'Side','branch':'mini','position':1})
                post({'action':'event','event':'ev-form','episode':'side','beat':1,'content':'Fox shift'})
                post({'action':'bind_form','episode':'side','event':'ev-form','character':'haley','form':'awakened_haley_fox','form_action':'active'})
                unbound=post({'action':'unbind_form','episode':'side','event':'ev-form'})
                self.assertIsNone(unbound['binding'])
                redone=post({'action':'redo_form','episode':'side','event':'ev-form'})
                self.assertEqual(redone['binding']['form_id'],'awakened_haley_fox')
                post({'action':'review_event','episode':'side','event':'ev-form','reviewer':'Author','source_id':'fixture','permitted':True})

                rejoined=post({'action':'rejoin','episode':'side','event':'ev-form','target_episode':'tapped-out','beat':2,'reviewer':'Author','source_id':'fixture','permitted':True})['event']
                unrejoined=post({'action':'unrejoin','target_episode':'tapped-out','event':rejoined})
                self.assertEqual(unrejoined['events'],[])
                restored_id=post({'action':'rejoin','episode':'side','event':'ev-form','target_episode':'tapped-out','beat':2,'reviewer':'Author','source_id':'fixture','permitted':True,'rejoined_event':rejoined})['event']
                self.assertEqual(restored_id,rejoined)
                post({'action':'unrejoin','target_episode':'tapped-out','event':rejoined})

                post({'action':'unreview_event','episode':'side','event':'ev-form','reviewer':'Author'})
                self.assertEqual(post({'action':'unadd_event','episode':'side','event':'ev-form'})['events'],[])
                restored=post({'action':'restore_event','episode':'side','event':'ev-form'})['events']
                self.assertEqual([e['id'] for e in restored],['ev-form'])

                post({'action':'event','event':'haley-awakening','episode':'hot-scoomp','beat':1,'content':'Awaken'})
                post({'action':'review_event','episode':'hot-scoomp','event':'haley-awakening','reviewer':'Author','source_id':'fixture','permitted':True})
                post({'action':'finish','id':'tapped-out','expected_revision':0,'reviewer':'Author'})
                with self.assertRaises(urllib.error.HTTPError):
                    post({'action':'reopen','id':'tapped-out','expected_revision':99})
                reopened=post({'action':'reopen','id':'tapped-out','expected_revision':0})
                self.assertEqual(reopened['episode']['status'],'draft')
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_http_sqlite_history_survives_server_restart_and_syncs_cover_and_favorite(self):
        import base64
        from prose_engine.notebook import NotebookStore
        from prose_engine.scoped_service import execute_scoped
        from story_graph.episode_timeline import TimelineStore

        cover1 = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\ncover1').decode()
        class FakeProvider:
            def generate_rewrite(self, request, prompt):
                return 'A quiet hall.'

        def start_server(db_path):
            srv = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            srv.timeline_path = db_path
            thr = threading.Thread(target=srv.serve_forever, daemon=True)
            thr.start()
            return srv, thr, f'http://127.0.0.1:{srv.server_port}'

        def post_json(base, path, payload):
            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'Origin': base},
            )
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)

        def get_json(base, path):
            with urllib.request.urlopen(base + path) as resp:
                return json.load(resp)

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'timeline.sqlite'
            srv1, thr1, base1 = start_server(db)
            try:
                post_json(base1, '/api/timeline', {'action': 'starters'})
                post_json(base1, '/api/timeline', {
                    'action': 'save', 'id': 'spring-break', 'expected_revision': 0,
                    'graph': {'nodes': [], 'edges': []}, 'script': 'A quiet room.', 'source_name': 'spring-break.fountain',
                })
                store = TimelineStore(db)
                book = NotebookStore(store)
                book.open('spring-break')
                draft_id = execute_scoped(
                    store, 'generate',
                    {'episode': 'spring-break', 'beat': 1, 'revision': 1, 'start': 0, 'end': 13, 'provider': 'codex-session'},
                    provider_factory=FakeProvider,
                )['draft_id']

                post_json(base1, '/api/timeline', {'action': 'fork', 'branch': 'mini', 'parent': 'main', 'episode': 'hot-scoomp', 'beat': 2})
                post_json(base1, '/api/timeline', {'action': 'create', 'id': 'side-ep', 'title': 'Side', 'branch': 'mini', 'position': 1})
                post_json(base1, '/api/timeline', {'action': 'event', 'event': 'ev-side', 'episode': 'side-ep', 'beat': 1, 'content': 'Side awakening'})
                post_json(base1, '/api/timeline', {'action': 'review_event', 'episode': 'side-ep', 'event': 'ev-side', 'reviewer': 'Author', 'source_id': 'fixture', 'permitted': True})
                rejoined_id = post_json(base1, '/api/timeline', {
                    'action': 'rejoin', 'episode': 'side-ep', 'event': 'ev-side',
                    'target_episode': 'tapped-out', 'beat': 2, 'reviewer': 'Author', 'source_id': 'fixture', 'permitted': True,
                })['event']

                cov_res = post_json(base1, '/api/timeline', {
                    'action': 'set_cover', 'id': 'spring-break', 'expected_revision': 1, 'expected_cover': None, 'cover': cover1,
                })
                self.assertEqual(cov_res['history']['next_undo_kind'], 'cover')

                fav_res = post_json(base1, '/api/drafts', {
                    'episode': 'spring-break', 'branch': 'main', 'action': 'favorite', 'draft': draft_id, 'value': True,
                })
                self.assertTrue(fav_res['favorite'])
                self.assertEqual(fav_res['timeline_history']['next_undo_kind'], 'draft_favorite')

                arch_res = post_json(base1, '/api/timeline', {'action': 'archive', 'id': 'side-ep', 'expected_revision': 0})
                self.assertEqual(arch_res['history']['next_undo_kind'], 'remove')
                self.assertEqual(get_json(base1, '/api/episode-context?episode=tapped-out&beat=2')['events'], [])

                # Granular cover undo synchronizes into SQLite timeline_action_history redo_stack.
                uc = post_json(base1, '/api/timeline', {'action': 'undo_cover', 'id': 'spring-break'})
                self.assertIsNone(uc['episode']['cover'])
                self.assertEqual(uc['history']['next_redo_kind'], 'cover')
            finally:
                srv1.shutdown(); srv1.server_close(); thr1.join()

            # Restart HTTP server on the same SQLite DB: history survives restart.
            srv2, thr2, base2 = start_server(db)
            try:
                initial = get_json(base2, '/api/timeline')
                hist = initial['history']
                self.assertTrue(hist['can_undo'])
                self.assertTrue(hist['can_redo'])
                self.assertEqual(hist['next_undo_kind'], 'remove')
                self.assertEqual(hist['next_redo_kind'], 'cover')

                with self.assertRaises(urllib.error.HTTPError) as stale:
                    post_json(base2, '/api/timeline', {'action': 'undo_history', 'expected_revision': hist['revision'] + 10})
                self.assertEqual(stale.exception.code, 400)

                # Redo cover globally via /api/timeline -> restores cover and syncs cover history.
                rc_global = post_json(base2, '/api/timeline', {'action': 'redo_history', 'expected_revision': hist['revision']})
                self.assertEqual(rc_global['kind'], 'cover')
                spring_card = next(c for c in rc_global['cards'] if c['id'] == 'spring-break')
                self.assertEqual(spring_card['cover'], cover1)

                # Undo cover globally, then undo archiving side-ep -> restores side-ep and rejoined event.
                u_cov = post_json(base2, '/api/timeline', {'action': 'undo_history', 'expected_revision': rc_global['history']['revision']})
                self.assertEqual(u_cov['kind'], 'cover')
                self.assertIsNone(next(c for c in u_cov['cards'] if c['id'] == 'spring-break')['cover'])

                u_rem = post_json(base2, '/api/timeline', {'action': 'undo_history', 'expected_revision': u_cov['history']['revision']})
                self.assertEqual(u_rem['kind'], 'remove')
                self.assertIn('side-ep', [c['id'] for c in u_rem['cards']])
                self.assertIn('mini', [b['id'] for b in u_rem['branches']])
                ctx_events = get_json(base2, '/api/episode-context?episode=tapped-out&beat=2')['events']
                self.assertEqual([ev['id'] for ev in ctx_events], [rejoined_id])

                # Undo draft_favorite globally, verify DraftStore reflects it, then redo via granular /api/drafts.
                u_fav = post_json(base2, '/api/timeline', {'action': 'undo_history', 'expected_revision': u_rem['history']['revision']})
                self.assertEqual(u_fav['kind'], 'draft_favorite')
                listed = post_json(base2, '/api/drafts', {'episode': 'spring-break', 'branch': 'main', 'action': 'list'})
                self.assertFalse(listed['drafts'][0]['favorite'])
                self.assertTrue(listed['favorite_history']['can_redo_favorite'])

                r_fav = post_json(base2, '/api/drafts', {'episode': 'spring-break', 'branch': 'main', 'action': 'redo-favorite'})
                self.assertTrue(r_fav['favorite'])
                self.assertEqual(r_fav['timeline_history']['next_undo_kind'], 'draft_favorite')

                # Global undo now undoes the granularly redone draft_favorite; granular redo_cover syncs back to undo_stack.
                u_fav2 = post_json(base2, '/api/timeline', {'action': 'undo_history', 'expected_revision': r_fav['timeline_history']['revision']})
                self.assertEqual(u_fav2['kind'], 'draft_favorite')
                self.assertFalse(post_json(base2, '/api/drafts', {'episode': 'spring-break', 'branch': 'main', 'action': 'list'})['drafts'][0]['favorite'])

                r_cov_gran = post_json(base2, '/api/timeline', {'action': 'redo_cover', 'id': 'spring-break'})
                self.assertEqual(r_cov_gran['episode']['cover'], cover1)
                self.assertEqual(r_cov_gran['history']['next_undo_kind'], 'cover')
            finally:
                srv2.shutdown(); srv2.server_close(); thr2.join()

