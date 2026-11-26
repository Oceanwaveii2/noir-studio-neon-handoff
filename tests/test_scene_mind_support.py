"""The active form, not a graph preview or a donor clip, owns its signature."""
import sqlite3
import unittest

from prose_engine import scene_mind_support as minds
from story_graph import scene_fragments as f


class SceneMindSupportTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:'); self.c.row_factory=sqlite3.Row; self.addCleanup(self.c.close)
        self.scope={'episode':'split','branch':'main','project':'p','universe':'u','scope_revision':1}
        rules=[{'form':f'rainee-split-{i}','mind':f'mind-{i}','speaker':f'Rainee {i}','scent':s} for i,s in
               enumerate(('tuberose','orange','sandalwood'),1)]
        self.cast=[{'form_id':r['form'],'node_id':r['mind']} for r in rules]
        body={'scope':self.scope,'rules':rules,'library':{'items':[{'clip':'timed','writing_eligible':True},
                                                                  {'clip':'audition','writing_eligible':False}]}}
        raw=f.encoded(body)
        self.c.execute('CREATE TABLE scene_mind_support(episode,payload,sha256)')
        self.c.execute('INSERT INTO scene_mind_support VALUES(?,?,?)',('split',raw,f.digest(raw)))
        self.active=minds.project(self.c,self.scope,'split',self.cast)

    def test_exact_active_forms_and_scope(self):
        self.assertIsNone(minds.project(self.c,self.scope,'rainee',self.cast))
        self.assertIsNone(minds.project(self.c,self.scope,'peter',self.cast))
        self.assertIsNone(minds.project(self.c,self.scope|{'branch':'alt'},'split',self.cast))
        self.assertEqual([r['scent'] for r in self.active['rules']],['tuberose','orange','sandalwood'])
        someone_else=[self.cast[0]|{'node_id':'previewed-mind'},*self.cast[1:]]
        self.assertEqual([r['scent'] for r in minds.project(self.c,self.scope,'split',someone_else)['rules']],
                         ['orange','sandalwood'])

    def test_explicit_personal_releases_cannot_swap_scents(self):
        lines=('Rainee 1: Clear.\nAction: She farts; tuberose.\n'
               'Rainee 2: Objection.\nAction: A pfft brings orange.\n'
               'Rainee 3: Check the fan.\nAction: A toot carries sandalwood.')
        self.assertFalse(minds.validate_output(self.active,lines,exercise=True))
        self.assertFalse(minds.validate_output(self.active,lines.replace('A toot carries','A quick squeak brings'),exercise=True))
        self.assertTrue(minds.validate_output(self.active,lines.replace('A toot carries','The indicator squeaks beside the'),exercise=True))
        swapped=lines.replace('tuberose','orange')
        self.assertEqual(len(minds.validate_output(self.active,swapped)),1)
        ambient=lines.replace('She farts; tuberose.','She gestures at the orange-painted door.')
        self.assertFalse(minds.validate_output(self.active,ambient))
        self.assertTrue(minds.validate_output(self.active,ambient,exercise=True))

    def test_reference_authority_is_timing_only(self):
        self.assertTrue(minds.allowed_use(self.c,self.scope,'timed','timing'))
        self.assertFalse(minds.allowed_use(self.c,self.scope,'timed','personality'))
        self.assertFalse(minds.allowed_use(self.c,self.scope,'timed','cutaway'))
        self.assertFalse(minds.allowed_use(self.c,self.scope,'audition','timing'))
