"""Run the saved Rainee graph and an independent four-way scene on SQLite copies."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from copy import deepcopy
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore, joined
from prose_engine.scoped_pipeline import build_packet
from story_graph import source_imports
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.fx06_scene import CAST, PERFUME_LINE, PETER, read as read_pilot
from story_graph.scene_fragments import digest
from story_graph.scene_override import SceneReplayStore
from story_graph.world_laws import WorldLawStore
from tools.studio_ui import StudioRequestHandler


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'deliverables/NOIR_FX06_GAG_COLLECTION_20261116/Neural Graph'


def _json(path, value):
    with path.open('x', encoding='utf-8') as out:
        out.write(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def _hash(path):
    with path.open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def _copy(stage, out, name, source):
    pw = out/name
    pw.mkdir()
    for asset, expected in source['files'].items():
        saved = stage/'before'/name/asset
        assert _hash(saved) == expected
        with closing(sqlite3.connect(saved.resolve().as_uri()+'?mode=ro', uri=True)) as a, closing(sqlite3.connect(pw/asset)) as b:
            a.backup(b)
            assert b.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    return TimelineStore(pw/'timeline.sqlite')


@contextmanager
def _studio(path, episode):
    with ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler) as server:
        server.timeline_path = Path(path)
        server.timeline_only = True
        server.initial_episode = episode
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f'http://127.0.0.1:{server.server_port}'

        def command(action, payload, error=None):
            req = Request(root+'/api/episode-command', json.dumps({'action':action,**payload}).encode(),
                          headers={'Origin':root,'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=10) as reply:
                    result = json.load(reply)
            except HTTPError as exc:
                with exc:
                    result = json.load(exc)
                if error is None or result.get('code') != error:
                    raise RuntimeError(f'Studio {action} failed: {result}') from exc
                return result
            assert error is None and result['provider_calls']==0
            return result

        try:
            with urlopen(root+'/scene-replay?episode='+episode,timeout=10) as reply:
                assert b'NOIR / SCENE REPLAY' in reply.read()
            yield command
        finally:
            server.shutdown()
            thread.join()


def _event(ident, node, op, actor=None, args=None, after=()):
    return {'id':ident,'node':node,'op':op,'actor':actor,'args':args or {},'after':list(after)}


def _saved_case(store, reference):
    scope = reference['scope']
    ep = scope['episode']
    base = scope | {'timeline_revision':reference['anchor']['timeline_revision'],
                    'fragment':reference['graph'],'fragment_revision':2,
                    'law_revision':WorldLawStore(store).open()['revision']}
    fragment = EpisodeCommands(store).execute('scene.fragment.open', base)['fragment']
    assert fragment['anchor']==reference['anchor']
    nodes = {n['key']:n['id'] for n in fragment['graph']['nodes']}
    with store._connect() as c:
        pilot = read_pilot(c,ep)
        junctions = source_imports.junctions(c,{})
    forms = FormGraphStore(Path(store.path).with_name('character-forms.sqlite'), imported=junctions)
    actual = {form.id:form.link.node_id for form in forms.junctions()['rainee'].forms if form.id in CAST}
    assert actual==pilot['mind_nodes']
    source = next(item for item in fragment['declaration']['evidence'] if item['id']=='complete-fusion')
    selector = source['selector']
    assert source['sha256']==pilot['cutaway']['sha256']==_hash(ASSETS/'Complete Cutaway.mp4')
    assert [selector['start'],selector['end']]==pilot['cutaway']['window_ms']
    author = json.loads((ASSETS/'override_recipe.json').read_text(encoding='utf-8'))
    decisions = author['fixture_inputs']
    law = author['law_fixture']
    assert law['protected_payoff']['text']==PERFUME_LINE and law['applicable_forms']==['rainee']
    assert [x['operator'] for x in author['transformation_overrides']]==[pilot['cutaway']['split'],pilot['cutaway']['rejoin']]
    observer = decisions['environment']['observer']
    room, gap, hall = decisions['environment']['air_paths'][0]
    helpers = decisions['transformations']['intervenes']
    profile = {'schema_version':1,'id':'rainee-with-cutaway','root':'rainee','cutoff':0,
               'locations':[room,hall,'far-hall'],
               'actors':[{'id':'rainee','location':room},{'id':observer,'location':hall},{'id':helpers,'location':hall}],
               'portals':[{'id':gap,'from':room,'to':hall,'allows_scent':True,'allows_sound':True,'permeability':.7}],
               'members':[{'id':mid,'mind':actual[mid]} for mid in CAST], 'interveners':[helpers],
               'anchors':{'split':nodes['n4'],'rejoin':nodes['n5'],'transform':{PETER:nodes['n6']}},
               'protected_line':{'lock':'fx06-exact-D09','speaker':observer,'node':nodes['n3']},
               'emission':{'form':'rainee','strength':law['source_emission']['strength_by_severity']},
               'force':{'form':PETER,'recipient':observer,'visible_from':[hall],'destination':'far-hall'},
               'patterns':[{'id':source['id'],'shape':'many_to_one','arity':3}]}
    ev = _event
    plan = {'schema_version':1,'events':[
        ev('first-release',nodes['n2'],'release','rainee',{'severity':decisions['release_1']['severity']}),
        ev('haley-notices',nodes['n2'],'notice',observer,{'release':'first-release'}),
        ev('haley-line',nodes['n3'],'line',observer,{'observation':'haley-notices'}),
        ev('split',nodes['n4'],'pattern_slot','rainee',{'members':list(CAST)}),
        ev('roast',nodes['n4'],'beat',after=['split']),
        ev('reunion',nodes['n5'],'pattern_slot','rainee',{'intervention':'francine-intervenes'}),
        ev('peter-transformation',nodes['n6'],'transform','rainee',{'avatar_id':PETER},['reunion']),
        ev('second-release',nodes['n6'],'release','rainee',{'severity':decisions['release_2']['severity']},['peter-transformation']),
        ev('haley-reels',nodes['n6'],'force',observer,{'release':'second-release'}),
    ],'overrides':[
        {'id':'borrow-split','mode':'borrow_pattern','evidence':source['id'],'operator':'invert_merge','at':'split'},
        {'id':'authored-intervention','mode':'insert_event','event':ev('francine-intervenes',nodes['n5'],'intervene',helpers)},
        {'id':'borrow-reunion','mode':'borrow_pattern','evidence':source['id'],'operator':'reuse_merge','at':'reunion'},
        {'id':'reader-cutaway','mode':'present','evidence':source['id'],'at':'split'},
    ]}
    return base, profile, plan


def _four_way(store, scope):
    store.fork('fx06-four-way',scope['branch'],scope['episode'],0)
    episode = 'fx06-four-way-scene'
    store.create_episode(episode,'Four-way split · replay fixture','fx06-four-way',10)
    script = ('INT. PRACTICE STAGE\n\nQuill enters.\n\nQuill splits into four bodies.\n\n'
              'Mara calls the four back and they reunite.\n')
    store.save(episode,0,script=script,source_name='Independent four-way authored verification fixture')
    own = scope | {'episode':episode,'branch':'fx06-four-way'}
    fragment = EpisodeCommands(store).execute('scene.fragment.import',own | {'timeline_revision':1,
                         'selection':{'start':0,'end':len(script)}})['fragment']
    nodes = {n['key']:n['id'] for n in fragment['graph']['nodes']}
    members = ['quill-east','quill-west','quill-north','quill-south']
    base = own | {'timeline_revision':1,'fragment':fragment['id'],'fragment_revision':1,
                  'law_revision':WorldLawStore(store).open()['revision']}
    profile = {'schema_version':1,'id':'four-way','root':'quill','cutoff':0,'locations':['stage'],'portals':[],
               'actors':[{'id':'quill','location':'stage'},{'id':'mara','location':'stage'}],
               'members':[{'id':mid,'mind':'mind-'+mid} for mid in members],'interveners':['mara'],
               'anchors':{'split':nodes['n3'],'rejoin':nodes['n4'],'transform':{}},
               'protected_line':None,'emission':None,'force':None,'patterns':[]}
    recipe = {'schema_version':1,'overrides':[],'events':[
        _event('quill-splits',nodes['n3'],'split','quill',{'members':members}),
        _event('mara-calls',nodes['n4'],'intervene','mara'),
        _event('quill-reunites',nodes['n4'],'rejoin','quill',{'intervention':'mara-calls'}),
    ]}
    return base, profile, recipe


def _timeline_fingerprint(store, episode):
    with store._connect() as c:
        rows = [list(r) for r in c.execute('SELECT * FROM events ORDER BY id')]
    book = NotebookStore(store).existing(episode)
    return (store.get_episode(episode),book,rows)


def _confirm_receipt(out, path, args, case):
    req = out / f'{case}-open.json'
    _json(req,args)
    run = subprocess.run([sys.executable,'-B','-m','prose_engine','episode','scene.override.open',
                          '--timeline',str(path),'--request',str(req)],cwd=ROOT,encoding='utf-8',
                         capture_output=True,timeout=40)
    if run.returncode:
        raise RuntimeError('CLI readback failed: '+run.stderr.strip())
    return json.loads(run.stdout)['receipt']


def _run_cases(store,out,reference):
    base, profile, plan = _saved_case(store,reference)
    ep = base['episode']
    four, quad, quad_plan = _four_way(store,reference['scope'])
    before = _timeline_fingerprint(store,ep)
    before4 = _timeline_fingerprint(store,four['episode'])
    book = before[1]
    frozen = next(m for m in book['masks'] if m['id']=='fx06-exact-D09')
    assert frozen['hard'] and joined(book['blocks'])[frozen['start']:frozen['end']]==PERFUME_LINE
    engine = SceneReplayStore(store)
    engine.install_profile(base,profile)
    engine.install_profile(four,quad)
    blocked, far = deepcopy(profile), deepcopy(profile)
    blocked['id']='sealed-air-path';blocked['portals'][0]['allows_scent']=False
    far['id']='observer-away';next(a for a in far['actors'] if a['id']=='haley')['location']='far-hall'
    engine.install_profile(base,blocked);engine.install_profile(base,far)
    request = base | {'profile':profile['id'],'recipe':plan}
    q_request = four | {'profile':quad['id'],'recipe':quad_plan}
    _json(out/'base-recipe.json',request);_json(out/'four-way-recipe.json',q_request)
    failures = {}
    with _studio(store.path,ep) as cmd:
        normal = cmd('scene.override.preview',request)['receipt']
        no_cutaway = deepcopy(plan);no_cutaway['overrides'].pop()
        quiet = cmd('scene.override.preview',request | {'recipe':no_cutaway})['receipt']
        assert normal['frames']==quiet['frames'] and normal['world_sha256']==quiet['world_sha256']
        assert normal['presentation'] and not quiet['presentation']
        advance = deepcopy(plan)
        middle = next(e for e in advance['events'] if e['id']=='split')
        next(e for e in advance['events'] if e['op']=='transform')['node']=middle['node']
        failures['previewed-as-early-form']=cmd('scene.override.replay',request|{'recipe':advance},'early_form')
        no_reunion = deepcopy(plan)
        no_reunion['events'] = [e for e in no_reunion['events'] if e['id']!='reunion']
        no_reunion['overrides'] = [e for e in no_reunion['overrides'] if e['id']!='borrow-reunion']
        next(e for e in no_reunion['events'] if e['op']=='transform')['after']=[]
        failures['without-reunion']=cmd('scene.override.replay',request|{'recipe':no_reunion},'blocked_transition')
        for ident in (blocked['id'],far['id']):
            failures[ident]=cmd('scene.override.replay',request|{'profile':ident},'blocked_transition')
        assert cmd('scene.override.list',base)['receipts']==[]
        first = cmd('scene.override.replay',request)
        repeated = cmd('scene.override.replay',request)
        assert first['status']=='SAVED' and repeated['status']=='REPLAYED'
        assert first['receipt']==repeated['receipt']==normal
        four_receipt = cmd('scene.override.replay',q_request)['receipt']
        assert cmd('scene.override.replay',q_request)['receipt']==four_receipt
        failures['cross-branch']=cmd('scene.override.open',four|{'receipt':normal['id']},'unknown_replay')
        assert cmd('scene.override.open',base|{'receipt':normal['id']})['receipt']==normal

    frames = {row['event']: row for row in normal['frames']}
    before_peter = normal['frames'][:list(frames).index('peter-transformation')]
    assert PETER not in json.dumps(before_peter)
    assert frames['reunion']['state']['root_form']=='rainee' and not frames['reunion']['state']['manifestations']
    assert frames['peter-transformation']['state']['root_form']==PETER
    assert {v['id']:v['mind'] for v in frames['split']['state']['manifestations']}=={r['id']:r['mind'] for r in profile['members']}
    assert frames['haley-line']['effects']==[{'protected_line':{'id':frozen['id'],'sha256':frozen['sha256']}}]
    assert frames['haley-notices']['state']['knowledge']['haley']==['scent-first-release']
    assert frames['haley-notices']['state']['knowledge']['francine']==[]
    assert frames['first-release']['effects'][0]['release']['force'] is False
    assert frames['second-release']['effects'][0]['release']['scent'] is None
    assert frames['haley-reels']['state']['actors']['haley']['location']=='far-hall'
    stages = {row['event']: row['state'] for row in four_receipt['frames']}
    assert len(stages['quill-splits']['manifestations'])==4 and not stages['quill-reunites']['manifestations']
    assert not four_receipt['overrides'] and 'rainee' not in json.dumps(four_receipt['frames'])
    assert _timeline_fingerprint(store,ep)==before and _timeline_fingerprint(store,four['episode'])==before4
    for name, req, value in (('rainee',base,normal),('four-way',four,four_receipt)):
        assert _confirm_receipt(out,store.path,req|{'receipt':value['id']},name)==value
        _json(out/f'{name}-receipt.json',value)
    return {'rainee':{'id':normal['id'],'episode':ep,'scope':reference['scope'],'world_sha256':normal['world_sha256'],
                    'form_trace':[(row['event'],row['state']['root_form'],len(row['state']['manifestations'])) for row in normal['frames']],
                    'locked_line_sha256':frozen['sha256']},
            'four_way':{'id':four_receipt['id'],'episode':four['episode'],'branch':four['branch'],
                        'sibling_count':len(stages['quill-splits']['manifestations'])},
            'nonmutating_cutaway':normal['world_sha256']==quiet['world_sha256'],
            'denials':{key:value['code'] for key,value in failures.items()},
            'cli_readback_equal':True,'copied_manuscripts_and_events_unchanged':True,'provider_calls':0}


def _spring(store, saved):
    a = saved['anchor']
    boundaries = a['start'],a['end']
    packet = build_packet(store,'spring-break',0,a['timeline_revision'],*boundaries)
    earlier = [e['id'] for e in store.resolve('spring-break',999)]
    later = [e['id'] for e in store.resolve('hot-scoomp',999)]
    assert 'haley-awakening' not in earlier and 'haley-awakening' in later
    assert not any(e['id']=='haley-awakening' for e in packet.events)
    assert 'awakened_haley_fox' not in json.dumps(packet.forms)
    return {'spring_break_sees_awakening':False,'hot_scoomp_sees_awakening':True,
            'verified_passage':saved['anchor']['text_sha256']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(argv)
    checkpoint = args.checkpoint.resolve(strict=True)
    stage, out = checkpoint.parent, args.output.resolve()
    if out.parent!=stage:
        parser.error('Keep verification copies beside the checkpoint')
    captured = json.loads(checkpoint.read_text(encoding='utf-8'))
    out.mkdir(exist_ok=False)
    first = _copy(stage,out,'rainee',captured['copies']['rainee'])
    second = _copy(stage,out,'spring-break',captured['copies']['spring-break'])
    result = _run_cases(first,out,captured['copies']['rainee'])
    result['timeline_isolation'] = _spring(second,captured['copies']['spring-break'])
    _json(out/'receipt.json',result)
    print('Rainee, three manifestations, Rainee after reunion, then Rainee Peter; four-way 0/4/0; Spring Break stays isolated.')


if __name__=='__main__':
    main()
