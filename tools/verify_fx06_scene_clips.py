"""Verify actual media on a recovered FX06 copy; allow one explicitly recorded writer dispatch."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from prose_engine import replay_minds, scene_mind_support
from prose_engine.notebook import DraftStore, NotebookStore, joined
from prose_engine.scoped_pipeline import build_packet, prompt_for, validate_output
from story_graph import scene_fragments as f
from story_graph import fx06_scene
from story_graph.episode_timeline import TimelineStore
from story_graph.world_laws import WorldLawStore
from tools.studio_ui import StudioRequestHandler
from tools.verify_fx06_mind_drafts import Once, WRITER_INSTRUCTION, _exact, backup, digest, load, put, studio


GAG_PICK=(116000,118800)
PERFORMANCE=(('p04-11-corrected-in-public','mg04-early-26.mp4','personality',
              'Let the previous speaker nearly finish her case, then cut in with a short, public correction. Check the listener’s reaction.'),
             ('p04-02-compliment','mg04-early-11.mp4','timing',
              'After the challenge, hold a short direct look before switching beats. Give the final fan callback space to land.'))
TIMING_SOURCE='fg-s09e02-lois-dinner'
TIMING_NOTE='Leave a gap after the sound before the listener reacts. Let an attempted reset lead into a delayed visual payoff.'
TAG='scene-clips-and-scent-signatures'


def upload(origin,scope,path,expected):
    data=path.read_bytes()
    assert sha256(data).hexdigest()==expected, path.name
    request=Request(origin+'/api/scene-clips/upload?'+urlencode(scope|{'name':path.name}),data=data,
                    headers={'Origin':origin,'Content-Type':'video/mp4'})
    with urlopen(request,timeout=30) as response:
        reply=json.load(response)
        assert response.status==201 and reply['provider_calls']==0
    asset=reply['asset']
    assert asset['content_sha256']==expected and asset['bytes']==len(data)
    target=origin+'/api/scene-clips/media?'+urlencode(scope|{'id':asset['id']})
    with urlopen(Request(target,headers={'Range':'bytes=0-63'}),timeout=10) as response:
        assert response.status==206 and response.read()==data[:64]
        assert response.headers['Content-Range']==f'bytes 0-63/{len(data)}'
    return asset


def refuse(command,action,fields,key):
    try:
        command(action,fields)
    except RuntimeError as exc:
        assert key in str(exc),exc
    else:
        raise AssertionError(f'{action} was expected to reject: {key}')


def load_media(origin,scope,package):
    clips=package/'Neural Graph'
    manifest=load(clips/'source_manifest.json')
    gag=manifest['gag_source']
    cut=upload(origin,scope,clips/gag['filename'],gag['original_sha256'])
    assert GAG_PICK[1]<=cut['duration_ms']
    assignments=[{'clip':cut['id'],'purpose':'cutaway','start_ms':GAG_PICK[0],'end_ms':GAG_PICK[1]}]
    origins=[{'source':gag['id'],'window_ms':list(GAG_PICK),'sha256':cut['content_sha256']}]
    movie=package/'Mean Girls (2004)'
    index=load(movie/'Mined Evidence/chunk_index.json')
    moments=load(movie/'Mined Evidence/linked_evidence.json')
    for moment_id,file,purpose,note in PERFORMANCE:
        proxy=next(v for v in index['local_review_chunks'] if v['file']==file)
        evidence=next(v for v in moments['moments'] if v['id']==moment_id)
        assert evidence['sha256']==manifest['reference_film']['original_sha256']==index['sha256']
        assert evidence['eligibility']=='transfer' and moment_id in moments['admitted_ids']
        asset=upload(origin,scope,movie/'Review Clips'/file,proxy['sha256'])
        source=evidence['span_ms']
        offset=round(proxy['proxy_mux_range_s'][0]*1000)
        start,end=[v-offset for v in source]
        assert 0<=start<end<=asset['duration_ms']
        assignments.append({'clip':asset['id'],'purpose':purpose,'note':note,'start_ms':start,'end_ms':end}
                           | ({'character':'Rainee 2'} if purpose=='personality' else {}))
        origins.append({'source':'Mean Girls (2004)','moment':moment_id,'source_window_ms':source,
                        'proxy_window_ms':[start,end],'sha256':asset['content_sha256']})
    media_dir=package/'Fart Media'
    items=[]
    for item in load(media_dir/'episode_index.json')['rows']:
        assert not item['can_supply_personality_memory_or_canon']
        asset=upload(origin,scope,media_dir/item['path'],item['media']['sha256'])
        items.append({'clip':asset['id'],'source':item['id'],'title':item['episode_title']+' · '+item['subject'],
                      'category':item['category'],'content_sha256':asset['content_sha256'],
                      'source_range_ms':[round(v*1000) for v in item['source_range_s']],'note':item['timing']})
        if item['id']==TIMING_SOURCE:
            end=min(asset['duration_ms'],item['source_range_s'][1]*1000-item['source_range_s'][0]*1000)
            assignments.append({'clip':asset['id'],'purpose':'timing','note':TIMING_NOTE,'start_ms':0,'end_ms':int(end)})
            origins.append({'source':item['id'],'source_window_ms':items[-1]['source_range_ms'],
                            'proxy_window_ms':[0,int(end)],'sha256':asset['content_sha256']})
    return items,assignments,origins


def packet_for(store,scope,junctions,preview):
    with store._connect() as c:
        saved,_=replay_minds._registered(c,scope)
    cmd=replay_minds._request(saved,'all')
    return build_packet(store,scope['episode'],cmd['beat'],cmd['revision'],cmd['start'],cmd['end'],
                        junctions=junctions,project_id=scope['project'],universe_id=scope['universe'],
                        branch=scope['branch'],law_revision=cmd['law_revision'],replay_binding=cmd['replay_binding'],
                        clip_binding=preview['scope']['clip_context']['binding'])


def preflight(checkpoint,output,package):
    saved=load(checkpoint);scope=saved['scope'];ep=scope['episode'];b=saved['verified_binding']
    output.mkdir(exist_ok=False); path=output/'studio'
    backup(checkpoint.parent/'before/workspace',path,saved['copy_hashes'])
    store=TimelineStore(path/'timeline.sqlite'); original=store.get_episode(ep)
    law_before=WorldLawStore(store).open(); lock=_exact(NotebookStore(store).existing(ep))
    with studio(path,ep) as (command,server):
        origin=f'http://127.0.0.1:{server.server_port}'
        replay_command=scope|{'receipt':b['replay']}
        baseline=command('scene.override.open',replay_command)['receipt']
        assert baseline['world_sha256']==b['world_sha256'] and baseline['timeline_revision']==b['timeline_revision']
        by_frame={v['event']:v for v in baseline['frames']}
        group,inputs,origins=load_media(origin,scope,package)
        data=scene_mind_support.install(store,scope,load(package/'rainee_split_mind_support.json'),group)
        assert len(data['library']['items'])==14 and sum(i['writing_eligible'] for i in data['library']['items'])==12
        assert len({link['to'] for link in data['links']})==1
        assert {l['mind'] for l in data['links']}=={a['node_id'] for a in b['cast']}
        assert command('scene.minds.open',scope)['mind_support']==data
        effective={}
        with store._connect() as c:
            for frame in baseline['frames']:
                state=frame['state']
                cast=[{'form_id':item['id'],'node_id':item['mind']} for item in state['manifestations']]
                projected=scene_mind_support.project(c,scope,state['root_form'],cast)
                effective[frame['event']]=[r['scent'] for r in projected['rules']] if projected else []
            assert not scene_mind_support.project(c,scope|{'branch':'other'},'split',b['cast'])
        assert [name for name,rules in effective.items() if rules]==['split','roast','francine-intervenes']
        assert by_frame['reunion']['state']['root_form']=='rainee'
        assert by_frame['peter-transformation']['state']['root_form']==fx06_scene.PETER
        assert by_frame['split']['node']==by_frame['roast']['node']
        dest=scope|{'fragment':b['fragment'],'fragment_revision':b['fragment_revision'],
                    'timeline_revision':b['timeline_revision'],'node':by_frame['roast']['node']}
        assert command('scene.clips.open',scope)['draft_node']==dest['node']
        refuse(command,'scene.clips.attach',dest|inputs[0]|{'replay':b['replay'],'event':'peter-transformation'},'wrong_beat')
        refuse(command,'scene.clips.attach',dest|inputs[-1]|{'purpose':'personality','character':'Rainee 3'},'wrong_purpose')
        for fields in inputs:
            if fields['purpose']=='cutaway':
                fields=fields|{'replay':b['replay'],'event':'split'}
            reply=command('scene.clips.attach',dest|fields)
            assert reply['provider_calls']==0
        cut=command('scene.override.open',replay_command)
        assert cut['receipt']==baseline and cut['clip_cues']==[{'clip':inputs[0]['clip'],'start_ms':GAG_PICK[0],
                                                              'end_ms':GAG_PICK[1],'event':'split'}]
        options=dest|{'test_signatures':True}
        preview=command('scene.clips.preview',options)
        refuse(command,'scene.clips.run',options|{'plan':'wrong'},'stale_clips')
        assert preview['provider_calls']==0 and not preview['generation_started']
        assert not preview['rhythm_guidance']['fully_locked']
        handler=StudioRequestHandler.__new__(StudioRequestHandler);handler.server=server
        packet=packet_for(store,scope,handler._form_store().junctions(),preview)
        prompt=prompt_for(packet,scene_function='comedy',rhythm_guidance=preview['rhythm_guidance'])
        assert preview['scope']==packet.public() and len(prompt.encode())==preview['prompt_bytes']
        assert 'Rainee Peter' not in prompt and 'peter_griffin_celestial_variant' not in prompt
        clip_section=prompt.split('CLIP NOTES (bounded',1)[1].split('END CLIP NOTES',1)[0]
        assert all(item.get('note','') in clip_section for item in inputs)
        assert '.mp4' not in prompt and 'Mean Girls' not in clip_section and 'clip-' not in clip_section
        assert all(rule['scent'] in prompt and rule['perfume'] not in prompt for rule in data['rules'])
        assert len((WRITER_INSTRUCTION+prompt).encode())<=replay_minds.LIMITS['input_bytes']
        print(f"Preflight passed: {len(group)} shared clips, {len(inputs)} scoped assignments, {len(prompt.encode())} writer bytes, zero calls.",flush=True)
    assert WorldLawStore(store).open()==law_before and store.get_episode(ep)==original
    put(output/'preflight.json',{'scope':scope,'dest':options,'plan':preview['plan'],'origins':origins,
         'prompt_sha256':digest(prompt),'prompt_bytes':preview['prompt_bytes'],'clip_scope':preview['scope']['clip_context'],
         'mind_support':data,'local_rules_by_frame':effective,'replay':b['replay'],'world_sha256':b['world_sha256'],
         'timeline_revision':b['timeline_revision'],'notebook_revision':b['notebook_revision'],
         'source_sha256':digest(original['script']),'protected_line_sha256':lock,'law_revision':law_before['revision']})


def live(output):
    evidence=load(output/'preflight.json'); path=output/'studio'; scope=evidence['scope']; ep=scope['episode']
    store=TimelineStore(path/'timeline.sqlite'); before=store.get_episode(ep)
    (output/'attempts').mkdir(exist_ok=False)
    with studio(path,ep) as (command,server):
        current=command('scene.clips.preview',evidence['dest'])
        assert current['plan']==evidence['plan']
        server.test_writer_factory=lambda:Once(output,TAG,evidence,replay_minds.LIMITS)
        print('Dispatching the single authorized draft.',flush=True)
        result=command('scene.clips.run',evidence['dest']|{'plan':evidence['plan']})
        put(output/'writer-result.json',result)
        draft=command('draft.open',scope|{'draft':result['draft_id']})
        put(output/'draft.json',draft)
        assert result['status'] in ('PROPOSED','BLOCKED') and result['provider_calls']==1, result
        assert draft['writing_context']['clip_context']==evidence['clip_scope']
        assert draft['writing_context']['mind_support']['package_sha256']==evidence['mind_support']['sha256']
        if draft['status']=='PROPOSED':
            assert not scene_mind_support.validate_output(draft['writing_context']['mind_support'],draft['text'],exercise=True)
        assert 'Peter' not in draft['text'] and fx06_scene.PERFUME_LINE not in draft['text']
        def unexpected():
            raise AssertionError('Duplicate request must reuse the saved draft')
        server.test_writer_factory=unexpected
        duplicate=command('scene.clips.run',evidence['dest']|{'plan':evidence['plan']})
        assert duplicate['replayed'] and duplicate['draft_id']==draft['id'] and duplicate['provider_calls']==0
        replay=command('scene.override.open',scope|{'receipt':evidence['replay']})['receipt']
        assert replay['world_sha256']==evidence['world_sha256']
    assert store.get_episode(ep)==before and digest(before['script'])==evidence['source_sha256']
    assert _exact(NotebookStore(store).existing(ep))==evidence['protected_line_sha256']
    assert WorldLawStore(store).open()['revision']==evidence['law_revision']
    assert len(list((output/'attempts').iterdir()))==1
    print('Saved draft '+draft['id']+' ('+draft['status']+'); duplicate used no second writer call.',flush=True)


def recheck(output):
    """Revalidate the exact saved response after validator fixes, preserving the original attempt."""
    evidence=load(output/'preflight.json'); path=output/'studio'; scope=evidence['scope']; ep=scope['episode']
    source=load(output/'draft.json'); notebook=NotebookStore(TimelineStore(path/'timeline.sqlite'))
    drafts=DraftStore(notebook); original=drafts.open(ep,scope['branch'],source['id'])
    assert source==original and original['status']=='BLOCKED' and original['attempt_id']
    response=(output/'attempts'/TAG/'writer-response.txt').read_text('utf-8').strip()
    assert response==original['text'] and len(list((output/'attempts').iterdir()))==1
    with studio(path,ep) as (command,server):
        server.test_writer_factory=lambda: (_ for _ in ()).throw(AssertionError('Recheck cannot dispatch'))
        repeated=command('scene.clips.run',evidence['dest']|{'plan':evidence['plan']})
        assert repeated['status']=='BLOCKED' and repeated['replayed'] and repeated['provider_calls']==0
        preview=command('scene.clips.preview',evidence['dest'])
        handler=StudioRequestHandler.__new__(StudioRequestHandler); handler.server=server
        packet=packet_for(notebook.timeline,scope,handler._form_store().junctions(),preview)
        assert packet.public()==original['writing_context'] and str(packet.character_store_token)==original['character_store_token']
        assert evidence['prompt_sha256']==digest(prompt_for(packet,scene_function='comedy',rhythm_guidance=preview['rhythm_guidance']))
        findings=validate_output(packet,response)
        assert not findings,findings
        assert digest(joined(notebook.existing(ep)['blocks']))==evidence['source_sha256']
        assert _exact(notebook.existing(ep))==evidence['protected_line_sha256']
        assert command('scene.override.open',scope|{'receipt':evidence['replay']})['receipt']['world_sha256']==evidence['world_sha256']
        assert WorldLawStore(notebook.timeline).open()['revision']==evidence['law_revision']
        ident=f._id('clip-recheck',original['id'],digest(response),'signature-sounds-v2')
        drafts.start(packet,original['provider'],parent=original['id'],draft_id=ident,scene_function='comedy',
            request_budget={'max_provider_calls':0,'token_limit':None},rhythm_guidance=preview['rhythm_guidance'],
            writing_run={'kind':'clip-output-recheck','candidate_sha256':digest(response),'attempt_id':original['attempt_id']},
            proposal={'text':response,'issue':{'kind':'saved-output-recheck'},'rhythm_evidence':original['rhythm_evidence']})
        corrected=command('draft.open',scope|{'draft':ident})
        assert corrected['status']=='PROPOSED' and corrected['text']==response and corrected['parent']==original['id']
    put(output/'rechecked-draft.json',corrected)
    print('Same writer output passed a zero-call recheck; preserved original attempt '+original['id']+'.',flush=True)


def apply_probe(output):
    evidence=load(output/'preflight.json'); rechecked=output/'rechecked-draft.json'
    draft=load(rechecked if rechecked.is_file() else output/'draft.json'); scope=evidence['scope']; ep=scope['episode']
    source=output/'studio'; trial=output/'edit-check';backup(source,trial)
    shutil.copytree(source/'timeline.clips',trial/'timeline.clips')
    with studio(trial,ep) as (command,server):
        basis=scope|{'timeline_revision':evidence['timeline_revision'],'notebook_revision':evidence['notebook_revision']}
        applied=command('draft.apply',basis|{'draft':draft['id'],'request_id':'clip-draft-check-apply'})['notebook']
        text=joined(applied['blocks']);assert draft['text'] in text and _exact(applied)==evidence['protected_line_sha256']
        undone=command('notebook.undo',scope|{'timeline_revision':applied['timeline_revision'],
                       'notebook_revision':applied['revision'],'request_id':'clip-draft-check-undo'})['notebook']
        assert digest(joined(undone['blocks']))==evidence['source_sha256']
        redone=command('notebook.redo',scope|{'timeline_revision':undone['timeline_revision'],
                       'notebook_revision':undone['revision'],'request_id':'clip-draft-check-redo'})['notebook']
        assert joined(redone['blocks'])==text and _exact(redone)==evidence['protected_line_sha256']
    put(output/'edit-check.json',{'draft':draft['id'],'applied':applied['revision'],'undone':undone['revision'],
                                  'redone':redone['revision'],'exact':_exact(redone)})
    print('Apply, undo and redo passed on a separate copy. Haley’s line stayed exact.',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('preflight','live','recheck','apply-probe'));p.add_argument('output',type=Path)
    p.add_argument('--checkpoint',type=Path,default=Path('.app-steward/local/noir-fx06-clip-intake-20261117/checkpoint.json'))
    p.add_argument('--package',type=Path,default=Path('deliverables/NOIR_FX06_GAG_COLLECTION_20261116'))
    a=p.parse_args();root=a.output.resolve()
    if a.action=='preflight':preflight(a.checkpoint.resolve(),root,a.package.resolve())
    elif a.action=='live':live(root)
    elif a.action=='recheck':recheck(root)
    else:apply_probe(root)


if __name__=='__main__':
    main()
