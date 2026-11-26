import copy
import json
import tempfile
import unittest
import threading
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from story_graph.episode_timeline import TimelineStore
from story_graph.world_laws import WorldLawStore
from prose_engine.notebook import NotebookStore, DraftStore, digest, joined, resolve
from prose_engine.scoped_pipeline import build_packet, generate_recorded, validate_output
from tools.studio_ui import StudioRequestHandler


class Provider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def generate_rewrite(self, request, prompt):
        self.calls += 1
        return self.text


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'timeline.sqlite'
        self.timeline = TimelineStore(self.path)
        self.timeline.add_starter_cards()
        self.text = '🕯 The brass key glowed.\r\n\r\nFrancine said, “Did you hear that?”\r\n'
        self.timeline.save('spring-break', 0, script=self.text, source_name='fixture.txt')
        self.timeline.save('tapped-out', 0, script='Another episode.', source_name='other.txt')
        self.book = NotebookStore(self.timeline)

    def mask(self, text, value=100, hard=False):
        start = self.text.index(text)
        return {'id': text, 'start': start, 'end': start+len(text), 'value': value,
                'sha256': digest(text), 'hard': hard}

    def legacy_external_save(self, expected, text):
        """Model a revision already written by an older, unguarded installation."""
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?',('spring-break',expected)).fetchone()
            self.assertEqual(c.execute('SELECT head FROM episodes WHERE id=?',('spring-break',)).fetchone()['head'],expected)
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',('spring-break',expected+1,old['graph'],text,'legacy-fixture.txt',digest(text)))
            c.execute('UPDATE episodes SET head=? WHERE id=?',(expected+1,'spring-break'))

    def test_migration_split_merge_unicode_and_revision_conflict(self):
        state = self.book.open('spring-break')
        self.assertEqual(joined(state['blocks']), self.text)
        self.assertTrue(all(b['kind'] == 'unresolved' and b['speaker'] is None for b in state['blocks']))
        first = state['blocks'][0]
        state = self.book.split('spring-break', 0, 1, first['id'], 3)
        self.assertEqual(joined(state['blocks']), self.text)
        self.assertNotEqual(state['blocks'][0]['id'], state['blocks'][1]['id'])
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.book.split('spring-break', 0, 1, first['id'], 2)
        state = self.book.merge('spring-break', 1, 1, state['blocks'][0]['id'], state['blocks'][1]['id'])
        self.assertEqual(joined(state['blocks']), self.text)
        reloaded = NotebookStore(TimelineStore(self.path)).open('spring-break')
        self.assertEqual(reloaded['revision'], 2)
        self.assertEqual(joined(reloaded['blocks']), self.text)
        state = self.book.undo('spring-break', 2, 1)
        self.assertEqual(len(state['blocks']), 3)
        self.assertEqual(self.timeline.get_episode('spring-break')['script'], self.text)

    def test_character_persona_and_reorder_preserve_original_revision(self):
        state = self.book.open('spring-break')
        blocks = copy.deepcopy(state['blocks'])
        blocks[0]['kind'] = 'narrator'
        blocks[1].update(kind='character', speaker='roger', form='nurse-franny')
        state = self.book.save('spring-break', 0, 1, blocks, 25, [])
        original_ids = [b['id'] for b in state['blocks']]
        state = self.book.save('spring-break', 1, 1, list(reversed(state['blocks'])), 25, [])
        self.assertEqual([b['id'] for b in state['blocks']], list(reversed(original_ids)))
        self.assertEqual(state['blocks'][0]['form'], 'nurse-franny')
        with self.timeline._connect() as c:
            original = c.execute('SELECT script FROM revisions WHERE episode=? AND revision=1', ('spring-break',)).fetchone()
        self.assertEqual(original['script'], self.text)
        state = self.book.undo('spring-break', 2, 2)
        self.assertEqual(joined(state['blocks']), self.text)

    def test_global_freeze_and_mask_override(self):
        state = self.book.open('spring-break')
        with self.assertRaisesRegex(ValueError, 'zero'):
            self.book.save('spring-break', 0, 1, state['blocks'], 0, [])
        with self.assertRaisesRegex(ValueError, 'protected or masked'):
            self.book.edit_text('spring-break', 0, 1, 2, 5, 'New')
        soft = self.mask('glowed', value=25)
        state = self.book.save('spring-break', 0, 1, state['blocks'], 100, [soft])
        start = self.text.index('glowed')
        state = self.book.edit_text('spring-break', 1, 1, start, start+6, 'shimmered')
        self.assertIn('shimmered', joined(state['blocks']))

    def test_default_lock_selectively_opens_dialogue_and_retains_explicit_locks(self):
        state = self.book.open('spring-break')
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        changed = self.text.replace('Did you hear that?', 'Did you see it?')
        result=generate_recorded(self.timeline,packet,'fixture',lambda:Provider(changed),lambda:packet)
        self.assertTrue(result['preserved'])
        self.assertEqual((result['provider_calls'],result['text']),(0,self.text))
        opening = self.mask('Did you hear that?', value=25)
        self.book.save('spring-break', 0, 1, state['blocks'], 100, [opening])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        self.assertEqual(generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(changed), lambda: packet)['status'], 'PROPOSED')
        start = self.text.index('Did you hear that?')
        locked = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text),
                              protected_ranges=[[start, start+len('Did you hear that?')]])
        self.assertTrue(validate_output(locked,changed))
        result=generate_recorded(self.timeline,locked,'fixture',lambda:Provider(changed),lambda:locked)
        self.assertEqual((result['provider_calls'],result['text']),(0,self.text))

    def test_shared_parentage_rule_is_scoped_and_never_a_protection_dial(self):
        state = self.book.open('spring-break')
        self.book.save('spring-break', 0, 1, state['blocks'], 25, [])
        for episode, text in [('spring-break', self.text), ('tapped-out', 'Another episode.')]:
            packet = build_packet(self.timeline, episode, 1, 1, 0, len(text))
            self.assertTrue(packet.world_laws)
            bad = text + " Haley's father arrived."
            self.assertTrue(validate_output(packet, bad))
            self.assertTrue(validate_output(packet, text + ' Haley has a father.'))
            good = Provider(text + " Francine visited her adoptive father Baba Ling.")
            # A literal father mention about Francine is not treated as Haley's parent.
            if episode == 'spring-break':
                self.assertEqual(generate_recorded(self.timeline, packet, 'fixture', lambda: good, lambda: packet)['status'], 'PROPOSED')

    def test_world_laws_persist_apply_across_episodes_and_reject_stale(self):
        world = WorldLawStore(self.timeline); original = world.open()
        laws = original['laws'] + [{'id':'example-law', 'name':'Example', 'statement':'The forbidden orchid does not exist.',
            'enabled':True, 'matcher':'literal', 'phrases':['forbidden orchid']}]
        changed = world.save(0, laws)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            world.save(0, laws)
        self.assertEqual(WorldLawStore(TimelineStore(self.path)).open(), changed)
        for episode, text in [('spring-break', self.text), ('tapped-out', 'Another episode.')]:
            p = build_packet(self.timeline, episode, 1, 1, 0, len(text))
            self.assertTrue(validate_output(p, text+' A forbidden orchid appeared.'))
            self.assertEqual(p.world_law_revision, 1)
        restored = world.undo(1)
        self.assertEqual(restored['laws'], original['laws'])
        self.assertEqual(restored['revision'], 2)

    def test_world_law_change_during_generation_makes_draft_stale(self):
        state = self.book.open('spring-break')
        self.book.save('spring-break', 0, 1, state['blocks'], 25, [])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        class ChangingProvider:
            def generate_rewrite(inner, request, prompt):
                laws = WorldLawStore(self.timeline); current = laws.open(); laws.save(current['revision'], current['laws'])
                return self.text
        with self.assertRaisesRegex(ValueError, 'Timeline changed'):
            generate_recorded(self.timeline, packet, 'fixture', ChangingProvider,
                lambda: build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text)))
        self.assertEqual(DraftStore(self.book).list('spring-break', 'main')[0]['status'], 'STALE')

    def test_masks_overlap_freeze_and_stale_anchors(self):
        state = self.book.open('spring-break')
        frozen = self.mask('brass key', hard=True)
        dialogue = self.mask('Did you hear that?', value=75)
        broad = self.mask('brass key glowed', value=50)
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [frozen, dialogue, broad])
        sections = resolve(self.text, 25, state['masks'])
        self.assertTrue(any(s['value'] == 100 and s['start'] <= frozen['start'] < s['end'] for s in sections))
        self.assertTrue(any(s['value'] == 75 and s['start'] <= dialogue['start'] < s['end'] for s in sections))
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        provider = Provider(self.text.replace('brass', 'grass'))
        result = generate_recorded(self.timeline, packet, 'fixture', lambda: provider, lambda: packet)
        self.assertEqual(result['status'], 'BLOCKED')
        dialogue_provider = Provider(self.text.replace('Did you hear that?', 'Did you see it?'))
        self.assertEqual(generate_recorded(self.timeline, packet, 'fixture', lambda: dialogue_provider, lambda: packet)['status'], 'PROPOSED')
        with self.assertRaisesRegex(ValueError, 'hard lock'):
            self.book.save('spring-break', 1, 1, state['blocks'], 25, [dialogue, broad])
        bad = dict(dialogue, sha256=digest('different'))
        with self.assertRaisesRegex(ValueError, 'Stale mask'):
            self.book.save('spring-break', 1, 1, state['blocks'], 25, [frozen, bad])

    def test_soft_mask_invalidates_on_edit_and_freeze_survives(self):
        state = self.book.open('spring-break')
        soft = self.mask('glowed', value=75)
        hard = self.mask('brass key', value=100, hard=True)
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [soft, hard])
        start = self.text.index('glowed')
        state = self.book.edit_text('spring-break', 1, 1, start, start+6, 'shimmered')
        self.assertEqual(state['timeline_revision'], 2)
        self.assertEqual(state['stale_masks'][0]['id'], 'glowed')
        self.assertEqual(state['masks'][0]['id'], 'brass key')
        state = self.book.undo('spring-break', 2, 2)
        self.assertEqual(joined(state['blocks']), self.text)
        self.assertEqual(self.timeline.get_episode('spring-break')['head'], 3)

    def test_cross_block_mask_and_stale_episode(self):
        state = self.book.open('spring-break')
        start = self.text.index('glowed'); end = self.text.index('Francine')+len('Francine')
        mask = {'id':'cross', 'start':start, 'end':end, 'value':100,
                'sha256':digest(self.text[start:end]), 'hard':False}
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [mask])
        self.legacy_external_save(1, self.text + 'external')
        self.assertTrue(self.book.open('spring-break')['stale'])
        with self.assertRaisesRegex(ValueError, 'stale'):
            build_packet(self.timeline, 'spring-break', 1, 2, 0, len(self.text))

    def test_sync_external_edit_reanchors_masks_and_preserves_frozen_text(self):
        state = self.book.open('spring-break')
        hard = self.mask('brass key', hard=True)
        soft = self.mask('glowed', value=75)
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [hard, soft])
        changed = self.text.replace('glowed', 'shimmered')
        self.legacy_external_save(1, changed)
        state = self.book.sync('spring-break', 1, 2)
        self.assertEqual(joined(state['blocks']), changed)
        self.assertEqual(state['stale_masks'][0]['id'], 'glowed')
        self.legacy_external_save(2, changed.replace('brass', 'silver'))
        with self.assertRaisesRegex(ValueError, 'protected or masked'):
            self.book.sync('spring-break', state['revision'], 3)

    def test_drafts_scope_favorites_apply_and_undo(self):
        state = self.book.open('spring-break')
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [self.mask('brass key', hard=True)])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        text = self.text.replace('glowed', 'shimmered')
        provider = Provider(text)
        result = generate_recorded(self.timeline, packet, 'fixture', lambda: provider, lambda: packet)
        drafts = DraftStore(self.book); ident = result['draft_id']
        second = generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(self.text), lambda: packet)['draft_id']
        drafts.favorite('spring-break', 'main', ident, True)
        self.assertEqual(provider.calls, 1)
        self.assertTrue(drafts.open('spring-break', 'main', ident)['favorite'])
        self.assertIn('shimmered', drafts.compare('spring-break', 'main', second, ident))
        self.assertEqual(drafts.list('tapped-out', 'main'), [])
        with self.assertRaises(ValueError): drafts.open('tapped-out', 'main', ident)
        used = drafts.use('spring-break', 'main', ident, 1, 1)
        self.assertEqual(joined(used['blocks']), text)
        with self.assertRaises(ValueError): drafts.use('spring-break', 'main', ident, 1, 1)
        restored = self.book.undo('spring-break', used['revision'], used['timeline_revision'])
        self.assertEqual(joined(restored['blocks']), self.text)

    def test_stale_and_failed_generation_are_retained(self):
        state = self.book.open('spring-break')
        self.book.save('spring-break', 0, 1, state['blocks'], 25, [])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        def fail(): raise RuntimeError('fixture error')
        with self.assertRaises(RuntimeError):
            generate_recorded(self.timeline, packet, 'fixture', fail, lambda: packet)
        with self.assertRaises(ValueError):
            generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(self.text), lambda: None)
        drafts = DraftStore(self.book).list('spring-break', 'main')
        self.assertEqual([d['status'] for d in drafts], ['FAILED', 'STALE'])
        with self.assertRaises(ValueError): DraftStore(self.book).use('spring-break', 'main', drafts[0]['id'], 1, 1)

    def test_dispatch_unknown_and_changed_protection(self):
        state = self.book.open('spring-break')
        state = self.book.save('spring-break', 0, 1, state['blocks'], 25, [])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        class LostProvider:
            def generate_rewrite(self, request, prompt):
                raise TimeoutError('remote outcome not known')
        with self.assertRaises(TimeoutError):
            generate_recorded(self.timeline, packet, 'fixture', LostProvider, lambda: packet)
        self.assertEqual(DraftStore(self.book).list('spring-break', 'main')[0]['status'], 'UNKNOWN')
        self.book.save('spring-break', 1, 1, state['blocks'], 75, [])
        with self.assertRaisesRegex(ValueError, 'Protection changed'):
            generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(self.text), lambda: packet)

    def test_draft_rejects_changed_timeline_and_partial_keep(self):
        state = self.book.open('spring-break')
        self.book.save('spring-break', 0, 1, state['blocks'], 25, [])
        packet = build_packet(self.timeline, 'spring-break', 1, 1, 0, len(self.text))
        new_text = self.text.replace('glowed', 'shimmered')
        ident = generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(new_text), lambda: packet)['draft_id']
        draft_store = DraftStore(self.book)
        start = self.text.index('glowed'); replacement = new_text.index('shimmered')
        used = draft_store.use('spring-break', 'main', ident, 1, 1, source_start=start, source_end=start+6,
                               candidate_start=replacement, candidate_end=replacement+9)
        self.assertEqual(joined(used['blocks']), new_text)
        state = self.book.undo('spring-break', 2, 2)
        packet = build_packet(self.timeline, 'spring-break', 1, 3, 0, len(self.text))
        ident = generate_recorded(self.timeline, packet, 'fixture', lambda: Provider(new_text), lambda: packet)['draft_id']
        self.timeline.add_event('later', 'tapped-out', 0, 'Future fixture event', status='draft')
        with self.assertRaisesRegex(ValueError, 'Timeline facts changed'):
            draft_store.use('spring-break', 'main', ident, state['revision'], state['timeline_revision'])
        self.assertEqual(self.timeline.get_episode('spring-break')['script'], self.text)

    def test_notebook_and_draft_http_endpoints_use_shared_service(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
        server.timeline_path = self.path; server.timeline_only = True
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def post(path, data, origin=None):
            req = urllib.request.Request(base+path, data=json.dumps(data).encode(),
                headers={'Content-Type':'application/json', 'Origin':origin or base})
            with urllib.request.urlopen(req) as response: return json.load(response)
        try:
            state = post('/api/notebook', {'action':'open', 'episode':'spring-break'})
            self.assertEqual(joined(state['blocks']), self.text)
            state = post('/api/notebook', {'action':'save', 'episode':'spring-break', 'revision':0,
                'timeline_revision':1, 'blocks':state['blocks'], 'default_protection':25, 'masks':[]})
            self.assertEqual(state['default_protection'], 25)
            self.assertEqual(post('/api/drafts', {'action':'list', 'episode':'spring-break', 'branch':'main'})['drafts'], [])
            laws = post('/api/world-laws', {'action':'open'})
            self.assertEqual(laws['laws'][0]['id'], 'haley-parentage')
            generated = self.text.replace('glowed', 'shimmered')
            provider = Provider(generated)
            with patch('prose_engine.providers.primary_session.create_scoped_provider', return_value=provider):
                proposal = post('/api/scoped', {'action':'generate','provider':'codex-session',
                    'episode':'spring-break','beat':1,'revision':1,'start':0,'end':len(self.text)})
            ident = proposal['draft_id']
            favored = post('/api/drafts', {'action':'favorite','episode':'spring-break','branch':'main','draft':ident,'value':True})
            self.assertTrue(favored['favorite'])
            self.assertEqual(self.timeline.get_episode('spring-break')['script'], self.text)
            used = post('/api/drafts', {'action':'use','episode':'spring-break','branch':'main','draft':ident,
                'revision':state['revision'],'timeline_revision':state['timeline_revision']})
            self.assertEqual(joined(used['blocks']), generated)
            undone = post('/api/notebook', {'action':'undo','episode':'spring-break',
                'revision':used['revision'],'timeline_revision':used['timeline_revision']})
            self.assertEqual(joined(undone['blocks']), self.text)
            self.assertEqual(provider.calls, 1)
            with self.assertRaises(urllib.error.HTTPError) as exc:
                post('/api/notebook', {'action':'open', 'episode':'spring-break'}, 'http://other')
            self.assertEqual(exc.exception.code, 403)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
