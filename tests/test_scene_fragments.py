"""Source identity, replayable saves and rejection cases for SceneFragment v1."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_fragments import SceneFragmentError, SceneFragmentStore, digest


TEXT = ('Opening note.\r\n\r\nINT. KITCHEN – NIGHT\r\n\r\nNora: Keep this.\r\n\r\n'
        'A mug on the table.\r\n\r\nEXT. ROAD – DAWN\r\n\r\nTraffic returns.\r\n')


class SceneFragmentTests(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.path = Path(work.name) / 'timeline.sqlite'
        self.timeline = TimelineStore(self.path, project_id='fixture-project', universe_id='fixture-universe')
        self.timeline.create_episode('one', 'One', 'main', 1)
        self.timeline.save('one', 0, script=TEXT, source_name='fixture-original')
        self.commands = EpisodeCommands(self.timeline)
        self.scope = {'project': 'fixture-project', 'universe': 'fixture-universe', 'episode': 'one', 'branch': 'main'}
        self.at = self.scope | {'timeline_revision': 1, 'selection': {'scene': 'scene-2'}}

    def run_command(self, name, args):
        return self.commands.execute('scene.fragment.' + name, args)

    def reason(self, code, operation, args):
        with self.assertRaises(SceneFragmentError) as error:
            self.run_command(operation, args)
        self.assertEqual(error.exception.code, code)

    def db_has_fragments(self):
        with self.timeline._connect() as c:
            return c.execute("SELECT 1 FROM sqlite_master WHERE name='scene_fragment_revisions'").fetchone() is not None

    def test_preview_import_reopen_and_round_trip(self):
        preview = self.run_command('preview', self.at)
        self.assertEqual(preview['status'], 'PREVIEW')
        self.assertFalse(self.db_has_fragments())
        self.assertEqual(self.run_command('list', self.scope)['fragments'], [])
        result = self.run_command('import', self.at)
        body = result['fragment']
        self.assertEqual(result['provider_calls'], 0)
        self.assertEqual(body['story_time'], 'unresolved')
        self.assertEqual([n['kind'] for n in body['graph']['nodes']], ['heading', 'dialogue', 'unclassified'])
        self.assertEqual([r['label'] for r in body['graph']['roles']], ['Nora'])
        self.assertTrue(all(e['kind'] == 'sequence' for e in body['graph']['edges']))
        self.assertEqual(self.run_command('import', self.at)['status'], 'REPLAYED')
        self.commands = EpisodeCommands(TimelineStore(self.path))
        exported = self.run_command('export', self.scope | {'fragment': body['id']})
        self.assertEqual(exported['fragment'], body)
        self.assertEqual(self.run_command('import', self.at | {'declaration': body['declaration']})['fragment'], body)
        self.assertEqual(self.timeline.get_episode('one')['script'], TEXT)
        self.assertEqual(self.timeline.get_episode('one')['head'], 1)

    def test_rebind_keeps_ids_across_unicode_and_crlf_shift(self):
        prior = self.run_command('import', self.at)['fragment']
        prefix = 'Before an unrelated section 🦊.\r\n\r\n'
        now = prefix + TEXT
        self.timeline.save('one', 1, script=now, source_name='fixture-original')
        target = self.scope | {'fragment': prior['id'], 'fragment_revision': 1}
        self.assertTrue(self.run_command('open', target)['needs_rebind'])
        res = self.run_command('rebind', target | {'timeline_revision': 2})
        rebased = res['fragment']
        self.assertEqual(res['status'], 'REBOUND')
        self.assertEqual(rebased['revision'], 2)
        self.assertEqual(rebased['remap']['delta'], len(prefix))
        self.assertEqual(rebased['anchor']['text_sha256'], prior['anchor']['text_sha256'])
        for a, b in zip(prior['graph']['passages'], rebased['graph']['passages']):
            self.assertEqual(a['id'], b['id'])
            self.assertEqual(a['sha256'], digest(now[b['start']:b['end']]))
        for key in ('nodes', 'roles', 'edges'):
            self.assertEqual(rebased['graph'][key], prior['graph'][key])
        self.assertEqual(self.run_command('export', target)['fragment'], prior)
        self.assertEqual(self.run_command('rebind', target | {'timeline_revision': 2})['status'], 'UNCHANGED')
        self.reason('stale_timeline', 'rebind', target | {'timeline_revision': 1})
        self.reason('wrong_scope', 'open', target | {'branch': 'wrong-branch'})

    def test_import_preserves_typed_speaker_boundaries_inside_one_paragraph(self):
        source = TEXT.replace('Nora: Keep this.', '“Keep this.”A mug fell.')
        self.timeline.save('one', 1, script=source, source_name='fixture-original')
        books = NotebookStore(self.timeline)
        saved = books.open('one')
        before, _, after = source.partition('“Keep this.”A mug fell.')
        parts = [('narrator', None, before), ('character', 'nora', '“Keep this.”'),
                 ('narrator', None, 'A mug fell.' + after)]
        new = [{'id': f'cue-fixture-{i}', 'kind': kind, 'speaker': speaker, 'form': None, 'text': text}
               for i, (kind, speaker, text) in enumerate(parts)]
        books.save('one', saved['revision'], saved['timeline_revision'], new,
                   saved['default_protection'], saved['masks'])
        graph = self.run_command('preview', self.at | {'timeline_revision': 2})['fragment']['graph']
        dialogue = next(node for node in graph['nodes'] if node['kind'] == 'dialogue')
        picked = next(p for p in graph['passages'] if p['id'] == dialogue['passage'])
        self.assertEqual(source[picked['start']:picked['end']], '“Keep this.”')
        self.assertEqual(graph['roles'][0]['character_hint'], 'nora')

    def test_rebind_rejects_both_edited_and_ambiguous_scene(self):
        prior = self.run_command('import', self.at)['fragment']
        a = prior['anchor']
        target = self.scope | {'fragment': prior['id'], 'fragment_revision': 1}
        selected = TEXT[a['start']:a['end']]
        self.timeline.save('one', 1, script=TEXT.replace('A mug', 'A bowl'), source_name='fixture-original')
        self.reason('changed_anchor', 'rebind', target | {'timeline_revision': 2})
        self.timeline.save('one', 2, script=TEXT + '\r\n' + selected, source_name='fixture-original')
        self.reason('ambiguous_anchor', 'rebind', target | {'timeline_revision': 3})
        self.assertEqual(self.run_command('open', self.scope | {'fragment': prior['id']})['fragment'], prior)

    def test_anchor_cannot_jump_to_a_surviving_original_duplicate(self):
        picked = self.run_command('preview', self.at)['fragment']['anchor']
        source = TEXT[picked['start']:picked['end']]
        self.timeline.save('one', 1, script=TEXT + '\r\n' + source, source_name='fixture-original')
        selected = self.run_command('import', self.at | {'timeline_revision': 2})['fragment']
        now = TEXT.replace('A mug', 'A bowl') + '\r\n' + source
        self.timeline.save('one', 2, script=now, source_name='fixture-original')
        self.reason('ambiguous_anchor', 'rebind', self.scope | {'fragment': selected['id'],
                    'fragment_revision': 1, 'timeline_revision': 3})

    def test_declarative_evidence_checks_and_rollback(self):
        spec = self.run_command('preview', self.at)['fragment']['declaration']
        clip = {'id': 'fusion', 'asset': 'complete-cutaway', 'sha256': 'a'*64, 'use': 'structure',
                'selector': {'kind': 'clip', 'clock': 'file_pts', 'track': 'video-0', 'unit': 'ms',
                             'start': 117400, 'end': 117500}}
        spec['evidence'] = [clip]
        spec['nodes'].append({'id': 'reference', 'kind': 'reference', 'label': 'Fusion', 'passage': None,
                              'roles': [], 'evidence': ['fusion']})
        spec['edges'].append({'from': 'reference', 'to': 'n2', 'kind': 'influences'})
        self.reason('unregistered_evidence', 'import', self.at | {'declaration': spec})
        SceneFragmentStore(self.timeline).register_evidence(self.scope, [clip])
        for field, value, reason in (('sha256', 'b'*64, 'wrong_edition'),
                                     ('selector', clip['selector'] | {'start': 13666, 'end': 13766}, 'selector_mismatch')):
            invalid = deepcopy(spec)
            invalid['evidence'][0][field] = value
            self.reason(reason, 'import', self.at | {'declaration': invalid})
        invalid = deepcopy(spec)
        invalid['edges'][-1]['to'] = 'unknown'
        self.reason('unknown_reference', 'import', self.at | {'declaration': invalid})
        invalid = deepcopy(spec)
        invalid['edges'][-1]['kind'] = 'causes'
        self.reason('reference_effect', 'import', self.at | {'declaration': invalid})
        invalid = deepcopy(spec)
        invalid['edges'].append({'from': 'n1', 'to': 'n3', 'kind': 'requires'})
        self.reason('causal_cycle', 'import', self.at | {'declaration': invalid})
        self.assertFalse(self.db_has_fragments())
        result = self.run_command('import', self.at | {'declaration': spec})
        self.assertEqual(result['fragment']['declaration']['evidence'], [clip])
        with self.timeline._connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_picked_text_cannot_split_crlf_or_use_changed_receipt(self):
        self.reason('partial_line', 'preview', self.at | {'selection': {'start': TEXT.index('\n'), 'end': len(TEXT)}})
        spec = self.run_command('preview', self.at)['fragment']['declaration']
        spec['passages'][0]['sha256'] = '0'*64
        self.reason('passage_mismatch', 'import', self.at | {'declaration': spec})
        self.assertFalse(self.db_has_fragments())
