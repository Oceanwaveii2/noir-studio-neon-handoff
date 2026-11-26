import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from story_graph.episode_timeline import TimelineStore
from story_graph.world_laws import WorldLawStore
from prose_engine.scoped_pipeline import build_packet, diagnose_output, prompt_for, validate_claims, validate_output


def fact(subject='haley',predicate='father',value='stan',assertion='fact'):
    return {'kind':'world_fact','subject':subject,'predicate':predicate,'value':value,
            'assertion':assertion,'source_id':'fixture-claim'}


def constraint(kind='relationship',subject='alice',predicate='partner',allowed=None,branch='*',start=None,end=None):
    return {'kind':kind,'subject':subject,'predicate':predicate,'allowed_values':allowed or [],
            'source_id':'fixture-author','authority':'author','branch':branch,
            'valid_from':start,'valid_until':end,'exceptions':[]}


def law(item):
    return {'id':'fixture-law','name':'Fixture','statement':'Fixture rule','enabled':True,
            'matcher':'typed','phrases':[],'constraints':[item]}


class StructuredLawsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=TimelineStore(Path(self.tmp.name)/'timeline.sqlite');self.store.add_starter_cards()
        self.store.save('spring-break',0,script='A quiet room.',source_name='fixture')
        self.world=WorldLawStore(self.store)

    def packet(self,episode='spring-break',beat=1):
        return build_packet(self.store,episode,beat,1,0,13)

    def test_world_law_undo_redo_survives_reopen(self):
        initial=self.world.open();changed=copy.deepcopy(initial['laws']);changed[0]['name']='Changed name'
        saved=self.world.save(initial['revision'],changed)
        undone=self.world.undo(saved['revision']);self.assertEqual(undone['laws'],initial['laws'])
        again=WorldLawStore(TimelineStore(self.store.path)).redo(undone['revision'])
        self.assertEqual(again['laws'],changed)
        with self.assertRaises(ValueError):self.world.redo(undone['revision'])

    def test_parentage_structured_and_source_evidence(self):
        p=self.packet()
        issue=validate_claims(p,[fact()])[0]
        self.assertEqual(issue['status'],'conflict');self.assertEqual(issue['rule_id'],'haley-parentage')
        self.assertEqual(issue['rule_source'],'author-context:haley-parentage')
        self.assertEqual(issue['claim_source'],'fixture-claim');self.assertEqual(issue['law_revision'],0)
        self.assertEqual(validate_claims(p,[fact(predicate='mother',value='francine')]),[])
        self.assertEqual(validate_claims(p,[fact(predicate='mother',value='rainee')]),[])
        self.assertEqual(validate_claims(p,[fact(value='none')]),[])
        self.assertEqual(validate_claims(p,[fact(assertion='belief')])[0]['status'],'uncertain')
        self.assertEqual(validate_claims(p,[fact(assertion='source_quote')])[0]['status'],'uncertain')
        self.assertEqual(validate_claims(p,[fact(subject='francine')])[0]['status'],'uncertain')

    def test_text_conflict_negation_quotation_and_other_father(self):
        p=self.packet()
        self.assertTrue(validate_output(p,"Haley's father arrived."))
        self.assertTrue(validate_output(p,'Haley has a father.'))
        for text in ["Haley's father does not exist.", 'Haley does not have a father.',
                     'Francine visited her adoptive father.',
                     "Haley's father-in-law arrived.", "Haley's father figure arrived.",
                     'In American Dad, Haley has a father.',
                     'Roger said, "Haley has a father."',
                     "Roger said, 'Haley has a father.'",
                     "Roger assumed Haley's father was Stan.",
                     'Haley believes Haley has a father.']:
            with self.subTest(text=text): self.assertEqual(validate_output(p,text),[])
        self.assertEqual(diagnose_output(p,'In American Dad, Haley has a father.')[0]['status'],'uncertain')

    def test_legacy_rules_are_compiled_without_rewriting_history(self):
        current=self.world.open(); old=copy.deepcopy(current['laws']);old[0].pop('constraints')
        self.world.save(0,old)
        p=self.packet();self.assertEqual(validate_claims(p,[fact()])[0]['status'],'conflict')
        self.assertNotIn('constraints',self.world.open()['laws'][0])
        self.assertEqual(self.world.undo(1)['laws'],current['laws'])

    def test_typed_constraints_validate_types_exceptions_and_staleness(self):
        for kind in ('identity','parentage','relationship','transformation','chronology','location','knowledge'):
            with self.subTest(kind=kind):
                item=constraint(kind=kind,allowed=['bob']); item['exceptions']=['carol']
                current=self.world.open();self.world.save(current['revision'],current['laws'][:1]+[law(item)])
                p=self.packet()
                self.assertEqual(validate_claims(p,[fact('alice','partner','bob')]),[])
                self.assertEqual(validate_claims(p,[fact('alice','partner','carol')]),[])
                self.assertEqual(validate_claims(p,[fact('alice','partner','dan')])[0]['status'],'conflict')
        with self.assertRaisesRegex(ValueError,'Stale'):
            self.world.save(0,self.world.open()['laws'])
        with self.assertRaisesRegex(ValueError,'unknown branch'):
            self.world.save(self.world.open()['revision'],[law(constraint(branch='does-not-exist'))])

    def test_time_and_branch_inheritance_freeze_at_fork(self):
        item=constraint(branch='main',start=[10,5],end=[10,10])
        self.world.save(0,self.world.open()['laws']+[law(item)])
        self.store.fork('early','main','spring-break',4)
        self.store.fork('during','main','spring-break',7)
        self.store.fork('late','main','spring-break',11)
        for branch in ('early','during','late'):
            self.store.create_episode(branch+'-episode',branch,branch,0)
            self.store.save(branch+'-episode',0,script='A quiet room.',source_name='fixture')
        for episode,beat,status in [('spring-break',4,'uncertain'),('spring-break',5,'conflict'),
                                    ('spring-break',11,'uncertain'),('early-episode',20,'uncertain'),
                                    ('during-episode',20,'conflict'),('late-episode',20,'uncertain')]:
            with self.subTest(episode=episode,beat=beat):
                self.assertEqual(validate_claims(self.packet(episode,beat),[fact('alice','partner','dan')])[0]['status'],status)
        self.assertNotIn('fixture-author',prompt_for(self.packet('spring-break',4)))
        self.assertIn('fixture-author',prompt_for(self.packet('spring-break',5)))

    def test_other_universe_does_not_inherit_parentage(self):
        other=TimelineStore(Path(self.tmp.name)/'other.sqlite')
        other.create_episode('other','Other','main',1);other.save('other',0,script='A quiet room.',source_name='fixture')
        p=build_packet(other,'other',0,1,0,13)
        self.assertEqual(validate_claims(p,[fact()])[0]['status'],'uncertain')
        self.assertEqual(validate_output(p,"Haley's father arrived."),[])

    def test_http_structured_claim_uses_same_snapshot_and_reports_evidence(self):
        from tools.studio_ui import StudioRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=Path(self.store.path);server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        req={'action':'validate','episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,
             'claims':[fact()]}
        request=urllib.request.Request(base+'/api/scoped',data=json.dumps(req).encode(),
                                      headers={'Content-Type':'application/json','Origin':base})
        try:
            with urllib.request.urlopen(request) as response: result=json.load(response)
            self.assertEqual(result['issues'][0]['rule_id'],'haley-parentage')
            self.assertEqual(result['issues'][0]['law_revision'],result['context']['world_law_revision'])
        finally:
            server.shutdown();server.server_close();thread.join()


class WorldLawsPageAndTypedSaveTests(unittest.TestCase):
    def test_world_laws_page_serves_structured_constraint_ui_and_typed_round_trip(self):
        import json
        import re
        import subprocess
        import tempfile
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from pathlib import Path
        from story_graph.episode_timeline import TimelineStore
        from tools.studio_ui import StudioRequestHandler

        with tempfile.TemporaryDirectory() as tmp:
            timeline_path = Path(tmp) / 'timeline.sqlite'
            TimelineStore(timeline_path)
            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = timeline_path
            server.timeline_only = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)

            def post(payload):
                req = urllib.request.Request(
                    base + '/api/world-laws',
                    data=json.dumps(payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json', 'Origin': base},
                )
                with urllib.request.urlopen(req) as resp:
                    return json.load(resp)

            try:
                with urllib.request.urlopen(base + '/world-laws') as resp:
                    self.assertEqual(resp.status, 200)
                    html = resp.read().decode('utf-8')
                for marker in ('id="lawMatcher"', 'id="lawConstraintsFieldset"', 'id="lawConstraintsList"', 'id="addConstraint"', 'haley_parentage', 'typed'):
                    self.assertIn(marker, html)
                scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, flags=re.S | re.I)
                self.assertTrue(scripts)
                js_path = Path(tmp) / 'world_laws_check.js'
                js_path.write_text('\n'.join(scripts), encoding='utf-8')
                checked = subprocess.run(['node', '--check', str(js_path)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

                opened = post({'action': 'open'})
                typed_law = {
                    'id': 'partner-law',
                    'name': 'Partner bond law',
                    'statement': 'Alice is partnered only with Bob.',
                    'enabled': True,
                    'matcher': 'typed',
                    'phrases': [],
                    'constraints': [{
                        'kind': 'relationship',
                        'subject': 'alice',
                        'predicate': 'partner',
                        'allowed_values': ['bob'],
                        'exceptions': [],
                        'branch': '*',
                        'valid_from': [1, 0],
                        'valid_until': None,
                        'authority': 'author',
                        'source_id': 'author-note-1',
                    }],
                }
                saved = post({'action': 'save', 'revision': opened['revision'], 'laws': opened['laws'] + [typed_law]})
                reopened = post({'action': 'open'})
                self.assertEqual(reopened['revision'], saved['revision'])
                partner = next(law for law in reopened['laws'] if law['id'] == 'partner-law')
                self.assertEqual(partner['matcher'], 'typed')
                self.assertEqual(partner['constraints'], typed_law['constraints'])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__=='__main__': unittest.main()
