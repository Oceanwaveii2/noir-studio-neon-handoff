"""Validate, write and reopen one already-prepared Spring Break copy."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

from prose_engine import scene_bridges as bridge
from prose_engine.notebook import DraftStore, NotebookStore, joined
from prose_engine.providers.session_attempts import SessionAttemptError
from story_graph import fx06_scene as fx, scene_bridge, scene_fragments as f
from story_graph.episode_timeline import TimelineStore
from telemetry.scene_bridge_trace import Trace, read_trace, stamp
from tools.spring_break_bridge import EPISODE, LOCK, PARENT, ROGER, RUN, sha
from tools.verify_fx06_mind_drafts import DBS, EFFORT, MODEL, backup, load, put, studio


def context(out):
    record = load(out/'PREVIEW.json')
    req = record['request']
    trace = Trace(out/'TRACE.jsonl', RUN)
    trace.scope = {k:v for k,v in req.items() if k!='bridge'}
    run = req | {'plan':record['preview']['plan']}
    return trace, req, run, record


def no_provider():
    raise AssertionError('This path must not dispatch a writer')


def reject(trace, case, check, message, *, mode='fixture'):
    started = perf_counter()
    try:
        check()
    except (ValueError,RuntimeError) as exc:
        if message.casefold() not in str(exc).casefold():
            raise
        trace.emit('guard.reject', 'REJECTED_AS_EXPECTED', case=case, mode=mode,
                   elapsed_ms=round((perf_counter()-started)*1000,2),
                   guard=message, exception=type(exc).__name__, provider_attempts=0)
    else:
        raise AssertionError('Expected rejection: '+case)


def fixture_text(continuation):
    lines = []
    for scene in continuation['program']['scenes']:
        lines.extend([scene['heading'], scene['location']])
        lines.append(scene['beats'][0]['stage'])
        lines.extend(f'{name}: Fixture line number {i+1} only.' for i,name in enumerate(scene['required_speakers']))
        lines.extend(b['stage'] for b in scene['beats'][1:])
    return '\n\n'.join(lines)


def probes(out):
    trace, req, run, record = context(out)
    probe = f'{trace.sequence+1:04d}'
    target = out/('failure-copy-'+probe)
    backup(out/'studio',target)
    replay = load(out/'CUTAWAY_REPLAY.json')
    fragment = load(out/'FRAGMENT.json')
    anchor = fragment['anchor']
    program = load(out/'BRIDGE_PLAN.json')['binding']['program']
    continuation = record['preview']['scope']['continuation']
    test_text = fixture_text(continuation)
    assert not bridge.validate_output(continuation,test_text)
    with studio(target,EPISODE) as (cmd, server):
        server.test_writer_factory = no_provider
        graph_request = trace.scope | {'timeline_revision':replay['args']['timeline_revision'],
                                       'selection':{'start':anchor['start'], 'end':anchor['end']}}
        wrong = deepcopy(fragment['declaration'])
        wrong['evidence'][0]['sha256'] = '0'*64
        reject(trace,'wrong-clip-edition',lambda:cmd('scene.fragment.preview',graph_request|{'declaration':wrong}),
               'Evidence edition does not match')
        wrong = deepcopy(replay['recipe'])
        wrong['overrides'][0]['at'] = 'peter-transformation'
        reject(trace,'wrong-destination-beat',lambda:cmd('scene.override.preview',replay['args']|{'recipe':wrong}),
               'Pattern must match an authored slot')
        reject(trace,'changed-run-plan',lambda:cmd('scene.bridge.run',run|{'plan':'stale-plan'}),
               'bridge plan changed')
        attempts = []

        class LostResponse:
            def generate_rewrite(self, request, prompt):
                attempts.append(request.request_id)
                raise SessionAttemptError('Simulated missing response after send',state='remote_unknown',
                                          attempt_id='simulated-lost-reply')

        server.test_writer_factory = LostResponse
        lost = cmd('scene.bridge.run',run)
        assert lost['status']=='UNKNOWN' and len(attempts)==1
        trace.emit('writer.simulated-interruption','UNKNOWN',case='lost-provider-response',mode='fixture',
                   plan=run['plan'],draft=lost['draft_id'],attempt=lost['attempt_id'],
                   simulated_sends=len(attempts),actual_provider_attempts=0)
    restarted = out/('interruption-restored-'+probe)
    backup(target,restarted)
    with studio(restarted,EPISODE) as (cmd,server):
        server.test_writer_factory = no_provider
        seen = cmd('scene.bridge.run',run)
        assert seen['draft_id']==lost['draft_id'] and seen['status']=='UNKNOWN'
        assert seen['replayed'] and seen['provider_calls']==0
        trace.emit('writer.simulated-recovery','REOPENED',case='lost-provider-response',mode='fixture',
                   draft=seen['draft_id'],status_after_restore='UNKNOWN',retry_sends=0,
                   actual_provider_attempts=0, integrity_check='ok')

        b = NotebookStore(TimelineStore(restarted/'timeline.sqlite'))
        current = b.existing(EPISODE)
        reject(trace,'apply-unconfirmed-draft',lambda:cmd('draft.apply',trace.scope | {
                    'draft':lost['draft_id'],'timeline_revision':current['timeline_revision'],
                    'notebook_revision':current['revision'],'request_id':'must-reject-unknown'}),
               'Only a completed proposal')

        # Exercise a human source edit on the fixture, then attempt to reuse its old graph.
        text = joined(current['blocks'])
        frozen = next(m for m in current['masks'] if m['id']==LOCK)
        reject(trace,'frozen-notebook-edit',lambda:b.edit_text(EPISODE,current['revision'],
               current['timeline_revision'],frozen['start'],frozen['end'],'Changed line.'),
               'protected or masked range')
        n = text.index('The closed door rattles.')
        end = n+len('The closed door rattles.')
        relaxed = b.save(EPISODE,current['revision'],current['timeline_revision'],current['blocks'],100,
                         [*current['masks'],{'id':'fixture-edit','start':n,'end':end,'value':25,
                                             'sha256':f.digest(text[n:end])}])
        changed = b.edit_text(EPISODE,relaxed['revision'],relaxed['timeline_revision'],n,end,
                              'The closed door shakes.')
        reject(trace,'changed-anchor',lambda:cmd('scene.fragment.rebind',trace.scope | {
                    'timeline_revision':changed['timeline_revision'],'fragment_revision':fragment['revision'],
                    'fragment':fragment['id']}),'original scene text no longer matches')
        reject(trace,'stale-bridge-preview',lambda:cmd('scene.bridge.preview',req),'original branch and saved notebook revision')
    wrong = deepcopy(program)
    wrong['actions'] = [a for a in wrong['actions'] if a['id']!='board-sedan']
    reject(trace,'incompatible-join',lambda:scene_bridge.compile_bridge(wrong),
           'No authorized action sequence')
    for key, proposal, expected in (
        ('inactive-form',test_text.replace('Rainee 3:','Peter:'),'unavailable speaker'),
        ('protected-cue-rewrite',test_text.replace('Fixture line number 1 only.',fx.PERFUME_LINE),
         'unavailable speaker'),
        ('output-budget',test_text+'x'*bridge.LIMITS['output_chars'],'exceeds'),
        ('altered-car-roster',test_text.replace('Rainee 2 and Rainee 3 take the back seats.',
                                              'Rainee 3 takes the back seat.'),'changed a mapped action'),
    ):
        errors = bridge.validate_output(continuation,proposal)
        assert any(expected in x for x in errors), (key,errors)
        trace.emit('guard.reject','REJECTED_AS_EXPECTED',case=key,mode='candidate-fixture',
                   guard=errors[0],candidate_sha256=f.digest(proposal),provider_attempts=0)
    put(out/'PREFLIGHT_PROOFS.json',{'status':'PASS','actual_provider_attempts':0,
        'unknown_after_restore':seen['status'],'duplicate_dispatches':seen['provider_calls'],
        'evidence_trace':trace.previous})
    print('Preflight: negative gates and an interrupted writer receipt passed on a separate fixture. Zero external calls.')


class SingleWriter:
    prefix = ('Private fictional writing task. No tools, file reads or web. Use only the supplied packet. '
              'End on the fixed departure direction. Print only the requested screenplay Markdown.\n\n')

    def __init__(self,out,trace,run,preview,span):
        self.out,self.trace,self.run,self.preview,self.span=out,trace,run,preview,span
        self.last_attempt_id='codex-'+run['plan'].removeprefix('scene-bridge-plan-')

    def generate_rewrite(self,request,prompt):
        prompt_bytes=len(prompt.encode('utf-8'))
        body=self.prefix+prompt
        size=len(body.encode('utf-8'))
        if prompt_bytes!=self.preview['prompt_bytes'] or size>bridge.LIMITS['input_bytes']:
            raise ValueError('The actual bounded request differs from its preview')
        exe=shutil.which('codex.exe') or shutil.which('codex')
        if not exe:
            raise SessionAttemptError('The Codex session executable is unavailable',state='rejected')
        attempt=self.out/'single-attempt'
        attempt.mkdir(exist_ok=False)
        result_file=attempt/'writer-response.txt'
        initial={'attempt_id':self.last_attempt_id,'plan':self.run['plan'],'request_id':request.request_id,
                 'provider':'codex-session','model_requested':MODEL,'input_bytes':size,
                 'input_sha256':f.digest(body),'max_dispatches':1}
        put(attempt/'DISPATCH.json',initial)
        start=self.trace.emit('writer.dispatch','STARTED',mode='live-codex',parent=self.span,
                              **initial, artifact='single-attempt/DISPATCH.json')
        clock=perf_counter()
        try:
            p=subprocess.run([exe,'--ask-for-approval','never','-c','web_search="disabled"','exec',
                              '--model',MODEL,'-c',f'model_reasoning_effort="{EFFORT}"','--sandbox','read-only',
                              '--ephemeral','--skip-git-repo-check','--json','-o',str(result_file),'-'],
                             input=body,capture_output=True,encoding='utf-8',errors='replace',cwd=attempt,timeout=120)
        except subprocess.TimeoutExpired as exc:
            self.trace.emit('writer.response','UNKNOWN',mode='live-codex',parent=start,attempt=self.last_attempt_id,
                            elapsed_ms=round((perf_counter()-clock)*1000,2),retry_attempts=0,usage=None)
            raise SessionAttemptError('Codex response was not confirmed',state='remote_unknown',
                                      attempt_id=self.last_attempt_id) from exc
        usage=None
        states=[]
        for line in p.stdout.splitlines():
            try:
                event=json.loads(line)
            except ValueError:
                continue
            if event.get('type') in ('thread.started','turn.started','turn.completed','turn.failed','error'):
                states.append(event['type'])
            if event.get('type')=='turn.completed' and isinstance(event.get('usage'),dict):
                usage={k:v for k,v in event['usage'].items() if isinstance(v,int)}
        observed={'attempt_id':self.last_attempt_id,'exit_code':p.returncode,'stream_states':states,
                  'usage':usage,'output_saved':result_file.is_file(),
                  'elapsed_ms':round((perf_counter()-clock)*1000,2)}
        if result_file.is_file():
            observed['raw_candidate_sha256']=sha(result_file)
        put(attempt/'RESULT.json',observed)
        self.trace.emit('writer.response','RETURNED' if p.returncode==0 and result_file.is_file() else 'UNCONFIRMED',
                        mode='live-codex',parent=start,artifact='single-attempt/RESULT.json',**observed)
        if p.returncode or not result_file.is_file():
            raise SessionAttemptError('Codex did not return a confirmed candidate',state='remote_unknown',
                                      attempt_id=self.last_attempt_id)
        return result_file.read_text('utf-8').strip()


def live(out):
    trace,req,run,record=context(out)
    if load(out/'PREFLIGHT_PROOFS.json')['status']!='PASS' or (out/'single-attempt').exists():
        raise ValueError('Complete zero-call preflight and do not run a second writer attempt')
    with trace.span('writer.run',mode='live-codex',plan=run['plan'],maximum_provider_attempts=1) as (span,event):
        with studio(out/'studio',EPISODE) as (cmd,server):
            server.test_writer_factory=lambda:SingleWriter(out,trace,run,record['preview'],span)
            sent=cmd('scene.bridge.run',run)
        if sent.get('status') in ('FAILED','UNKNOWN') and not sent.get('draft_id'):
            raise ValueError('A writer failure must have a saved attempt')
        put(out/'WRITER_REPLY.json',sent)
        with studio(out/'studio',EPISODE) as (cmd,server):
            server.test_writer_factory=no_provider
            reopened=cmd('scene.bridge.run',run)
        assert reopened['draft_id']==sent['draft_id'] and reopened.get('replayed') and reopened.get('provider_calls')==0
        trace.emit('writer.retry','REOPENED',mode='studio-api',parent=span,simulate_lost_acknowledgement=True,
                   draft=reopened['draft_id'],candidate_status=reopened['status'],additional_dispatches=0)
        d=DraftStore(NotebookStore(TimelineStore(out/'studio/timeline.sqlite'))).open(
            EPISODE,trace.scope['branch'],sent['draft_id'])
        assert d['status']==sent['status']
        event.update(draft=d['id'],attempt=d.get('attempt_id'),candidate_status=d['status'],
                     candidate_sha256=f.digest(d['text']) if d['text'] else None,
                     provider_attempts=1 if (out/'single-attempt/DISPATCH.json').is_file() else 0,
                     validated=d['status']=='PROPOSED',artifact='WRITER_REPLY.json')
    print('Writer status:',sent['status'],'; recorded once. Retry reopened the same result.')


def recheck(out):
    trace,_,run,_=context(out)
    reply=load(out/'WRITER_REPLY.json')
    raw=(out/'single-attempt/writer-response.txt').read_text('utf-8').strip()
    with trace.span('writer.recheck',mode='local-no-call',original_draft=reply['draft_id']) as (_,event):
        with studio(out/'studio',EPISODE) as (cmd,server):
            server.test_writer_factory=no_provider
            old=cmd('draft.open',trace.scope|{'draft':reply['draft_id']})
            assert old['status']=='BLOCKED' and old['text']==raw and old['attempt_id']
            incoming=run|{'draft':old['id']}
            new=cmd('scene.bridge.recheck',incoming)
            proposed=cmd('draft.open',trace.scope|{'draft':new['draft_id']})
            assert proposed['status']=='PROPOSED' and proposed['parent']==old['id'] and proposed['text']==raw
            assert old==cmd('draft.open',trace.scope|{'draft':old['id']})
            again=cmd('scene.bridge.recheck',incoming)
            assert again['replayed'] and again['draft_id']==new['draft_id']
            assert again['provider_calls']==new['provider_calls']==0
        artifact=out/'RECHECKED_DRAFT.json'
        if artifact.is_file():
            prior=load(artifact)
            assert {k:v for k,v in prior.items() if k!='replayed'}=={k:v for k,v in new.items() if k!='replayed'}
        else:
            put(artifact,new)
        event.update(draft=new['draft_id'],parent_draft=old['id'],attempt=old['attempt_id'],
                     candidate_sha256=new['candidate_sha256'],additional_provider_attempts=0,
                     candidate_bytes_preserved=True,original_status='BLOCKED',new_status='PROPOSED',
                     already_saved=new['replayed'],
                     change='short dialogue allowed, boundaries and story state unchanged',
                     artifact='RECHECKED_DRAFT.json')
    print('Validated the exact saved writer response. Zero additional calls.')


def verify_boundaries(source, text, parent, book):
    lock=next(m for m in book['masks'] if m['id']==LOCK)
    before=text[:parent['fork']].encode('utf-8')
    anchor=lock['start'],lock['end']
    end=text.index(ROGER)
    retained=text[end:].encode('utf-8')
    assert before==source[:parent['fork']].encode('utf-8')
    assert lock['hard'] and lock['value']==100 and f.digest(text[slice(*anchor)])==parent['frozen']['sha256']
    assert retained==source[parent['join']:].encode('utf-8') and text.count(ROGER)==1
    return {'prefix_sha256':f.digest(text[:parent['fork']]),'frozen_sha256':lock['sha256'],
            'roger_sha256':f.digest(text[end:]),'roger_bytes':len(retained),'join_offset':end}


def apply_and_recover(out, checkpoint):
    trace,req,run,prep=context(out)
    program=load(out/'BRIDGE_PLAN.json')
    parent=program['binding']['parent']
    solved=program['solved']
    base=load(checkpoint.parent/'resume.json')
    original_reply=load(out/'WRITER_REPLY.json')
    response=load(out/'RECHECKED_DRAFT.json') if (out/'RECHECKED_DRAFT.json').is_file() else original_reply
    if response['status']!='PROPOSED':
        raise ValueError('No validated writer proposal is available to apply')
    origin=out/'studio'
    store=TimelineStore(origin/'timeline.sqlite')
    notes=NotebookStore(store)
    with store._connect() as c:
        prepared=c.execute('SELECT payload,revision,timeline_revision FROM notebook_revisions WHERE episode=? AND revision=?',
                           (EPISODE,prep['preview']['scope']['protection_revision'])).fetchone()
    before=json.loads(prepared['payload']) | {k:prepared[k] for k in ('revision','timeline_revision')}
    parent_ep=store.get_episode(PARENT)
    original=joined(before['blocks'])
    assert f.digest(original)==prep['prepared_script_sha256']
    already_applied=joined(notes.existing(EPISODE)['blocks'])!=original
    with trace.span('draft.apply',mode='studio-api',draft=response['draft_id']) as (span,event), studio(origin,EPISODE) as (cmd,server):
        server.test_writer_factory=no_provider
        draft=cmd('draft.open',trace.scope | {'draft':response['draft_id']})
        assert draft['status']=='PROPOSED' and not bridge.validate_output(
            prep['preview']['scope']['continuation'],draft['text'])
        slot=program['binding']['slot']
        req_apply=trace.scope | {'draft':draft['id'],'timeline_revision':before['timeline_revision'],
                     'notebook_revision':before['revision'],'request_id':'apply-'+run['plan']}
        if not already_applied:
            reject(trace,'apply-outside-bridge',lambda:cmd('draft.apply',req_apply | {
                    'request_id':'must-reject-outside-slot','source_start':0,'source_end':parent['fork'],
                    'candidate_start':0,'candidate_end':len(draft['text'])}),'outside the draft or source')
            assert joined(notes.existing(EPISODE)['blocks'])==original
        result=cmd('draft.apply',req_apply)
        book=result['notebook']
        written=joined(book['blocks'])
        assert result['status']==('REPLAYED' if already_applied else 'APPLIED')
        assert written==original[:slot['start']]+draft['text']+original[slot['end']:]
        repeated=cmd('draft.apply',req_apply)
        assert repeated['receipt']==result['receipt'] and repeated['status']=='REPLAYED'
        assert repeated['notebook']['revision']==book['revision']
        trace.emit('draft.retry','REOPENED',mode='studio-api',parent=span,request_id=req_apply['request_id'],
                   receipt=result['receipt'],after_revision=book['revision'],duplicate_commits=0)
        event.update(receipt=result['receipt'],child_revision=book['timeline_revision'],
                     notebook_revision=book['revision'],script_sha256=f.digest(written),
                     reopened_after_interruption=already_applied)
    with trace.span('scene.join',draft=response['draft_id']) as (_,event):
        proof=verify_boundaries(parent_ep['script'],written,parent,book)
        assert set(solved['goal']) <= set(solved['exit']) and not (set(solved['exit']) & set(solved['forbidden']))
        assert written.index('### SCENE 6: THE DEPARTURE') < written.index(ROGER)
        assert bridge.SLOT not in written
        event.update(**proof, all_entry_conditions_met=True, retained_as_source=True, source_rewritten=False,
                     join_owns_roger_entry=True)
    with trace.span('workspace.restore',mode='recovery') as (_,event):
        suffix='' if not (out/'applied-snapshot').exists() else '-'+str(trace.sequence)
        saved=out/('applied-snapshot'+suffix)
        backup(origin,saved)
        restored=out/('restored'+suffix)
        backup(saved,restored)
        clip=load(out/'IMPORTED_EVIDENCE.json')['clip']
        media_name=clip['sha256']+'.mp4'
        for source,dest in ((origin,saved),(saved,restored)):
            (dest/'timeline.clips').mkdir()
            shutil.copyfile(source/'timeline.clips'/media_name,dest/'timeline.clips'/media_name)
            assert sha(dest/'timeline.clips'/media_name)==clip['sha256']
        event.update(integrity_check='ok',snapshot_sha256={name:sha(saved/name) for name in DBS},
                     restored_sha256={name:sha(restored/name) for name in DBS},
                     restored_clip_sha256=clip['sha256'],additional_provider_attempts=0)
    restored_store=TimelineStore(restored/'timeline.sqlite')
    with trace.span('history.verify',mode='recovery') as (span,event),studio(restored,EPISODE) as (cmd,server):
        server.test_writer_factory=no_provider
        opened=cmd('scene.bridge.open',req)
        assert not opened['current'] and {d['id'] for d in opened['drafts']}=={
            response['draft_id'],original_reply['draft_id']}
        repeated=cmd('draft.apply',req_apply)
        assert repeated['receipt']==result['receipt'] and repeated['status']=='REPLAYED'
        assert joined(repeated['notebook']['blocks'])==written
        trace.emit('restore.reopened','CHECKED',mode='studio-api',parent=span,draft=response['draft_id'],
                   receipt=repeated['receipt'],provider_attempts=0,duplicate_commits=0)
        state=repeated['notebook']
        for action,expected in (('notebook.undo',original),('notebook.redo',written)):
            reply=cmd(action,trace.scope | {'timeline_revision':state['timeline_revision'],
                          'notebook_revision':state['revision'],'request_id':action.replace('.','-')+'-spring-break'})
            state=reply['notebook']
            text=joined(state['blocks'])
            assert text==expected
            facts=verify_boundaries(parent_ep['script'],text,parent,state)
            trace.emit(action,'CHECKED',mode='recovery',parent=span,receipt=reply['receipt'],
                       timeline_revision=state['timeline_revision'],script_sha256=f.digest(text),**facts)
        assert restored_store.get_episode(PARENT)==parent_ep
        event.update(restored=True,history_round_trip=True,fallthrough_to_roger=True)
    with trace.span('import.rebind',mode='studio-api') as (_,event), studio(origin,EPISODE) as (cmd,_):
        old=load(out/'CUTAWAY_REPLAY.json')
        later=cmd('scene.fragment.rebind',trace.scope | {'timeline_revision':book['timeline_revision'],
                  'fragment':old['args']['fragment'],'fragment_revision':old['args']['fragment_revision']})['fragment']
        new_args=old['args'] | {'timeline_revision':book['timeline_revision'],'fragment_revision':later['revision']}
        replay=cmd('scene.override.replay',new_args | {'recipe':old['recipe']})['receipt']
        assert replay['world_sha256']==old['receipt']['world_sha256']
        assert {tuple(sorted(e.items())) for e in later['graph']['edges'] if e['kind']=='influences'}=={
            tuple(sorted(e.items())) for e in load(out/'FRAGMENT.json')['graph']['edges'] if e['kind']=='influences'}
        put(out/'REBOUND.json',{'fragment':later,'replay':replay})
        event.update(fragment=later['id'],revision=later['revision'],replay=replay['id'],
                     world_sha256=replay['world_sha256'],scope_unchanged=True,artifact='REBOUND.json')
    with trace.span('cli.parity',mode='cli') as (_,event):
        p=subprocess.run([sys.executable,'-B','-m','prose_engine.cli','episode','scene.bridge.open',
                         '--timeline',str(origin/'timeline.sqlite'),'--request','-'],
                         input=json.dumps(req),text=True,encoding='utf-8',capture_output=True,timeout=25)
        assert p.returncode==0,p.stderr
        cli=json.loads(p.stdout)
        assert cli==opened
        event.update(same_receipt=True,writer_attempts=0,exit_code=p.returncode)
    assert store.get_episode(PARENT)==parent_ep
    assert all(sha(p)==h for p,h in base['sha_at_resume'].items())
    with (out/'SPRING_BREAK_THREE_RETURN.md').open('xb') as report:
        report.write(written.encode('utf-8'))
    with (out/'GENERATED_BRIDGE.md').open('xb') as report:
        report.write((draft['text']+'\n').encode('utf-8'))
    put(out/'E2E_PROOFS.json',{'status':'VERIFIED','workspace':str(origin),'scope':trace.scope,
        'draft':draft['id'],'apply_receipt':result['receipt'],'boundaries':proof,
        'cutaway_replay':replay['id'],'trace_entry_count':len(read_trace(out/'TRACE.jsonl')),
        'parent_and_active_workspaces_unchanged':True,'restore_undo_redo_passed':True,
        'live_writer_attempts':1,'trace_head_sha256':trace.previous})
    print('Applied the generated bridge, joined the saved Roger scene, and verified restart, Undo/Redo and restore.')
