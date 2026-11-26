"""The director, run journal, shared edit receipts and exact protections."""
import tempfile
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import DraftStore, NotebookStore, digest, joined
from prose_engine.providers.deepseek_session import DeepSeekSessionProvider
from prose_engine.scoped_service import execute_scoped
from prose_engine.writing_runs import WritingRuns, _draft_id
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore


class Writer:
    def __init__(self):
        self.calls=[]

    def generate_rewrite(self, request, prompt):
        self.calls.append((request,prompt))
        return request.original_text+' Then she waited.'


class EpisodeWritingRunTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'timeline.sqlite'
        self.timeline=TimelineStore(self.path)
        self.timeline.create_episode('episode','Episode','main',1)
        self.text='## ACT I\r\n\r\n## SCENE 1\r\n\r\nThe key stayed. 🗝\r\n\r\nThe lock rattled.\r\n\r\nShe listened.\r\n\r\nA door clicked.'
        self.timeline.save('episode',0,script=self.text,source_name='test.txt')
        self.notebook=NotebookStore(self.timeline)
        before=self.notebook.open('episode')
        self.mapping=map_episode(self.timeline,'episode',1)
        beats=[p for p in self.mapping['beats'] if p['text']!='## ACT I']
        masks=[dict(id=str(i),start=b['start'],end=b['end'],value=value,hard=value==100,sha256=digest(b['text']))
               for i,(b,value) in enumerate(zip(beats,(100,25,50,75)))]
        saved=self.notebook.save('episode',before['revision'],1,before['blocks'],100,masks)
        self.request={'episode':'episode','branch':'main','revision':1,'project':self.mapping['project_id'],
                      'universe':self.mapping['universe_id'],'source_sha256':self.mapping['source_sha256'],
                      'anchor_token':self.mapping['anchor_token'],'beats':[b['id'] for b in beats],
                      'notebook_revision':saved['revision'],'max_attempts':3,
                      'direction':'Linger on the setup, then land the joke faster.','request_id':'fixture-run'}
        self.writer=Writer()
        self.commands=EpisodeCommands(self.timeline,provider_factory=lambda:self.writer)

    def test_direction_keeps_boundaries_and_different_weights(self):
        outline=self.commands.execute('director.open',self.request)
        self.assertIn('ACT I',outline['acts'][-1]['title'])
        base=self.commands.execute('director.preview',dict(self.request,direction=''))
        preview=self.commands.execute('director.preview',self.request)
        self.assertNotEqual(base['director']['id'],preview['director']['id'])
        self.assertEqual([p['cutoff'] for p in base['parts']],[p['cutoff'] for p in preview['parts']])
        self.assertEqual([p['locked'] for p in preview['parts']],[True,False,False,False])
        self.assertEqual(preview['planned_attempts'],3)
        self.assertEqual([x['controls']['pace'] for x in preview['director']['choices']],['slow','slow','fast','fast'])
        self.assertEqual(preview['director']['choices'][-1]['controls']['comedy'],'payoff')
        self.assertFalse(self.writer.calls)

        result=self.commands.execute('run.start',{**self.request,'plan_id':preview['director']['id']})
        self.assertEqual(result['status'],'COMPLETED',result)
        self.assertEqual(len(self.writer.calls),3)
        self.assertNotIn(self.writer.calls[-1][0].original_text,self.writer.calls[0][1])
        opened=self.commands.execute('draft.open',{'episode':'episode','branch':'main','draft':result['draft_id']})
        self.assertEqual(opened['origin'],'generated')
        receipts = result['generation_receipt']['writer_receipts']
        self.assertEqual(len(receipts), 3)
        self.assertEqual(receipts, opened['writer_receipts'])
        for receipt in receipts:
            child = DraftStore(self.notebook).open('episode', 'main', receipt['draft_id'])
            self.assertEqual(receipt['response_sha256'], digest(child['text']))
        self.assertIn('The key stayed. 🗝\r\n\r\n',opened['text'])
        self.assertEqual(opened['writing_run']['director']['id'],preview['director']['id'])
        self.assertEqual(self.timeline.get_episode('episode')['script'],self.text)

    def test_reopen_writer_and_apply_then_replay_after_undo_and_redo(self):
        queued=self.commands.execute('run.start',{**self.request,'defer':True})
        self.assertEqual(queued['status'],'QUEUED')
        reopened=EpisodeCommands(TimelineStore(self.path),provider_factory=lambda:self.writer)
        status=reopened.execute('run.resume',self.request)
        self.assertEqual(status['status'],'COMPLETED',status)
        self.assertEqual(reopened.execute('run.start',self.request)['draft_id'],status['draft_id'])
        self.assertEqual(len(self.writer.calls),3)
        with self.assertRaisesRegex(ValueError,'different writing run'):
            reopened.execute('run.start',dict(self.request,direction='Change'))

        req={'episode':'episode','branch':'main','draft':status['draft_id'],
             'notebook_revision':self.request['notebook_revision'],'timeline_revision':1,'request_id':'apply-this'}
        first=reopened.execute('draft.apply',req)
        self.assertEqual(first['status'],'APPLIED')
        self.assertTrue(first['notebook']['can_undo'])
        n=first['notebook']
        undo_req={'episode':'episode','notebook_revision':n['revision'],'timeline_revision':n['timeline_revision']}
        undone=reopened.execute('notebook.undo',undo_req)
        self.assertEqual(joined(undone['notebook']['blocks']),self.text)
        replay=reopened.execute('draft.apply',req)
        self.assertEqual(replay['receipt'],first['receipt'])
        self.assertEqual(replay['notebook'],undone['notebook'])
        self.assertEqual(replay['status'],'REPLAYED')
        n=undone['notebook']
        redone=reopened.execute('notebook.redo',{'episode':'episode','notebook_revision':n['revision'],
                                               'timeline_revision':n['timeline_revision']})
        self.assertEqual(joined(redone['notebook']['blocks']),joined(first['notebook']['blocks']))
        self.assertEqual(reopened.execute('notebook.undo',undo_req)['status'],'REPLAYED')
        self.assertEqual(reopened.execute('notebook.undo',undo_req)['notebook'],redone['notebook'])
        with self.assertRaisesRegex(ValueError,'different edit'):
            reopened.execute('draft.apply',{**req,'source_start':0})

    def test_interruptions_do_not_resend_and_cancel_during_call(self):
        entered,release=threading.Event(),threading.Event()
        self.addCleanup(release.set)
        writer=self.writer
        class Paused:
            def generate_rewrite(self,request,prompt):
                entered.set()
                if not release.wait(6):
                    raise RuntimeError('Test did not release the writer')
                return writer.generate_rewrite(request,prompt)
        runs=WritingRuns(self.timeline,provider_factory=Paused)
        runs.start(self.request)
        output=[]
        thread=threading.Thread(target=lambda:output.append(runs.run('fixture-run','episode')),daemon=True)
        thread.start()
        self.assertTrue(entered.wait(5))
        self.assertEqual(runs.run('fixture-run','episode')['status'],'RUNNING')
        req = {k:self.request[k] for k in ('project','universe','episode','branch')}
        active, = self.commands.execute('processing.open',req)['jobs']
        self.assertEqual(active['status'],'RUNNING')
        self.assertEqual([step['id'] for step in active['steps'] if step['status']=='RUNNING'],['write-2'])
        self.assertEqual(active['run_id'],'fixture-run')
        self.assertTrue(runs.cancel('fixture-run','episode')['cancel_requested'])
        release.set()
        thread.join(8)
        self.assertEqual(output[0]['status'],'CANCELLED')
        self.assertEqual(runs.run('fixture-run','episode')['completed'],2)
        self.assertEqual(len(writer.calls),1)
        self.assertEqual(self.timeline.get_episode('episode')['script'],self.text)
        stopped, = self.commands.execute('processing.open',req|{'job':active['id']})['jobs']
        self.assertEqual(stopped['status'],'CANCELLED')
        self.assertFalse([step for step in stopped['steps'] if step['status']=='RUNNING'])

    def test_expired_dispatch_with_unknown_result_is_never_repeated(self):
        class Interrupted:
            def generate_rewrite(self,request,prompt):
                raise KeyboardInterrupt()
        runs=WritingRuns(self.timeline,provider_factory=Interrupted)
        runs.start(self.request)
        with self.assertRaises(KeyboardInterrupt):
            runs.run('fixture-run','episode')
        # Simulate the lease expiring after the process exits.
        with self.timeline._connect() as c:
            c.execute("UPDATE episode_writing_runs SET expires=0 WHERE id='fixture-run'")
        req = {k:self.request[k] for k in ('project','universe','episode','branch')}
        interrupted, = self.commands.execute('processing.open',req)['jobs']
        self.assertEqual(interrupted['status'],'UNKNOWN')
        self.assertEqual([step['id'] for step in interrupted['steps'] if step['status']=='UNKNOWN'],['write-2'])
        reopened=self.commands.execute('run.resume',self.request)
        self.assertEqual(reopened['parts'][1]['draft_id'],_draft_id('fixture-run',1))
        self.assertEqual(reopened['status'],'UNKNOWN')
        self.assertEqual(self.commands.execute('run.start',self.request)['status'],'UNKNOWN')
        self.assertFalse(self.writer.calls)
        recovered, = self.commands.execute('processing.open',req)['jobs']
        self.assertEqual(recovered['id'],interrupted['id'])
        self.assertEqual(recovered['status'],'UNKNOWN')

    def test_limits_and_changed_masks_stop_before_the_session(self):
        with self.assertRaisesRegex(ValueError,'writer slots'):
            self.commands.execute('run.start',dict(self.request,max_attempts=2))
        self.commands.execute('run.start',{**self.request,'defer':True})
        n=self.notebook.existing('episode')
        self.notebook.save('episode',n['revision'],1,n['blocks'],75,n['masks'])
        stale=self.commands.execute('run.resume',self.request)
        self.assertEqual(stale['status'],'STALE')
        self.assertFalse(self.writer.calls)

    def test_exact_selection_spends_nothing_and_replays(self):
        b=next(b for b in self.mapping['beats'] if b['id']==self.request['beats'][0])
        req={'episode':'episode','revision':1,'beat':0,'start':b['start'],'end':b['end'],
             'provider':'codex-session','request_id':'exact-selection'}
        def forbidden():
            self.fail('A fully frozen selection constructed a writer')
        first=execute_scoped(self.timeline,'generate',req,provider_factory=forbidden)
        self.assertTrue(first['preserved'])
        replay=execute_scoped(self.timeline,'generate',req,provider_factory=forbidden)
        self.assertEqual(replay['draft_id'],first['draft_id'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(DraftStore(self.notebook).open('episode','main',first['draft_id'])['text'],b['text'])

    def test_exact_author_commands_preserve_without_a_generated_draft(self):
        beat = next(b for b in self.mapping['beats'] if b['id'] == self.request['beats'][0])
        selection = self.commands.execute('run.selection', {
            **self.request, 'request_id':'locked-selection', 'beat':0, 'provider':'codex-session',
            'start':beat['start'], 'end':beat['end'],
        })
        self.assertEqual(selection['status'], 'PRESERVED')
        self.assertNotIn('draft_id', selection)
        request = dict(self.request, beats=self.request['beats'][:1], max_attempts=0)
        result = self.commands.execute('run.start', request)
        self.assertEqual(result['status'], 'PRESERVED')
        self.assertIsNone(result['draft_id'])
        self.assertIsNone(result['generation_receipt'])
        self.assertEqual(result, self.commands.execute('run.status', request))
        self.assertFalse(self.writer.calls)

    def test_saved_graph_cook_receipt_and_revision(self):
        graph = {'nodes':[{'id':node} for node in ('a','b','unrelated')],
                 'edges':[{'from':'a','to':'b'}]}
        revision = self.timeline.save('episode', 1, graph=graph)
        request = {'episode':'episode', 'revision':revision, 'mode':'downstream', 'target':'a'}
        first = self.commands.execute('graph.cook', request)
        self.assertEqual(first['receipt']['checked_nodes'], ['a','b'])
        self.assertFalse(first['reused'])
        reopened = EpisodeCommands(TimelineStore(self.path))
        self.assertEqual(reopened.execute('graph.cook', request), dict(first, reused=True))
        graph['edges'].append({'from':'b','to':'a'})
        new_revision = self.timeline.save('episode', revision, graph=graph)
        with self.assertRaisesRegex(ValueError,'saved graph changed'):
            reopened.execute('graph.cook', request)
        with self.assertRaisesRegex(ValueError,'dependency cycle'):
            reopened.execute('graph.cook', dict(request, revision=new_revision))

    def test_selection_response_receipt_replays_across_clients(self):
        beat = next(b for b in self.mapping['beats'] if b['id'] == self.request['beats'][1])
        req = {**self.request, 'request_id':'selection-local-fixture', 'beat':0,
               'provider':'codex-session', 'start':beat['start'], 'end':beat['end']}
        first = self.commands.execute('run.selection', dict(req, action='run.selection'))
        self.assertEqual(first['origin'], 'generated')
        self.assertEqual(first['writer_receipt']['response_sha256'], digest(first['text']))
        reopened = EpisodeCommands(TimelineStore(self.path))
        replayed = reopened.execute('run.selection', req)
        self.assertTrue(replayed['replayed'])
        self.assertEqual(replayed['writer_receipt'], first['writer_receipt'])
        self.assertEqual(len(self.writer.calls), 1)

    def _selection(self, **overrides):
        target = self.mapping['beats'][-1]
        return {'episode':'episode', 'branch':'main', 'revision':1, 'beat':0,
                'start':target['start'], 'end':target['end'], 'provider':'codex-session',
                'request_id':'durable-selection', 'notebook_revision':self.request['notebook_revision'],
                **overrides}

    def test_selection_recovers_exact_journal_reply_after_interruption(self):
        ledger = self.path.with_name('fixture-usage.jsonl')
        replies = []
        raw = '  A latch slipped. 🗝\r\n'

        def writer(prompt):
            replies.append(digest(prompt))
            return raw

        def factory():
            return DeepSeekSessionProvider(session_handler=writer, ledger=ledger, max_calls=1)

        commands = EpisodeCommands(self.timeline, provider_factory=factory)
        req = self._selection()
        preview = commands.execute('run.selection.preview', req)
        req['expected_prompt_sha256'] = preview['prompt_sha256']
        self.assertEqual(commands.execute('run.selection', dict(req, defer=True))['status'], 'QUEUED')
        with patch.object(DraftStore, 'finish', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                commands.execute('run.resume', req)
        self.assertEqual(replies, [preview['prompt_sha256']])
        journal = factory().attempts
        attempt, = journal.list_attempts()
        self.assertEqual(attempt['state'], 'completed')
        self.assertEqual(attempt['response_sha256'], digest(raw))
        self.assertNotIn('response_text', attempt)
        with journal.transaction() as db:
            self.assertEqual(db.execute('SELECT response_text FROM attempts').fetchone()[0], raw)
        with self.timeline._connect() as c:
            c.execute('UPDATE episode_writing_runs SET expires=0 WHERE id=?', (req['request_id'],))
        reopened = EpisodeCommands(TimelineStore(self.path), provider_factory=factory)
        self.assertTrue(reopened.execute('run.status', req)['resume_available'])
        final = reopened.execute('run.resume', req)
        self.assertEqual(final['status'], 'COMPLETED', final)
        self.assertEqual(replies, [preview['prompt_sha256']])
        draft = reopened.execute('draft.open', {'episode':'episode', 'branch':'main', 'draft':final['draft_id']})
        self.assertEqual(draft['text'], raw.strip())
        self.assertEqual(draft['writer_receipt']['raw_response_sha256'], digest(raw))
        self.assertEqual(draft['writer_receipt']['prompt_sha256'], preview['prompt_sha256'])
        self.assertEqual(draft['writer_receipt']['attempt_id'], attempt['id'])
        self.assertEqual(reopened.execute('run.resume', req), final)
        self.assertEqual(self.timeline.get_episode('episode')['script'], self.text)

    def test_selection_preflight_and_echo_are_not_applicable(self):
        no_budget = self._selection(max_attempts=0)
        blocked = self.commands.execute('run.selection', no_budget)
        self.assertEqual((blocked['status'], blocked['stage']), ('BLOCKED', 'context'))
        self.assertIn('budget', blocked['reason'])
        self.assertFalse(self.writer.calls)
        self.assertEqual(self.commands.execute('run.status', no_budget), blocked)
        bad_preview = self._selection(request_id='bad-preview', expected_prompt_sha256='0' * 64)
        rejected = self.commands.execute('run.selection', bad_preview)
        self.assertEqual(rejected['status'], 'BLOCKED')
        self.assertIn('preview changed', rejected['reason'])
        self.assertFalse(self.writer.calls)

        class Echo:
            def generate_rewrite(self, request, prompt):
                return request.original_text

        commands = EpisodeCommands(self.timeline, provider_factory=Echo)
        echo = commands.execute('run.selection', self._selection(request_id='echo'))
        self.assertEqual(echo['status'], 'BLOCKED')
        self.assertIn('unchanged', echo['reason'])
        self.assertIsNone(echo['draft_id'])
        self.assertIsNone(echo['generation_receipt'])

    def test_selection_deadline_is_independent_of_lease(self):
        req = self._selection()
        queued = self.commands.execute('run.selection', dict(req, defer=True))
        with self.timeline._connect() as c:
            row = c.execute('SELECT payload FROM episode_writing_runs WHERE id=?', (queued['id'],)).fetchone()
            data = json.loads(row['payload'])
            data['processing'].update(stage='context', deadline_at=1)
            c.execute("""UPDATE episode_writing_runs SET state='RUNNING', expires=9999999999,
                         payload=? WHERE id=?""", (json.dumps(data), queued['id']))
        expired = self.commands.execute('run.status', req)
        self.assertTrue(expired['resume_available'])
        self.assertIn('deadline', expired['reason'])
        result = self.commands.execute('run.resume', req)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertEqual(len(self.writer.calls), 1)
