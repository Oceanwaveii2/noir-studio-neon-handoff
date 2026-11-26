"""Preflight, run and check the three bounded replay-backed Mind drafts on copies."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine import replay_minds as minds
from prose_engine.notebook import NotebookStore, joined
from prose_engine.scoped_pipeline import build_packet, prompt_for
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.fx06_scene import PERFUME_LINE
from tools.studio_ui import StudioRequestHandler


MODEL = 'gpt-6.1-terra'
EFFORT = 'low'
WRITER_INSTRUCTION = ('This is a private fictional writing comparison. Use no tools, no web or file access. '
                      'Return only the six requested lines, without code fences or explanation.\n\n')
GUIDANCE = re.compile(r'(MIND GUIDANCE DATA \(optional tactics only\):\n)([^\n]*)(\nEND MIND GUIDANCE\n)')
DBS = ('timeline.sqlite','character-forms.sqlite')


def digest(text):
    return sha256(text.encode('utf-8')).hexdigest()


def put(path,value):
    with path.open('x',encoding='utf-8') as handle:
        json.dump(value,handle,indent=2,ensure_ascii=False)
        handle.write('\n')


def load(path):
    return json.loads(path.read_text('utf-8'))


def backup(source,target,expected=None):
    target.mkdir(exist_ok=False)
    for name in DBS:
        origin=(source/name).resolve(strict=True)
        if expected is not None:
            assert sha256(origin.read_bytes()).hexdigest()==expected[name]
        with closing(sqlite3.connect(origin.as_uri()+'?mode=ro',uri=True)) as a, closing(sqlite3.connect(target/name)) as b:
            a.backup(b)
            assert b.execute('PRAGMA integrity_check').fetchone()==('ok',)


@contextmanager
def studio(path,episode):
    with ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler) as server:
        server.timeline_path=path/'timeline.sqlite'
        server.timeline_only=True
        server.initial_episode=episode
        server.form_graph=FormGraphStore(path/'character-forms.sqlite')
        server.test_writer_factory=None
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'

        def command(action,args):
            req=Request(origin+'/api/episode-command',json.dumps({'action':action,**args}).encode(),
                        {'Origin':origin,'Content-Type':'application/json'})
            try:
                with urlopen(req,timeout=150) as reply:
                    return json.load(reply)
            except HTTPError as exc:
                with exc:
                    raise RuntimeError(f'{action}: {json.load(exc)}') from exc

        try:
            yield command,server
        finally:
            server.shutdown()
            thread.join()


def _prompts(store,commands,junctions,info):
    scope=info['scope']
    cases={}
    for tag in minds.CONDITIONS:
        initial=minds._request(info,tag)
        view=commands('scene.minds.preview',scope|{'condition':tag})
        assert view['provider_calls']==0 and not view['generation_started'] and not view['rhythm_guidance']['fully_locked']
        args=(scope['episode'],initial['beat'],initial['revision'],initial['start'],initial['end'])
        packet=build_packet(store,*args,junctions=junctions(),project_id=scope['project'],universe_id=scope['universe'],
                            branch=scope['branch'],law_revision=initial['law_revision'],replay_binding=initial['replay_binding'])
        prompt=prompt_for(packet,scene_function='comedy',rhythm_guidance=view['rhythm_guidance'])
        assert view['scope']==packet.public() and len(prompt.encode())==view['prompt_bytes']
        assert 'Rainee Peter' not in prompt and 'peter_griffin_celestial_variant' not in prompt
        match=GUIDANCE.search(prompt)
        assert match and len(GUIDANCE.findall(prompt))==1
        shared=GUIDANCE.sub(r'\1<cards>\3',prompt)
        total=len((WRITER_INSTRUCTION+prompt).encode())
        assert total <= info['limits']['input_bytes']
        cases[tag]={'prompt_sha256':digest(prompt),'shared_prompt_sha256':digest(shared),'prompt_bytes':total,
                    'guidance':json.loads(match[2]),'active_cast':packet.fx06['active_cast'],
                    'history_cutoff':packet.beat,'frame_sha256':packet.fx06['replay_minds']['frame_sha256']}
    a,b,c=(cases[tag] for tag in minds.CONDITIONS)
    assert a['shared_prompt_sha256']==b['shared_prompt_sha256']==c['shared_prompt_sha256']
    assert a['active_cast']==b['active_cast']==c['active_cast'] and len(a['active_cast'])==3
    assert b['guidance']==[] and a['guidance'][0]==c['guidance'][0] and a['guidance'][2]==c['guidance'][2]
    assert c['guidance'][1]==minds.CHANGE and a['guidance'][1]!=c['guidance'][1]
    return cases


def preflight(checkpoint,output):
    record=load(checkpoint)
    output.mkdir(exist_ok=False)
    path=output/'studio'
    backup(checkpoint.parent/'before/workspace',path,record['workspace_hashes'])
    scope=record['case']['scope']
    store=TimelineStore(path/'timeline.sqlite')
    info=minds.install(store,scope,record['case']['id'])
    put(output/'comparison.json',info)
    with studio(path,scope['episode']) as (command,server):
        handler=StudioRequestHandler.__new__(StudioRequestHandler)
        handler.server=server
        junctions=lambda:handler._form_store().junctions()
        cases=_prompts(store,command,junctions,info)
        assert all(v['draft'] is None for v in command('scene.minds.open',scope)['variants'])
    put(output/'preflight.json',cases)
    print('Preflight: same world and prompt outside the card block, three original links, zero writer calls.',flush=True)


class Once:
    def __init__(self,root,tag,fixture,limits):
        self.root,self.tag,self.fixture,self.limits=root,tag,fixture,limits
        self.last_attempt_id='fx06-minds-'+tag

    def generate_rewrite(self,request,prompt):
        exe=shutil.which('codex.exe') or shutil.which('codex')
        if not exe:
            raise ValueError('The Codex writer is unavailable')
        body=WRITER_INSTRUCTION+prompt
        assert digest(prompt)==self.fixture['prompt_sha256']
        if len(body.encode())>self.limits['input_bytes']:
            raise ValueError('The comparison prompt exceeds the saved budget')
        folder=self.root/'attempts'/self.tag
        folder.mkdir(exist_ok=False)
        put(folder/'dispatch.json',{'attempt_id':self.last_attempt_id,'condition':self.tag,'model':MODEL,
                                   'reasoning':EFFORT,'provider':'openai','payload_bytes':len(body.encode()),
                                   'prompt_sha256':digest(prompt),'max_dispatches':1,'request_id':request.request_id})
        output=folder/'writer-response.txt'
        result=subprocess.run([exe,'--ask-for-approval','never','-c','web_search="disabled"','exec',
                               '--model',MODEL,'-c',f'model_reasoning_effort="{EFFORT}"','--sandbox','read-only',
                               '--ephemeral','--skip-git-repo-check','-o',str(output),'-'],cwd=folder,
                              input=body,encoding='utf-8',errors='replace',capture_output=True,timeout=120)
        (folder/'writer.log').write_text(result.stderr+result.stdout,encoding='utf-8')
        put(folder/'result.json',{'exit':result.returncode,'output_saved':output.is_file()})
        if result.returncode or not output.is_file():
            raise ValueError('The single recorded writer invocation did not return a candidate')
        return output.read_text('utf-8').strip()


def _exact(state):
    text=joined(state['blocks'])
    mask=next(m for m in state['masks'] if m['id']=='fx06-exact-D09')
    exact=text[mask['start']:mask['end']]
    assert mask['hard'] and mask['value']==100 and exact==PERFUME_LINE and digest(exact)==mask['sha256']
    return mask['sha256']


def run_live(output):
    path=output/'studio'
    info=load(output/'comparison.json')
    scope=info['scope'];episode=scope['episode']
    planned=load(output/'preflight.json')
    (output/'attempts').mkdir(exist_ok=False)
    with studio(path,episode) as (command,server):
        for tag in minds.CONDITIONS:
            server.test_writer_factory=lambda tag=tag:Once(output,tag,planned[tag],info['limits'])
            print('Dispatching one recorded draft: '+tag,flush=True)
            try:
                result=command('scene.minds.run',scope|{'condition':tag})
            except RuntimeError as exc:
                put(output/('run-'+tag+'.json'),{'error':str(exc),'attempt_retried':False})
                print('Stopped '+tag+' after its recorded attempt.',flush=True)
                continue
            put(output/('run-'+tag+'.json'),result)
            print(tag+' saved as '+result['status'],flush=True)
            server.test_writer_factory=lambda:(_ for _ in ()).throw(AssertionError('Tried to restart a completed selection'))
            repeated=command('scene.minds.run',scope|{'condition':tag})
            assert repeated['replayed'] and repeated['draft_id']==result['draft_id']
        readback=command('scene.minds.open',scope)
    put(output/'saved-drafts.json',readback)


def _author_state(path,episode):
    store=TimelineStore(path/'timeline.sqlite')
    return NotebookStore(store).existing(episode)


def verify_history(output):
    workspace=output/'studio'
    info=load(output/'comparison.json')
    scope=info['scope'];episode=scope['episode']
    before=_author_state(workspace,episode)
    original=joined(before['blocks']);locked=_exact(before)
    with studio(workspace,episode) as (command,_):
        saved=command('scene.minds.open',scope)
        first={v['condition']:v['draft'] for v in saved['variants']}
        diff=command('draft.compare',scope|{'first':first['all']['id'],'second':first['one-changed']['id']})['diff']
        (output/'all-vs-changed.diff').write_text(diff,encoding='utf-8')
    results={}
    for tag,draft in first.items():
        assert draft and draft['status']=='PROPOSED' and draft['text'] and draft['source_text']==original[draft['start']:draft['end']]
        proof=output/('edit-'+tag)
        backup(workspace,proof)
        with studio(proof,episode) as (command,_):
            def edit(action,step,source,extra=None):
                p=scope|{'notebook_revision':source['revision'],'timeline_revision':source['timeline_revision'],
                         'request_id':'fx06-minds-'+tag+'-'+step}|(extra or {})
                state=command(action,p)
                assert state['status']=='APPLIED' and _exact(state['notebook'])==locked
                return state['notebook'],state['receipt']

            altered,applied=edit('draft.apply','apply',before,{'draft':draft['id']})
            expected=original[:draft['start']]+draft['text']+original[draft['end']:]
            assert joined(altered['blocks'])==expected
            restored,undone=edit('notebook.undo','undo',altered)
            assert joined(restored['blocks'])==original
            repeated,redone=edit('notebook.redo','redo',restored)
            assert joined(repeated['blocks'])==expected
        reopened=_author_state(proof,episode)
        assert joined(reopened['blocks'])==expected and _exact(reopened)==locked
        results[tag]={'draft':draft['id'],'apply':applied,'undo':undone,'redo':redone,
                      'reopened_timeline_revision':reopened['timeline_revision'],'lock_sha256':locked,
                      'outside_selection_bytes_unchanged':True,'provider_calls':0}
    assert _author_state(workspace,episode)==before
    put(output/'apply-undo-redo.json',results)
    print('All three independently applied, undone, redone, and reopened with exact outside text and lock.',flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['preflight','run-live','verify-history'])
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    checkpoint=args.checkpoint.resolve(strict=True)
    output=args.output.resolve()
    if output.parent!=checkpoint.parent:
        parser.error('Use an isolated output beside the checkpoint')
    if args.action=='preflight': preflight(checkpoint,output)
    elif args.action=='run-live': run_live(output)
    else: verify_history(output)


if __name__=='__main__':
    main()
