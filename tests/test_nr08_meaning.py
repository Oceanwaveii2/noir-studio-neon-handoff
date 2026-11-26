import copy
import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from prose_engine.meaning_checks import assess_meaning
from prose_engine.notebook import DraftStore, NotebookStore
from prose_engine.scoped_pipeline import build_packet, generate, validate_output
from prose_engine.scoped_service import execute_scoped
from story_graph.episode_timeline import TimelineStore
from tools.evaluate_meaning import evaluate


class Provider:
    def __init__(self,text):self.text=text;self.calls=0
    def generate_rewrite(self,request,prompt):self.calls+=1;return self.text


class MeaningChecksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'timeline.sqlite';self.store=TimelineStore(self.path)
        self.store.add_starter_cards();self.store.save('spring-break',0,script='A quiet room.',source_name='fixture')
        self.store.add_event('future','tapped-out',1,'A secret future star appears.',status='approved',permitted=True,source_id='future-fixture',reviewer='author')
        self.store.add_event('private','spring-break',1,'Roger privately discovers the hidden clue.',status='approved',permitted=True,source_id='private-fixture',reviewer='author',viewpoint='roger')
        self.packet=build_packet(self.store,'spring-break',1,1,0,13)

    def test_labeled_development_results_publish_misses_and_uncertainty(self):
        report=evaluate()
        self.assertEqual(report['sample_count'],36);self.assertEqual(report['provider_calls'],0)
        self.assertEqual(report['contradiction_false_positives'],[])
        self.assertEqual(report['contradiction_false_negatives_including_abstentions'],['p05','p06','p07','p08'])
        rows={row['id']:row for row in report['rows']}
        for ident in ('b03','q03','j02'):self.assertEqual(rows[ident]['actual'],'uncertain')
        self.assertEqual(rows['s01']['actual'],'unavailable')
        self.assertNotEqual(rows['f01']['actual'],'supported');self.assertEqual(rows['f02']['actual'],'supported')
        self.assertEqual(rows['k01']['actual'],'unavailable');self.assertEqual(rows['k02']['actual'],'supported')
        self.assertTrue(report['confidence_note'].startswith('Development-set'))

    def test_quotation_rumor_and_joke_do_not_hard_block(self):
        for text in ["Haley's father was only a rumor.",'The note read, ‘Haley has a father.’','Roger joked that Haley has a father.']:
            with self.subTest(text=text):
                self.assertEqual(validate_output(self.packet,text),[])
                assessment=assess_meaning(self.packet,text)
                self.assertEqual(assessment['status'],'uncertain')
                self.assertEqual(assessment['findings'][0]['rule_source'],'author-context:haley-parentage')

    def test_no_match_is_unavailable_not_approved(self):
        result=assess_meaning(self.packet,'The kitchen fell silent.')
        self.assertEqual(result['status'],'unavailable');self.assertFalse(result['canonical_write'])
        self.assertIn('not verified',result['assessment_scope']);self.assertEqual(result['coverage']['semantic_verifier'],'not_configured')
        miss=assess_meaning(self.packet,'A man sired Haley.')
        self.assertNotEqual(miss['status'],'supported');self.assertNotEqual(miss['status'],'contradicted')
        for text in ('Haley has no father figure.','Haley does not have a father-in-law.'):
            self.assertNotEqual(assess_meaning(self.packet,text)['status'],'supported')

    def test_evidence_and_scope_exclude_future_and_private_events(self):
        result=assess_meaning(self.packet,'Haley has a father.')
        self.assertEqual(result['status'],'contradicted')
        self.assertEqual(result['findings'][0]['rule_source'],'author-context:haley-parentage')
        self.assertEqual(result['scope']['episode'],'spring-break');self.assertEqual(result['scope']['beat'],1)
        self.assertNotIn('secret future star',json.dumps(result));self.assertNotIn('privately discovers',json.dumps(result))

    def test_typed_claim_evidence_is_not_automatic_prose_extraction(self):
        claim={'kind':'world_fact','subject':'haley','predicate':'father','value':'stan','assertion':'fact','source_id':'fixture:claim'}
        before=self.store.get_episode('spring-break')
        result=assess_meaning(self.packet,'The room is quiet.',[claim])
        item=next(f for f in result['findings'] if f['method']=='structured_claim')
        self.assertEqual(item['status'],'contradicted');self.assertEqual(item['claim_source'],'fixture:claim')
        self.assertEqual(item['rule_source'],'author-context:haley-parentage')
        self.assertEqual(self.store.get_episode('spring-break'),before)
        claim['assertion']='belief';result=assess_meaning(self.packet,'The room is quiet.',[claim])
        self.assertEqual(result['status'],'uncertain')

    def test_validation_and_draft_persist_evidence_without_extra_calls(self):
        book=NotebookStore(self.store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
        req={'episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,'provider':'codex-session'}
        p=Provider('Roger joked that Haley has a father.')
        result=execute_scoped(self.store,'generate',req,provider_factory=lambda:p)
        self.assertEqual(result['status'],'PROPOSED');self.assertEqual(result['meaning']['status'],'uncertain')
        self.assertEqual(p.calls,1)
        draft=DraftStore(NotebookStore(TimelineStore(self.path))).open('spring-break','main',result['draft_id'])
        self.assertEqual(draft['meaning_evidence'],result['meaning'])
        check=execute_scoped(self.store,'validate',{**req,'text':'A man sired Haley.'},provider_factory=lambda:p)
        self.assertEqual(check['meaning']['status'],'unavailable');self.assertEqual(p.calls,1)
        self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')

    def test_strong_typed_conflict_and_exact_copy_guards_are_distinct(self):
        claim={'kind':'world_fact','subject':'haley','predicate':'father','value':'stan','assertion':'fact','source_id':'fixture:claim'}
        req={'episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,'claims':[claim]}
        result=execute_scoped(self.store,'validate',req)
        self.assertEqual(result['issues'][0]['status'],'conflict');self.assertEqual(result['meaning']['status'],'contradicted')
        protected=build_packet(self.store,'spring-break',1,1,0,13,protected_ranges=[[2,7]])
        locked=generate(protected,Provider('A noisy hall.'))
        self.assertEqual(locked['status'],'BLOCKED');self.assertEqual(locked['meaning']['status'],'unavailable')
        phrase='Seven silver birds flew quietly over the silent garden wall.'
        copied=generate(self.packet,Provider(phrase),references=[phrase])
        self.assertEqual(copied['status'],'PROPOSED')
        self.assertEqual(copied['meaning']['status'],'unavailable')

    def test_changed_rule_and_sibling_sources_do_not_get_invented(self):
        report=evaluate();rows={r['id']:r for r in report['rows']}
        for ident in ('f01','s01','k01'):
            self.assertEqual(rows[ident]['actual'],'unavailable')
            self.assertFalse(any(f['rule_source'] for f in rows[ident]['findings']))
        self.assertEqual(rows['f02']['findings'][0]['rule_source'],'fixture:host-after-beat-five')
        self.assertEqual(rows['k02']['findings'][0]['rule_source'],'fixture:clue-after-beat-five')

    def test_studio_validation_exposes_unavailable_without_provider(self):
        from tools.studio_ui import StudioRequestHandler
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=self.path;server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        body={'action':'validate','episode':'spring-break','beat':1,'revision':1,'start':0,'end':13,'text':'A man sired Haley.'}
        request=urllib.request.Request(base+'/api/scoped',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
        try:
            with urllib.request.urlopen(request) as response:result=json.load(response)
            self.assertEqual(result['meaning']['status'],'unavailable')
            self.assertEqual(result['meaning']['coverage']['semantic_verifier'],'not_configured')
            self.assertEqual(self.store.get_episode('spring-break')['script'],'A quiet room.')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
