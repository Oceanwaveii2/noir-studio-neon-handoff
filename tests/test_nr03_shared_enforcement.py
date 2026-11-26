import io
import json
from contextlib import redirect_stdout
from dataclasses import replace
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.world_laws import WorldLawStore
from prose_engine import cli as prose_cli
from prose_engine.scoped_service import execute_scoped
from prose_engine.notebook import DraftStore, NotebookStore
from tools.studio_ui import StudioRequestHandler
from tools import workbench


class Provider:
    def __init__(self,text): self.text=text;self.calls=0;self.prompts=[]
    def generate_rewrite(self,request,prompt):
        self.calls+=1;self.prompts.append(prompt);return self.text


class SharedEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'timeline.sqlite'
        self.store=TimelineStore(self.path,project_id='project',universe_id='universe');self.store.add_starter_cards()
        self.store.save('spring-break',0,script='A quiet room.',source_name='fixture')
        self.store.add_event('future','tapped-out',1,'Future glitter secret.',status='approved',permitted=True,reviewer='fixture',source_id='fixture')
        self.req={'episode':'spring-break','branch':'main','project':'project','universe':'universe',
                  'beat':1,'revision':1,'start':0,'end':13,'provider':'codex-session'}

    def test_one_service_enforces_law_and_no_calls_for_read_actions(self):
        p=Provider("Haley's father arrived.")
        for action in ('context','export','retrieve','validate'):
            result=execute_scoped(self.store,action,self.req,provider_factory=lambda:p)
            self.assertNotIn('Future glitter secret',json.dumps(result))
        self.assertEqual(p.calls,0)
        for action in ('generate','condition','variant'):
            result=execute_scoped(self.store,action,self.req,provider_factory=lambda:p)
            self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(p.calls,3)
        self.assertTrue(all('Haley' in prompt and 'Future glitter secret' not in prompt for prompt in p.prompts))

    def test_wrong_stale_and_changed_scope_fail_without_unsafe_output(self):
        p=Provider('A quiet room.')
        for changes in ({'universe':'other'},{'branch':'missing'},{'law_revision':99},{'revision':0}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                execute_scoped(self.store,'generate',{**self.req,**changes},provider_factory=lambda:p)
        self.assertEqual(p.calls,0)
        store=self.store
        with patch('prose_engine.scoped_pipeline.validate_output',None):
            with self.assertRaisesRegex(ValueError,'validators are unavailable'):
                execute_scoped(self.store,'generate',self.req,provider_factory=lambda:p)
        self.assertEqual(p.calls,0)
        class Changing:
            def generate_rewrite(inner,request,prompt):
                laws=WorldLawStore(store);current=laws.open();laws.save(current['revision'],current['laws'])
                return 'A quiet room.'
        with self.assertRaisesRegex(ValueError,'changed during'):
            execute_scoped(store,'generate',self.req,provider_factory=Changing)
        self.assertEqual(DraftStore(NotebookStore(store)).list('spring-break','main')[-1]['status'],'STALE')

    def test_http_cli_and_service_share_context_and_validation(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=self.path;server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            request=urllib.request.Request(base+'/api/scoped',data=json.dumps({**self.req,'action':'export'}).encode(),
                    headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(request) as response: http=json.load(response)
            local=execute_scoped(self.store,'export',self.req)
            command=[sys.executable,'-B','-m','prose_engine','scoped','export','--timeline',str(self.path),
                     '--project','project','--universe','universe','--episode','spring-break','--branch','main',
                     '--beat','1','--revision','1','--start','0','--end','13']
            run=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)
            cli=json.loads(run.stdout)
            self.assertEqual(http['scope'],local['scope']);self.assertEqual(cli['scope'],local['scope'])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_workbench_timeline_opens_the_scoped_studio(self):
        with patch.object(sys,'argv',['workbench','--timeline',str(self.path),'--episode','spring-break']), \
             patch('tools.studio_ui.run_server') as server:
            self.assertEqual(workbench.main(),0)
            self.assertEqual(server.call_args.kwargs['timeline_path'],str(self.path))
            self.assertTrue(server.call_args.kwargs['timeline_only'])
        self.assertIn('episode timeline and universe laws are not connected',workbench.PAGE)

    def test_apply_draft_uses_current_scope_and_revision(self):
        book=NotebookStore(self.store);state=book.open('spring-break')
        book.save('spring-break',state['revision'],1,state['blocks'],25,[])
        candidate=Provider('A dim room.')
        result=execute_scoped(self.store,'generate',self.req,provider_factory=lambda:candidate)
        self.assertEqual(result['status'],'PROPOSED')
        apply={**self.req,'draft':result['draft_id'],'notebook_revision':1}
        with self.assertRaisesRegex(ValueError,'scope'):
            execute_scoped(self.store,'apply-draft',{**apply,'beat':2})
        applied=execute_scoped(self.store,'apply-draft',apply)
        self.assertEqual(applied['status'],'APPLIED')
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A dim room.')
        self.assertEqual(candidate.calls,1)

    def test_form_changes_invalidate_a_draft_before_apply(self):
        from story_graph.character_forms import AFM_JUNCTIONS, CharacterJunction, FormLink
        book=NotebookStore(self.store);state=book.open('spring-break')
        book.save('spring-break',state['revision'],1,state['blocks'],25,[])
        forms=dict(AFM_JUNCTIONS)
        result=execute_scoped(self.store,'generate',self.req,junctions=lambda:forms,
                              provider_factory=lambda:Provider('A dim room.'))
        group=forms['francine']
        forms['francine']=CharacterJunction(group.id,(replace(group.forms[0],link=FormLink('digital_mind','new-mind')),*group.forms[1:]))
        with self.assertRaisesRegex(ValueError,'scope'):
            execute_scoped(self.store,'apply-draft',{**self.req,'draft':result['draft_id'],'notebook_revision':1},junctions=lambda:forms)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_direct_reference_routes_fail_before_model_if_policy_unavailable(self):
        from prose_engine.reference_service import RetrievalSetup
        from tools import finish_scene, variations_demo, eval_best_of_n
        unavailable=RetrievalSetup('unconfigured','fixture policy unavailable')
        cases=[(finish_scene,['finish','--allow-book-references']),
               (variations_demo,['variations']),
               (eval_best_of_n,['eval','--references','1','--allow-book-references'])]
        for module,argv in cases:
            with self.subTest(module=module.__name__), patch.object(sys,'argv',argv), \
                 patch('prose_engine.reference_service.prepare_retrieval',return_value=unavailable), \
                 patch.object(module,'create_prose_provider') as provider:
                self.assertEqual(module.main(),1);provider.assert_not_called()

    def test_cli_form_store_shares_custom_junctions_and_node_data_with_http_and_service(self):
        forms_path=self.path.parent/'character-forms.sqlite'
        form_store=FormGraphStore(forms_path)
        g0=form_store.change({'action':'save_node_data','revision':0,'character':'francine','node':'character:francine:form:francine',
                              'content':{'text_fields':{'voice':'Shared Francine cadence.'}}})
        custom_path=self.path.parent/'custom-forms.sqlite'
        custom_store=FormGraphStore(custom_path)
        custom_store.change({'action':'save_node_data','revision':0,'character':'francine','node':'character:francine:form:francine',
                             'content':{'text_fields':{'voice':'Explicit custom Francine cadence.'}}})
        self.assertGreater(g0['revision'],0)
        svc=execute_scoped(self.store,'context',self.req,junctions=form_store.junctions)
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.path;server.timeline_only=True;server.form_graph=form_store
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            req=urllib.request.Request(base+'/api/scoped',
                                       data=json.dumps({'action':'context',**self.req}).encode('utf-8'),
                                       headers={'Content-Type':'application/json','Origin':base})
            with urllib.request.urlopen(req,timeout=5) as response:
                http_res=json.load(response)
        finally:
            server.shutdown();server.server_close();thread.join()
        sibling_buf=io.StringIO()
        with redirect_stdout(sibling_buf):
            code=prose_cli.main(['scoped','context','--timeline',str(self.path),'--project','project','--universe','universe',
                                 '--branch','main','--episode','spring-break','--beat','1','--revision','1','--start','0','--end','13'])
        self.assertEqual(code,0)
        cli_sibling=json.loads(sibling_buf.getvalue())
        self.assertEqual(cli_sibling['scope'],svc['scope'])
        self.assertEqual(http_res['scope'],svc['scope'])
        self.assertIn('Shared Francine cadence.',json.dumps(cli_sibling['scope']['characters']['francine']))
        self.assertIn('Shared Francine cadence.',json.dumps(http_res['scope']['characters']['francine']))
        explicit_buf=io.StringIO()
        with redirect_stdout(explicit_buf):
            code=prose_cli.main(['scoped','context','--timeline',str(self.path),'--project','project','--universe','universe',
                                 '--branch','main','--episode','spring-break','--beat','1','--revision','1','--start','0','--end','13',
                                 '--form-store',str(custom_path)])
        self.assertEqual(code,0)
        cli_explicit=json.loads(explicit_buf.getvalue())
        svc_custom=execute_scoped(self.store,'context',self.req,junctions=custom_store.junctions)
        self.assertEqual(cli_explicit['scope'],svc_custom['scope'])
        self.assertIn('Explicit custom Francine cadence.',json.dumps(cli_explicit['scope']['characters']['francine']))


class Step3FencingAndStandaloneEnforcementTests(unittest.TestCase):
    def test_eval_best_of_n_has_no_direct_luar_index_load(self):
        import ast
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / 'tools' / 'eval_best_of_n.py'
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == 'LuarIndex':
                self.fail('tools/eval_best_of_n.py must not reference LuarIndex directly')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'load':
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'LuarIndex':
                    self.fail('tools/eval_best_of_n.py must not call LuarIndex.load directly')

    def test_load_luar_scorer_gates_on_rank_local_policy(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from prose_engine.reference_service import RetrievalSetup
        from tools.eval_best_of_n import load_luar_scorer

        with patch('prose_engine.reference_service.prepare_retrieval', return_value=RetrievalSetup('disabled', 'Policy disabled for test')):
            with self.assertRaisesRegex(ValueError, 'Policy disabled'):
                load_luar_scorer('books')

        fake_index = object()
        ready = RetrievalSetup('ready', 'ok', drive=SimpleNamespace(index=fake_index))
        with patch('prose_engine.reference_service.prepare_retrieval', return_value=ready) as prep, \
             patch('prose_engine.voice.luar.LuarEncoder', return_value=object()):
            scorer = load_luar_scorer('custom-books')
        prep.assert_called_once_with('custom-books', 'luar', 'local', purposes=('rank_local',))
        self.assertIs(scorer.index, fake_index)

    def test_enforce_standalone_world_laws_and_voice_world_cli_timeline(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        from prose_engine.cli import main as cli_main
        from prose_engine.scoped_service import enforce_standalone_world_laws
        from story_graph.episode_timeline import TimelineStore
        from story_graph.world_laws import WorldLawStore

        unscoped = enforce_standalone_world_laws('The crimson key lay on the desk.')
        self.assertFalse(unscoped['enforced'])
        self.assertTrue(unscoped['passed'])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / 'timeline.sqlite'
            store = TimelineStore(db_path)
            laws = WorldLawStore(store)
            opened = laws.open()
            laws.save(opened['revision'], opened['laws'] + [{
                'id': 'no-crimson-key',
                'name': 'No crimson key',
                'statement': 'Avoid crimson key mentions.',
                'enabled': True,
                'matcher': 'literal',
                'phrases': ['crimson key'],
            }])

            scoped = enforce_standalone_world_laws('The crimson key lay on the desk.', timeline_path=db_path)
            self.assertTrue(scoped['enforced'])
            self.assertFalse(scoped['passed'])
            self.assertTrue(any('no-crimson-key' in item for item in scoped['violations']))

            script_path = root / 'scene.txt'
            script_path.write_text('The crimson key lay on the desk.\n', encoding='utf-8')
            buf_unscoped = io.StringIO()
            with contextlib.redirect_stdout(buf_unscoped):
                rc_unscoped = cli_main(['voice', 'world', '--file', str(script_path), '--world-file', 'books/world_state.json'])
            self.assertEqual(rc_unscoped, 0)

            buf_scoped = io.StringIO()
            with contextlib.redirect_stdout(buf_scoped):
                rc_scoped = cli_main([
                    'voice', 'world', '--file', str(script_path),
                    '--world-file', 'books/world_state.json',
                    '--timeline', str(db_path),
                ])
            self.assertEqual(rc_scoped, 1)
            self.assertIn('no-crimson-key', buf_scoped.getvalue())
            self.assertIn('universe world-law violations: 1', buf_scoped.getvalue())


if __name__=='__main__': unittest.main()
