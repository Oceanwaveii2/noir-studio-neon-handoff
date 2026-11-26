"""Bounded, source-linked multi-passage generation through the scoped engine."""
from __future__ import annotations

from story_graph.beat_map import map_episode
from story_graph.director import MAX_BEATS, select
from .scoped_service import execute_scoped
from .scoped_pipeline import build_packet, validate_output
from .notebook import NotebookStore, DraftStore
from .providers.session_registry import session_names

def _prepare_group(store, request, *, junctions=None, legacy_source=None, books_root=None, director_plan=None):
    mapping=map_episode(store,request['episode'],request['revision'],viewpoint=request.get('viewpoint') or None)
    if request.get('project') != mapping['project_id'] or request.get('universe') != mapping['universe_id'] or request.get('branch') != mapping['branch']:
        raise ValueError('Episode scope changed; refresh the beat map')
    if request.get('source_sha256') != mapping['source_sha256']:
        raise ValueError('Source changed; refresh the beat map')
    if request.get('anchor_token') is not None and request['anchor_token'] != mapping['anchor_token']:
        raise ValueError('Passage anchors changed; refresh the beat map')
    selected=select(mapping, request.get('beats'))
    notebook=NotebookStore(store)
    state=notebook.existing(mapping['episode'])
    if state is None or state['stale'] or state['timeline_revision']!=mapping['revision']:
        raise ValueError('Notebook protection is missing or stale')
    mode=request.get('provider')
    backend=request.get('references','none')
    if mode not in session_names() or backend not in ('none','topic','luar','style'):
        raise ValueError('Choose a valid session and book-reference setting')
    from .scoped_references import FUNCTIONS
    function=request.get('scene_function','scene')
    if function not in FUNCTIONS and function!='auto': raise ValueError('Choose a valid scene function')
    common={k:request.get(k) for k in ('episode','revision','project','universe','branch','viewpoint','direction')}
    common['direction']=common['direction'] or ''
    common.update(provider=mode,references=backend,scene_function=function,
                  reference_delivery=request.get('reference_delivery','excerpt'))
    jobs=[dict(common,beat=b['scope_beat'],start=b['start'],end=b['end'],passage_anchor=b['anchor']) for b in selected]
    controls=[None] * len(jobs)
    if director_plan:
        if [item['beat']['id'] for item in director_plan['choices']] != request['beats']:
            raise ValueError('Director plan does not match the selected passages')
        controls=[item['controls'] for item in director_plan['choices']]
    # Compile all plans before any dispatch. An ordinal never widens story scope.
    previews=[]
    for index,(job, control) in enumerate(zip(jobs, controls),1):
        previews.append(execute_scoped(store,'rhythm-preview',job,junctions=junctions,
            legacy_source=legacy_source,books_root=books_root,rhythm_position={'index':index,'count':len(jobs)},
            director_controls=control))
    for job,preview,control in zip(jobs,previews,controls):
        if execute_scoped(store,'context',job,junctions=junctions,legacy_source=legacy_source,
                          director_controls=control)['scope']!=preview['scope']:
            raise ValueError('Scope changed during rhythm group preparation')
    bindings=[p['reference_binding'] for p in previews if p['reference_binding']]
    if bindings:
        from .scoped_references import verify_draft_binding, DEFAULT_BOOKS
        if any(binding!=bindings[0] for binding in bindings):
            raise ValueError('Book settings changed during rhythm group preparation')
        verify_draft_binding(bindings[0],books_root or DEFAULT_BOOKS)
    from .rhythm_guidance import group_guidance
    guidance=group_guidance([{'beat':beat['id'],'plan':preview['rhythm_guidance']}
                             for beat,preview in zip(selected,previews)])
    if request.get('rhythm_plan_id') is not None and request['rhythm_plan_id']!=guidance['id']:
        raise ValueError('Rhythm plan changed; preview the selection again')
    return mapping,selected,jobs,previews,guidance


def preview_group(store, request, *, junctions=None, legacy_source=None, books_root=None):
    _,_,_,previews,guidance=_prepare_group(store,request,junctions=junctions,
        legacy_source=legacy_source,books_root=books_root)
    return {'status':'PREVIEW','rhythm_guidance':guidance,
            'reference_receipts':[r for p in previews for r in p['reference_receipts']],
            'generation_started':False,'provider_calls':0,'drafts_created':0}


def generate_group(store, request, *, junctions=None, legacy_source=None, provider_factory=None, books_root=None):
    mapping,selected,jobs,previews,guidance=_prepare_group(store,request,junctions=junctions,
        legacy_source=legacy_source,books_root=books_root)
    results=[]
    for index,(beat,job,preview) in enumerate(zip(selected,jobs,previews),1):
        try:
            if execute_scoped(store,'context',job,junctions=junctions,legacy_source=legacy_source)['scope']!=preview['scope']:
                raise ValueError('Scope changed after rhythm group preflight')
            result=execute_scoped(store,'generate',{**job,'rhythm_plan_id':preview['rhythm_guidance']['id']},junctions=junctions,legacy_source=legacy_source,
                                   provider_factory=provider_factory,books_root=books_root,
                                   rhythm_position={'index':index,'count':len(jobs)})
        except Exception as exc:
            return {'status':'PARTIAL','completed':results,'error':str(exc),'failed_beat':beat['id']}
        results.append({'beat':beat['id'],'draft_id':result['draft_id'],'status':result['status']})
        if result['status']!='PROPOSED':
            return {'status':'PARTIAL','completed':results,'error':'A passage proposal did not pass validation.','failed_beat':beat['id']}
    try:
        for job,preview in zip(jobs,previews):
            if execute_scoped(store,'context',job,junctions=junctions,legacy_source=legacy_source)['scope']!=preview['scope']:
                raise ValueError('Scope changed before rhythm group assembly')
        return assemble_group(store, request, results, guidance, junctions=junctions, books_root=books_root)
    except Exception as exc:
        return {'status':'PARTIAL','completed':results,'error':str(exc)}


def assemble_group(store, request, results, guidance, *, junctions=None, books_root=None,
                   draft_id=None, writing_run=None, write_guard=None):
    from .notebook import timeline_token
    from .scoped_groups import compose
    from .scoped_references import verify_draft_binding, DEFAULT_BOOKS
    drafts = DraftStore(NotebookStore(store))
    children = [drafts.open(request['episode'], request['branch'], row['draft_id']) for row in results]
    writer_receipts = [{'draft_id':child['id'], **child['writer_receipt']} for child in children
                       if child['origin'] == 'generated' and child.get('writer_receipt')]
    if writing_run and (not writer_receipts or len(writer_receipts) +
                        sum(child['origin'] == 'preserved' for child in children) != len(children)):
        raise ValueError('The saved passages do not have complete writer receipts')
    bindings = [c['reference_binding'] for c in children if c['reference_receipts']]
    if bindings and any(b != bindings[0] for b in bindings):
        raise ValueError('Book settings changed between passages')
    if bindings:
        verify_draft_binding(bindings[0], books_root or DEFAULT_BOOKS)
    packet,candidate,segments=compose(store,children,junctions() if junctions else None)
    receipts=[receipt for child in children for receipt in child['reference_receipts']]
    features={'scope':'consecutive-beat-group','observations':[
        {'beat':result['beat'],'draft_id':child['id'],'cadence':child['reference_features']}
        for result,child in zip(results,children) if child.get('reference_features')]} if receipts else None

    def guard(c):
        if write_guard:
            write_guard(c)
        base = timeline_token(c)
        if any(child['timeline_token'] != base for child in children):
            raise ValueError('Timeline changed between passages')

    aggregate=drafts.start(packet,request['provider'],reference_receipts=receipts,
        scene_function=request.get('scene_function','scene'),reference_features=features,
        rhythm_guidance=guidance,composite_segments=segments,reference_binding=bindings[0] if bindings else None,
        request_budget={'max_provider_calls':sum(c['request_budget']['max_provider_calls'] for c in children),
                        'token_limit':None}, draft_id=draft_id, writing_run=writing_run, write_guard=guard,
        proposal={'text':candidate,'issue':{'kind':'beat_group','children':[c['id'] for c in children],
                    'source_sha256':request['source_sha256'],'beats':request['beats']},
                  'writer_receipts':writer_receipts,
                  'rhythm_evidence':{'scope':'consecutive-beat-group','observations':[
                      {'beat':result['beat'],'draft_id':child['id'],'evidence':child.get('rhythm_evidence')}
                      for result,child in zip(results,children)]}})
    return {'status':'PROPOSED','draft_id':aggregate,'completed':results,'text':candidate,
            'reference_features':features,'rhythm_guidance':guidance,
            'book_status':{'state':'ready' if receipts else 'disabled','count':len(receipts)}}
