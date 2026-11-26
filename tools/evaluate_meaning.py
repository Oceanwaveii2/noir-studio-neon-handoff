"""Evaluate scoped meaning diagnostics on synthetic fixtures; never calls a model."""
from __future__ import annotations
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from story_graph.episode_timeline import TimelineStore
from story_graph.world_laws import WorldLawStore
from prose_engine.meaning_checks import assess_meaning
from prose_engine.scoped_pipeline import build_packet

FIXTURE=ROOT/'tests/fixtures/nr08_meaning_cases.json'


def evaluate():
    cases=json.loads(FIXTURE.read_text(encoding='utf-8-sig'))['cases']
    with tempfile.TemporaryDirectory() as temp:
        store=TimelineStore(Path(temp)/'timeline.sqlite');store.add_starter_cards()
        for episode in ('spring-break','tapped-out'):
            store.save(episode,0,script='A quiet room.',source_name='synthetic-source')
        store.add_event('secret-future','tapped-out',1,'A confidential future clue appears.',status='approved',permitted=True,source_id='fixture:future',reviewer='author')
        store.add_event('private-clue','spring-break',5,'Roger learns a private clue.',status='approved',permitted=True,viewpoint='roger',source_id='fixture:private',reviewer='author')
        store.fork('sibling','main','spring-break',2);store.create_episode('sibling-story','Sibling story','sibling',0)
        store.save('sibling-story',0,script='A quiet room.',source_name='synthetic-source')
        rule=lambda kind,predicate,source: {'kind':kind,'subject':'roger','predicate':predicate,'allowed_values':['beach-host' if kind=='transformation' else 'yes'],
            'source_id':source,'authority':'author','branch':'main','valid_from':[10,5],'valid_until':None,'exceptions':[]}
        extra={'id':'fixture-scoped-rules','name':'Synthetic time and knowledge','statement':'Fixture-only scoped rules.',
               'enabled':True,'matcher':'typed','phrases':[],'constraints':[rule('transformation','active-form','fixture:host-after-beat-five'),rule('knowledge','knows-clue','fixture:clue-after-beat-five')]}
        laws=WorldLawStore(store);current=laws.open();laws.save(current['revision'],current['laws']+[extra])
        rows=[];durations=[]
        for case in cases:
            packet=build_packet(store,case['episode'],case['beat'],1,0,13,case['viewpoint'])
            started=time.perf_counter_ns()
            assessment=assess_meaning(packet,case['text'],[case['claim']] if case['claim'] else [])
            elapsed=(time.perf_counter_ns()-started)/1_000_000;durations.append(elapsed)
            rows.append({'id':case['id'],'category':case['category'],'text':case['text'],'claim':case['claim'],'episode':case['episode'],'beat':case['beat'],
                'viewpoint':case['viewpoint'],'expected':case['expected'],'actual':assessment['status'],
                'expected_basis':case['expected_basis'],'findings':assessment['findings'],
                'latency_ms':round(elapsed,4)})
        expected_conflicts=[x for x in rows if x['expected']=='contradicted']
        actual_conflicts=[x for x in rows if x['actual']=='contradicted']
        false_positives=[x['id'] for x in actual_conflicts if x['expected']!='contradicted']
        false_negatives=[x['id'] for x in expected_conflicts if x['actual']!='contradicted']
        categories={}
        for row in rows:
            item=categories.setdefault(row['category'],{'count':0,'exact_matches':0,'contradiction_false_positives':0,'contradiction_false_negatives':0})
            item['count']+=1;item['exact_matches']+=row['actual']==row['expected']
            item['contradiction_false_positives']+=row['actual']=='contradicted' and row['expected']!='contradicted'
            item['contradiction_false_negatives']+=row['expected']=='contradicted' and row['actual']!='contradicted'
        return {'set':'synthetic_development_set','scope':'one synthetic AFM universe, two main episodes, one sibling; time-scoped transformation and knowledge rules',
            'sample_count':len(rows),'exact_label_matches':sum(r['actual']==r['expected'] for r in rows),
            'expected_contradictions':len(expected_conflicts),'predicted_contradictions':len(actual_conflicts),
            'contradiction_false_positives':false_positives,'contradiction_false_negatives_including_abstentions':false_negatives,
            'abstained_expected_contradictions':[x['id'] for x in expected_conflicts if x['actual'] in ('uncertain','unavailable')],
            'categories':categories,'latency_ms':{'total':round(sum(durations),4),'median':round(statistics.median(durations),4),'max':round(max(durations),4)},
            'provider_calls':0,'cost':'No external model calls; local CPU time only',
            'confidence_note':'Development-set results and rule-based labels are not calibrated probabilities or a general accuracy estimate.',
            'rows':rows}


def main():
    print(json.dumps(evaluate(),indent=2,ensure_ascii=True))

if __name__=='__main__':main()
