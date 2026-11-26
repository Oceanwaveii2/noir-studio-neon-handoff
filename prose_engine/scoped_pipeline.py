"""Fail-closed episode packet shared by generation, retrieval, validation and export.

The caller explicitly selects the target script span. Legacy inputs are never mixed in.
The checks enforce known records and exact labels, not semantic proof about model output.
"""
from __future__ import annotations
from contextlib import nullcontext
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re
from story_graph.character_forms import AFM_JUNCTIONS
from story_graph import fx06_scene
from story_graph.episode_timeline import TimelineStore
from story_graph import source_timing
from story_graph.world_laws import WorldLawStore, check_laws, parentage_findings
from story_graph.typed_laws import active_laws, branch_points, validate_world_claim
from story_graph.universe_scope import NarrativeContext, verify_scope
from story_graph.scenarios.foxy_mo2 import run_foxy_mo2, build_foxy_mo2_world
from story_graph.character_profiles import (
    merge_node_profiles,
    resolve as resolve_characters,
    snapshot as character_snapshot,
)
from story_graph.beat_rhythm import read as read_beat_rhythm
from .models import ProseRewriteRequest, ProtectedSpan, SpanCategory


_DIALOGUE = re.compile(r'“[^”]+”|"[^"\r\n]+"|^[ \t]*[A-Z][A-Z0-9 .\'-]{1,30}:[^\r\n]+',
                       re.MULTILINE)


def _exact_spans(script, start, end, ranges, *, include_dialogue=True):
    if ranges is None:
        ranges = []
    if not isinstance(ranges, list) or len(ranges) > 128:
        raise ValueError("Protected ranges must be a list of at most 128 [start, end] pairs")
    intervals = [(m.start(), m.end()) for m in _DIALOGUE.finditer(script, 0)] if include_dialogue else []
    for pair in ranges:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2 or
                any(type(n) is not int for n in pair) or not 0 <= pair[0] < pair[1] <= len(script)):
            raise ValueError("Protected range is outside this revision")
        intervals.append(tuple(pair))
    merged = []
    for a, b in sorted(intervals):
        a, b = max(a, start), min(b, end)
        if a >= b:
            continue
        if merged and a < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return tuple((a, b, script[a:b]) for a, b in merged)


def recovery_scope(store, episode):
    """The same episode cannot accidentally retry an unresolved scoped dispatch."""
    key = json.dumps([str(Path(store.path).resolve()), episode])
    return "timeline:" + hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class ScopedPacket:
    episode: str
    branch: str
    beat: int
    viewpoint: str | None
    revision: int
    target: str
    target_sha256: str
    events: tuple[dict, ...]
    forms: dict
    hidden_phrases: tuple[str, ...]
    form_sources: tuple[dict, ...] = ()
    start: int = 0
    end: int | None = None
    protected: tuple[tuple[int, int, str], ...] = ()
    protection_revision: int | None = None
    protection_ranges: tuple[tuple[int, int, int], ...] = ()
    world_laws: tuple[dict, ...] = ()
    world_law_revision: int = 0
    context: NarrativeContext | None = None
    characters: dict = field(default_factory=dict)
    character_store_token: str = 'none'
    beat_rhythm: dict = field(default_factory=dict)
    passage_anchor: dict | None = None
    composite: tuple = ()
    source_graph: dict | None = None
    fx06: dict | None = None
    clip_context: dict | None = None
    mind_support: dict | None = None
    continuation: dict | None = None
    relationships: tuple[dict, ...] = ()
    media_guidance: tuple[dict, ...] = ()
    universe_kind: str = ""
    state_digest: str = ""
    canon_state: object = field(default=None, repr=False, compare=False)
    compositor: dict | None = None
    compositor_books: object = field(default=None, repr=False, compare=False)

    def character_receipts(self):
        return [{'character_id':cid,'form_id':part['form_id'],'node':part['node'],
                 'status':part['status'],'revision':part['revision'],
                 'fields':[{'id':item['id'],'category':item['category'],'source':item['source'],
                            'confidence':item['confidence']} for item in part['fields']]}
                for cid,group in self.characters.items() for part in group['profiles']]

    def public(self) -> dict:
        return {'episode':self.episode,'branch':self.branch,'beat':self.beat,'viewpoint':self.viewpoint,
                'revision':self.revision,'target':self.target,'target_sha256':self.target_sha256,
                'events':[dict(e) for e in self.events], 'forms':self.forms,
                'form_sources':[dict(item) for item in self.form_sources],
                'start':self.start,'end':self.end,
                'protected_ranges':[[a,b] for a,b,_ in self.protected],
                'protection_revision':self.protection_revision,
                'protection_values':[[a,b,value] for a,b,value in self.protection_ranges],
                'world_laws':[dict(law) for law in self.world_laws],
                'world_law_revision':self.world_law_revision,
                'characters':self.characters,
                'beat_rhythm':self.beat_rhythm,
                'passage_anchor':self.passage_anchor,
                'composite_scopes':[p.public() for p in self.composite],
                'source_graph':self.source_graph,
                **({'fx06': self.fx06} if self.fx06 else {}),
                **({'clip_context': self.clip_context} if self.clip_context else {}),
                **({'mind_support': self.mind_support} if self.mind_support else {}),
                **({'continuation': self.continuation} if self.continuation else {}),
                **({'relationships': list(self.relationships)} if self.relationships else {}),
                **({'media_guidance': list(self.media_guidance)} if self.media_guidance else {}),
                **({'compositor': self.compositor} if self.compositor else {}),
                'context':self.context.public() if self.context else None}


@lru_cache(maxsize=1)
def _u4_disclosures():
    packets=run_foxy_mo2()
    beats={packet.beat_id:i for i,packet in enumerate(packets,1)}
    rows=tuple((cid,form,beat_id,beats[beat_id])
               for cid,forms in build_foxy_mo2_world().form_reveal_beats.items()
               for form,beat_id in forms.items())
    return packets,rows


def build_packet(store: TimelineStore, episode: str, beat: int, revision: int,
                 start: int, end: int, viewpoint: str | None = None, junctions=None,
                 legacy_spring_text: str | None = None, *, protected_ranges=None,
                  project_id=None, universe_id=None, branch=None, law_revision=None, passage_anchor=None,
                 replay_binding=None, clip_binding=None, continuation_binding=None, connection=None,
                 compositor_preparation=None, books_root=None) -> ScopedPacket:
    if type(beat) is not int or beat < 0 or type(revision) is not int:
        raise ValueError('Episode, beat and revision are required')
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError('Select a nonempty script range')
    if viewpoint is not None and (not isinstance(viewpoint,str) or not viewpoint.strip()):
        raise ValueError('Viewpoint must be a character ID or omitted')
    if connection is None:
        WorldLawStore(store,project_id=project_id,universe_id=universe_id)
    with (nullcontext(connection) if connection is not None else store._connect()) as c:
        if connection is None:
            c.execute('BEGIN')
        identity=verify_scope(c,project_id=project_id,universe_id=universe_id)
        if compositor_preparation is not None:
            from .scene_bridges import _junctions
            junctions = _junctions(store, c, episode)
        if junctions is None:
            junctions=AFM_JUNCTIONS if identity['kind']=='afm-starters' else {}
        ep=c.execute('SELECT * FROM episodes WHERE id=?',(episode,)).fetchone()
        if not ep: raise ValueError('Unknown episode')
        if branch is not None and branch != ep['branch']: raise ValueError('Branch does not match episode')
        if ep['head'] != revision: raise ValueError('Stale episode revision')
        row=c.execute('SELECT script,graph,source_name FROM revisions WHERE episode=? AND revision=?',(episode,revision)).fetchone()
        if not row: raise ValueError('Episode revision is missing')
        script=row['script']
        used_legacy=False
        if not script and identity['kind']=='afm-starters' and episode=='spring-break' and revision==0 and legacy_spring_text is not None:
            script=legacy_spring_text
            used_legacy=True
        if end > len(script): raise ValueError('Script range is outside this revision')
        target=script[start:end]
        if not target.strip(): raise ValueError('Selected script range is empty')
        from story_graph.source_imports import snapshot as source_snapshot, junctions as imported_junctions
        source_graph=source_snapshot(c,episode,revision,script,hashlib.sha256(row['graph'].encode('utf-8')).hexdigest(),start,end,viewpoint)
        if source_graph is not None:
            original_ids=set(junctions)
            seen_ids={item['character_id'] for item in source_graph['characters']}
            junctions={cid:group for cid,group in imported_junctions(c,junctions).items() if cid in original_ids or cid in seen_ids}
        from story_graph.beat_anchors import check as check_anchor
        anchor = check_anchor(store,c,episode,revision,start,end,beat,viewpoint,passage_anchor) if not used_legacy else None
        cut = source_timing.cut_for(start,end,source_timing.windows(c,episode))
        if cut:
            if (anchor is None and beat == 0) or (anchor and anchor['status'] == 'source-verified'):
                beat = cut.beat
            if beat > cut.beat:
                raise ValueError('Requested beat is later than the verified passage timing')
        protected=_exact_spans(script,start,end,protected_ranges)
        visible=[r for r in store._resolve_rows(c,episode,beat,source_span=(start,end))
                 if source_timing.visible_to(r,viewpoint)]
        if source_graph is not None and source_timing.managed(c) and not any('source_timing' in e for e in visible):
            # The imported edition's historical form is another route to the
            # same disclosure. Keep it behind the timeline and viewpoint.
            source_graph = dict(source_graph, characters=[item for item in source_graph['characters']
                                if item['active_form'] != source_timing.IMPORTED_FORM])
        visible_ids={e['id'] for e in visible}
        active_ids=store._active_event_ids(c)
        hidden=[r['content'] for r in c.execute("SELECT id,content FROM events ORDER BY id") if r['id'] in active_ids and r['id'] not in visible_ids]
        branch=ep['branch']
        u4_boundary=store._u4_boundary(c,episode,beat) if identity['kind']=='afm-starters' else 0
        world_laws = WorldLawStore.in_connection(c,project_id=identity['project_id'],universe_id=identity['universe_id'],
                                                allow_uninitialized=connection is not None)
        if law_revision is not None and (type(law_revision) is not int or law_revision != world_laws['revision']):
            raise ValueError('Stale world law revision')
        applicable_laws=active_laws(world_laws['laws'],branch_points(c,episode,beat),branch)
        if replay_binding is not None:
            from . import replay_minds
            scene = replay_minds.project(store,c,identity,episode,branch,revision,beat,start,end,viewpoint,
                                         replay_binding,junctions)
        else:
            scene = fx06_scene.project(c,episode,branch,beat,start,end,script)
        continuation = None
        if continuation_binding is not None:
            from . import branch_continuations
            continuation=branch_continuations.project(store,c,identity,episode,branch,revision,beat,start,end,
                                                       viewpoint,continuation_binding,junctions)
        clip_context = None
        if clip_binding is not None:
            from . import scene_clips
            clip_context = scene_clips.project(store,c,identity,episode,branch,revision,start,end,viewpoint,
                                               clip_binding,scene)
        mind_support = None
        if scene and scene['active_cast']:
            from . import scene_mind_support
            mind_scope={'project':identity['project_id'],'universe':identity['universe_id'],
                        'episode':episode,'branch':branch,'scope_revision':identity['scope_revision']}
            mind_support=scene_mind_support.project(c,mind_scope,scene['root_form'],scene['active_cast'])
        if clip_binding and clip_binding.get('test_signatures') and not mind_support:
            raise ValueError('The local signature test requires the three active Minds')
        if replay_binding is None and scene and scene['active_cast']:
            junctions = fx06_scene.add_forms(c, junctions)
            linked = {f.id:f.link for f in junctions['rainee'].forms}
            ports = [linked.get(a['form_id']) for a in scene['active_cast']]
            if any(p is None or p.kind!='digital_mind' or p.node_id!=a['node_id']
                   for a,p in zip(scene['active_cast'],ports)):
                raise ValueError('FX06 requires its three original Digital Mind links')
        graph_hash=hashlib.sha256(row['graph'].encode('utf-8')).hexdigest()
        source_name=row['source_name'] or ('legacy-spring-source' if used_legacy else '')
        profile_rows,profile_token=character_snapshot(c)
        profile_rows,profile_token=merge_node_profiles(profile_rows,profile_token,junctions)
        beat_rhythm=read_beat_rhythm(c,episode,beat,json.loads(row['graph']))
    from .notebook import NotebookStore, resolve
    notebook = (NotebookStore.existing_in_connection(connection, episode) if connection is not None
                else NotebookStore(store).existing(episode))
    protection_revision = None
    protection_ranges = ()
    if notebook is not None:
        if notebook['stale']:
            raise ValueError('Notebook protection is stale for this episode revision')
        protection_revision = notebook['revision']
        protection_ranges = tuple((max(start, r['start']), min(end, r['end']), r['value'])
                                  for r in resolve(script, notebook['default_protection'], notebook['masks'])
                                  if r['start'] < end and start < r['end'])
        extra = [[a,b] for a,b,value in protection_ranges if value == 100]
        # Once an author has a notebook, its explicit settings replace the
        # legacy automatic dialogue lock. Caller-supplied hard locks remain.
        protected = _exact_spans(script, start, end, list(protected_ranges or []) + extra,
                                 include_dialogue=False)
    approved={cid:set() for cid in junctions}
    active={}
    sources=[]
    if source_graph is not None:
        for item in source_graph['characters']:
            cid=item['character_id'];form=item['active_form']
            if cid in approved:
                approved[cid].add(form);active[cid]=form
                sources.append({'character':cid,'form':form,'source_id':item['source_node'],
                                'source_line':item['source_line'],'edition':source_graph['edition'],
                                'status':'historical-source-evidence-not-canon'})
    if u4_boundary and viewpoint is None:
        packets, disclosures=_u4_disclosures()
        for cid,form,beat_id,number in disclosures:
            if number <= u4_boundary and cid in junctions:
                approved[cid].add(form)
                sources.append({'character':cid,'form':form,'beat':number,'source_id':'spring-break/u4/'+beat_id})
        if episode=='spring-break':
            for cid,group in packets[u4_boundary-1].form_context.items():
                current=next((f['id'] for f in group['forms'] if f['status']=='active'),None)
                if current: active[cid]=current
    for event in visible:
        cid=event.get('form_character'); fid=event.get('form_id'); action=event.get('form_action')
        if event['id']=='haley-awakening' and event['episode']=='hot-scoomp' and not fid:
            cid,fid,action='haley','awakened_haley_fox','active'
        if cid in junctions and fid in {f.id for f in junctions[cid].forms}:
            approved[cid].add(fid)
            if action=='active': active[cid]=fid
    if scene and scene['root_form']==fx06_scene.PETER and 'rainee' in approved:
        approved['rainee'].add(fx06_scene.PETER)
        active['rainee']=fx06_scene.PETER
    ep_pos = int(ep['position']) if ep and ep['position'] is not None else None
    tt_override = bool(dict(ep).get('time_travel_override', False)) if ep else False
    if not continuation:
        for cid, junction in junctions.items():
            if scene and cid == scene.get('root'):
                continue
            staged, lineage = junction.route_at(episode, branch, ep_pos, time_travel_override=tt_override)
            if staged:
                approved[cid].update(lineage)
                active[cid] = staged
    if continuation:
        actual=continuation['active_forms']
        forms={cid:junctions[cid].project(approved={form},active=form,episode_pos=ep_pos,time_travel_override=tt_override) for cid,form in actual.items()}
    else:
        forms={cid:group.project(approved=approved[cid],active=active.get(cid),episode_pos=ep_pos,time_travel_override=tt_override) for cid,group in junctions.items()}
    form_basis = {'forms':forms,'fx06':scene} if scene else forms
    if continuation:
        form_basis={'forms':forms,'continuation':continuation}
    allowed_form_ids={f['id'] for g in forms.values() for f in g['forms']}
    if scene:
        allowed_form_ids.update(a['form_id'] for a in scene['active_cast'])
    if continuation:
        allowed_form_ids.update(continuation['known_forms'])
        allowed_form_ids.update(continuation['cast'])
        allowed_form_ids.update(group.forms[0].id for group in junctions.values())
    for group in junctions.values():
        for form in group.forms:
            if form.id not in allowed_form_ids:
                hidden.extend([form.label,form.id.replace('_',' ')])
    characters,profile_hidden=resolve_characters(forms,profile_rows,visible,viewpoint,hidden,applicable_laws)
    if source_graph is not None:
        for item in source_graph['characters']:
            if item['character_id'] in characters:
                characters[item['character_id']]['source_snapshot']=item
    hidden.extend(profile_hidden)
    relationships = ()
    if not continuation or continuation.get('kind') not in ('scene-bridge', 'scene-plan'):
        from story_graph.character_relationships import project as project_relationships
        relationship_forms = {cid: [data['active_form']] for cid, data in characters.items()}
        if scene and scene['active_cast']:
            relationship_forms[scene['root']] = [actor['form_id'] for actor in scene['active_cast']]
        if continuation and continuation.get('root_form') == 'split':
            relationship_forms[continuation['root']] = [actor for actor in continuation['cast']
                                                        if actor not in continuation['active_forms']]
        relationships = project_relationships(relationship_forms, junctions, kind=identity['kind'],
                                               episode=episode, branch=branch, beat=beat,
                                               laws=applicable_laws, hidden=hidden)
    directed = [edge for edge in relationships if edge['kind'] == 'dialogue_stance']
    if directed:
        form_basis = {'projection': form_basis, 'directed_relationships': directed}
    form_hash=hashlib.sha256(json.dumps(form_basis,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
    context=NarrativeContext(1,identity['project_id'],identity['universe_id'],identity['scope_revision'],
        episode,branch,beat,viewpoint,revision,world_laws['revision'],revision,graph_hash,form_hash,
        source_name,hashlib.sha256(script.encode('utf-8')).hexdigest())
    if mind_support and any(check_laws(r['scent'],applicable_laws) for r in mind_support['rules']):
        raise ValueError('A local character scent conflicts with a configured world law')
    if continuation and any(check_laws(scent,applicable_laws) for scent in continuation['scents'].values()):
        raise ValueError('A local character scent conflicts with a configured world law')
    if clip_context:
        for pin in clip_context['binding']['pins']:
            note = ' '.join(p for p in (pin['character'],pin['note']) if p)
            if any(h.strip().casefold() in note.casefold() for h in hidden if isinstance(h,str) and len(h.strip())>=8):
                raise ValueError('Clip guidance includes information unavailable at this beat')
            if check_laws(note,applicable_laws):
                raise ValueError('Clip guidance conflicts with a configured world law')
    override=beat_rhythm['profile']['author_override']
    if any(h.strip().casefold() in override.casefold() for h in hidden if isinstance(h,str) and len(h.strip())>=8):
        raise ValueError('Beat direction includes information unavailable at this beat')
    if override and check_laws(override,applicable_laws):
        raise ValueError('Beat direction conflicts with a configured world law')
    public_events=tuple(
        {k:e[k] for k in ('id','episode','beat','content','viewpoint','source_id','reviewer')}
        | ({'source_timing':e['source_timing'], 'perspective':'reader-revealed' if viewpoint is None else 'witnessed'}
           if 'source_timing' in e else {}) for e in visible)
    approved_text='\n'.join(e['content'] for e in public_events).casefold()
    for phrase in hidden:
        if not isinstance(phrase,str) or len(phrase.strip()) < 8: continue
        p=phrase.strip().casefold()
        if p not in approved_text and re.search(r'(?<!\w)'+re.escape(p)+r'(?!\w)',target.casefold()):
            raise ValueError('The selection contains known information unavailable at this beat')
    from . import media_overrides
    media_scope = {'project': identity['project_id'], 'universe': identity['universe_id'], 'scope_revision': identity['scope_revision'],
                   'episode': episode, 'branch': branch}
    with (nullcontext(connection) if connection is not None else store._connect()) as c:
        if connection is None:
            c.execute('BEGIN')
        media_guidance = media_overrides.project(store, c, media_scope, revision, start, end, viewpoint,
                                                 forms, scene, continuation, hidden, applicable_laws)
        has_custom_canon = any(
            c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
            for t in ('universe_laws_v2', 'state_deltas')
        )
        compiled_state = None
        if identity['kind'] == 'afm-starters' or has_custom_canon:
            from .canon_guard import compile_afm_state
            compiled_state = compile_afm_state(
                universe_id=identity['universe_id'],
                branch=branch,
                episode_id=episode,
                beat=beat,
                viewpoint=viewpoint,
                timeline_conn=c,
                seed_afm=(identity['kind'] == 'afm-starters'),
            )
    packet = ScopedPacket(episode,branch,beat,viewpoint,revision,target,hashlib.sha256(target.encode()).hexdigest(),
                        public_events,forms,tuple(x for x in hidden if isinstance(x,str) and len(x.strip())>=8),
                        tuple(sources),start,end,protected,protection_revision,protection_ranges,
                        tuple(applicable_laws), world_laws['revision'],context,characters,profile_token,beat_rhythm,anchor,
                        source_graph=source_graph,fx06=scene,clip_context=clip_context,mind_support=mind_support,
                        continuation=continuation,relationships=relationships,media_guidance=media_guidance,
                        universe_kind=identity['kind'],
                        state_digest=compiled_state.state_digest if compiled_state else "",
                        canon_state=compiled_state)
    if compositor_preparation is not None:
        from dataclasses import replace
        from .cook import render_context
        with (nullcontext(connection) if connection is not None else store._connect()) as c:
            if connection is None:
                c.execute('BEGIN')
            context = render_context(store, c, packet, compositor_preparation, books_root)
        packet = replace(packet, compositor=context, compositor_books=books_root)
    return packet


def retrieve(packet: ScopedPacket, query: str = '', limit: int = 10) -> list[dict]:
    if not isinstance(query,str) or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Invalid retrieval request')
    terms=set(re.findall(r'\w+',query.casefold()))
    ranked=[]
    for e in packet.events:
        score=len(terms & set(re.findall(r'\w+',e['content'].casefold())))
        if not terms or score: ranked.append((score,e))
    ranked.sort(key=lambda x:-x[0])
    return [dict(e) for _,e in ranked[:limit]]


def validate_claims(packet: ScopedPacket, claims: list[dict]) -> list[dict]:
    if not isinstance(claims,list): raise ValueError('Claims must be a list')
    event_ids={e['id'] for e in packet.events}; issues=[]
    for i, claim in enumerate(claims):
        if isinstance(claim,dict) and claim.get('kind')=='world_fact':
            for finding in validate_world_claim(claim,packet.world_laws,packet.world_law_revision):
                if finding['status'] != 'supported': issues.append({'claim':i+1,**finding})
            continue
        if not isinstance(claim,dict) or set(claim)!={'kind','subject','value'}:
            raise ValueError('Claims require kind, subject and value')
        kind,subject,value=claim['kind'],claim['subject'],claim['value']
        if not all(isinstance(x,str) and x for x in (kind,subject,value)): raise ValueError('Claim values must be text')
        if kind=='event': valid=value in event_ids
        elif kind in ('active_form','available_form'):
            valid=any(f['id']==value and (kind=='available_form' or f['status']=='active')
                      for f in packet.forms.get(subject,{}).get('forms',[]))
            if packet.fx06 and subject == packet.fx06['root'] and packet.fx06['active_cast']:
                in_cast = any(a['form_id']==value for a in packet.fx06['active_cast'])
                valid = in_cast if kind=='active_form' else valid or in_cast
        else: raise ValueError('Unknown claim kind')
        if not valid: issues.append({'claim':i+1,'reason':'Not supported in this episode and beat'})
    return issues


def diagnose_output(packet: ScopedPacket, text: str) -> list[dict]:
    if not isinstance(text,str): raise ValueError('Output must be text')
    return [finding for law in packet.world_laws if law.get('matcher')=='haley_parentage'
            for finding in parentage_findings(text,law,packet.world_law_revision)]


def build_infill_plan(packet: ScopedPacket, *, default_tier: int = 0):
    """Compile an occurrence-safe InfillPlan from a ScopedPacket's protection ranges."""
    from .slot_infill import plan_infill_slots

    ranges = packet.protection_ranges or tuple((a, b, 100) for a, b, _ in packet.protected)
    return plan_infill_slots(
        packet.target,
        ranges,
        default_tier=default_tier,
        base_offset=packet.start,
    )


def validate_output(
    packet: ScopedPacket,
    text: str,
    *,
    source_edit=None,
    check_seams: bool = True,
    enforce_tier_fidelity: bool = False,
    check_semantic: bool = True,
) -> list[str]:
    if not isinstance(text,str) or not text.strip(): return ['Output is empty']
    # A fully protected notebook selection is exact, including its boundaries.
    # Substring preservation alone would allow additions around a 100% passage.
    if packet.protection_ranges:
        cursor=packet.start
        for a,b,value in packet.protection_ranges:
            if a!=cursor or value!=100: break
            cursor=b
        else:
            if cursor==packet.end and text!=packet.target:
                return ['Output changed a fully protected passage']
    cursor = 0
    for a,b,exact in packet.protected:
        found = text.find(exact,cursor)
        if found < 0:
            return [f'Output changed, moved out of order, or omitted protected text at {a}:{b}']
        cursor = found + len(exact)
    if packet.protected and packet.target != text:
        from .notebook import remap_masks, digest
        anchors = [dict(id=str(i), start=a-packet.start, end=b-packet.start, value=100,
                        sha256=digest(exact)) for i,(a,b,exact) in enumerate(packet.protected)]
        try:
            remap_masks(packet.target, text, anchors, source_edit)
        except ValueError as exc:
            return [str(exc)]
    if check_seams and (packet.protection_ranges or packet.protected) and packet.target != text:
        from .slot_infill import validate_infill_seams
        plan = build_infill_plan(packet)
        if plan.locked_slots() or enforce_tier_fidelity:
            seam_report = validate_infill_seams(
                plan,
                text,
                source_edit=source_edit,
                enforce_tier_fidelity=enforce_tier_fidelity,
                allow_empty=source_edit is not None,
            )
            if not seam_report.valid:
                return seam_report.issues
    if packet.world_laws:
        new_violations = check_laws(text, packet.world_laws) - check_laws(packet.target, packet.world_laws)
        if new_violations:
            return ['Output introduces a world-law conflict: ' + ', '.join(sorted({law for law, _ in new_violations}))]
        if check_semantic:
            from .meaning_checks import _semantic_paraphrase_findings
            before_sem = {
                (f.get('rule_id'), str(f.get('evidence') or '').casefold())
                for f in _semantic_paraphrase_findings(packet, packet.target)
                if f.get('status') == 'contradicted'
            }
            after_sem = [
                f for f in _semantic_paraphrase_findings(packet, text)
                if f.get('status') == 'contradicted'
                and (f.get('rule_id'), str(f.get('evidence') or '').casefold()) not in before_sem
            ]
            if after_sem:
                first_sem = after_sem[0]
                return [f"Output introduces a world-law semantic conflict ({first_sem['rule_id']}): {first_sem['reason']}"]
    if packet.canon_state is not None:
        from collections import Counter
        from story_graph.state_validator import validate_text
        before_counts = Counter(
            (f.code, f.rule_id, f.evidence.casefold())
            for f in validate_text(packet.target, packet.canon_state)
            if f.status == 'conflict'
        )
        after_findings = [
            f for f in validate_text(text, packet.canon_state)
            if f.status == 'conflict'
        ]
        after_counts = Counter((f.code, f.rule_id, f.evidence.casefold()) for f in after_findings)
        new_keys = after_counts - before_counts
        if new_keys:
            first = next(
                f for f in after_findings if (f.code, f.rule_id, f.evidence.casefold()) in new_keys
            )
            return [f'Output introduces a canon state conflict ({first.code}:{first.rule_id}): {first.reason}']
    allowed='\n'.join([packet.target]+[e['content'] for e in packet.events]).casefold()
    lowered=text.casefold()
    for phrase in packet.hidden_phrases:
        p=phrase.strip().casefold()
        if p not in allowed and re.search(r'(?<!\w)'+re.escape(p)+r'(?!\w)',lowered):
            return ['Output contains information unavailable at this beat']
    if packet.canon_state is not None and getattr(packet.canon_state, 'hidden_facts', ()):
        from .canon_rules import is_negated
        for hf in packet.canon_state.hidden_facts:
            val = str(hf.get('object_value') or '').strip().casefold()
            if len(val) >= 6 and val not in allowed:
                for m in re.finditer(r'(?<!\w)' + re.escape(val) + r'(?!\w)', lowered):
                    if not is_negated(lowered, m):
                        return ['Output contains information unavailable at this beat']
    if packet.fx06 and packet.fx06['active_cast'] and text != packet.target:
        if packet.fx06.get('replay_minds'):
            from .replay_minds import validate_output as validate_replay_output
            turn_issues=validate_replay_output(text)
        else:
            turn_issues=fx06_scene.validate_turns(text)
        if turn_issues or not packet.mind_support:
            return turn_issues
        from .scene_mind_support import validate_output as validate_mind_rules
        return validate_mind_rules(packet.mind_support,text,exercise=_signature_test(packet))
    if packet.continuation:
        from .branch_continuations import validate_output as check_continuation
        return check_continuation(packet.continuation,text)
    return []


def evaluate_infill_proposal(
    packet: ScopedPacket,
    fills,
    *,
    plan=None,
    default_tier: int = 0,
    enforce_tier_fidelity: bool = True,
    allow_empty: bool = False,
) -> dict:
    """Apply occurrence-safe slot fills to a ScopedPacket and run full seam + canon validation."""
    from .slot_infill import apply_slot_fills

    resolved_plan = plan if plan is not None else build_infill_plan(packet, default_tier=default_tier)
    applied = apply_slot_fills(
        resolved_plan,
        fills,
        validate=False,
        enforce_tier_fidelity=enforce_tier_fidelity,
        allow_empty=allow_empty,
    )
    issues = list(applied["validation"]["issues"])
    source_edit = tuple(applied["source_edit"]) if applied["applied_slots"] else None
    pipeline_issues = validate_output(
        packet,
        applied["text"],
        source_edit=source_edit,
        check_seams=False,
        enforce_tier_fidelity=False,
    )
    for msg in pipeline_issues:
        if msg not in issues:
            issues.append(msg)
    return {
        "valid": len(issues) == 0,
        "text": applied["text"],
        "source_edit": list(applied["source_edit"]),
        "candidate_bounds": list(applied["candidate_bounds"]),
        "applied_slots": applied["applied_slots"],
        "issues": issues,
        "validation": applied["validation"],
        "plan": resolved_plan.to_dict(),
    }


def _signature_test(packet):
    return bool(packet.clip_context and packet.clip_context['binding'].get('test_signatures'))


def prompt_for(packet: ScopedPacket, references=(), scene_function='scene', reference_features=None, reference_receipts=None, rhythm_guidance=None) -> str:
    if rhythm_guidance is None:
        from .rhythm_guidance import compile_guidance
        rhythm_guidance=compile_guidance(packet,scene_function,reference_features,reference_receipts)
    if packet.continuation and packet.continuation.get('polish'):
        from .conditioner import scene_polish_prompt
        from .media_overrides import writer_context as media_context
        base_prompt = scene_polish_prompt(packet.continuation, packet.world_laws, reference_features,
                                          rhythm_guidance.get('craft_cards', ()))
        media_block = media_context(item for item in packet.media_guidance if item['target']['kind'] == 'beat')
        return (base_prompt + '\n' + media_block) if media_block else base_prompt
    if rhythm_guidance.get('reference_delivery') == 'cadence':
        # Keep citation IDs and hashes in Noir's receipts, not the writer's prompt.
        rhythm_guidance = {k:v for k,v in rhythm_guidance.items() if k != 'reference_basis'}
        references = ()
    craft_cards = rhythm_guidance.get('craft_cards', ())
    if craft_cards:
        rhythm_guidance = {key: value for key, value in rhythm_guidance.items() if key != 'craft_cards'}
    facts='\n'.join(
        '- '+e['content']+{'reader-revealed':' (already shown to the reader)',
                           'witnessed':' (known to the selected viewpoint)'}.get(e.get('perspective'),'')
        for e in packet.events) or '- No approved timeline events.'
    split = bool(packet.fx06 and packet.fx06['active_cast'])
    replay = split and packet.fx06.get('replay_minds')
    characters = packet.characters
    cast_context = ''
    if replay:
        from .replay_minds import writer_context
        cast_context = writer_context(packet.fx06)
        # Keep varying experiment fingerprints in the receipt, outside the writer prompt.
        rhythm_guidance = {k:v for k,v in rhythm_guidance.items() if k not in ('binding','id')}
        characters = {k:v for k,v in characters.items() if k!=packet.fx06['root']}
    elif split:
        cast_context = fx06_scene.writer_context(packet.fx06)
    clip_notes = ''
    if packet.clip_context:
        from .scene_clips import writer_context as clip_writer_context
        clip_notes = clip_writer_context(packet.clip_context)
        rhythm_guidance = {k:v for k,v in rhythm_guidance.items() if k not in ('binding','id')}
    local_rules = ''
    if packet.mind_support:
        from .scene_mind_support import writer_context as mind_rule_context
        local_rules = mind_rule_context(packet.mind_support,exercise=_signature_test(packet))
    branch_context=''
    from .media_overrides import writer_context as media_context
    if packet.continuation:
        from .branch_continuations import writer_context as branch_writer_context
        if craft_cards and packet.continuation['kind'] == 'scene-plan':
            from .scene_plan import writer_context as plan_context
            branch_context = plan_context(packet.continuation, packet.media_guidance, craft_cards=craft_cards)
        else:
            branch_context = branch_writer_context(packet.continuation, packet.media_guidance)
        rhythm_guidance={k:v for k,v in rhythm_guidance.items() if k not in ('binding','id')}
    from story_graph.character_relationships import writer_context as relationship_context
    labels = {form['id']: form['label'] for group in packet.forms.values() for form in group['forms']
              if form['kind'] != 'base'}
    if split:
        labels.update({actor['form_id']: actor['speaker'] for actor in packet.fx06['active_cast']})
    if packet.continuation and packet.continuation.get('kind') not in ('scene-bridge', 'scene-plan'):
        labels.update(packet.continuation['cast'])
    relationship_notes = relationship_context(packet.relationships, labels)
    from .dialogue_dial import relationship_delivery_context
    relationship_notes += relationship_delivery_context(packet.relationships, labels)
    compositor_notes = ''
    if packet.compositor:
        inputs = packet.compositor
        cues = [{key: pin[key] for key in ('kind', 'role', 'observation', 'selector')} for pin in inputs['pins']]
        compositor_notes = ('\nSAVED COOK DIRECTION (pacing and evidence for this passage):\n'
                            + inputs['skeleton']['skeleton'] + '\n'
                            + json.dumps({'act_structure': inputs['preset'], 'timing': inputs['timing'],
                                          'active_forms': inputs['forms'], 'media_cues': cues,
                                          'canon_mode': inputs['canon_tag']['mode'],
                                          'time_travel_carrier': inputs['canon_tag']['tt_carrier']},
                                         ensure_ascii=False) + '\n')
    forms='\n'.join(f"- {cid}: "+', '.join(f['label']+' ('+f['status']+')' for f in group['forms'])
                    for cid,group in packet.forms.items() if not (split and cid=='rainee'))
    locks=json.dumps([text for _,_,text in packet.protected],ensure_ascii=False)
    protection = [{'text': packet.target[a-packet.start:b-packet.start], 'protection': value}
                  for a,b,value in packet.protection_ranges]
    purpose = packet.continuation['kind'] if packet.continuation else None
    if purpose == 'scene-plan':
        opening = 'Write only the planned scene between the frozen fork and the retained scene. Follow each turn’s speaker permissions. '
        protection = [{'start': a, 'end': b, 'protection': value} for a,b,value in packet.protection_ranges]
    elif purpose:
        opening = 'Replace only the continuation slot with new text immediately following the saved scene. Never rewrite the prior scene. '
    elif rhythm_guidance.get('craft_mode') == 'expand':
        opening = (
            'Expand and vividly rewrite the unlocked portions of the selected text using the attached character-node '
            'data, media notes, and 190-book craft excerpts so the prose is concrete, expressive, and non-robotic. '
            'Preserve every 100%-locked substring verbatim and stay strictly inside the world laws, character forms, '
            'and approved story-graph causal order. '
        )
    else:
        opening = 'Rewrite only the selected text. Preserve its facts and respect the specified protection levels. '
    return (opening+'Copy each protected '
            'substring verbatim and in order, including whitespace and punctuation. Use only the following '
            'approved history, world laws and forms; do not introduce future, private or unlisted story facts.\n\n'
            'PROTECTION GUIDE: 100% means exact text. At 75%, preserve most wording while allowing modest polish. '
            'At 50%, balance preservation and rewriting. At 25%, keep the central idea and established facts '
            'while allowing substantial new wording and filling gaps from eligible context. '
            'World laws, approved facts and explicit hard locks apply at every setting. '
            'Percentages below 100 are creative guidance, not a measurable change guarantee.\n\n'
            'SCENE FUNCTION: '+scene_function+'. This selection overrides the beat intent if different; other beat controls remain in effect. Approved story facts and laws take priority.\n\n'
            'SELECTED BEAT RHYTHM (author direction; do not alter facts or exact locks):\n'+
             (json.dumps(packet.beat_rhythm['profile'],ensure_ascii=False) if packet.beat_rhythm.get('status')=='configured' else 'No beat direction set; follow the selected writing.')+'\n\n'+
             'RHYTHM CRAFT PLAN (advisory techniques, never new story facts; author directions and exact locks take priority):\n'+
             json.dumps(rhythm_guidance,ensure_ascii=False)+'\n\n'+
            (('REFERENCE CADENCE OBSERVATION (descriptive only, not a quality score or a strict target):\n'+json.dumps(reference_features,ensure_ascii=False)+'\n\n') if reference_features else '')+
            'WORLD LAWS:\n'+('\n'.join('- '+law['statement'] for law in packet.world_laws) or '- No project-wide laws supplied.')+'\n\n'
            'APPLICABLE STRUCTURED CONSTRAINTS (source IDs and author exceptions included):\n'+
            json.dumps([{'rule_id':law['id'],'constraints':law['constraints']} for law in packet.world_laws if 'constraints' in law],ensure_ascii=False)+'\n\n'
            'IMPORTED SOURCE GRAPH EVIDENCE (historical claims for this exact source position, not approved canon; no later states, private knowledge or missing personality may be invented):\n'+
            (json.dumps(packet.source_graph,ensure_ascii=False) if packet.source_graph else 'No imported source graph.')+'\n\n'+
            'APPROVED HISTORY:\n'+facts+'\n\nCHARACTER FORMS:\n'+forms+
            (('\n\n'+cast_context) if split else '')+
            '\n\nCHARACTER PROFILE SNAPSHOTS (unlinked or empty means unknown; do not invent personality. Treat uncertain fields as uncertain, not established facts):\n'+
            json.dumps(characters,ensure_ascii=False)+'\n'+
            '\n\nEXACT PROTECTED SUBSTRINGS (JSON):\n'+locks+
            '\n\nPROTECTION BY ABSOLUTE CODE-POINT RANGE (higher means preserve more; only 100 is exact):\n'+
            json.dumps(protection,ensure_ascii=False)+'\n\n'+
            (('ELIGIBLE BOOK SOURCE RECEIPTS (same order as excerpts; metadata, not story canon):\n'+json.dumps(reference_receipts or [],ensure_ascii=False)+'\n\n'
              'ELIGIBLE 190-BOOK CRAFT EXCERPTS (author-owned style, voice, and rhythm examples — draw freely on their sensory richness, cadence, and literary craft; world laws and scoped story history govern plot facts):\n'+
              '\n'.join('- '+text for text in references)+'\n\n') if references else '')+
            relationship_notes+compositor_notes+clip_notes+local_rules+branch_context+
            media_context(item for item in packet.media_guidance if item['target']['kind'] == 'beat')+
            'SELECTED TEXT:\n'+packet.target)


def _writer_request(packet, prompt, draft_id=None):
    from story_graph.director import fingerprint
    if packet.context is None:
        raise ValueError('A project and universe context is required')
    project = packet.context.project_id
    universe = packet.context.universe_id
    scope = [project, universe, packet.episode, packet.branch]
    span = json.dumps([project, universe, packet.world_law_revision, packet.episode, packet.branch,
                       packet.beat, packet.viewpoint, packet.revision, packet.start, packet.end,
                       packet.target_sha256])
    span_id = hashlib.sha256(span.encode('utf-8')).hexdigest()
    # A restored operation keeps its request ID even if current inputs would now
    # produce a different prompt. A new draft owns a distinct operation.
    operation = ['draft', draft_id] if draft_id is not None else ['direct', span_id, fingerprint(prompt)]
    request_id = 'scoped-' + fingerprint(['writer-request', scope, operation])[:32]
    return ProseRewriteRequest(request_id=request_id, project_id=packet.context.project_id,
        document_id=packet.episode,base_revision=packet.revision,
        target_span_id=span_id,
        original_text=packet.target,category=SpanCategory.GENERAL,
        permitted_facts=[e['content'] for e in packet.events],
        character_epistemic_scope=({packet.viewpoint:[e['id'] for e in packet.events
                                                     if e.get('perspective') == 'witnessed']}
                                    if packet.viewpoint else {}),
        protected_spans=[ProtectedSpan(span_id=f'{a}:{b}',category=SpanCategory.GENERAL,text=text,
                         content_hash=hashlib.sha256(text.encode()).hexdigest()) for a,b,text in packet.protected])


def generate(packet: ScopedPacket, provider, *, references=(), reference_receipts=None, scene_function='scene',
             reference_features=None, rhythm_guidance=None, _retain_candidate=False, limits=None) -> dict:
    from .rhythm_guidance import compile_guidance
    if rhythm_guidance is None:
        rhythm_guidance = compile_guidance(packet, scene_function, reference_features, reference_receipts)
    prompt = prompt_for(packet, references, scene_function, reference_features, reference_receipts, rhythm_guidance)
    result = provider.generate_rewrite(_writer_request(packet, prompt), prompt)
    return _evaluate_rewrite(packet, result, references, reference_receipts, reference_features,
                             rhythm_guidance, _retain_candidate, limits)


def _evaluate_rewrite(packet, result, references, reference_receipts, reference_features,
                      rhythm_guidance, retain_candidate, limits, *, reject_echo=False):
    from .rhythm_guidance import evidence
    if limits and isinstance(result,str) and len(result) > limits['output_chars']:
        return {'status':'BLOCKED','issues':['The writer returned more text than this run can keep.']}
    rhythm_evidence=evidence(packet.target,result) if isinstance(result,str) else None
    problems=validate_output(packet,result)
    if reject_echo and isinstance(result, str) and result.strip() == packet.target.strip():
        problems.append('The writer returned the selected text unchanged.')
    if _signature_test(packet) and result==packet.target:
        problems.append('The signature test needs an explicit action from each active form')
    from .meaning_checks import assess_meaning
    meaning=assess_meaning(packet,result)
    if problems:
        blocked={'status':'BLOCKED','issues':problems,'diagnostics':diagnose_output(packet,result),'meaning':meaning,
                  'reference_receipts':reference_receipts or [],'rhythm_guidance':rhythm_guidance,'rhythm_evidence':rhythm_evidence}
        if retain_candidate: blocked['_candidate']=result
        return blocked
    return {'status':'PROPOSED','text':result,'target_sha256':packet.target_sha256,
            'scope':{'episode':packet.episode,'branch':packet.branch,'beat':packet.beat,
                     'viewpoint':packet.viewpoint,'revision':packet.revision,'start':packet.start,'end':packet.end,
                     'context':packet.context.public()},
            'diagnostics':diagnose_output(packet,result),'meaning':meaning,
            'reference_receipts':reference_receipts or [],
            'character_status':{cid:{'status':value['status'],'active_form':value['active_form']} for cid,value in packet.characters.items()},
            'character_receipts':packet.character_receipts(),
            'beat_rhythm':packet.beat_rhythm,
             'reference_features':reference_features,
             'rhythm_guidance':rhythm_guidance,'rhythm_evidence':rhythm_evidence,
            'warning':'Review factual changes: exact text checks cannot detect invented facts, omissions or paraphrased future information.'}


class _StaleDraftScope(ValueError):
    pass


def generate_recorded(store, packet, provider_name, provider_factory, recheck, parent=None, *, references=(),
                      reference_receipts=None, reference_check=None, scene_function='scene', reference_features=None,
                      reference_binding=None, request_budget=None, rhythm_guidance=None, run_part=None,
                      draft_identity=None):
    """Record an attempt before dispatch and finalize it only after scope recheck."""
    from .notebook import DraftStore, NotebookStore
    from .providers.deepseek_session import DeepSeekSessionProvider
    from .providers.session_attempts import SessionAttemptError
    from .providers.deepseek import BudgetExceeded
    drafts = DraftStore(NotebookStore(store))
    from .rhythm_guidance import compile_guidance
    if rhythm_guidance is None: rhythm_guidance=compile_guidance(packet,scene_function,reference_features,reference_receipts)
    locked = rhythm_guidance['fully_locked']
    prompt = '' if locked else prompt_for(packet, references, scene_function, reference_features,
                                           reference_receipts, rhythm_guidance)
    encoded_prompt = prompt.encode('utf-8')
    prompt_size = len(encoded_prompt)
    prompt_sha256 = hashlib.sha256(encoded_prompt).hexdigest()
    options = draft_identity or {}
    progress = (run_part or {}).get('progress', lambda _: nullcontext())
    prior = (run_part or {}).get('existing_draft')
    finish_guard = (run_part or {}).get('finish_guard')
    limits = None
    replay = packet.fx06.get('replay_minds') if packet.fx06 else None
    if replay or packet.clip_context or packet.continuation:
        limits = (packet.continuation or packet.clip_context or replay)['limits']
        if not locked and prompt_size > limits['input_bytes']:
            raise ValueError('This bounded draft exceeds its saved input budget')
        request_budget = {'max_provider_calls':0 if locked else 1,'token_limit':None,
                          'input_bytes':prompt_size,'input_bytes_limit':limits['input_bytes'],
                          'output_chars_limit':limits['output_chars']}
    if run_part:
        limits = run_part['limits']
        if not locked and prompt_size > limits['input_bytes']:
            raise ValueError('A passage exceeds the run’s input budget')
        if run_part.get('prompt_sha256', prompt_sha256) != prompt_sha256:
            raise ValueError('Writer input changed after preparation; no request was sent')
        options = {'draft_id':run_part['draft_id'],'writing_run':run_part['receipt'],
                   'write_guard':run_part['write_guard']}
        request_budget={'max_provider_calls':0 if locked else 1, 'token_limit':None,
                        'input_bytes':prompt_size, 'output_chars_limit':limits['output_chars']}
    if locked:
        if recheck()!=packet or store.prerequisites(packet.episode):
            raise ValueError('Scope changed before preserving this passage')
        if reference_check:
            reference_check()
        request_budget=request_budget or {'max_provider_calls':0,'token_limit':None}
        options={**options,'proposal':{'text':packet.target,'issue':{'kind':'exact-protection'}}}
    if prior is not None:
        draft_id = prior['id']
    else:
        with (progress('validate') if locked else nullcontext()):
            draft_id = drafts.start(packet, provider_name, parent,reference_receipts=reference_receipts,
                                scene_function=scene_function,reference_features=reference_features,
                                reference_binding=reference_binding,request_budget=request_budget,
                                rhythm_guidance=rhythm_guidance,**options)
    if locked:
        return {'status':'PROPOSED','origin':'preserved','text':packet.target,'draft_id':draft_id,'provider_calls':0,
                'rhythm_guidance':rhythm_guidance,'preserved':True}
    try:
        if reference_check: reference_check()
        if recheck() != packet or store.prerequisites(packet.episode):
            raise ValueError('Timeline changed before generation; no request was sent')
        if reference_check: reference_check()
    except Exception:
        drafts.finish(draft_id, 'STALE', issue={'reason':'Scope changed or could not be rechecked before dispatch'},
                      write_guard=finish_guard)
        raise
    provider = None
    candidate = None
    polish = None
    try:
        request = _writer_request(packet, prompt, draft_id)
        with (progress('writer') if (run_part or {}).get('selection') else nullcontext()):
            provider = provider_factory()
            if prior and prior.get('provider_request_id'):
                if (not prior.get('provider_journal_id') or not isinstance(provider, DeepSeekSessionProvider)
                        or prior['provider_request_id'] != request.request_id
                        or prior.get('provider_prompt_sha256') != prompt_sha256):
                    raise SessionAttemptError('The earlier writer request cannot be recovered. No request was repeated.',
                                              state='remote_unknown')
                candidate = provider.recover_rewrite(request, prompt_sha256, prior['provider_journal_id'],
                                                     prior.get('provider_job_id'))
            else:
                journal_id = provider.attempts.identity() if run_part and isinstance(provider, DeepSeekSessionProvider) else None
                drafts.provider_ready(draft_id, provider, request.request_id, prompt_sha256, journal_id=journal_id,
                                      write_guard=(run_part or {}).get('write_guard'))
    except Exception as exc:
        state = getattr(exc, 'state', '')
        if prior and prior.get('provider_request_id'):
            status = 'FAILED' if state in ('failed', 'cancelled') else 'UNKNOWN'
        else:
            status = 'UNKNOWN' if state in ('started', 'remote_unknown', 'cancel_requested') else 'FAILED'
        attempt_id = getattr(exc, 'attempt_id', None)
        drafts.finish(draft_id, status, issue={'type':type(exc).__name__, 'state':state, 'attempt_id':attempt_id},
                      attempt_id=attempt_id, write_guard=finish_guard)
        raise
    try:
        if reference_check: reference_check()
        if recheck() != packet or store.prerequisites(packet.episode):
            raise ValueError('Timeline or character profile changed before generation; no request was sent')
        if run_part:
            run_part['before_dispatch']()
    except Exception:
        drafts.finish(draft_id, 'STALE', issue={'reason':'Scope or book settings changed before dispatch'},
                      write_guard=finish_guard)
        raise
    try:
        with progress('write'):
            if candidate is None:
                candidate = provider.generate_rewrite(request, prompt)
        with progress('validate'):
            result = _evaluate_rewrite(packet, candidate, references, reference_receipts, reference_features,
                                       rhythm_guidance, True, limits, reject_echo=bool((run_part or {}).get('selection')))
            if packet.compositor and result['status'] == 'PROPOSED':
                from .conditioner import polish_cook_candidate
                polished = polish_cook_candidate(candidate, [text for _, _, text in packet.protected])
                if polished['locked_bytes_intact'] and polished['text'] != candidate:
                    final = _evaluate_rewrite(packet, polished['text'], references, reference_receipts,
                                              reference_features, rhythm_guidance, True, limits, reject_echo=True)
                    if final['status'] == 'PROPOSED':
                        result = final
                accepted = result['text'] != candidate
                polish = {'slop_before': polished['slop_before'],
                          'slop_after': polished['slop_after'] if accepted else polished['slop_before'],
                          'slop_delta': polished['slop_delta'] if accepted else 0.0,
                          'changed': accepted, 'locked_bytes_intact': True}
    except Exception as exc:
        state = getattr(exc, 'state', '')
        # Once dispatch begins, absence of a confirmed result is not proof the
        # remote operation failed. The session journal remains authoritative.
        status = 'FAILED' if isinstance(exc,BudgetExceeded) or state in ('failed', 'rejected', 'cancelled', 'budget_exhausted') else 'UNKNOWN'
        attempt_id=getattr(exc,'attempt_id',None) or getattr(provider,'last_attempt_id',None)
        drafts.finish(draft_id, status, issue={'type':type(exc).__name__, 'state':state,
                                               'attempt_id':attempt_id},attempt_id=attempt_id, write_guard=finish_guard)
        raise
    try:
        if reference_check: reference_check()
        current = recheck()
        if current != packet or store.prerequisites(packet.episode):
            raise ValueError('Timeline changed during generation; proposal was not accepted')
    except Exception:
        drafts.finish(draft_id, 'STALE', text=result.get('text',result.get('_candidate')),
                      issue={'reason':'Scope changed or could not be rechecked'},
                      attempt_id=getattr(provider,'last_attempt_id',None),meaning_evidence=result.get('meaning'),
                      rhythm_evidence=result.get('rhythm_evidence'),write_guard=finish_guard)
        raise
    attempt_id = getattr(provider, 'last_attempt_id', None)
    response_sha256 = hashlib.sha256(candidate.encode('utf-8')).hexdigest() if isinstance(candidate, str) else None
    on_saved = (run_part or {}).get('on_saved')

    def publish(c):
        finish_guard(c)
        try:
            drafts.guard_scope(c, packet)
        except ValueError as exc:
            raise _StaleDraftScope(str(exc)) from exc

    with (progress('save') if on_saved and result['status']=='PROPOSED' else nullcontext()):
        try:
            drafts.finish(draft_id, result['status'], text=result.get('text',result.get('_candidate')),
                          issue=result.get('issues'), attempt_id=attempt_id, meaning_evidence=result.get('meaning'),
                          rhythm_evidence=result.get('rhythm_evidence'), writer_response_sha256=response_sha256,
                          raw_response_sha256=getattr(provider, 'last_response_sha256', None),
                          compositor_polish=polish,
                          write_guard=publish if on_saved and result['status']=='PROPOSED' else finish_guard,
                          on_saved=on_saved)
        except _StaleDraftScope as exc:
            drafts.finish(draft_id, 'STALE', issue={'reason':str(exc)}, attempt_id=attempt_id, write_guard=finish_guard)
            raise
    result.pop('_candidate',None)
    saved = drafts.open(packet.episode, packet.branch, draft_id)
    return {**result, 'draft_id':draft_id, 'provider_request_id':request.request_id, 'attempt_id':attempt_id,
            'origin':saved['origin'], 'writer_receipt':saved.get('writer_receipt')}


def export_packet(packet: ScopedPacket) -> str:
    return json.dumps(packet.public(),ensure_ascii=False,indent=2)
