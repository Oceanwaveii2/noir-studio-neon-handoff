"""Closed transitions, branch isolation and deterministic replay receipts."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore
from story_graph.episode_timeline import TimelineStore
from story_graph.fx06_scene import PETER
from story_graph.scene_fragments import SceneFragmentError, SceneFragmentStore, digest
from story_graph.scene_override import SceneReplayStore
from story_graph.world_laws import WorldLawStore


LINE = 'Is that floral perfume?'
TEXT = ('INT. HALL\n\nA scent leaves the source room.\n\nHaley: ' + LINE + '\n\n'
        'The root splits.\n\nFrancine calls them back. They reunite.\n\nThe later form takes over.\n')
CLIP = {'id': 'fusion', 'asset': 'fixture-clip', 'sha256': 'a'*64, 'use': 'structure',
        'selector': {'kind': 'clip', 'clock': 'file_pts', 'track': 'video-0', 'unit': 'ms', 'start': 900, 'end': 1000}}


class SceneOverrideTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'timeline.sqlite'
        self.timeline = TimelineStore(self.path, project_id='test-project', universe_id='test-world')
        self.timeline.create_episode('scene-test', 'Scene', 'main', 1)
        self.timeline.save('scene-test', 0, script=TEXT, source_name='authored fixture')
        self.laws = WorldLawStore(self.timeline)
        self.commands = EpisodeCommands(self.timeline)
        self.scope = {'project': 'test-project', 'universe': 'test-world', 'episode': 'scene-test', 'branch': 'main'}
        notebook = NotebookStore(self.timeline)
        original = notebook.open('scene-test')
        index = TEXT.index(LINE)
        lock = {'id': 'exact-response', 'start': index, 'end': index+len(LINE), 'value': 100,
                'hard': True, 'sha256': digest(LINE)}
        notebook.save('scene-test', original['revision'], 1, original['blocks'], 100, [lock])
        selection = self.scope | {'timeline_revision': 1, 'selection': {'start': 0, 'end': len(TEXT)}}
        declaration = self.commands.execute('scene.fragment.preview', selection)['fragment']['declaration']
        declaration['evidence'] = [CLIP]
        declaration['nodes'].append({'id': 'reference', 'kind': 'reference', 'label': 'Clip',
                                     'passage': None, 'roles': [], 'evidence': ['fusion']})
        declaration['edges'] += [{'from': 'reference', 'to': name, 'kind': 'influences'} for name in ('n4','n5')]
        SceneFragmentStore(self.timeline).register_evidence(self.scope, [CLIP])
        self.graph = self.commands.execute('scene.fragment.import', selection | {'declaration': declaration})['fragment']
        self.nodes = {n['key']:n['id'] for n in self.graph['graph']['nodes']}
        self.base = self.scope | {'fragment': self.graph['id'], 'fragment_revision': 1,
                                  'timeline_revision': 1, 'law_revision': 0}

    def setup_profile(self, count=3, *, name='base', air=True, observer='hall'):
        data = {'schema_version': 1, 'id': name, 'root': 'rainee', 'cutoff': 0,
                'locations': ['room', 'hall', 'outside', 'far-hall'],
                'actors': [{'id':'rainee','location':'room'}, {'id':'haley','location':observer},
                           {'id':'francine','location':'hall'}],
                'portals': [{'id':'gap','from':'room','to':'hall','allows_scent':air,'allows_sound':True,'permeability':.7}],
                'members': [{'id':f'part-{i}','mind':f'mind:{i}'} for i in range(1,count+1)],
                'interveners': ['francine'], 'anchors': {'split':self.nodes['n4'],'rejoin':self.nodes['n5'],
                                                        'transform': {PETER:self.nodes['n6']}},
                'protected_line': {'lock':'exact-response','speaker':'haley','node':self.nodes['n3']},
                'emission': {'form':'rainee','strength':{'normal':'floral','severe':'overpowering-floral'}},
                'force': {'form':PETER,'recipient':'haley','visible_from':['hall'],'destination':'far-hall'},
                'patterns': [{'id':'fusion','shape':'many_to_one','arity':3}]}
        SceneReplayStore(self.timeline).install_profile(self.base, data)
        return data

    def plan(self, count=3, pattern=True):
        def ev(ident, node, op, actor, args=None, after=()):
            return {'id':ident,'node':self.nodes[node],'op':op,'actor':actor,'after':list(after),'args':args or {}}
        events = [ev('first-release','n2','release','rainee',{'severity':'severe'}),
                  ev('notice','n2','notice','haley',{'release':'first-release'}),
                  ev('line','n3','line','haley',{'observation':'notice'}),
                  ev('split','n4','pattern_slot' if pattern else 'split','rainee',
                     {'members':[f'part-{i}' for i in range(1,count+1)]}),
                  ev('rejoin','n5','pattern_slot' if pattern else 'rejoin','rainee',{'intervention':'intervention'}),
                  ev('transform','n6','transform','rainee',{'avatar_id':PETER}),
                  ev('second-release','n6','release','rainee',{'severity':'severe'},['transform']),
                  ev('reaction','n6','force','haley',{'release':'second-release'})]
        intervention = ev('intervention','n5','intervene','francine')
        if not pattern:
            return {'schema_version':1,'events':events+[intervention],'overrides':[]}
        return {'schema_version':1,'events':events,'overrides':[
            {'id':'reverse','mode':'borrow_pattern','operator':'invert_merge','evidence':'fusion','at':'split'},
            {'id':'call','mode':'insert_event','event':intervention},
            {'id':'restore','mode':'borrow_pattern','operator':'reuse_merge','evidence':'fusion','at':'rejoin'},
            {'id':'screen','mode':'present','evidence':'fusion','at':'split'},
        ]}

    def replay(self, mode, recipe=None, profile='base', **changes):
        req = self.base | {'profile':profile} | changes
        if recipe is not None:
            req['recipe'] = recipe
        return self.commands.execute('scene.override.'+mode, req)

    def reject(self, code, recipe, profile='base', **changes):
        with self.assertRaises(SceneFragmentError) as expected:
            self.replay('replay', recipe, profile, **changes)
        self.assertEqual(expected.exception.code, code)

    def test_cutaway_shape_feeds_destination_world_and_audience_cue_is_inert(self):
        self.setup_profile()
        plan = self.plan()
        a = self.replay('preview', plan)['receipt']
        without = deepcopy(plan)
        without['overrides'].pop()
        b = self.replay('preview', without)['receipt']
        self.assertEqual(a['frames'], b['frames'])
        self.assertEqual(a['world_sha256'], b['world_sha256'])
        self.assertEqual(len(a['presentation']), 1)
        self.assertEqual(b['presentation'], [])
        self.assertEqual(self.replay('list')['receipts'], [])
        frames = {f['event']:f for f in a['frames']}
        self.assertEqual(frames['line']['effects'][0]['protected_line']['sha256'], digest(LINE))
        self.assertEqual(frames['notice']['state']['knowledge'],
                         {'rainee':[],'haley':['scent-first-release'],'francine':[]})
        self.assertEqual(len(frames['split']['state']['manifestations']), 3)
        self.assertNotIn('rainee', frames['split']['state']['actors'])
        self.assertEqual(frames['rejoin']['state']['manifestations'], [])
        self.assertEqual(frames['rejoin']['state']['root_form'], 'rainee')
        split_index = next(i for i,f in enumerate(a['frames']) if f['event']=='transform')
        self.assertNotIn(PETER, str(a['frames'][:split_index]))
        self.assertEqual(frames['transform']['state']['root_form'], PETER)
        self.assertFalse(frames['first-release']['effects'][0]['release']['force'])
        second = frames['second-release']['effects'][0]['release']
        self.assertIsNone(second['scent']); self.assertTrue(second['force'])
        self.assertEqual(frames['reaction']['state']['actors']['haley']['location'], 'far-hall')

    def test_four_way_is_driven_by_the_profile_and_receipt_reopens(self):
        self.setup_profile(4)
        plan = self.plan(4, pattern=False)
        first = self.replay('replay', plan)
        again = self.replay('replay', plan)
        self.assertEqual([first['status'],again['status']], ['SAVED','REPLAYED'])
        self.assertEqual(first['receipt'],again['receipt'])
        frames = {f['event']:f['state'] for f in first['receipt']['frames']}
        self.assertEqual([x['mind'] for x in frames['split']['manifestations']], ['mind:1','mind:2','mind:3','mind:4'])
        self.assertTrue(all(frames['split']['knowledge'][f'part-{i}']==[] for i in range(1,5)))
        self.assertFalse(set(frames['rejoin']['actors']) & {f'part-{i}' for i in range(1,5)})
        fresh = EpisodeCommands(TimelineStore(self.path))
        got = fresh.execute('scene.override.open', self.scope | {'receipt':first['receipt']['id']})
        self.assertEqual(got['receipt'],first['receipt'])
        self.assertEqual(self.timeline.get_episode('scene-test')['script'],TEXT)
        with self.timeline._connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],0)

    def test_bad_path_and_unavailable_observer_do_not_commit_replay(self):
        self.setup_profile(name='blocked', air=False)
        self.setup_profile(name='away', observer='outside')
        for profile in ('blocked','away'):
            self.reject('blocked_transition', self.plan(), profile)
        self.assertEqual(self.replay('list')['receipts'],[])

    def test_wrong_time_missing_reunion_and_unresolved_pattern_fail_closed(self):
        self.setup_profile()
        direct = self.plan(pattern=False)
        next(row for row in direct['events'] if row['id']=='transform')['node'] = self.nodes['n4']
        self.reject('early_form', direct)
        direct = self.plan(pattern=False)
        direct['events'] = [s for s in direct['events'] if s['id'] not in ('rejoin','intervention')]
        self.reject('blocked_transition', direct)
        plan = self.plan()
        plan['overrides'].pop(0)
        self.reject('unresolved_slot', plan)
        self.reject('pattern_arity', self.plan(count=4))
        self.assertEqual(self.replay('list')['receipts'],[])

    def test_scope_law_revision_and_branch_isolation(self):
        self.setup_profile()
        program = self.plan()
        receipt = self.replay('replay', program)['receipt']
        self.timeline.fork('alternate','main','scene-test',0)
        self.timeline.create_episode('alternate-scene','Alt','alternate',2)
        with self.assertRaisesRegex(SceneFragmentError,'not saved'):
            self.commands.execute('scene.override.open', self.scope | {'receipt':receipt['id'],
                                   'branch':'alternate','episode':'alternate-scene'})
        self.laws.save(0,[])
        self.reject('stale_laws', program)
        self.reject('wrong_scope', program, branch='alternate')
        self.assertEqual(self.replay('preview', law_revision=1)['receipt']['frames'][0]['state']['root_form'],'rainee')
