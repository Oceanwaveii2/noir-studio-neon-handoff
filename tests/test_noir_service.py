"""Loopback service, offline writers, shared budgets, and cache invalidation."""
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine.notebook import NotebookStore
from prose_engine.providers.deepseek import BudgetExceeded
from prose_engine.providers.session_attempts import SessionAttemptError
from prose_engine.providers.session_registry import WriterWindow, registered
from prose_engine.reference_service import ReferenceReaders, RetrievalSetup
from prose_engine.service_daemon import NoirService, ServiceHTTP, open_ticket, workspace_key, write_ticket
from story_graph.episode_timeline import TimelineStore
from tools.noir_client import NoirClient, ServiceError


class SessionWindowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.file = self.root/'usage.jsonl'
        self.calls = []

    def fake(self, name):
        return lambda prompt: self.calls.append((name, prompt)) or 'Simple result.'

    def test_prompts_and_attempts_cannot_exceed_the_shared_window_on_restart(self):
        allowed = ['codex-session','gemini-session']
        request = SimpleNamespace()
        window = WriterWindow(self.file, 'one', allowed, 1, 16, attach=self.fake)
        with self.assertRaisesRegex(SessionAttemptError,'byte limit'):
            window.connect('codex-session','first').generate_rewrite(request,'💡'*5)
        self.assertEqual(window.status()['used'], 0)
        window.connect('gemini-session','first').generate_rewrite(request,'checked')
        restarted = WriterWindow(self.file, 'one', allowed, 1, 16, attach=self.fake)
        with self.assertRaises(BudgetExceeded):
            restarted.connect('codex-session','another').generate_rewrite(request,'blocked')
        self.assertEqual(self.calls,[('gemini-session','checked')])
        self.assertEqual(restarted.status()['used'], 1)
        with self.assertRaisesRegex(ValueError,'different budget'):
            WriterWindow(self.file, 'one', allowed, 2, 16, attach=self.fake)

    def test_unknown_send_does_not_fallback_or_replay(self):
        def unattested(prompt):
            self.calls.append(prompt)
            raise TimeoutError('No answer')
        allowed = ['codex-session','gemini-session']
        a = WriterWindow(self.file, 'unknown', allowed, 2, 100, attach=lambda _: unattested)
        with self.assertRaises(SessionAttemptError) as first:
            a.connect('codex-session','episode').generate_rewrite(SimpleNamespace(),'first')
        b = WriterWindow(self.file, 'unknown', allowed, 2, 100, attach=self.fake)
        with self.assertRaises(SessionAttemptError) as second:
            b.connect('gemini-session','different-episode').generate_rewrite(SimpleNamespace(),'second')
        self.assertEqual(first.exception.attempt_id, second.exception.attempt_id)
        self.assertEqual(b.status()['uncertain'], 1)
        self.assertEqual(self.calls, ['first'])

    def test_named_and_custom_hosts_use_one_fixed_offline_command(self):
        prog = self.root/'fixture.py'
        prog.write_text('import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read() + b" done\\r\\n")\n',
                        encoding='utf-8')
        config = self.root/'writers.json'
        names = ['deepseek-session', 'claude-session', 'grok-session', 'my-writer-session']
        config.write_text(json.dumps({'schema_version':1,'writers':{n:{'argv':[sys.executable,str(prog)]} for n in names}}))
        window = WriterWindow(self.file,'registry',names,4,800,config=config)
        for name in names:
            prompt = 'one\npass 🗝'
            output = window.connect(name,'fixture').generate_rewrite(SimpleNamespace(protected_spans=[True]),prompt)
            self.assertEqual(output,prompt+' done\r\n')
        self.assertEqual(window.status()['used'],4)
        config.write_text(json.dumps({'schema_version':1,'writers':{'codex-session':{'argv':[sys.executable]}}}))
        with self.assertRaisesRegex(ValueError,'reserved'):
            registered(config)


class SharedHttpTests(unittest.TestCase):
    def test_offline_gemini_run_is_saved_and_unauthorized_requests_never_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = TimelineStore(root/'story.sqlite')
            timeline.create_episode('fixture','Fixture','main',1)
            script = 'The lock rattled.'
            timeline.save('fixture',0,script=script,source_name='fixture.txt')
            notebook = NotebookStore(timeline)
            head = notebook.open('fixture')
            notebook.save('fixture',head['revision'],1,head['blocks'],25,[])
            calls = []
            def connect(name):
                self.assertEqual(name,'gemini-session')
                return lambda prompt: calls.append(prompt) or 'The lock rattled twice.'
            path = root/'ticket.json'
            with patch.dict('os.environ', {'NOIR_SESSION_REGISTRY': ''}):
                writer = WriterWindow(path.with_suffix('.usage.jsonl'),'gemini-fixture',['gemini-session'],1,28_000,attach=connect)
                service = NoirService(timeline,root,writer)
                with ServiceHTTP(0,service,'test-'+'a'*40) as http:
                    ticket=open_ticket(path,http.server_port,workspace_key(timeline))
                    ticket['token'] = http.token
                    write_ticket(path,ticket)
                    client=NoirClient(path)
                    thread=threading.Thread(target=http.serve_forever,daemon=True)
                    thread.start()
                    try:
                        url = ticket['url']
                        with self.assertRaises(HTTPError) as no_ticket:
                            urlopen(url+'/v1/status',timeout=3)
                        self.assertEqual(no_ticket.exception.code,403)
                        cookies={'Authorization':'Bearer '+ticket['token'],'Origin':'https://example.org'}
                        with self.assertRaises(HTTPError) as browser:
                            urlopen(Request(url+'/v1/status',headers=cookies),timeout=3)
                        self.assertEqual(browser.exception.code,403)
                        with self.assertRaisesRegex(ServiceError,'Unknown scoped'):
                            client.scope('generate')
                        val=client.request('/v1/open',{'episode':'fixture'})
                        m=val['map']
                        req={'episode':'fixture','branch':'main','revision':1,'project':m['project_id'],
                             'universe':m['universe_id'],'source_sha256':m['source_sha256'],
                             'anchor_token':m['anchor_token'],'notebook_revision':val['notebook']['revision'],
                             'beats':[m['beats'][0]['id']],'request_id':'offline-gemini','provider':'gemini-session',
                             'max_attempts':1,'max_input_bytes':28_000,'max_output_chars':40}
                        with self.assertRaisesRegex(ServiceError,'not enabled'):
                            client.command('run.start',**{**req,'provider':'codex-session'})
                        with self.assertRaisesRegex(ServiceError,'max_attempts'):
                            client.command('run.start',**{**req,'max_attempts':2})
                        self.assertEqual(calls,[])
                        client.command('run.start',**req)
                        for _ in range(70):
                            run=client.command('run.status',episode='fixture',request_id='offline-gemini')
                            if run['status'] not in ('QUEUED','RUNNING'):
                                break
                            time.sleep(.05)
                        self.assertEqual(run['status'],'COMPLETED',run)
                        self.assertEqual(client.command('run.start',**req),run)
                        draft=client.command('draft.open',episode='fixture',branch='main',draft=run['draft_id'])
                        self.assertIn('rattled twice',draft['text'])
                        self.assertEqual(len(calls),1)
                        self.assertEqual(timeline.get_episode('fixture')['script'],script)
                    finally:
                        http.shutdown()
                        thread.join(timeout=3)
                        service.close()

    def test_lost_ledger_and_mismatched_workspace_cannot_reuse_ticket(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ticket.json'
            ticket=open_ticket(path,8790,'workspace')
            write_ticket(path,ticket)
            with self.assertRaisesRegex(ValueError,'different service'):
                open_ticket(path,8790,'other workspace')
            with self.assertRaisesRegex(ValueError,'ledger is missing'):
                open_ticket(path,8790,'workspace')


class ReaderPoolTests(unittest.TestCase):
    def test_reuses_verified_inputs_and_replaces_changed_policy(self):
        pool=ReferenceReaders()
        def load(): return RetrievalSetup('ready','test')
        first=('local-not-a-real-index','style','corpus',('remote_transfer',),(('policy','first'),))
        a=pool.read(first,load)
        self.assertIs(pool.read(first,load),a)
        b=pool.read((*first[:-1],(('policy','changed'),)),load)
        self.assertIsNot(a,b)
        self.assertEqual(pool.metrics(),{'loaded':{'style':2},'hits':{'style':1},'resident':1})
