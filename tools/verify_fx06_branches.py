"""Materialize the two corrected FX06 forks and verify one saved-result continuation."""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import file_digest
from pathlib import Path
import shutil

from prose_engine import branch_continuations as bc
from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import DraftStore, NotebookStore, joined
from prose_engine.scoped_pipeline import build_packet, prompt_for, validate_output
from story_graph import fx06_scene as fx, scene_branches as branches, scene_fragments as f
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_override import SceneReplayStore
from tools.studio_ui import StudioRequestHandler
from tools.verify_fx06_mind_drafts import Once, WRITER_INSTRUCTION, _exact, backup, digest, load, put, studio


FORKS=(('fx06-nurse-peter','Nurse Franny · Peter Holds',False),
       ('fx06-nurse-relapse','Nurse Franny · The Three Return',True))
TAG='fx06-08-continuation-from-saved-relapse'
FROZEN='fx06-exact-D09'

BEATS=(('nurse-arrives','Francine takes her Nurse Franny form while the three Rainees are still apart.'),
       ('nurse-reunion','Nurse Franny calls all three back together using only her voice. The three converge into one Rainee.'),
       ('peter-arrives','Only after the reunion does Rainee swell into her enormous Peter form, big as a house.'),
       ('peter-payoff','One blast from Rainee Peter sends Haley to the far end of the hall. Haley braces against the wall, defeated.'))
RETURN=('relapse','Only after Haley has landed does Peter’s outline waver. The Peter form destabilizes into the same three Rainees. Nurse Franny looks from the three to Haley.')


def _prefix(text,graph,replay):
    """Copy the saved scene heading, source scent, exact response and first split."""
    by_node={n['id']:n for n in graph['graph']['nodes']}
    by_p={p['id']:p for p in graph['graph']['passages']}
    by_frame={v['event']:v for v in replay['frames']}
    nodes=[next(n for n in by_node.values() if n['kind']=='heading')]+[
        by_node[by_frame[event]['node']] for event in ('first-release','haley-line','split')]
    first=graph['anchor']['start']; last=by_p[nodes[-1]['passage']]['end']
    return first,text[first:last],[(key,node,by_p[node['passage']]) for key,node in
             zip(('heading','scent','frozen-response','initial-split'),nodes)]


def _scene(origin,text,original_nodes,title,relapse,evidence,*,beats=BEATS,ending=(RETURN,),rejoin='nurse-reunion'):
    passages=[]; nodes=[]
    def add(key,kind,label,start,end,roles=()):
        pid='text-'+key
        passages.append({'id':pid,'start':start,'end':end,'sha256':digest(text[start:end])})
        nodes.append({'id':key,'kind':kind,'label':label,'passage':pid,'roles':list(roles),'evidence':[]})
    for key,node,span in original_nodes:
        add(key,node['kind'],node['label'],span['start']-origin,span['end']-origin,
            ('haley',) if key=='frozen-response' else ())
    for key,paragraph in beats+(ending if relapse else ()):
        start=len(text)+2
        text+='\n\n'+paragraph
        add(key,'event',paragraph,start,len(text))
    edges=[{'from':a['id'],'to':b['id'],'kind':'sequence'} for a,b in zip(nodes,nodes[1:])]
    nodes.append({'id':'cutaway','kind':'reference','label':'Verified fusion shape',
                  'passage':None,'roles':[],'evidence':[evidence['id']]})
    edges.extend({'from':'cutaway','to':key,'kind':'influences'}
                 for key in ('initial-split',rejoin)+(('relapse',) if relapse else ()))
    declaration={'schema_version':1,'title':title,'passages':passages,'nodes':nodes,'edges':edges,
                 'roles':[{'id':'haley','label':'Haley','character_hint':'haley','form_hint':'haley'}],
                 'evidence':[evidence]}
    return text,declaration


def _graph_plan(nodes,registered,relapse):
    def event(ident,node,op,actor=None,args=None,after=()):
        return {'id':ident,'node':nodes[node],'op':op,'actor':actor,'args':args or {},'after':list(after)}
    a='rainee'; b='haley'; n='francine'
    profile=deepcopy(registered)
    profile.update(id='fx06-nurse-fork',anchors={'split':nodes['initial-split'],'rejoin':nodes['nurse-reunion'],'transform':{}},
                   branch_rules={'transforms':[
                       {'id':bc.NURSE,'actor':n,'from_form':n,'node':nodes['nurse-arrives'],'needs_reunion':False},
                       {'id':fx.PETER,'actor':a,'from_form':a,'node':nodes['peter-arrives'],'needs_reunion':True}],
                       'reactivation':{'node':nodes['relapse'],'form':fx.PETER,'release':'peter-release'} if relapse else None})
    profile['protected_line']=profile['protected_line']|{'node':nodes['frozen-response']}
    events=[event('first-release','scent','release',a,{'severity':'severe'}),
            event('haley-notices','scent','notice',b,{'release':'first-release'}),
            event('haley-line','frozen-response','line',b,{'observation':'haley-notices'}),
            event('split','initial-split','pattern_slot',a,{'members':list(fx.CAST)}),
            event('nurse-franny','nurse-arrives','transform',n,{'avatar_id':bc.NURSE}),
            event('voice-intervention','nurse-reunion','intervene',n),
            event('reunion','nurse-reunion','pattern_slot',a,{'intervention':'voice-intervention'}),
            event('peter-transformation','peter-arrives','transform',a,{'avatar_id':fx.PETER}),
            event('peter-release','peter-payoff','release',a,{'severity':'severe'}),
            event('haley-defeated','peter-payoff','force',b,{'release':'peter-release'})]
    patterns=[('borrow-first-split','split','invert_merge'),('borrow-voice-reunion','reunion','reuse_merge')]
    if relapse:
        events.append(event('destabilizes','relapse','pattern_slot',a,{'members':list(fx.CAST)}))
        patterns.append(('borrow-repeat-split','destabilizes','invert_merge'))
    source=profile['patterns'][0]['id']
    overrides=[{'id':ident,'mode':'borrow_pattern','evidence':source,'at':at,'operator':action}
               for ident,at,action in patterns]
    return profile,{'schema_version':1,'events':events,'overrides':overrides}


def install_forks(store,scope,receipt,*,forks=FORKS,scene_plan=_scene,graph_plan=_graph_plan,
                  source_name='FX06-08 authored fork from saved D09'):
    engine=SceneReplayStore(store)
    notebook=NotebookStore(store)
    base=engine.execute('scene.override.open',scope|{'receipt':receipt})['receipt']
    graph=engine.fragments.execute('scene.fragment.open',scope|{'fragment':base['fragment']})['fragment']
    original=store.get_episode(scope['episode'])['script']; old=notebook.existing(scope['episode'])
    mask=next(v for v in old['masks'] if v['id']==FROZEN)
    origin,prefix,original_nodes=_prefix(original,graph,base)
    evidence=next(v for v in graph['declaration']['evidence'] if v['id']=='complete-fusion')
    with store._connect() as c:
        row=c.execute('SELECT * FROM scene_replay_profiles WHERE episode=? AND id=?',(scope['episode'],base['profile'])).fetchone()
        profile=f._object(branches._unpack(row),('scope','fragment','profile'))['profile']
    cases=[]
    for name,title,relapse in forks:
        store.fork(name,scope['branch'],scope['episode'],base['timeline_cutoff'])
        ep=name+'-scene'; store.create_episode(ep,title,name,10)
        branch=scope|{'branch':name,'episode':ep}
        scene,declaration=scene_plan(origin,prefix,original_nodes,title,relapse,evidence)
        complete=scene+'\n\n'+branches.SLOT
        now=store.save(ep,0,script=complete,source_name=source_name)
        view=notebook.open(ep)
        exact=mask|{'start':mask['start']-origin,'end':mask['end']-origin}
        slot={'id':'fx06-continuation-slot','start':len(complete)-len(branches.SLOT),'end':len(complete),
              'sha256':digest(branches.SLOT),'value':25,'hard':False}
        book=notebook.save(ep,view['revision'],now,view['blocks'],100,[exact,slot])
        assert _exact(book)==mask['sha256'] and joined(book['blocks'])==complete
        engine.fragments.register_evidence(branch,[evidence])
        fragment=engine.fragments.execute('scene.fragment.import',branch|{'timeline_revision':now,
                            'selection':{'start':0,'end':len(scene)},'declaration':declaration})['fragment']
        nodes={v['key']:v['id'] for v in fragment['graph']['nodes']}
        policy,recipe=graph_plan(nodes,profile,relapse)
        args=branch|{'timeline_revision':now,'fragment':fragment['id'],'fragment_revision':fragment['revision'],
                     'law_revision':base['law_revision'],'profile':policy['id']}
        engine.install_profile(args,policy)
        saved=engine.execute('scene.override.replay',args|{'recipe':recipe})['receipt']
        result=branches.install(store,branch,parent=scope,parent_replay=base['id'],fork_event='haley-line',child_replay=saved['id'])
        cases.append({'scope':branch,'result':result,'replay':saved,'profile':policy,'recipe':recipe,'args':args})
    assert store.get_episode(scope['episode'])['script']==original and notebook.existing(scope['episode'])==old
    return cases


def check_paths(cases):
    a,b=([{k:v for k,v in frame.items() if k!='node'} for frame in item['replay']['frames']] for item in cases)
    assert a==b[:-1]
    ids=[x['event'] for x in a]
    assert ids==['entry','first-release','haley-notices','haley-line','split','nurse-franny','voice-intervention',
                 'reunion','peter-transformation','peter-release','haley-defeated']
    states={frame['event']:frame['state'] for frame in b}
    assert states['nurse-franny']['actors']['francine']['form']==bc.NURSE and states['split']['actors']['francine']['form']=='francine'
    assert states['reunion']['manifestations']==[] and states['reunion']['root_form']=='rainee'
    assert a[-1]['state']['root_form']==fx.PETER and len(a[-1]['state']['reactions'])==1
    assert len(b[-1]['state']['reactions'])==1 and b[-1]['event']=='destabilizes'
    assert b[-1]['state']['manifestations']==states['split']['manifestations']
    assert b[-1]['state']['split_origin']==fx.PETER and b[-1]['state']['root_form']=='split'
    assert all(b[-1]['state']['knowledge'][a['id']]==[] for a in states['split']['manifestations'])
    assert all(frame['state']['actors']['haley']['location']=='far-hall' for frame in (a[-1],b[-1]))
    assert no_shocker(a+b)


def no_shocker(frames):
    return 'shocker' not in f.encoded(frames).casefold()


def packet_for(store,scope,handler,preview):
    p=preview['scope']
    return build_packet(store,scope['episode'],p['beat'],p['revision'],p['start'],p['end'],
                        junctions=handler._form_store().junctions(),project_id=scope['project'],universe_id=scope['universe'],
                        branch=scope['branch'],law_revision=p['world_law_revision'],
                        continuation_binding=p['continuation']['binding'])


def rejected(call,action,args,code):
    try:
        call(action,args)
    except RuntimeError as exc:
        assert code in str(exc),exc
    else:
        raise AssertionError('Expected rejection: '+code)


def prepare(checkpoint,out):
    record=load(checkpoint); out.mkdir(exist_ok=False); studio_path=out/'studio'
    backup(checkpoint.parent/'before/workspace',studio_path,record['copied_db'])
    source=Path(record['source']); prior=source/'timeline.clips'
    if prior.is_dir():
        shutil.copytree(prior,studio_path/'timeline.clips')
        for file in (studio_path/'timeline.clips').iterdir():
            with file.open('rb') as item:
                assert file_digest(item,'sha256').hexdigest()==file.stem
    store=TimelineStore(studio_path/'timeline.sqlite'); base=record['parent_scope']
    with store._connect() as c:
        before=[tuple(r) for r in c.execute('SELECT * FROM episode_drafts WHERE episode=? ORDER BY rowid',(base['episode'],))]
    cases=install_forks(store,base,record['replay']); check_paths(cases)
    put(out/'branches.json',cases)
    # Browser and shared commands are used on the same copied workspace.
    left,right=cases; chosen=right['scope']; result=right['result']; request=chosen|{'result':result['id']}
    with studio(studio_path,base['episode']) as (cmd,server):
        assert len(cmd('scene.branches.open',base)['results'])==2
        rejected(cmd,'scene.branches.preview',left['scope']|{'result':result['id']},'wrong_result')
        early=deepcopy(right['recipe']); rel=next(e for e in early['events'] if e['id']=='destabilizes'); rel['node']=early['events'][3]['node']
        rejected(cmd,'scene.override.preview',right['args']|{'recipe':early},'blocked_transition')
        missing=deepcopy(right['recipe']); missing['events']=[e for e in missing['events'] if e['id']!='haley-defeated']
        rejected(cmd,'scene.override.preview',right['args']|{'recipe':missing},'missing_prerequisite')
        no_reunion=deepcopy(right['recipe']); no_reunion['events']=[e for e in no_reunion['events'] if e['id']!='reunion']; no_reunion['overrides']=[e for e in no_reunion['overrides'] if e['at']!='reunion']
        rejected(cmd,'scene.override.preview',right['args']|{'recipe':no_reunion},'blocked_transition')
        assert cmd('scene.override.open',base|{'receipt':record['replay']})['receipt']['world_sha256']==record['parent_world_sha256']
        other=cmd('scene.branches.preview',left['scope']|{'result':left['result']['id']})['scope']['continuation']
        assert 'Rainee Peter' in other['cast'].values() and 'Rainee 1' not in other['cast'].values() and not other['scents']
        view=cmd('scene.branches.preview',request); assert view['provider_calls']==0 and not view['rhythm_guidance']['fully_locked']
        handler=StudioRequestHandler.__new__(StudioRequestHandler); handler.server=server
        packet=packet_for(store,chosen,handler,view)
        prompt=prompt_for(packet,scene_function='comedy',rhythm_guidance=view['rhythm_guidance'])
        context=packet.continuation
        assert set(context['cast'].values())=={'Nurse Franny','Haley','Rainee 1','Rainee 2','Rainee 3'}
        assert list(sorted(context['scents'].values()))==['orange','sandalwood','tuberose']
        assert 'Hot Scoomp' not in prompt and 'Shocker' not in context['prior'] and 'Scratch preface' not in prompt
        assert 'Mean Girls' not in prompt and 'fx06-nurse-peter' not in prompt
        assert len(prompt.encode())==view['prompt_bytes'] and len((WRITER_INSTRUCTION+prompt).encode())<=bc.LIMITS['input_bytes']
        rejected(cmd,'scene.branches.run',request|{'plan':'wrong'},'stale_result')
    with store._connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM episode_drafts WHERE episode=? ORDER BY rowid',(base['episode'],))]==before
    seed_path=out/'fresh-world.sqlite'; fresh=TimelineStore(seed_path,project_id='fresh-story',universe_id='fresh-universe')
    seed=EpisodeCommands(fresh).execute('scene.branches.seed',{'project':'fresh-story','universe':'fresh-universe',
              'roles':{'lead':'quill','listener':'mara','helper':'kit'}})
    assert not seed['inherited_facts'] and 'rainee' not in f.encoded(seed).casefold()
    put(out/'fresh-seed.json',seed)
    put(out/'preflight.json',{'scope':chosen,'request':request,'plan':view['plan'],'prompt_sha256':digest(prompt),
          'prompt_bytes':view['prompt_bytes'],'parent_result':result['id'],'frozen_sha256':record['dialogue_sha256'],
          'terminal_world_sha256':result['world_sha256'],'writer_calls':0})
    print('Both corrected forks replayed and saved. Cross-branch, early repeat and no-reunion checks rejected. No writer calls.',flush=True)


def live(out):
    pre=load(out/'preflight.json'); scope=pre['scope']; request=pre['request']; studio_path=out/'studio'
    (out/'attempts').mkdir(exist_ok=False)
    store=TimelineStore(studio_path/'timeline.sqlite'); original=store.get_episode(scope['episode'])
    with studio(studio_path,scope['episode']) as (cmd,server):
        assert cmd('scene.branches.preview',request)['plan']==pre['plan']
        server.test_writer_factory=lambda:Once(out,TAG,pre,bc.LIMITS)
        print('Dispatching one continuation from the saved second ending.',flush=True)
        response=cmd('scene.branches.run',request|{'plan':pre['plan']})
        put(out/'writer-result.json',response)
        draft=cmd('draft.open',scope|{'draft':response['draft_id']}); put(out/'continuation.json',draft)
        assert response['status']=='PROPOSED' and response['provider_calls']==1, response
        assert draft['writing_context']['continuation']['binding']['result']==pre['parent_result']
        assert draft['writing_context']['continuation']['lineage']['world_sha256']==pre['terminal_world_sha256']
        def unexpected():
            raise AssertionError('A repeated continuation cannot dispatch another writer')
        server.test_writer_factory=unexpected
        retry=cmd('scene.branches.run',request|{'plan':pre['plan']})
        assert retry['replayed'] and retry['draft_id']==draft['id'] and retry['provider_calls']==0
    assert original==store.get_episode(scope['episode'])
    assert _exact(NotebookStore(store).existing(scope['episode']))==pre['frozen_sha256']
    print('Saved continuation '+draft['id']+' with one invocation. Retry spent zero calls.',flush=True)


def edit_probe(out):
    path=out/'rechecked-continuation.json'
    pre=load(out/'preflight.json'); draft=load(path if path.is_file() else out/'continuation.json'); scope=pre['scope']; trial=out/'edit-check'
    backup(out/'studio',trial)
    store=TimelineStore(trial/'timeline.sqlite'); notebook=NotebookStore(store)
    siblings={c['scope']['episode']:store.get_episode(c['scope']['episode']) for c in load(out/'branches.json')
              if c['scope']!=scope}
    base=load(out/'branches.json')[0]['result']['parent']['scope']['episode']; siblings[base]=store.get_episode(base)
    with studio(trial,scope['episode']) as (cmd,server):
        before=notebook.existing(scope['episode']); state=before
        for action,extra in [('draft.apply',{'draft':draft['id']}),('notebook.undo',{}),('notebook.redo',{})]:
            state=cmd(action,scope|extra|{'timeline_revision':state['timeline_revision'],'notebook_revision':state['revision']})['notebook']
            assert _exact(state)==pre['frozen_sha256']
            text=joined(state['blocks']); prior=joined(before['blocks'])[:draft['start']]
            assert text==joined(before['blocks']) if action=='notebook.undo' else text==prior+draft['text']
    assert all(store.get_episode(ep)==value for ep,value in siblings.items())
    put(out/'edit-check.json',{'applied_undone_redone':True,'exact_sha256':_exact(state),'isolated':sorted(siblings)})
    print('Apply, undo and redo checked on a separate copy. Base and sibling were untouched.',flush=True)


def recheck(out):
    """Keep the paid attempt immutable; save the unchanged response after the guard fix."""
    pre=load(out/'preflight.json'); original=load(out/'continuation.json'); scope=pre['scope']; path=out/'studio'
    response=(out/'attempts'/TAG/'writer-response.txt').read_text('utf-8').strip()
    assert response==original['text'] and original['status']=='BLOCKED' and original['attempt_id']
    assert len(list((out/'attempts').iterdir()))==1
    store=TimelineStore(path/'timeline.sqlite'); notebook=NotebookStore(store)
    with studio(path,scope['episode']) as (cmd,server):
        def unexpected():
            raise AssertionError('Local recheck must not call a writer')
        server.test_writer_factory=unexpected
        preview=cmd('scene.branches.preview',pre['request'])
        if preview['plan']==pre['plan']:
            replayed=cmd('scene.branches.run',pre['request']|{'plan':pre['plan']})
            assert replayed['status']=='BLOCKED' and replayed['draft_id']==original['id'] and replayed['provider_calls']==0
        else:
            rejected(cmd,'scene.branches.run',pre['request']|{'plan':pre['plan']},'stale_result')
        assert cmd('draft.open',scope|{'draft':original['id']})==original
        handler=StudioRequestHandler.__new__(StudioRequestHandler); handler.server=server
        packet=packet_for(store,scope,handler,preview)
        assert packet.public()==original['writing_context'] and packet.character_store_token==original['character_store_token']
        prompt=prompt_for(packet,scene_function='comedy',rhythm_guidance=preview['rhythm_guidance'])
        assert digest(prompt)==pre['prompt_sha256'] and _exact(notebook.existing(scope['episode']))==pre['frozen_sha256']
        assert not validate_output(packet,response),validate_output(packet,response)
        drafts=DraftStore(notebook); ident=f._id('branch-recheck',original['id'],digest(response))
        drafts.start(packet,original['provider'],parent=original['id'],draft_id=ident,scene_function='comedy',
                   rhythm_guidance=preview['rhythm_guidance'],request_budget={'max_provider_calls':0,'token_limit':None},
                   writing_run={'kind':'branch-output-recheck','candidate_sha256':digest(response),'attempt_id':original['attempt_id']},
                   proposal={'text':response,'issue':{'kind':'saved-output-recheck'},'rhythm_evidence':original['rhythm_evidence']})
        saved=cmd('draft.open',scope|{'draft':ident})
        assert saved['status']=='PROPOSED' and saved['parent']==original['id'] and saved['text']==response
    put(out/'rechecked-continuation.json',saved)
    print('The unchanged response passed locally. Kept the audit trail and made no second call: '+ident,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('prepare','live','recheck','edit-check')); parser.add_argument('output',type=Path)
    parser.add_argument('--checkpoint',type=Path,default=Path('.app-steward/local/noir-fx06-branches-20261117/checkpoint.json'))
    args=parser.parse_args(); path=args.output.resolve()
    if args.operation=='prepare':prepare(args.checkpoint.resolve(),path)
    elif args.operation=='live':live(path)
    elif args.operation=='recheck':recheck(path)
    else:edit_probe(path)


if __name__=='__main__':
    main()
