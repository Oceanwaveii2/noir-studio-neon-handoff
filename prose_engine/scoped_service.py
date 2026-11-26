"""Shared timeline-scoped operation dispatcher for UI and automation adapters."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from .scoped_pipeline import (build_packet, retrieve, validate_claims, validate_output,
                              diagnose_output, generate_recorded, recovery_scope)


def resolve_default_timeline(timeline_path=None, env_var: str = 'NOIR_TIMELINE') -> Path | None:
    """Resolve an explicit timeline path or configured NOIR_TIMELINE SQLite file."""
    if timeline_path:
        return Path(timeline_path)
    configured = os.environ.get(env_var, '').strip()
    if configured:
        candidate = Path(configured)
        if candidate.is_file():
            return candidate
    return None


def add_timeline_law_args(parser) -> None:
    """Register optional timeline scope flags for standalone world-law checks."""
    parser.add_argument('--timeline', default=None, help='Optional timeline sqlite for universe world-law checks')
    parser.add_argument('--project', default=None, help='Expected project ID')
    parser.add_argument('--universe', default=None, help='Expected universe ID')
    parser.add_argument('--episode', default=None, help='Optional episode ID for branch and beat law activation')
    parser.add_argument('--branch', default='main', help='Episode branch for time-bounded laws')
    parser.add_argument('--beat', type=int, default=0, help='Beat index for time-bounded laws')


def check_namespace_world_laws(text: str, args) -> dict:
    """Run universe world-law enforcement from parsed CLI/tool arguments."""
    return enforce_standalone_world_laws(
        text,
        timeline_path=getattr(args, 'timeline', None),
        project_id=getattr(args, 'project', None),
        universe_id=getattr(args, 'universe', None),
        episode=getattr(args, 'episode', None),
        branch=getattr(args, 'branch', 'main') or 'main',
        beat=getattr(args, 'beat', 0) or 0,
    )


def enforce_standalone_world_laws(text: str, *, timeline_path=None, project_id=None, universe_id=None, episode=None, branch: str = 'main', beat: int = 0) -> dict:
    """Evaluate text against universe world laws when a timeline store is supplied."""
    resolved = resolve_default_timeline(timeline_path)
    if not resolved:
        return {'enforced': False, 'passed': True, 'violations': [], 'diagnostics': [],
                'warning': 'No timeline supplied; world laws were not checked.'}
    from story_graph.episode_timeline import TimelineStore
    from story_graph.typed_laws import active_laws, branch_points
    from story_graph.world_laws import WorldLawStore, check_laws, parentage_findings
    from .meaning_checks import _semantic_paraphrase_findings
    store = TimelineStore(resolved, project_id=project_id, universe_id=universe_id)
    law_state = WorldLawStore(store, project_id=project_id, universe_id=universe_id).open()
    laws = [law for law in law_state['laws'] if law.get('enabled')]
    if episode:
        with store._connect() as c:
            laws = active_laws(laws, branch_points(c, episode, int(beat)), branch)
    matched = check_laws(text, laws)
    violations = sorted({f'{law_id}: {phrase}' for (law_id, phrase) in matched})
    diagnostics = [finding for law in laws if law.get('matcher') == 'haley_parentage'
                   for finding in parentage_findings(text, law, law_state['revision'])]
    sem_findings = _semantic_paraphrase_findings(
        SimpleNamespace(world_laws=tuple(laws), world_law_revision=law_state['revision']),
        text,
    )
    for item in sem_findings:
        diagnostics.append(item)
        if item.get('status') == 'contradicted':
            violations.append(f"{item['rule_id']}: {item['evidence']}")
    with store._connect() as c:
        scope_row = store.scope()
        has_custom_canon = any(
            c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            for t in ('universe_laws_v2', 'state_deltas')
        )
        if scope_row['kind'] == 'afm-starters' or has_custom_canon:
            from .canon_guard import check_prose_canon, format_finding
            state_findings = check_prose_canon(
                text,
                universe_id=law_state['universe_id'],
                branch=branch,
                episode_id=episode or 'spring-break',
                beat=int(beat),
                timeline_conn=c,
                seed_afm=(scope_row['kind'] == 'afm-starters'),
            )
            for item in state_findings:
                diagnostics.append(item.to_dict())
                if item.status == 'conflict':
                    violations.append(format_finding(item))
    return {'enforced': True, 'passed': len(violations) == 0, 'violations': sorted(set(violations)),
            'diagnostics': diagnostics, 'revision': law_state['revision'],
            'timeline': str(resolved),
            'scope': {'project_id': law_state['project_id'], 'universe_id': law_state['universe_id'],
                      'branch': branch, 'beat': int(beat)}}


def record_standalone_draft(
    text: str,
    *,
    original_text: str = '',
    source_path=None,
    route: str = 'standalone',
    provider_name: str = 'unknown',
    timeline_path=None,
    project_id=None,
    universe_id=None,
    episode=None,
    branch: str = 'main',
    beat: int = 0,
    out_dir=None,
    issues=(),
    extra=None,
) -> dict:
    """Record a standalone or legacy generation through scope-aware drafts or telemetry receipts."""
    resolved = resolve_default_timeline(timeline_path)
    prov = provider_name if isinstance(provider_name, str) and provider_name else 'unknown'
    issues_list = [str(x) for x in (issues or ()) if str(x)]
    cand_sha = hashlib.sha256((text or '').encode('utf-8')).hexdigest()
    orig_sha = hashlib.sha256((original_text or '').encode('utf-8')).hexdigest()

    if resolved and resolved.is_file() and episode:
        from story_graph.episode_timeline import TimelineStore
        from .notebook import DraftStore, NotebookStore
        store = TimelineStore(resolved, project_id=project_id, universe_id=universe_id)
        ep = store.get_episode(episode)
        script = ep['script'] or original_text
        if script:
            packet = build_packet(
                store, episode, int(beat), ep['head'], 0, len(script),
                project_id=project_id, universe_id=universe_id, branch=branch or ep['branch'],
            )
            law_check = enforce_standalone_world_laws(
                text, timeline_path=resolved, project_id=project_id, universe_id=universe_id,
                episode=episode, branch=branch or ep['branch'], beat=int(beat),
            )
            if not law_check['passed']:
                issues_list.extend(law_check['violations'])
            drafts = DraftStore(NotebookStore(store))
            status = 'BLOCKED' if issues_list else 'PROPOSED'
            draft_id = drafts.start(
                packet,
                prov,
                proposal={
                    'text': text or original_text,
                    'issue': {'kind': 'standalone_scoped', 'route': route, 'reasons': issues_list} if issues_list else {'kind': 'standalone_scoped', 'route': route},
                },
            )
            if status == 'BLOCKED':
                with store._connect() as c:
                    c.execute('UPDATE episode_drafts SET status=? WHERE id=?', ('BLOCKED', draft_id))
            return {
                'schema_version': 1,
                'recorded_in_timeline': True,
                'scope_status': 'scoped-timeline',
                'draft_id': draft_id,
                'status': status,
                'route': route,
                'episode': episode,
                'branch': branch or ep['branch'],
                'beat': int(beat),
                'world_law_checked': True,
                'issues': issues_list,
                'candidate_sha256': cand_sha,
                'original_sha256': orig_sha,
            }

    receipt = {
        'schema_version': 1,
        'recorded_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'recorded_in_timeline': False,
        'scope_status': 'unscoped-standalone' if not resolved else 'timeline-without-episode',
        'route': route,
        'provider': prov,
        'source_path': str(source_path) if source_path else None,
        'timeline': str(resolved) if resolved else None,
        'world_law_checked': bool(resolved),
        'issues': issues_list,
        'original_sha256': orig_sha,
        'candidate_sha256': cand_sha,
        'extra': extra or {},
    }
    target_dir = Path(out_dir) if out_dir else Path('telemetry/eval')
    target_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = target_dir / 'generation_receipts.jsonl'
    with receipt_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + '\n')
    return {**receipt, 'receipt_path': str(receipt_path)}


def _selection_identity(store, action, request):
    import re
    from story_graph.director import fingerprint
    key = request.get('request_id')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,125}',key):
        raise ValueError('Invalid selection request ID')
    scope = store.scope()
    return {'draft_id':fingerprint(['scoped-selection',scope['project_id'],request['episode'],key])[:32],
            'writing_run':{'id':key,'kind':'selection','checksum':fingerprint([action,request])}}


def mind_selection_key(request_id, card_digest):
    from story_graph.director import fingerprint
    return 'mind-'+fingerprint([request_id,card_digest])


def _selection_replay(store, identity, request):
    with store._connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episode_drafts'").fetchone():
            return None
        row=c.execute('SELECT status,payload FROM episode_drafts WHERE id=? AND episode=?',
                      (identity['draft_id'],request['episode'])).fetchone()
        if row is None:
            return None
        import json
        saved=json.loads(row['payload'])
        if saved.get('writing_run') != identity['writing_run']:
            raise ValueError('Request ID already belongs to a different selection')
        return {'status':row['status'],'draft_id':identity['draft_id'],'replayed':True,
                'text':saved['text'] if row['status']=='PROPOSED' else None,
                'origin':saved.get('origin', 'unknown'), 'writer_receipt':saved.get('writer_receipt'),
                'provider_request_id':saved.get('provider_request_id'),
                'attempt_id':saved.get('attempt_id'),'provider_calls':0}


def execute_scoped(store, action, request, *, junctions=None, legacy_source=None, provider_factory=None,
                   books_root=None, rhythm_position=None, director_controls=None, run_part=None, replay_binding=None,
                   clip_binding=None, expected_clip_scope=None, continuation_binding=None, selection_run=False):
    """Compile one scope and recompile it around every explicit provider call.

    The optional suppliers are called again during recheck, not cached. No model
    is constructed for context, retrieval, validation or export.
    """
    if action not in ('context','export','retrieve','validate','generate','condition','variant','apply-draft','rhythm-preview'):
        raise ValueError('Unknown scoped action')
    direction=request.get('direction','')
    if not isinstance(direction,str) or len(direction)>500:
        raise ValueError('Writing direction must be text up to 500 characters')
    draft_identity=None
    identify=not run_part and action in ('generate','condition','variant') and request.get('request_id') is not None
    version_minds=identify and replay_binding and not clip_binding
    if identify and not version_minds:
        draft_identity=_selection_identity(store,action,request)
        if replay := _selection_replay(store,draft_identity,request):
            return replay
    if action=='apply-draft':
        from .episode_commands import EpisodeCommands
        from .notebook import NotebookStore, DraftStore
        drafts=DraftStore(NotebookStore(store))
        episode=store.get_episode(request['episode'])
        draft=drafts.open(request['episode'],episode['branch'],request['draft'])
        if (request.get('branch') not in (None,draft['branch']) or request['revision']!=draft['source_revision']
                or request['start']!=draft['start'] or request['end']!=draft['end']
                or (request.get('viewpoint') or None)!=draft['viewpoint']
                or (not draft.get('composite_segments') and request.get('beat') not in (0,draft['beat']))
                or request.get('law_revision') not in (None,draft['world_law_revision'])):
            raise ValueError('Draft does not match the requested scope')
        result=EpisodeCommands(store,junctions=junctions,books_root=books_root).execute('draft.apply',
                  {**request,'branch':draft['branch'],'timeline_revision':request['revision']})
        return {**result,'context':draft['writing_context'] if draft.get('composite_segments') else draft['context']}
    def compile_packet():
        packet=build_packet(store,request['episode'],request['beat'],request['revision'],request['start'],request['end'],
            request.get('viewpoint') or None, junctions() if junctions else None,
            legacy_source() if legacy_source else None, protected_ranges=request.get('protected_ranges'),
            project_id=request.get('project'),universe_id=request.get('universe'),
            branch=request.get('branch'),law_revision=request.get('law_revision'),passage_anchor=request.get('passage_anchor'),
            replay_binding=replay_binding,clip_binding=clip_binding,continuation_binding=continuation_binding,
            compositor_preparation=request.get('compositor_preparation'), books_root=books_root)
        if direction or director_controls:
            from dataclasses import replace
            from story_graph.world_laws import check_laws
            from story_graph.beat_rhythm import _validate
            if any(h.strip().casefold() in direction.casefold() for h in packet.hidden_phrases if len(h.strip())>=8):
                raise ValueError('Writing direction includes information unavailable at this beat')
            if check_laws(direction,packet.world_laws):
                raise ValueError('Writing direction conflicts with a configured world law')
            rhythm=dict(packet.beat_rhythm)
            profile=dict(rhythm['profile'])
            if director_controls:
                profile.update(director_controls)
                _validate(profile)
            profile['author_override']='\n'.join(x for x in (profile['author_override'], direction) if x)
            rhythm['profile']=profile
            rhythm['status']='configured'
            packet=replace(packet,beat_rhythm=rhythm)
        return packet
    packet=compile_packet()
    parent = request.get('parent_draft')
    if packet.continuation and (rough := packet.continuation.get('polish')):
        if parent is not None and parent != rough['draft']:
            raise ValueError('The validated rough draft owns the polish variant')
        parent = rough['draft']
    if expected_clip_scope is not None and packet.public() != expected_clip_scope:
        raise ValueError('The saved writing context changed; preview again')
    if version_minds:
        replay=packet.fx06['replay_minds']
        original=request
        request=request | {'request_id':mind_selection_key(original['request_id'],replay['card_sha256'])}
        draft_identity=_selection_identity(store,action,request)
        if saved := _selection_replay(store,draft_identity,request):
            return saved
        # Older selections used the unversioned key. Reuse only a matching card.
        old_identity=_selection_identity(store,action,original)
        if old := _selection_replay(store,old_identity,original):
            from .notebook import DraftStore, NotebookStore
            prior=DraftStore(NotebookStore(store)).open(packet.episode,packet.branch,old['draft_id'])
            if prior['writing_context']['fx06']['replay_minds']['card_sha256']==replay['card_sha256']:
                return old
    from . import scoped_pipeline as pipeline
    if any(not callable(getattr(pipeline,name,None)) for name in ('validate_output','validate_claims','diagnose_output')):
        raise ValueError('Scoped validators are unavailable')
    if not isinstance(pipeline.validate_output(packet,packet.target),list):
        raise ValueError('Scoped output validator is unavailable')
    if action in ('context','export'):
        return {'scope':packet.public(),'warning':'Only recorded timeline material is scoped; model output requires review.'}
    if action=='retrieve':
        return {'results':retrieve(packet,request.get('query','')),'context':packet.context.public()}
    if action=='validate':
        text=request.get('text',packet.target)
        from .canon_corrector import auto_correct_canon
        from .meaning_checks import assess_meaning, assess_semantic_review
        claims=request.get('claims',[])
        world_claims=[c for c in claims if isinstance(c,dict) and c.get('kind')=='world_fact']
        corr=auto_correct_canon(
            text,
            apply=True,
            compiled_state=packet.canon_state,
            character_profiles=packet.characters,
            episode_id=packet.episode,
            branch=packet.branch,
            beat=packet.beat,
            viewpoint=packet.viewpoint,
            protected_ranges=tuple((max(0, a - packet.start), max(0, b - packet.start)) for a, b, _ in packet.protected),
        )
        return {'issues':validate_claims(packet,claims) +
                [{'reason':x} for x in validate_output(packet,text)],
                'diagnostics':diagnose_output(packet,text),
                'meaning':assess_meaning(packet,text,world_claims,semantic_review=bool(request.get('semantic_review', False))),
                'semantic_review':assess_semantic_review(packet,text,world_claims),
                'suggested_corrections':[c.to_dict() for c in corr.corrections],
                'auto_corrected_text':corr.corrected_text,
                'context':packet.context.public()}
    if store.prerequisites(packet.episode):
        raise ValueError('Episode has an unmet continuity prerequisite')
    mode=request.get('provider')
    from .providers.session_registry import session_names
    if mode not in session_names():
        raise ValueError('Choose a configured writing session')
    backend=request.get('references','none')
    from .scoped_references import FUNCTIONS
    scene_function=request.get('scene_function','scene')
    if scene_function in ('auto', '', None) or scene_function not in FUNCTIONS:
        scene_function = 'scene'
    if scene_function=='scene' and packet.beat_rhythm.get('status')=='configured':
        intent = packet.beat_rhythm.get('profile', {}).get('intent')
        if intent in FUNCTIONS:
            scene_function = intent
    if backend not in ('none','topic','luar','style','hybrid'):
        raise ValueError('Choose no books, topic, LUAR, style or hybrid references')
    delivery=request.get('reference_delivery','excerpt')
    if delivery not in ('cadence','excerpt'):
        raise ValueError('Choose a valid book reference delivery')
    craft_mode=request.get('craft_mode','preserve')
    if craft_mode not in ('preserve','expand'):
        raise ValueError('Choose preserve or expand craft mode')
    bundle=None
    from .rhythm_guidance import compile_guidance
    base=compile_guidance(packet,scene_function,position=rhythm_position,craft_mode=craft_mode)
    if (action != 'rhythm-preview' and packet.continuation and packet.continuation.get('kind') == 'scene-plan'
            and packet.protected and not base['fully_locked']):
        raise ValueError('The planned scene contains exact protected text. Unlock the intended writable passage to use this plan.')
    if backend!='none' and not (delivery=='cadence' and base['fully_locked']):
        from .scoped_references import DEFAULT_BOOKS, select_references
        bundle=select_references(packet,root=books_root or DEFAULT_BOOKS,backend=backend,
                                 provider=mode,scene_function=scene_function)
    from .scoped_references import beat_craft_cards, cadence_observation, craft_observation
    features=(craft_observation if delivery=='cadence' else cadence_observation)(bundle['texts']) if bundle else None
    guidance=compile_guidance(packet,scene_function,features,bundle['receipts'],rhythm_position,craft_mode=craft_mode) if bundle else base
    if bundle and delivery=='cadence':
        from story_graph.director import fingerprint
        guidance = {**guidance, 'reference_delivery': delivery}
        if cards := beat_craft_cards(packet, features, bundle):
            guidance['craft_cards'] = cards
        guidance['id']=fingerprint({k:v for k,v in guidance.items() if k!='id'})
    if request.get('rhythm_plan_id') is not None and request['rhythm_plan_id']!=guidance['id']:
        raise ValueError('Rhythm plan changed; preview the selection again')
    if action=='rhythm-preview':
        if bundle:
            from .scoped_references import verify_references
            verify_references(bundle)
        if compile_packet()!=packet: raise ValueError('Scope changed while preparing rhythm guidance')
        from .scoped_references import draft_binding
        prompt = b'' if guidance['fully_locked'] else pipeline.prompt_for(
            packet, bundle['texts'] if bundle else (), scene_function, features,
            bundle['receipts'] if bundle else None, guidance).encode('utf-8')
        from hashlib import sha256
        return {'status':'PREVIEW','scope':packet.public(),'rhythm_guidance':guidance,'reference_features':features,
                'craft_cards':guidance.get('craft_cards', []),
                'reference_receipts':bundle['receipts'] if bundle else [],
                'reference_binding':draft_binding(bundle) if bundle else None,
                'prompt_bytes':len(prompt),'prompt_sha256':sha256(prompt).hexdigest(),
                'generation_started':False,'provider_calls':0,'drafts_created':0}
    if selection_run and guidance['fully_locked']:
        return {'status':'PRESERVED','origin':'preserved','preserved':True,'provider_calls':0,
                'rhythm_guidance':guidance,'reason':'The selected text is fully protected.',
                'scope':packet.public()}
    if run_part and packet.public() != run_part['expected_scope']:
        raise ValueError('The saved writing context changed before dispatch')
    if provider_factory is None:
        from .providers.primary_session import create_scoped_provider
        provider_factory=lambda: create_scoped_provider(mode,recovery_scope=recovery_scope(store,packet.episode))
    from sqlite3 import IntegrityError
    try:
        if bundle:
            from .scoped_references import verify_references, draft_binding
            result=generate_recorded(store,packet,mode,provider_factory,compile_packet,parent,
                  references=bundle['texts'],reference_receipts=bundle['receipts'],reference_check=lambda:verify_references(bundle),scene_function=scene_function,reference_features=features,reference_binding=draft_binding(bundle),rhythm_guidance=guidance,run_part=run_part,draft_identity=draft_identity)
            return {**result,'book_status':{'state':'ready','message':bundle['message'],'count':len(bundle['receipts'])}}
        result=generate_recorded(store,packet,mode,provider_factory,compile_packet,parent,scene_function=scene_function,rhythm_guidance=guidance,run_part=run_part,draft_identity=draft_identity)
    except IntegrityError:
        if draft_identity and (replay := _selection_replay(store,draft_identity,request)):
            return replay
        raise
    return {**result,'book_status':{'state':'disabled','message':'No book references were requested.','count':0}}
