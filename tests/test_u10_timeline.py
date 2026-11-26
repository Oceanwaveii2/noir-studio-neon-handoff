import tempfile
import unittest
from pathlib import Path
from story_graph.episode_timeline import TimelineStore
from tools.u10_backup import backup

class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'timeline.sqlite'; self.s=TimelineStore(self.path)
        for eid,pos in [('spring',1),('hot',2),('tapped',3)]: self.s.create_episode(eid,eid,'main',pos)

    def test_timeline_preview_and_undo_move_and_detached_flag_together(self):
        from prose_engine.episode_commands import EpisodeCommands

        graph = {'nodes': [{'id': 'spring'}, {'id': 'hot'}],
                 'edges': [{'from': 'spring', 'to': 'hot', 'kind': 'TEMPORAL_LOCK'}]}
        self.s.save('spring', 0, graph=graph)
        commands = EpisodeCommands(self.s)
        initial = self.s.history_state()['revision']
        req = dict(episode='hot', branch='main', episode_revision=0, expected_revision=initial, after='start')
        preview = commands.execute('timeline.preview', {**req, 'command': 'timeline.move'})
        self.assertEqual(preview['before'], ['spring', 'hot', 'tapped'])
        self.assertEqual(preview['after'], ['hot', 'spring', 'tapped'])
        self.assertEqual(len(preview['temporal_locks']), 1)
        self.assertEqual(self.s.history_state()['revision'], initial)
        self.assertEqual(self.s.get_episode('hot')['timeline_repair'], [])
        with self.assertRaisesRegex(ValueError, 'Preview'):
            commands.execute('timeline.move', req)
        with self.assertRaisesRegex(ValueError, 'impact changed'):
            commands.execute('timeline.move', {**req, 'preview_token': 'wrong', 'disconnect': True})
        moved = commands.execute('timeline.move', {**req, 'preview_token': preview['token'], 'disconnect': True})
        self.assertEqual(self.s.cards()[0]['id'], 'hot')
        self.assertEqual(len(self.s.get_episode('hot')['timeline_repair']), 1)
        undone = commands.execute('timeline.undo', {'expected_revision': moved['history']['revision']})
        self.assertEqual(self.s.cards()[0]['id'], 'spring')
        self.assertEqual(self.s.get_episode('hot')['timeline_repair'], [])
        commands.execute('timeline.redo', {'expected_revision': undone['history']['revision']})
        self.assertEqual(self.s.cards()[0]['id'], 'hot')
        self.assertEqual(len(self.s.get_episode('hot')['timeline_repair']), 1)
        self.assertEqual(self.s.get_episode('spring')['graph'], graph)

    def test_word_prep_and_canon_tag_persist_in_revisioned_workspace(self):
        from prose_engine.episode_commands import EpisodeCommands
        from prose_engine.notebook import NotebookStore

        self.s.save('spring', 0, script='“Original.”', source_name='fixture')
        book = NotebookStore(self.s)
        before = book.open('spring')
        request = dict(episode='spring', timeline_revision=1, notebook_revision=before['revision'], request_id='prep-1',
                       nodes=[{'kind': 'character', 'speaker': 'Rainee', 'text': '“New exact words.”', 'noise_mode': '0'},
                              {'kind': 'world-law', 'text': '@law:clock'}])
        commands = EpisodeCommands(self.s)
        result = commands.execute('word_prep.promote', request)
        self.assertEqual(result['status'], 'APPLIED')
        current = self.s.get_episode('spring')
        self.assertEqual(current['script'], '“Original.”\n\nRainee: “New exact words.”')
        self.assertEqual(current['graph']['nodes'][-1]['data']['law_refs'], ['clock'])
        self.assertEqual(commands.execute('word_prep.promote', request)['status'], 'REPLAYED')
        state = book.open('spring')
        mask = state['masks'][-1]
        self.assertEqual((mask['value'], current['script'][mask['start']:mask['end']]), (100, '“New exact words.”'))
        tag = commands.execute('canon.tag.save', dict(episode='spring', timeline_revision=current['head'], canon_revision=0,
                               mode='time_travel_canon', tt_carrier='rainee'))['canon_tag']
        self.assertEqual(TimelineStore(self.path).get_episode('spring')['canon_tag'], tag)
        book.undo('spring', state['revision'], current['head'])
        self.assertEqual(self.s.get_episode('spring')['script'], '“Original.”')
        self.assertEqual(self.s.get_episode('spring')['graph']['nodes'], [])

    def test_recoverable_episode_removal_preserves_content_and_rejects_stale_edits(self):
        from prose_engine.notebook import NotebookStore
        self.s.save('tapped',0,script='An existing draft',source_name='draft.txt')
        with self.assertRaisesRegex(ValueError,'changed'): self.s.set_archived('tapped',0,True)
        self.s.set_archived('tapped',1,True)
        self.assertNotIn('tapped',[row['id'] for row in self.s.cards()])
        self.assertEqual(self.s.archived_cards()[0]['id'],'tapped')
        for action in (lambda: self.s.get_episode('tapped'),lambda: self.s.resolve('tapped',0),
                       lambda: self.s.add_event('late','tapped',0,'late'),
                       lambda: NotebookStore(self.s).existing('tapped')):
            with self.assertRaises(ValueError): action()
        self.s.set_archived('tapped',1,False)
        self.assertEqual(self.s.get_episode('tapped')['script'],'An existing draft')
        self.s.set_archived('tapped',1,True)
        self.s.set_archived('tapped',1,False)
        self.assertEqual(self.s.get_episode('tapped')['head'],1)

    def test_removing_episode_excludes_events_from_main_and_frozen_branch_until_restored(self):
        self.s.add_event('past','spring',1,'existing history',status='approved',permitted=True,source_id='source',reviewer='reviewer')
        self.s.fork('side','main','spring',1);self.s.create_episode('side-ep','Side','side',1)
        self.assertEqual([e['id'] for e in self.s.resolve('side-ep',0)],['past'])
        scope=self.s.scope()['scope_revision'];self.s.set_archived('spring',0,True)
        self.assertEqual(self.s.scope()['scope_revision'],scope+1)
        self.assertEqual(self.s.resolve('hot',0),[]);self.assertEqual(self.s.resolve('side-ep',0),[])
        with self.assertRaises(ValueError):self.s.add_event('new','spring',0,'unavailable')
        self.s.set_archived('spring',0,False)
        self.assertEqual([e['id'] for e in self.s.resolve('hot',0)],['past'])
        self.assertEqual([e['id'] for e in self.s.resolve('side-ep',0)],['past'])
        with tempfile.TemporaryDirectory() as tmp:
            starter=TimelineStore(Path(tmp)/'starter.sqlite');starter.add_starter_cards()
            starter.set_archived('spring-break',0,True)
            self.assertNotIn('spring-break',[e['id'] for e in starter.cards()])
            starter.set_archived('spring-break',0,False)
            self.assertEqual(starter.get_episode('spring-break')['status'],'draft')

    def test_future_drafts_and_private_events_filtered(self):
        self.s.add_event('past','spring',1,'past',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.add_event('awakening','hot',2,'awakening',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.add_event('prank','tapped',1,'prank',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.add_event('draft','hot',1,'draft',permitted=True)
        self.s.add_event('private','hot',1,'secret',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer',viewpoint='haley')
        self.assertEqual([x['id'] for x in self.s.resolve('spring',99)],['past'])
        self.assertEqual([x['id'] for x in self.s.resolve('hot',1)],['past'])
        self.assertEqual([x['id'] for x in self.s.resolve('tapped',0)],['past','awakening'])
        self.assertEqual([x['id'] for x in self.s.resolve('tapped',0,'haley')],['past','private','awakening'])

    def test_fork_freezes_parent_at_beat_and_does_not_leak(self):
        self.s.add_event('before','hot',1,'before',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.add_event('after','hot',3,'after',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.fork('side','main','hot',1); self.s.create_episode('side1','Side','side',1)
        self.s.add_event('side-event','side1',1,'side',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.s.add_event('late-parent','spring',0,'late parent change',status='approved',permitted=True,source_id='fixture',reviewer='fixture reviewer')
        self.assertEqual([x['id'] for x in self.s.resolve('side1',2)],['before','side-event'])
        self.assertEqual([x['id'] for x in self.s.resolve('tapped',2)],['late-parent','before','after'])

    def test_script_graph_revision_persist_and_finished_pinned(self):
        self.s.save('tapped',0,graph={'nodes':[{'id':'x'}],'edges':[]},script='INT. ROOM\nHello',source_name='my-script.txt')
        with self.assertRaisesRegex(ValueError,'Stale'): self.s.save('tapped',0,script='overwrite',source_name='x')
        self.s.finish('tapped',1,'fixture reviewer')
        with self.assertRaisesRegex(ValueError,'Reopen'): self.s.save('tapped',1,script='other',source_name='x')
        self.s.reopen('tapped'); self.s.save('tapped',1,script='new',source_name='next.txt')
        s=TimelineStore(self.path); result=s.get_episode('tapped')
        self.assertEqual(result['finished_revision'],1); self.assertEqual(result['script'],'new')
        self.assertEqual(result['graph']['nodes'][0]['id'],'x')
        self.assertEqual(s.get_episode('spring')['script'],'')

    def test_cover_reference_survives_reload_and_size_is_bounded(self):
        self.s.create_episode('cover-story','Cover story','main',4,cover='data:image/png;base64,YWJj')
        cards=TimelineStore(self.path).cards()
        self.assertEqual(next(x for x in cards if x['id']=='cover-story')['cover'],'data:image/png;base64,YWJj')
        with self.assertRaises(ValueError): self.s.create_episode('huge','Huge','main',5,cover='x'*1400001)

    def test_fixed_order_and_awakening_prerequisite(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=TimelineStore(Path(tmp)/'starter.sqlite'); s.add_starter_cards()
            self.assertEqual([x['id'] for x in s.cards()],['spring-break','hot-scoomp','tapped-out'])
            with self.assertRaises(ValueError): s.finish('tapped-out',0,'fixture reviewer')
            with self.assertRaises(ValueError): s.create_episode('tapped-out','Wrong order','main',0)
            s.add_event('haley-awakening','hot-scoomp',1,'Awakening',status='draft',permitted=True)
            self.assertTrue(s.prerequisites('tapped-out'))
            with self.assertRaises(ValueError): s.review_event('spring-break','haley-awakening','owner','fixture',True)
            with self.assertRaises(ValueError): s.review_event('hot-scoomp','haley-awakening','owner','fixture',False)
            s.review_event('hot-scoomp','haley-awakening','owner','fixture',True)
            self.assertFalse(s.prerequisites('tapped-out'))
            self.assertEqual([e['id'] for e in s.resolve('tapped-out',0)],['haley-awakening'])
            self.assertEqual(s.resolve('spring-break',999),[])
            s.finish('tapped-out',0,'owner')

    def test_sibling_branches_and_viewpoint_stay_isolated(self):
        self.s.add_event('private','spring',1,'secret',status='approved',permitted=True,viewpoint='haley',source_id='fixture',reviewer='reviewer')
        self.s.fork('one','main','hot',1); self.s.fork('two','main','hot',1)
        self.s.create_episode('one-episode','One','one',1); self.s.create_episode('two-episode','Two','two',1)
        self.s.add_event('branch-change','one-episode',0,'one only',status='approved',permitted=True,source_id='fixture',reviewer='reviewer')
        self.assertEqual(self.s.resolve('two-episode',4),[])
        self.assertEqual([e['id'] for e in self.s.resolve('one-episode',4,'haley')],['private','branch-change'])
        self.assertEqual([e['id'] for e in self.s.resolve('one-episode',4,'roger')],['branch-change'])

    def test_sqlite_backup_restores_episode_and_refuses_overwrite(self):
        self.s.save('tapped',0,script='A saved draft',source_name='draft.txt')
        path=Path(self.tmp.name)/'backup.sqlite'
        receipt=backup(self.path,path)
        self.assertEqual(receipt['status'],'PASS')
        restored=TimelineStore(path)
        self.assertEqual(restored.get_episode('tapped')['script'],'A saved draft')
        with self.assertRaises(FileExistsError): backup(self.path,path)

    def test_invalid_fork_rejected(self):
        with self.assertRaises(ValueError): self.s.fork('bad','main','missing',1)

    def test_rejoin_requires_review_and_respects_target_beat(self):
        self.s.fork('side','main','hot',1)
        self.s.create_episode('side1','Side','side',1)
        self.s.add_event('change','side1',3,'An approved change',status='approved',permitted=True,source_id='fixture',reviewer='reviewer')
        self.s.add_event('secret','side1',3,'Private change',status='approved',permitted=True,source_id='fixture',reviewer='reviewer',viewpoint='haley')
        with self.assertRaises(ValueError): self.s.rejoin('side1','change','spring',1,'reviewer','fixture',True)
        with self.assertRaises(ValueError): self.s.rejoin('side1','change','tapped',1,'reviewer','fixture',False)
        with self.assertRaises(ValueError): self.s.rejoin('side1','secret','tapped',1,'reviewer','fixture',True)
        imported=self.s.rejoin('side1','change','tapped',2,'reviewer','fixture',True)
        self.assertEqual(self.s.resolve('tapped',1),[])
        self.assertEqual([e['id'] for e in self.s.resolve('tapped',2)],[imported])
        self.assertEqual([e['id'] for e in self.s.resolve('side1',9)],['change'])
        self.s.set_archived('side1',0,True)
        self.assertEqual(self.s.resolve('tapped',2),[])
        self.s.set_archived('side1',0,False)
        self.assertEqual([e['id'] for e in self.s.resolve('tapped',2)],[imported])

    def test_undo_and_redo_for_fork_events_forms_reviews_rejoins_and_reopen(self):
        from types import SimpleNamespace
        junctions = {'haley': SimpleNamespace(forms=[SimpleNamespace(id='awakened_haley_fox')])}
        self.s.fork('side', 'main', 'hot', 1)
        self.s.create_episode('side1', 'Side', 'side', 1)
        with self.assertRaisesRegex(ValueError, 'episodes on this branch'):
            self.s.unfork('side')
        self.s.fork('empty-branch', 'main', 'hot', 1)
        self.s.unfork('empty-branch')
        self.assertNotIn('empty-branch', [b['id'] for b in self.s.branches()])
        self.s.fork('empty-branch', 'main', 'hot', 1)
        self.assertIn('empty-branch', [b['id'] for b in self.s.branches()])

        self.s.add_event('draft-ev', 'side1', 1, 'Haley shifts')
        self.s.bind_form_event('side1', 'draft-ev', 'haley', 'awakened_haley_fox', 'active', junctions)
        unbound = self.s.unbind_form_event('side1', 'draft-ev')
        self.assertIsNone(unbound['binding'])
        self.assertTrue(unbound['can_redo_binding'])
        redone_bind = self.s.redo_form_event('side1', 'draft-ev', junctions)
        self.assertEqual(redone_bind['binding']['form_id'], 'awakened_haley_fox')
        self.s.review_event('side1', 'draft-ev', 'Author', 'fixture', True)

        merged_id = self.s.rejoin('side1', 'draft-ev', 'tapped', 2, 'Author', 'fixture', True)
        with self.assertRaisesRegex(ValueError, 'parent rejoin'):
            self.s.unreview_event('side1', 'draft-ev')
        with self.assertRaisesRegex(ValueError, 'unrejoin'):
            self.s.unreview_event('tapped', merged_id)
        unjoined = self.s.unrejoin('tapped', merged_id)
        self.assertEqual(unjoined['rejoined_event'], merged_id)
        self.assertEqual(self.s.resolve('tapped', 2), [])
        restored_id = self.s.rejoin('side1', 'draft-ev', 'tapped', 2, 'Author', 'fixture', True, rejoined_id=merged_id)
        self.assertEqual(restored_id, merged_id)
        self.s.unrejoin('tapped', merged_id)

        self.s.unreview_event('side1', 'draft-ev')
        self.assertEqual(self.s.episode_events('side1')[0]['status'], 'draft')
        self.s.unadd_event('side1', 'draft-ev')
        self.assertEqual(self.s.episode_events('side1'), [])
        restored = self.s.restore_event('side1', 'draft-ev', junctions)
        self.assertEqual(restored['id'], 'draft-ev')
        self.assertEqual(self.s.episode_events('side1')[0]['form_id'], 'awakened_haley_fox')

        self.s.finish('tapped', 0, 'Author')
        with self.assertRaisesRegex(ValueError, 'Episode changed'):
            self.s.reopen('tapped', expected_revision=99)
        reopened = self.s.reopen('tapped', expected_revision=0)
        self.assertEqual(reopened['last_reviewer'], 'Author')
        self.assertEqual(self.s.get_episode('tapped')['status'], 'draft')

        with tempfile.TemporaryDirectory() as tmp:
            afm = TimelineStore(Path(tmp) / 'afm.sqlite')
            afm.add_starter_cards()
            afm.add_event('haley-awakening', 'hot-scoomp', 1, 'Awakening')
            afm.review_event('hot-scoomp', 'haley-awakening', 'Author', 'fixture', True)
            afm.finish('tapped-out', 0, 'Author')
            with self.assertRaisesRegex(ValueError, 'Reopen Tapped Out'):
                afm.unreview_event('hot-scoomp', 'haley-awakening')
            afm.reopen('tapped-out', expected_revision=0)
            afm.unreview_event('hot-scoomp', 'haley-awakening')
            self.assertTrue(afm.prerequisites('tapped-out'))

    def test_sqlite_timeline_action_history_survives_reload_with_branches_and_rejoins(self):
        from types import SimpleNamespace
        junctions = {'haley': SimpleNamespace(forms=[SimpleNamespace(id='awakened_haley_fox')])}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'history.sqlite'
            store = TimelineStore(db)
            self.assertEqual(store.history_state(), {
                'revision': 0, 'can_undo': False, 'can_redo': False,
                'undo_count': 0, 'redo_count': 0, 'next_undo_kind': None, 'next_redo_kind': None,
            })

            store.create_episode('ep-1', 'Episode 1', 'main', 10)
            store.create_episode('ep-2', 'Episode 2', 'main', 11)
            store.create_episode('ep-mid', 'Middle', 'main', 99, after='ep-1')
            self.assertEqual([c['id'] for c in store.cards()], ['ep-1', 'ep-mid', 'ep-2'])

            store.move_episode('ep-mid', 0, after='ep-2')
            self.assertEqual([c['id'] for c in store.cards()], ['ep-1', 'ep-2', 'ep-mid'])

            store.add_event('ev-parent', 'ep-1', 1, 'Parent awakening')
            store.bind_form_event('ep-1', 'ev-parent', 'haley', 'awakened_haley_fox', 'active', junctions)
            store.review_event('ep-1', 'ev-parent', 'Author', 'fixture', True)

            store.fork('side', 'main', 'ep-1', 1)
            store.create_episode('side-ep', 'Side Ep', 'side', 1)
            store.add_event('ev-side', 'side-ep', 1, 'Side event')
            store.review_event('side-ep', 'ev-side', 'Author', 'fixture', True)
            rejoined_id = store.rejoin('side-ep', 'ev-side', 'ep-2', 2, 'Author', 'fixture', True)

            store.fork('empty-branch', 'main', 'ep-2', 0)
            store.finish('ep-mid', 0, 'Author')
            store.set_archived('ep-1', 0, True)

            self.assertNotIn('ep-1', [c['id'] for c in store.cards()])
            self.assertEqual([c['id'] for c in store.archived_cards()], ['ep-1'])
            self.assertEqual([e['id'] for e in store.resolve('ep-2', 5)], [rejoined_id])
            self.assertEqual([e['id'] for e in store.resolve('side-ep', 5)], ['ev-side'])

            # Reopen SQLite store from disk: history stacks and revision survive reload.
            reloaded = TimelineStore(db)
            state0 = reloaded.history_state()
            self.assertTrue(state0['can_undo'])
            self.assertFalse(state0['can_redo'])
            self.assertEqual(state0['next_undo_kind'], 'remove')

            with self.assertRaisesRegex(ValueError, 'changed elsewhere'):
                reloaded.undo_history(expected_revision=state0['revision'] + 5)
            self.assertEqual(reloaded.history_state(), state0)

            undone = reloaded.undo_history(expected_revision=state0['revision'], junctions=junctions)
            self.assertEqual(undone['action'], 'undo')
            self.assertEqual(undone['kind'], 'remove')
            self.assertIn('ep-1', [c['id'] for c in reloaded.cards()])
            self.assertIn('side', [b['id'] for b in reloaded.branches()])
            self.assertEqual([e['id'] for e in reloaded.resolve('ep-2', 5)], ['ev-parent', rejoined_id])
            self.assertEqual([e['id'] for e in reloaded.resolve('side-ep', 5)], ['ev-parent', 'ev-side'])

            # Reload again and redo archiving ep-1, then undo again.
            reloaded2 = TimelineStore(db)
            redone = reloaded2.redo_history(expected_revision=reloaded2.history_state()['revision'], junctions=junctions)
            self.assertEqual(redone['kind'], 'remove')
            self.assertNotIn('ep-1', [c['id'] for c in reloaded2.cards()])
            self.assertEqual([e['id'] for e in reloaded2.resolve('side-ep', 5)], ['ev-side'])
            reloaded2.undo_history(junctions=junctions)

            # Multi-step undo/redo back across finish, empty-branch fork, rejoin, review, and add_event.
            expected_kinds = ['finish', 'fork', 'rejoin', 'review_event', 'add_event']
            for kind in expected_kinds:
                step = TimelineStore(db).undo_history(junctions=junctions)
                self.assertEqual(step['kind'], kind)
            checker = TimelineStore(db)
            self.assertEqual(checker.get_episode('ep-mid')['status'], 'draft')
            self.assertNotIn('empty-branch', [b['id'] for b in checker.branches()])
            self.assertEqual(checker.episode_events('side-ep'), [])
            self.assertEqual([e['id'] for e in checker.resolve('ep-2', 5)], ['ev-parent'])

            for kind in reversed(expected_kinds):
                step = TimelineStore(db).redo_history(junctions=junctions)
                self.assertEqual(step['kind'], kind)
            checker = TimelineStore(db)
            self.assertEqual(checker.get_episode('ep-mid')['status'], 'finished')
            self.assertIn('empty-branch', [b['id'] for b in checker.branches()])
            self.assertEqual([e['id'] for e in checker.resolve('ep-2', 5)], ['ev-parent', rejoined_id])

            # Undoing once then making a forward edit clears redo_stack while keeping event_reviews audit rows.
            TimelineStore(db).undo_history(junctions=junctions)
            checker = TimelineStore(db)
            self.assertTrue(checker.history_state()['can_redo'])
            with checker._connect() as c:
                before_reviews = c.execute('SELECT COUNT(*) FROM event_reviews').fetchone()[0]
            checker.create_episode('ep-tail', 'Tail', 'main', 99, after='ep-2')
            after_state = TimelineStore(db).history_state()
            self.assertFalse(after_state['can_redo'])
            self.assertEqual(after_state['next_undo_kind'], 'create')
            with TimelineStore(db)._connect() as c:
                after_reviews = c.execute('SELECT COUNT(*) FROM event_reviews').fetchone()[0]
            self.assertEqual(after_reviews, before_reviews)

