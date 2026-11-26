"""Write one bounded next beat from an immutable branch result."""
from __future__ import annotations

import re

from story_graph import fx06_scene, scene_branches, scene_fragments as f


COMMANDS=frozenset('scene.branches.'+op for op in ('open','preview','run','seed'))
LIMITS={'input_bytes':16_000,'output_chars':1_400}
PROVIDER='codex-session'
NURSE='nurse_pamela_franny_anderson'
NAMES={'rainee':'Rainee','francine':'Francine','haley':'Haley',NURSE:'Nurse Franny',fx06_scene.PETER:'Rainee Peter'}


def _error(code,message):
    raise f.SceneFragmentError(code,message)


def _scope(identity,episode,branch):
    return {'project':identity['project_id'],'universe':identity['universe_id'],'scope_revision':identity['scope_revision'],
            'episode':episode,'branch':branch}


def _frame_notes(store, c, scope, head, replay):
    """Read display text from the exact graph and source the frames were saved against."""
    try:
        fragment, script, digest = f.SceneFragmentStore(store).pinned_replay(c, scope, head, replay)
    except f.SceneFragmentError:
        return {}
    if digest != replay['graph_sha256']:
        return {}
    passages = {item['id']: item for item in fragment['graph']['passages']}
    notes = {}
    for node in fragment['graph']['nodes']:
        if span := passages.get(node['passage']):
            excerpt = script[span['start']:span['end']].strip()
            notes[node['id']] = excerpt if len(excerpt) <= 420 else excerpt[:419]+'…'
    return notes


def project(store,c,identity,episode,branch,head,beat,start,end,viewpoint,binding,junctions):
    if 'scene_plan' in binding:
        from . import scene_plan
        return scene_plan.project(store,c,identity,episode,branch,head,beat,start,end,viewpoint,binding)
    if isinstance(binding, dict) and 'bridge' in binding:
        from . import scene_bridges
        return scene_bridges.project(store,c,identity,episode,branch,head,beat,start,end,viewpoint,binding)
    from . import scene_mind_support
    f._object(binding,('result','sha256'))
    scope=_scope(identity,episode,branch)
    record,stamp,frame,prior=scene_branches.resolve(store,c,scope,head,binding['result'])
    slot=record['slot']
    if stamp!=binding['sha256'] or (beat,start,end,viewpoint)!=(record['parent']['timeline_cutoff'],slot['start'],slot['end'],None):
        _error('wrong_result','The continuation must start in the exact slot after the recorded branch')
    parent=record['parent']['scope']
    state=frame['state']
    base=fx06_scene.read(c,parent['episode'])
    if not base or state['root']!='rainee':
        _error('wrong_result','The branch must use the saved FX06 character graph')
    ports={form.id:form.link for form in junctions['rainee'].forms} if 'rainee' in junctions else {}
    cast=[{'form_id':item['id'],'node_id':item['mind']} for item in state['manifestations']]
    cards={a['form_id']:a for a in base['actors']}
    for actor in cast:
        ident,link=actor['form_id'],ports.get(actor['form_id'])
        if link is None or link.kind!='digital_mind' or link.node_id!=actor['node_id'] or base['mind_nodes'].get(ident)!=link.node_id:
            _error('stale_minds','The active manifestations no longer have their original Mind links')
    scents=scene_mind_support.project(c,parent,state['root_form'],cast)
    allowed={}; location={}; guidance={}; active_forms={}
    for ident,actor in state['actors'].items():
        if ident in cards:
            a=cards[ident]; label=a['speaker']
            guidance[label]={'role':a['role'],'tactics':[x['try'] for x in a['tendencies'][:2]]}
        else:
            form=actor['form']
            group=junctions.get(ident)
            if not group or form not in {x.id for x in group.forms} or form not in NAMES:
                _error('stale_minds','A branch actor or its form could not be resolved')
            label=NAMES[form]
            active_forms[ident]=form
        allowed[ident]=label
        location[label]=actor['location']
    known=sorted(set(active_forms.values())|({state['split_origin']} if state.get('split_origin') else set()))
    return {'binding':binding,'lineage':{'fork':record['parent']['fork'],'replay':record['replay'],
             'terminal_event':frame['event'],'parent_frame_sha256':record['frame_sha256'],'world_sha256':record['world_sha256']},
            'scents':{r['speaker']:r['scent'] for r in scents['rules']} if scents else {},
            'scent_package_sha256':scents['package_sha256'] if scents else None,
            'root':state['root'],'root_form':state['root_form'],'active_forms':active_forms,'known_forms':known,
            'speaker_locations':location,'cast':allowed,'guidance':guidance,'prior':prior,'limits':LIMITS}


def guard(store,c,packet):
    if packet.continuation.get('kind') == 'scene-plan':
        from . import scene_plan
        return scene_plan.guard(store,c,packet)
    if packet.continuation.get('kind') == 'scene-bridge':
        from . import scene_bridges
        return scene_bridges.guard(store,c,packet)
    context=packet.context
    continuation=packet.continuation
    scope={'project':context.project_id,'universe':context.universe_id,'scope_revision':context.scope_revision,
           'episode':packet.episode,'branch':packet.branch}
    record,stamp,frame,_=scene_branches.resolve(store,c,scope,packet.revision,continuation['binding']['result'])
    if stamp!=continuation['binding']['sha256'] or record['frame_sha256']!=continuation['lineage']['parent_frame_sha256']:
        _error('stale_result','The continuation’s saved result changed')
    from . import scene_mind_support
    cast=[{'form_id':item['id'],'node_id':item['mind']} for item in frame['state']['manifestations']]
    scents=scene_mind_support.project(c,record['parent']['scope'],frame['state']['root_form'],cast)
    if (scents['package_sha256'] if scents else None)!=continuation['scent_package_sha256']:
        _error('stale_minds','The authorized local character rules changed')


def writer_context(continuation, media_guidance=()):
    if continuation.get('kind') == 'scene-plan':
        from . import scene_plan
        return scene_plan.writer_context(continuation, media_guidance)
    if continuation.get('kind') == 'scene-bridge':
        from . import scene_bridges
        return scene_bridges.writer_context(continuation, media_guidance)
    speakers=list(continuation['cast'].values())
    from .media_overrides import writer_context as media_context
    media_block = media_context(item for item in media_guidance if item['target']['kind'] == 'beat')
    return ('\nSAVED SCENE RESULT (already happened in this branch; continue after it, without repeating it):\n'
            +continuation['prior']+'\nEND SAVED SCENE\n\nCURRENT SPEAKERS AND POSITIONS:\n'
            +f.encoded(continuation['speaker_locations'])+'\nDISTINCT BEHAVIOR NOTES:\n'+f.encoded(continuation['guidance'])
            +'\nLOCAL CHARACTER SCENT CUES (only the named active forms):\n'+f.encoded(continuation['scents'])
            +media_block
            +'\nWrite one short comedic response beat. Give each of '+', '.join(speakers)+
            ' one new dialogue line prefixed with their exact name and a colon. Add exactly one line beginning Action: '
            'with a small visible gesture at the current positions. No other speakers, new gas release, force reaction, '
            'form change, departure, Shocker, lore, or mention of a future episode. The three do not remember private '
            'events from when they were inactive. Do not repeat the prior joke or frozen line. '
            'Maintain distinct voices. Plain text only.\n')


_TRANSITION=re.compile(r'\b(?:morph\w*|transform\w*|rejoin\w*|merg\w*|fart\w*|pass(?:es|ed)? gas|blows? .{0,32}away|split(?:s|ting)? (?:back )?into)\b',re.I)


def validate_output(continuation,text):
    if continuation.get('kind') == 'scene-plan':
        from . import scene_plan
        return scene_plan.validate_output(continuation,text)
    if continuation.get('kind') == 'scene-bridge':
        from . import scene_bridges
        return scene_bridges.validate_output(continuation,text)
    cast=set(continuation['cast'].values())
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if len(lines)!=len(cast)+1 or any(':' not in line for line in lines):
        return ['Use one dialogue line per active speaker and one Action line']
    spoken=set()
    for line in lines:
        speaker,body=line.split(':',1)
        if speaker not in cast|{'Action'} or speaker in spoken or not body.strip():
            return ['A continuation speaker is inactive, missing or repeated']
        spoken.add(speaker)
    if _TRANSITION.search(text) or fx06_scene.PERFUME_LINE in text or re.search(r'\bshocker\b',text,re.I):
        return ['A continuation must not repeat frozen dialogue or add a new transition or release']
    if fx06_scene.PETER not in continuation['known_forms'] and re.search(r'\bPeter\b',text,re.I):
        return ['That form has not been revealed in this branch']
    if NURSE not in continuation['known_forms'] and re.search(r'\bNurse Frann(?:y| Anderson)?\b',text,re.I):
        return ['That form has not been revealed in this branch']
    return []


def execute(store,action,request,*,junctions=None,provider_factory=None,provider_resolver=None):
    from .notebook import DraftStore, NotebookStore
    from .scoped_service import execute_scoped
    if action not in COMMANDS:
        raise ValueError('Unknown branch action')
    op=action.rsplit('.',1)[-1]
    if op=='seed':
        return scene_branches.seed(request['roles'])
    with store._connect() as c:
        c.execute('BEGIN')
        scope,head=f.SceneFragmentStore._scope(c,request)
        if op=='open':
            results=[]
            for item in scene_branches.list_visible(c,scope):
                branch=item['scope']
                ep=c.execute('SELECT title,head FROM episodes WHERE id=? AND status<>\'archived\'',(branch['episode'],)).fetchone()
                if ep:
                    trace,_=scene_branches._replay(c,branch,item['replay'])
                    current=ep['head']==item['timeline_revision']
                    notes=_frame_notes(store,c,branch,ep['head'],trace) if current else {}
                    results.append(item|{'title':ep['title'],'current':ep['head']==item['timeline_revision'],
                        'frames':[{'event':v['event'],'operation':v['operation'],'state':v['state'],
                                   'note':notes.get(v['node'])} for v in trace['frames']]})
        else:
            record,stamp,_,_=scene_branches.resolve(store,c,scope,head,request.get('result'))
    if op=='open':
        drafts=[]
        if any(row['scope']==scope for row in results):
            for d in DraftStore(NotebookStore(store)).list(scope['episode'],scope['branch']):
                continuation = (d.get('writing_context') or {}).get('continuation') or {}
                if result := continuation.get('binding', {}).get('result'):
                    drafts.append({'id':d['id'],'status':d['status'],'result':result})
        return {'results':results,'drafts':drafts,'provider_calls':0}
    slot=record['slot']; binding={'result':record['id'],'sha256':stamp}
    incoming=scope|{'revision':head,'beat':record['parent']['timeline_cutoff'],'start':slot['start'],'end':slot['end'],
                    'law_revision':record['law_revision'],'provider':PROVIDER,'references':'none','scene_function':'comedy'}
    args={'junctions':junctions,'continuation_binding':binding}
    preview=execute_scoped(store,'rhythm-preview',incoming,**args)
    if preview['prompt_bytes']>LIMITS['input_bytes']:
        _error('branch_budget','This continuation exceeds the one-call budget')
    plan=f._id('branch-continuation',incoming,preview['scope'],preview['rhythm_guidance']['id'])
    if op=='preview':
        return preview|{'plan':plan}
    if request.get('plan')!=plan:
        _error('stale_result','Preview this exact saved branch result before generating')
    if preview['rhythm_guidance']['fully_locked']:
        _error('protected_slot','The continuation slot is fully protected')
    if provider_factory is None and provider_resolver:
        provider_factory=lambda:provider_resolver(PROVIDER,scope['episode'])
    incoming|={'request_id':plan,'continuation_binding':binding,'rhythm_plan_id':preview['rhythm_guidance']['id']}
    reply=execute_scoped(store,'generate',incoming,provider_factory=provider_factory,
                         expected_clip_scope=preview['scope'],**args)
    return reply|{'plan':plan,'result':record['id'],'provider_calls':reply.get('provider_calls',0 if reply.get('replayed') else 1)}
