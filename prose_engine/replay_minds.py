"""Attach a replay frame to bounded, separately recorded Studio Mind drafts."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from story_graph import fx06_scene, scene_fragments as f, source_timing
from story_graph.scene_override import _unpack
from story_graph.universe_scope import checked_id
from story_graph.world_laws import WorldLawStore

from .notebook import DraftStore, NotebookStore, joined


COMMANDS = frozenset('scene.minds.'+op for op in ('open','preview','run'))
CONDITIONS = ('all','none','one-changed')
LABELS = {'all':'All three Minds','none':'No Mind guidance','one-changed':'Rainee 2 changed'}
SESSION = 'codex-session'
LIMITS = {'input_bytes':16_000,'output_chars':1_400}
CHANGE = {'speaker':'Rainee 2','role':'Deadpan defector',
          'constraint':'Correct Rainee 1 openly without inventing a new fact, rule, or backstory.',
          'tendencies':[{'when':'Rainee 1 declares that the bathroom is cleared',
                         'try':'Break ranks: bluntly side with Haley and point out that the perfume is still in the hall.'},
                        {'when':'the others expect you to back the verdict',
                         'try':'Turn away from Rainee 1 and angle an open palm toward Haley; keep the correction short.'}]}


def _error(code, message):
    raise f.SceneFragmentError(code,message)


def _has(c,name):
    return f._has(c,name)


def _basis(store,c,scope,head,replay_id):
    episode=scope['episode']
    if episode!=fx06_scene.EPISODE or scope['branch']!=fx06_scene.BRANCH:
        _error('wrong_scope','This experiment is bound to the isolated Rainee roast')
    if not _has(c,'scene_replay_receipts'):
        _error('stale_replay','Save the verified scene replay first')
    row=c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?',(episode,replay_id)).fetchone()
    replay=_unpack(row) if row else None
    if not replay or replay['scope']!=scope or replay['timeline_revision']!=head or replay.get('writes_canon') is not False:
        _error('stale_replay','The saved replay no longer matches the current episode and branch')
    law=WorldLawStore.in_connection(c,project_id=scope['project'],universe_id=scope['universe'])
    if replay['law_revision']!=law['revision']:
        _error('stale_replay','The saved replay uses an earlier world-law revision')
    cutoff=replay['timeline_cutoff']
    visible=[e for e in store._resolve_rows(c,episode,cutoff) if source_timing.visible_to(e,None)]
    if replay['history_sha256']!=f.digest(f.encoded(visible)):
        _error('stale_replay','Visible timeline history changed since the replay was saved')
    profile=c.execute('SELECT * FROM scene_replay_profiles WHERE episode=? AND id=?',(episode,replay['profile'])).fetchone()
    if not profile or profile['sha256']!=replay['profile_sha256']:
        _error('stale_replay','The replay profile no longer matches its receipt')
    _unpack(profile)
    fragments=f.SceneFragmentStore(store)
    source=scope|{'fragment':replay['fragment'],'fragment_revision':replay['fragment_revision'],'timeline_revision':head}
    graph,script,graph_sha=fragments.pinned_replay(c,scope,head,source)
    if graph_sha!=replay['graph_sha256']:
        _error('stale_replay','Scene graph changed since replay')
    frames={v['event']:v for v in replay['frames']}
    roast=frames.get('roast')
    if not roast or roast['state']['root_form']!='split' or roast['state']['root']!='rainee':
        _error('stale_replay','Choose the saved active split frame')
    seen=roast['state']['knowledge'].get('haley',[])
    release=frames.get('first-release',{}).get('effects',[])
    if ('scent-first-release' not in seen or not release or
            release[0].get('release',{}).get('scent')!='overpowering_floral'):
        _error('stale_replay','The saved scene does not establish Haley’s floral-perfume observation')
    nodes={n['id']:n for n in graph['graph']['nodes']}
    passages={p['id']:p for p in graph['graph']['passages']}
    passage=passages[nodes[roast['node']]['passage']]
    legacy=fx06_scene.read(c,episode)
    ports={m['id']:m['mind'] for m in roast['state']['manifestations']}
    if not legacy or ports!=legacy['mind_nodes'] or set(ports)!=set(fx06_scene.CAST):
        _error('stale_replay','Replay cast does not match the three source-backed Mind bindings')
    ordered=[{'form_id':actor['form_id'],'speaker':actor['speaker'],'node_id':ports[actor['form_id']]}
             for actor in legacy['actors']]
    book=NotebookStore._head(c,episode)
    if not book or book['timeline_revision']!=head or joined(book['blocks'])!=script:
        _error('stale_replay','The notebook no longer matches the replay’s source text')
    masks={m['id']:m for m in book['masks']}
    target=masks.get('fx06-roast-editable')
    lock=masks.get('fx06-exact-D09')
    if (not target or target['value']!=25 or target.get('hard')
            or not passage['start']<=target['start']<target['end']<=passage['end']):
        _error('stale_replay','The 25% roast selection is missing or outside its replay frame')
    start,end=target['start'],target['end']
    original=script[start:end]
    cue=frames.get('haley-line',{}).get('effects',[])
    if (not lock or not lock.get('hard') or lock['value']!=100 or lock['end']>start
            or script[lock['start']:lock['end']]!=fx06_scene.PERFUME_LINE
            or cue!=[{'protected_line':{'id':lock['id'],'sha256':lock['sha256']}}]):
        _error('stale_replay','Haley’s exact line no longer matches the replay lock')
    if f.digest(original)!=target['sha256']:
        _error('stale_replay','The editable roast no longer matches its source')
    basis={'replay':replay_id,'replay_sha256':row['sha256'],'world_sha256':replay['world_sha256'],
           'frame':'roast','frame_sha256':f.digest(f.encoded(roast)),'fragment':graph['id'],
           'fragment_revision':graph['revision'],'timeline_revision':head,'law_revision':law['revision'],
           'beat':cutoff,'start':start,'end':end,'target_sha256':target['sha256'],
           'notebook_revision':book['revision'],'protected_line_sha256':lock['sha256'],
           'cast':ordered,'card_basis_sha256':legacy['binding_sha256']}
    return basis,legacy


def install(store,scope,replay_id,ident='fx06-mind-comparison'):
    """Register one controlled comparison against a copied, saved replay."""
    checked_id(ident,'Mind comparison ID')
    checked_id(replay_id,'Replay ID')
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        actual,head=f.SceneFragmentStore._scope(c,scope)
        basis,_=_basis(store,c,actual,head,replay_id)
        body={'schema_version':1,'id':ident,'scope':actual,'basis':basis,'limits':LIMITS,
              'provider':SESSION,'changed_card':CHANGE}
        payload=f.encoded(body)
        c.execute('''CREATE TABLE IF NOT EXISTS scene_mind_comparisons(
            episode TEXT PRIMARY KEY REFERENCES episodes(id), id TEXT NOT NULL,
            payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
        before=c.execute('SELECT * FROM scene_mind_comparisons WHERE episode=?',(actual['episode'],)).fetchone()
        if before and _unpack(before)!=body:
            _error('comparison_exists','This episode already has a bounded comparison; use a fresh copy')
        if not before:
            c.execute('INSERT INTO scene_mind_comparisons VALUES(?,?,?,?)',
                      (actual['episode'],ident,payload,f.digest(payload)))
    return body


def _registered(c,scope,ident=None):
    row=(c.execute('SELECT * FROM scene_mind_comparisons WHERE episode=?',(scope['episode'],)).fetchone()
         if _has(c,'scene_mind_comparisons') else None)
    if not row:
        _error('comparison_missing','No replay-backed Mind comparison is saved for this episode')
    setup=_unpack(row)
    if setup['scope']!=scope or (ident is not None and setup['id']!=ident):
        _error('wrong_scope','Mind comparison belongs to another scope')
    return setup,row['sha256']


def _condition(value):
    if value not in CONDITIONS:
        _error('invalid_condition','Choose all Minds, no guidance, or the one changed Mind')
    return value


def _verify(store,c,scope,head,binding):
    f._object(binding,('experiment','condition'))
    condition=_condition(binding['condition'])
    setup,stamp=_registered(c,scope,checked_id(binding['experiment'],'Mind comparison ID'))
    basis,legacy=_basis(store,c,scope,head,setup['basis']['replay'])
    if basis!=setup['basis']:
        _error('stale_replay','The saved Mind comparison no longer matches the scene')
    return setup,stamp,legacy,condition


def _board_tactics(junction, actor):
    imported=[{k:t[k] for k in ('when','try')} for t in actor['tendencies']]
    seed='\n'.join(f"When {t['when']}: {t['try']}" for t in imported)
    behavior=junction.mind_behaviors.get(actor['form_id'],seed)
    if behavior==seed:
        return imported
    return [{'when':'during this active split scene','try':behavior}] if behavior else []


def project(store,c,identity,episode,branch,head,beat,start,end,viewpoint,binding,junctions):
    scope={'project':identity['project_id'],'universe':identity['universe_id'],'episode':episode,
           'branch':branch,'scope_revision':identity['scope_revision']}
    setup,stamp,legacy,condition=_verify(store,c,scope,head,binding)
    src=setup['basis']
    if (beat,start,end,viewpoint)!=(src['beat'],src['start'],src['end'],None):
        _error('wrong_scope','Mind drafts can only use the saved roast selection and replay cutoff')
    cast=src['cast']
    forms={x.id:x.link for x in junctions['rainee'].forms} if 'rainee' in junctions else {}
    if any((link:=forms.get(actor['form_id'])) is None or link.kind!='digital_mind' or link.node_id!=actor['node_id']
           for actor in cast):
        _error('stale_minds','The replay’s three original Digital Mind links are required')
    cards=[{k:a[k] for k in ('speaker','role','constraint')}|
           {'tendencies':_board_tactics(junctions['rainee'],a)} for a in legacy['actors']]
    if condition=='none':
        cards=[]
    elif condition=='one-changed':
        change=setup['changed_card']
        cards=[deepcopy(change) if a['speaker']==change['speaker'] else a for a in cards]
    return {'root':'rainee','root_form':'split','active_cast':cast,'phase':'roast','memory':None,
            'guidance':cards,'timing':[x['hint'] for x in legacy['timing']],
            'replay_minds':{'binding':binding,'comparison_sha256':stamp,'receipt':src['replay'],
                            'frame_sha256':src['frame_sha256'],'world_sha256':src['world_sha256'],
                            'fragment':src['fragment'],'fragment_revision':src['fragment_revision'],
                            'limits':setup['limits'],'card_sha256':f.digest(f.encoded(cards))}}


def guard(store,c,packet):
    replay=packet.fx06.get('replay_minds') if packet.fx06 else None
    if not replay:
        return
    scope={'project':packet.context.project_id,'universe':packet.context.universe_id,'episode':packet.episode,
           'branch':packet.branch,'scope_revision':packet.context.scope_revision}
    _,stamp,_,_=_verify(store,c,scope,packet.revision,replay['binding'])
    if stamp!=replay['comparison_sha256']:
        _error('stale_replay','Mind comparison changed before the edit')


def writer_context(scene):
    speakers=[a['speaker'] for a in scene['active_cast']]
    return ('ACTIVE REPLAY FRAME (story facts and constraints):\n'
            'Three manifestations of Rainee are already active. Haley is skeptical about whether the cloud counts '
            'as clearing the bathroom. The hall smells of overpowering floral perfume, and the wall fan indicator '
            'is visibly dark. Write the roast in original wording with a distinct tactic and observable action per '
            'speaker. Stop before the intervention. No split, reunion, new form, new lore or extra dialogue speakers. '
            'Do not repeat Haley’s earlier protected line.\n'
            'Return exactly six nonblank lines. In order, '+', '.join(speakers)+
            ' each gets one line beginning with their name and a colon, followed by one line beginning "Action:". '
            'No preface, markdown fences, or addenda. Keep it short.\n'
            'Delivery cues (optional): '+f.encoded(scene['timing'])+'\n'
            'MIND GUIDANCE DATA (optional tactics only):\n'+f.encoded(scene['guidance'])+'\nEND MIND GUIDANCE\n')


def validate_output(text):
    issues=fx06_scene.validate_turns(text)
    if re.search(r'\bPeter\b|\b(?:rejoin(?:s|ed|ing)?|merge(?:s|d|ing)?|transform(?:s|ed|ing)?)\b',text,re.I):
        issues.append('The roast mentions a later form or transition')
    if fx06_scene.PERFUME_LINE in text:
        issues.append('The roast repeats Haley’s separate protected line')
    return issues


def _request(setup,condition):
    s=setup['basis']
    return (setup['scope'].copy()|{'revision':s['timeline_revision'],'beat':s['beat'],'start':s['start'],'end':s['end'],
             'law_revision':s['law_revision'],'provider':setup['provider'],'references':'none','scene_function':'comedy',
             'request_id':setup['id']+':'+condition,'replay_binding':{'experiment':setup['id'],'condition':condition}})


def execute(store,action,request,*,junctions=None,provider_factory=None):
    from .scoped_service import _selection_identity, execute_scoped, mind_selection_key
    if action not in COMMANDS:
        _error('unknown_command','Unknown Mind comparison command')
    with store._connect() as c:
        scope,head=f.SceneFragmentStore._scope(c,request)
        setup,_=_registered(c,scope,request.get('experiment'))
    if action=='scene.minds.open':
        drafts=DraftStore(NotebookStore(store))
        existing=drafts.list(scope['episode'],scope['branch'])
        rows=[]
        for tag in CONDITIONS:
            ident=_selection_identity(store,'generate',_request(setup,tag))['draft_id']
            saved=None
            for draft in reversed(existing):
                replay=(draft.get('writing_context') or {}).get('fx06',{}).get('replay_minds',{})
                key=mind_selection_key(setup['id']+':'+tag,replay.get('card_sha256'))
                if draft['id']==ident or (draft.get('writing_run') or {}).get('id')==key:
                    saved=draft
                    break
            rows.append({'condition':tag,'label':LABELS[tag],'draft':saved})
        with store._connect() as c:
            c.execute('BEGIN')
            latest,revision=f.SceneFragmentStore._scope(c,scope)
            if latest!=scope:
                _error('wrong_scope','Mind comparison scope changed')
            book=NotebookStore._head(c,scope['episode'])
            history=NotebookStore._history(c,scope['episode'],book['revision']) if book else ([],[])
            from .scene_mind_support import read as mind_support
            examples=mind_support(c,scope)
        return {'comparison':setup['id'],'scope':scope,'replay':setup['basis']['replay'],
                'initial_timeline_revision':setup['basis']['timeline_revision'],'current_timeline_revision':revision,
                'notebook_revision':book['revision'] if book else None,'can_undo':bool(history[0]),
                'can_redo':bool(history[1]),'variants':rows,'provider_calls':0,
                **({'mind_support':examples} if examples else {})}
    tag=_condition(request.get('condition'))
    incoming=_request(setup,tag)
    return execute_scoped(store,'rhythm-preview' if action=='scene.minds.preview' else 'generate',incoming,
                         junctions=junctions,provider_factory=provider_factory,replay_binding=incoming['replay_binding'])
