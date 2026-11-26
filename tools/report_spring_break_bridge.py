"""Render the verified Spring Break evidence as JSON and a local trace reader."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from telemetry.scene_bridge_trace import Trace, read_trace
from tools.spring_break_bridge import BASE, ROOT, RUN, sha
from tools.verify_fx06_mind_drafts import load, put


HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Noir / Spring Break run trace</title><style>
:root{color-scheme:dark;--base:#13151a;--panel:#1e2129;--line:#343a46;--type:#eff1f7;--muted:#b2bdd1;--accent:#a0ead6;--warm:#ffbf94}
*{box-sizing:border-box}body{margin:0;background:var(--base);color:var(--type);font:16px/1.5 system-ui,sans-serif}
main{max-width:1550px;margin:auto;padding:28px clamp(16px,4vw,58px)}header p{color:var(--muted);max-width:74ch}
.eyebrow{font-size:.78rem;letter-spacing:.13em;color:var(--accent)}h1{font-size:clamp(2rem,5vw,3.3rem);line-height:1.1;margin:.2em 0}h2{font-size:1.22rem}a{color:var(--accent)}.links{display:flex;gap:1rem;flex-wrap:wrap}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:.6rem;margin:1.3rem 0}
.metrics div,section{background:var(--panel);border:1px solid var(--line);border-radius:9px;padding:.85rem}
.metrics strong{display:block;color:var(--accent);font-size:1.35rem}.metrics span{font-size:.86rem;color:var(--muted)}
.controls{display:flex;gap:.75rem;align-items:flex-end;flex-wrap:wrap;margin-bottom:.75rem}
label{display:grid;gap:.25rem;font-size:.82rem;color:var(--muted)}input,select,button{font:inherit;color:var(--type);background:var(--base);border:1px solid var(--line);border-radius:7px;padding:.45rem .55rem}
input{min-width:min(340px,75vw)}:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.grid{display:grid;grid-template-columns:minmax(280px,1fr) minmax(0,1.1fr);gap:.8rem}
#rows{display:grid;gap:.3rem;max-height:63vh;overflow:auto;padding:2px}button{text-align:left;cursor:pointer}
button[aria-pressed="true"]{border-color:var(--accent);background:#23352f}button small{display:block;color:var(--muted)}
.status{color:var(--warm)}#meta{color:var(--muted)}pre{max-height:58vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.45 ui-monospace,monospace}
@media(max-width:780px){.grid{grid-template-columns:1fr}#rows{max-height:35vh}}
</style></head><body><main>
<header><div class="eyebrow">NOIR / VERIFIED COPY</div><h1>Spring Break run trace</h1>
<p>Read the observed events in order, including the rejected drafts and the retries. Select any event to inspect its source, scope, receipt and state changes. Live, local and simulated events are marked separately.</p>
<div class="links"><a href="ARCHITECTURE.md">Architecture</a><a href="VERIFICATION.json">Verification</a><a href="TRACE.jsonl">Raw trace</a><a href="GENERATED_BRIDGE.md">Generated bridge</a></div></header>
<div class="metrics" id="metrics"></div><div class="controls"><label>Search the trace<input id="search" placeholder="stage, case, receipt, or fact"></label>
<label>Status<select id="filter"><option value="">All statuses</option></select></label><span id="count" role="status"></span></div>
<div class="grid"><section><h2>Events</h2><div id="rows"></div></section>
<section><h2 id="heading">Selected event</h2><p id="meta"></p><pre id="detail"></pre></section></div>
</main><script type="application/json" id="run-data">DATA_MARKER</script><script>
'use strict';
const data = JSON.parse(document.getElementById('run-data').textContent);
const at = id => document.getElementById(id);
const el = (tag, text) => { const node=document.createElement(tag); node.textContent=text; return node; };
const entries = data.events;
let current = 1;
function showMetric(label, val) {
  const box=el('div',''); box.append(el('strong',val),el('span',label)); at('metrics').append(box);
}
showMetric('Trace events',entries.length);
showMetric('Live writer invocations',data.proof.writer.invocations);
showMetric('Exact Roger bytes',data.proof.source.roger_bytes.toLocaleString());
showMetric('Core fixtures passed',data.proof.core.fixtures);
for(const value of [...new Set(entries.map(row=>row.status))].sort()){
  const item=el('option',value);item.value=value;at('filter').append(item);
}
function inspect(row) {
  current=row.sequence; at('heading').textContent=row.sequence+' · '+row.stage;
  at('meta').textContent=[row.mode,row.status,row.case,row.utc,row.elapsed_ms===null?'':row.elapsed_ms+' ms'].filter(Boolean).join(' · ');
  at('detail').textContent=JSON.stringify(row,null,2);
  for(const node of at('rows').children) node.setAttribute('aria-pressed',String(Number(node.dataset.sequence)===current));
}
function render(){
  const query=at('search').value.trim().toLowerCase();
  const status=at('filter').value;
  const selected=entries.filter(row=>(!status||row.status===status)&&(!query||JSON.stringify(row).toLowerCase().includes(query)));
  at('count').textContent=selected.length+' of '+entries.length+' events';
  at('rows').replaceChildren(...selected.map(row=>{
    const btn=el('button',''); btn.type='button'; btn.dataset.sequence=row.sequence;
    const title=el('span',String(row.sequence).padStart(3,'0')+' · '+row.stage);
    const status=el('small',row.status+' · '+row.mode+' · '+row.case); status.className='status';
    btn.append(title,status); btn.onclick=()=>inspect(row); return btn;
  }));
  if(!selected.length){at('heading').textContent='No matching events';at('meta').textContent='';at('detail').textContent='';return;}
  inspect(selected.find(row=>row.sequence===current)||selected[0]);
}
at('search').addEventListener('input',render);at('filter').addEventListener('change',render);render();
</script></body></html>"""


def render(out):
    core_path=out/'core-final.log'
    log=core_path.read_text('utf-8-sig')
    core=re.search(r'Core baseline: (\d+)/(\d+) passed \(floor (\d+)\)',log)
    arch=re.search(r'Architecture check fixtures: (\d+)/(\d+) passed \(floor (\d+)\)',log)
    if 'Core CI: PASS' not in log or not core or not arch:
        raise ValueError('The final core test receipt is not a pass')
    e2e=load(out/'E2E_PROOFS.json')
    writer=load(out/'single-attempt/RESULT.json')
    dispatch=load(out/'single-attempt/DISPATCH.json')
    plan=load(out/'BRIDGE_PLAN.json')
    replay=load(out/'REBOUND.json')['replay']
    preflight=load(out/'PREFLIGHT_PROOFS.json')
    first=load(out/'WRITER_REPLY.json')
    child=load(out/'RECHECKED_DRAFT.json')
    assert e2e['status']=='VERIFIED' and preflight['status']=='PASS' and writer['exit_code']==0
    assert len(plan['binding']['imports']['cutaway'])==3 and len(plan['binding']['imports']['minds'])==3
    events=read_trace(out/'TRACE.jsonl')

    def latest(stage,status='CHECKED'):
        return next(row for row in reversed(events) if row['stage']==stage and row['status']==status)

    assert sum(r['stage']=='writer.dispatch' for r in events)==1
    assert latest('draft.apply')['evidence']['receipt']==e2e['apply_receipt']
    assert latest('scene.join')['evidence']['roger_sha256']==e2e['boundaries']['roger_sha256']
    assert latest('writer.recheck')['evidence']['candidate_sha256']==child['candidate_sha256']
    assert latest('import.rebind')['evidence']['world_sha256']==replay['world_sha256']
    assert latest('workspace.restore')['evidence']['restored_clip_sha256']==load(out/'IMPORTED_EVIDENCE.json')['clip']['sha256']
    assert latest('service.parity')['evidence']['provider_attempts']==0
    assert latest('cli.parity')['evidence']['same_receipt']
    assert latest('history.verify')['evidence']['history_round_trip']
    core_proof={'status':'PASS','fixtures':int(core[1]),'ran':int(core[2]),'floor':int(core[3]),
                'architecture_checks':int(arch[1]),'architecture_ran':int(arch[2]),'architecture_floor':int(arch[3]),
                'log_sha256':sha(core_path),'log':'core-final.log'}
    trace=Trace(out/'TRACE.jsonl',RUN)
    trace.scope=e2e['scope']
    trace.emit('verification.core','CHECKED',**{'result':core_proof},mode='core-ci',providers=0)
    event_id=trace.emit('verification.close','CHECKED',mode='local',one_writer=True,canon_published=False,
                        restore_undo_redo=True,source_unchanged=True,span_rebound=True)
    events=read_trace(out/'TRACE.jsonl')
    failures=sorted({r['case'] for r in events if r['status']=='REJECTED_AS_EXPECTED'})
    names=['SOURCE_ANCHORS.json','IMPORTED_EVIDENCE.json','FRAGMENT.json','CUTAWAY_REPLAY.json','BRIDGE_PLAN.json',
           'PREVIEW.json','PREFLIGHT_PROOFS.json','single-attempt/DISPATCH.json','single-attempt/RESULT.json',
           'WRITER_REPLY.json','RECHECKED_DRAFT.json','E2E_PROOFS.json','REBOUND.json','GENERATED_BRIDGE.md',
           'SPRING_BREAK_THREE_RETURN.md','ARCHITECTURE.md','TRACE.jsonl','core-final.log']
    proof={'status':'VERIFIED_ON_COPY','scope':e2e['scope'],'run':RUN,'studio':'http://127.0.0.1:8886/?episode=spring-break-three-return-scene',
           'trace':{'events':len(events),'final_event':event_id,'head_sha256':events[-1]['sha256'],'chain_valid':True},
           'source':e2e['boundaries'] | {'source_and_active_pointer_unchanged':True,'canon_published':False},
           'importer':{'edges':plan['binding']['imports']['cutaway'],'mind_targets':plan['binding']['imports']['minds'],
                       'new_semantic_import_calls':0,'after_apply_replay':replay['id'],'world_sha256':replay['world_sha256']},
           'bridge':{'scenes':[s['heading'] for s in plan['solved']['scenes']],
                     'required_facts':plan['solved']['goal'],'exit':plan['solved']['exit'],'join':'retained exact Scene 7 suffix'},
           'writer':{'invocations':1,'provider':dispatch['provider'],'model_requested':dispatch['model_requested'],
                     'input_payload_bytes':dispatch['input_bytes'],'usage_reported':writer['usage'],
                     'original_draft':first['draft_id'],'original_status':first['status'],'applied_draft':child['draft_id'],
                     'candidate_unchanged':True,'added_calls_recheck':0},
           'recovery':{'lost_reply_simulated':'UNKNOWN','provider_resends':0,'duplicate_commits':0,
                       'restored_clip_verified':True,'restore_undo_redo':True,'apply_receipt':e2e['apply_receipt']},
           'negative_probes':failures,'core':core_proof,'release_and_master_canon':'not run',
           'artifacts':{name:sha(out/name) for name in names}}
    put(out/'VERIFICATION.json',proof)
    data=json.dumps({'events':events,'proof':proof},ensure_ascii=False).replace('<','\\u003c')
    with (out/'TRACE_VIEW.html').open('x',encoding='utf-8') as report:
        report.write(HTML.replace('DATA_MARKER',data))
    print(f'{len(events)} hash-checked events, {len(failures)} distinct rejection checks. The trace reader and verification report are saved.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=BASE/'verified')
    render(parser.parse_args().out.resolve())
