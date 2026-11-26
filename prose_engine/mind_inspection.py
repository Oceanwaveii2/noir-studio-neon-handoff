"""Read the writer's resolved Mind inputs or an immutable saved audition."""
from __future__ import annotations

import json

from story_graph import fx06_scene, scene_branches, scene_fragments as f
from story_graph.beat_map import map_episode
from story_graph.universe_scope import checked_id

from . import media_overrides, replay_minds, scene_bridges, scene_mind_support, story_timeline
from .notebook import DraftStore
from .scoped_pipeline import build_packet


COMMAND = 'mind.inspect'


def _beat(ident, stage, label=None):
    return {'id': ident, 'label': label or ident.replace('-', ' ').capitalize(), 'stage': stage}


def _choose(beats, turn, *, default=None):
    if not beats:
        raise ValueError('Choose a saved story passage or replay.')
    ident = turn or default or beats[0]['id']
    selected = next((beat for beat in beats if beat['id'] == ident), None)
    if selected is None:
        raise ValueError('This beat does not belong to the selected story or draft.')
    return selected


def _witnesses(frames, actor, known):
    """Resolve facts to the observation in the prefix of this replay."""
    releases, facts = {}, []
    for frame in frames:
        for effect in frame['effects']:
            if 'release' in effect:
                releases['scent-' + frame['event']] = (frame['event'], effect['release']['scent'])
            seen = effect.get('observation')
            if seen and seen['actor'] == actor and seen['fact'] in known:
                release, scent = releases.get(seen['fact'], (None, None))
                facts.append({'id': seen['fact'], 'witness': actor, 'observed_at': frame['event'],
                              'source_beat': release, 'scent': scent})
    return facts


def _cast(actors, groups, *, cards=(), root=None, speakers=None):
    by_form = {card['form']: card for card in cards}
    forms = {character: {form.id: form for form in group.forms} for character, group in groups.items()}
    labels = {'francine': 'Francine', 'peter_griffin_celestial_variant': 'Rainee Peter',
              'nurse_pamela_franny_anderson': 'Nurse Franny'}
    subjects = []
    for actor, state in actors.items():
        form_id = state['form']
        character = root if root is not None and actor in by_form else actor
        form = forms.get(character, {}).get(form_id)
        profile = by_form.get(form_id, {})
        label = profile.get('label') or labels.get(form_id) or (form.label if form else None)
        label = label or form_id.replace('_', ' ').replace('-', ' ').title()
        subjects.append({'actor': actor, 'character': character, 'form': form_id, 'label': label,
                         'mind': state.get('mind'), 'mind_revision': state.get('mind_revision'),
                         'location': state.get('location'), 'status': 'active',
                         'speaker_allowed': label in speakers if speakers is not None else None})
    return subjects


def _select(subjects, groups, request):
    character, form_id = request.get('character'), request.get('form')
    if form_id is not None and character is None:
        raise ValueError('Choose the character that owns this form.')
    if not character:
        return next((item for item in subjects if item['mind']), subjects[0] if subjects else None)
    if chosen := next((item for item in subjects if item['character'] == character and
                       (form_id is None or item['form'] == form_id)), None):
        return chosen
    group = groups.get(character)
    form = next((x for x in group.forms if x.id == form_id), None) if group else None
    if form is None:
        raise ValueError('Choose a form from this character graph.')
    return {'actor': None, 'character': character, 'form': form_id, 'label': form.label,
            'mind': form.link.node_id if form.link and form.link.kind == 'digital_mind' else None,
            'mind_revision': None, 'location': None, 'status': 'planning_only', 'speaker_allowed': False}


def _relationship_rows(edges, subject):
    return [edge for edge in edges if any(edge[side]['character'] == subject['character']
            and edge[side]['form'] == subject['form'] for side in ('from', 'to'))]


def _media_for(subject, items, beat=None):
    return [cue for cue in items if (beat is None or cue['target'].get('beat') == beat)
            and (cue['actor'] is None or (cue['actor']['character'], cue['actor']['form']) ==
                 (subject['character'], subject['form']))]


def _selected_details(subject, *, card=None, profiles=(), knowledge=(), relationships=(),
                      rules=(), media=(), sources=()):
    if not subject:
        return None
    return dict(subject, card=card, profiles=list(profiles), knowledge=list(knowledge),
                relationships=list(relationships), local_rules=list(rules),
                media=list(media), sources=list(sources))


def _bridge_saved_text(draft, program, beat):
    if draft is None or not draft.get('text'):
        return None
    text = draft['text']
    anchors = [line for scene in program['scenes']
               for line in (scene['heading'], scene['location'], *(b['stage'] for b in scene['beats']))]
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip('\r\n') == beat.get('text')]
    if len(starts) != 1:
        return None
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip('\r\n') in anchors), len(lines))
    return ''.join(lines[start:end])


def _bridge(store, c, scope, head, request, track, groups, draft=None):
    data = (draft['writing_context']['continuation'] if draft else track['inspection'])
    program = data['program']
    replay = data.get('replay', {})
    turns = {row['beat']: row for row in data['turns']} if draft else data['turns']
    stages = {b['id']: b['stage'] for scene in program['scenes'] for b in scene['beats']}
    status = 'saved' if draft else track['bridge_state']
    beats = [_beat(ident, status if ident in stages else 'replay') for ident in turns]
    if not draft:
        beats.append(_beat('retained-join', 'retained', 'Roger rejoin'))
    beat = dict(_choose(beats, request.get('turn'), default=next(iter(stages))))
    frames = replay.get('frames', [])
    frame_index = next((i for i, frame in enumerate(frames) if frame['event'] == beat['id']), None)
    prefix = frames[:frame_index + 1] if frame_index is not None else frames
    observed = prefix[-1]['state']['knowledge'] if prefix else {}
    stage = stages.get(beat['id'])
    if stage:
        beat['text'] = stage
    elif track:
        exact = next((row for scene in track['scenes'] for row in scene['beats'] if row['id'] == beat['id']), None)
        if exact:
            beat['text'] = exact['passage']['text']
    turn = turns.get(beat['id'], {'actors': {}, 'speakers': []})
    speakers = turn['speakers'] if stage is not None else None
    root = frames[0]['state']['root'] if frames else 'rainee'
    subjects = _cast(turn['actors'], groups, cards=data['minds'], root=root, speakers=speakers)
    subject = _select(subjects, groups, request)
    selected = _selected_details(subject)
    if subject and subject['status'] == 'active':
        form = subject['form']
        card = next((card for card in data['minds'] if card['form'] == form and
                     card.get('revision') == subject['mind_revision']), None)
        sources = []
        if card:
            seed = next((item for item in data.get('seed_cards', ()) if item['form'] == form), None)
            sources = [{'type': 'bound_mind', 'sha256': card['source_sha256']}]
            if seed and card['guidance'] != seed['guidance']:
                sources.append({'type': 'form_board', 'id': subject['mind'], 'sha256': card['revision']})
        edges = _relationship_rows(turn.get('relationships', ()), subject)
        # The bridge prompt admits an edge at this turn only if both ends may speak.
        labels = {'nurse_pamela_franny_anderson': 'Nurse Franny',
                  **{item['form']: item['label'] for item in data['minds']}}
        edges = [dict(edge, in_turn_dialogue=scene_bridges.speaking_relationship(edge, speakers or (), labels))
                 for edge in edges]
        selected = _selected_details(subject, card=card, relationships=edges, sources=sources,
                                     knowledge=_witnesses(prefix, subject['actor'], observed.get(subject['actor'], ())))
    media = []
    if draft:
        media = draft['writing_context'].get('media_guidance', ())
    elif stage and status == 'planned' and f._has(c, media_overrides.TABLE):
        slot = data['slot']
        packet = build_packet(store, scope['episode'], data['cutoff'], head, slot['start'], slot['end'],
                              junctions=groups, project_id=scope['project'], universe_id=scope['universe'],
                              branch=scope['branch'], continuation_binding=track['bridge'], connection=c)
        if packet.continuation['turns'] != list(turns.values()) or packet.continuation['minds'] != data['minds']:
            raise ValueError('The Mind board changed. Reopen the beat to inspect the updated input.')
        media = packet.media_guidance
    if selected and selected['status'] == 'active':
        selected['media'] = _media_for(selected, media, beat['id'])
    saved = [] if draft else track['drafts']
    audition = _bridge_saved_text(draft, program, beat)
    return {'kind': 'bridge', 'beat': beat, 'beats': beats, 'subjects': subjects, 'selected': selected,
            'speakers': speakers, 'actors': turn['actors'], 'replay': replay.get('id'),
            'retained': track['retained'] if not draft else None,
            'drafts': saved if stage else [], 'audition': audition,
            'cutaway': [edge for edge in data['imports']['cutaway'] if edge['event'] == beat['id']]}


def _profile_details(subject, packet):
    group = packet['characters'].get(subject['character'], {})
    # An imported legacy profile for a different active form must not follow a
    # replay manifestation. The regular packet has already applied inheritance.
    return group['profiles'] if group.get('active_form') == subject['form'] else ()


def _roast_card(guidance, legacy, speaker):
    card = next((item for item in guidance if item['speaker'] == speaker), None)
    if not card:
        return None
    actor = next(item for item in legacy['actors'] if item['speaker'] == speaker)
    source = legacy['evidence']
    available = {(t['when'], t['try']): t['evidence'] for t in actor['tendencies']}
    cues = []
    for t in card['tendencies']:
        receipts = [source[ident] for ident in available.get((t['when'], t['try']), ())]
        cues.append(dict(t, evidence=receipts, origin='performance' if receipts else 'authored_guidance'))
    return dict(card, tendencies=cues)


def _audition(draft, legacy, label):
    writing = draft['writing_context']['fx06']
    condition = writing['replay_minds']['binding']['condition']
    name = replay_minds.LABELS[condition]
    if draft['writing_context'].get('clip_context'):
        name += ' · with clips'
    lines = [line for line in (draft.get('text') or '').splitlines() if line.strip()]
    matches = [(line, lines[i+1]) for i, line in enumerate(lines[:-1])
               if line.startswith(label + ':') and lines[i+1].startswith('Action:')]
    dialogue, action = matches[0] if len(matches) == 1 else (None, None)
    return {'id': draft['id'], 'label': name, 'condition': condition, 'status': draft['status'],
            'source_revision': draft['source_revision'], 'provider': draft.get('provider'),
            'card': _roast_card(writing['guidance'], legacy, label),
            'dialogue': dialogue, 'action': action}


def _roast(store, c, scope, request, groups, draft=None):
    setup, stamp = replay_minds._registered(c, scope)
    replay, _ = scene_branches._replay(c, scope, setup['basis']['replay'])
    legacy = fx06_scene.read(c, scope['episode'])
    if not legacy or legacy['binding_sha256'] != setup['basis']['card_basis_sha256']:
        raise ValueError('The saved Mind evidence does not match this roast.')
    frames = replay['frames']
    index = next(i for i, row in enumerate(frames) if row['event'] == 'roast')
    frame = frames[index]
    beat = _beat('roast', 'saved' if draft else 'roast', 'Rainee split · Roast')
    _choose([beat], request.get('turn'))

    def matches(value):
        context = value.get('writing_context') or {}
        scene = context.get('fx06', {})
        receipt = scene.get('replay_minds', {})
        return (receipt.get('comparison_sha256') == stamp and receipt.get('receipt') == replay['id']
                and receipt.get('frame_sha256') == setup['basis']['frame_sha256']
                and receipt.get('world_sha256') == replay['world_sha256']
                and receipt.get('binding', {}).get('experiment') == setup['id']
                and receipt.get('binding', {}).get('condition') in replay_minds.CONDITIONS
                and scene.get('active_cast') == setup['basis']['cast']
                and receipt.get('card_sha256') == f.digest(f.encoded(scene.get('guidance'))))

    if draft:
        if not matches(draft):
            raise ValueError('The draft has no verified Mind inputs for this roast.')
        packet = draft['writing_context']
    else:
        req = replay_minds._request(setup, 'all')
        if req['revision'] != request['timeline_revision']:
            raise ValueError('The live roast is on another revision. Open a saved audition from Mind Drafts.')
        packet = build_packet(store, scope['episode'], req['beat'], req['revision'], req['start'], req['end'],
                              junctions=groups, project_id=scope['project'], universe_id=scope['universe'],
                              branch=scope['branch'], law_revision=req['law_revision'],
                              replay_binding=req['replay_binding'], connection=c).public()
    writing = packet['fx06']
    actors = dict(frame['state']['actors'])
    labels = [{'form': actor['form_id'], 'label': actor['speaker']} for actor in writing['active_cast']]
    speakers = [actor['speaker'] for actor in writing['active_cast']]
    raw_cards = {item['speaker']: item for item in writing['guidance']}
    for actor in writing['active_cast']:
        form = actor['form_id']
        card = raw_cards.get(actor['speaker'])
        actors[form] = dict(actors[form], mind=actor['node_id'], mind_revision=f.digest(f.encoded(card)) if card else None)
    subjects = _cast(actors, groups, cards=labels, root=writing['root'], speakers=speakers)
    subject = _select(subjects, groups, request)
    selected = _selected_details(subject)
    auditions = []
    if subject and subject['status'] == 'active':
        label = subject['label']
        card = _roast_card(writing['guidance'], legacy, label)
        knowledge = _witnesses(frames[:index + 1], subject['actor'],
                               frame['state']['knowledge'].get(subject['actor'], ()))
        support = packet.get('mind_support') or {}
        rules = [r for r in support.get('rules', ()) if (r['form'], r['mind']) == (subject['form'], subject['mind'])]
        pins = (packet.get('clip_context') or {}).get('binding', {}).get('pins', ())
        media = [pin for pin in pins if pin['character'] in (None, subject['form'], subject['actor'], label)]
        if rules and not draft and (library := scene_mind_support.read(c, scope)):
            media.extend(dict(item, purpose='timing', library=True) for item in library['library']['items'])
        selected = _selected_details(subject, card=card, profiles=_profile_details(subject, packet),
                                     knowledge=knowledge, relationships=_relationship_rows(packet.get('relationships', ()), subject),
                                     rules=rules, media=media)
        if label in speakers:
            drafts = [draft] if draft else []
            if not draft and f._has(c, 'episode_drafts'):
                drafts = [dict(json.loads(row['payload']), status=row['status']) for row in c.execute(
                    'SELECT status,payload FROM episode_drafts WHERE episode=? AND branch=? ORDER BY rowid',
                    (scope['episode'], scope['branch']))]
            auditions = [_audition(item, legacy, label) for item in drafts if matches(item) and item.get('text')]
    return {'kind': 'roast', 'beat': beat, 'beats': [beat], 'replay': replay['id'],
            'speakers': speakers, 'subjects': subjects, 'selected': selected,
            'actors': actors, 'persistent_memory': writing['memory'],
            'world_laws': packet['world_laws'], 'auditions': auditions}


def _passage(store, c, scope, head, request, track, groups):
    viewpoint = request.get('viewpoint')
    mapping = map_episode(store, scope['episode'], head, viewpoint=viewpoint, _connection=c)
    by_range = {(row['start'], row['end']): row for row in mapping['beats']}
    rows = [row for scene in track['scenes'] for row in scene['beats']]
    passages = {row['id']: row['passage'] for row in rows} if rows else {row['id']: row for row in mapping['beats']}
    beats = ([_beat(row['id'], 'passage', row['label']) for row in rows] if rows else [
        _beat(row['id'], 'passage', f"Passage {row['number']}") for row in mapping['beats']])
    beat = dict(_choose(beats, request.get('turn')))
    passage = passages[beat['id']]
    start, end = passage['start'], passage['end']
    mapped = by_range.get((start, end), {})
    packet = build_packet(store, scope['episode'], mapped.get('scope_beat', 0), head, start, end, viewpoint,
                          junctions=groups, project_id=scope['project'], universe_id=scope['universe'],
                          branch=scope['branch'], passage_anchor=mapped.get('anchor'), connection=c).public()
    beat.update(text=packet['target'], cutoff=packet['beat'],
                timing=(packet['passage_anchor'] or {}).get('status', 'unverified'))
    actors = {}
    for character, profile in packet['characters'].items():
        active = profile['profiles'][-1]
        link = active['node'] or {}
        actors[character] = {'form': profile['active_form'],
                             'mind': link.get('node_id') if link.get('kind') == 'digital_mind' else None,
                             'mind_revision': active['revision'] if link.get('kind') == 'digital_mind' else None}
    subjects = _cast(actors, groups)
    subject = _select(subjects, groups, request)
    selected = _selected_details(subject)
    if subject and subject['status'] == 'active':
        selected = _selected_details(dict(subject, status='in_scope'), profiles=_profile_details(subject, packet),
                                     relationships=_relationship_rows(packet.get('relationships', ()), subject),
                                     media=_media_for(subject, packet.get('media_guidance', ())))
    return {'kind': 'passage', 'beat': beat, 'beats': beats, 'subjects': subjects,
            'selected': selected, 'actors': actors, 'speakers': None, 'viewpoint': viewpoint,
            'world_laws': packet['world_laws'], 'visible_events': packet['events'],
            'fragment': track.get('fragment')}


def _planned_scene(request, plan, groups, draft):
    turns = {turn['id']:turn for turn in plan['turns']}
    beats = [_beat(turn['id'], 'saved' if draft else 'planned') for turn in turns.values()]
    beat = _choose(beats, request.get('turn'),
                   default=next((turn['id'] for turn in turns.values() if turn['stage'] and turn['speakers']), None))
    turn = turns[beat['id']]
    if turn['stage']:
        beat['text'] = turn['stage']
    cast = turn[turn['phase']]
    voices = {speaker['actor']:speaker for speaker in turn['speakers']}
    subjects = []
    for actor, value in cast.items():
        voice = voices.get(actor)
        card = voice['mind'] if voice else None
        subjects.append({'actor':actor, **value, 'status':'active', 'speaker_allowed':voice is not None,
                         'mind_revision':card.get('revision') if card else None})
    subject = _select(subjects, groups, request)
    speaker = voices.get(subject['actor']) if subject else None
    if subject and subject['status'] == 'planning_only':
        subject['label'] = plan['form_labels'].get(subject['form'], subject['label'])
    selected = _selected_details(subject, card=speaker['mind'] if speaker else None,
                                 knowledge=[{'id':fact} for fact in speaker['known']] if speaker else (),
                                 relationships=_relationship_rows(turn['relationships'], subject) if subject else (),
                                 rules=[rule for rule in turn['rules'] if subject and rule['form']==subject['form']])
    program = {'scenes':[{**scene, 'beats':[turns[ident] for ident in scene['beats']]}
                          for scene in plan['scenes']]}
    return {'kind':'bridge', 'plan_id':plan['id'], 'beat':beat, 'beats':beats, 'selected':selected,
            'speakers':[speaker['label'] for speaker in turn['speakers']], 'subjects':subjects, 'actors':cast,
            'replay':plan['replay'], 'retained':plan['rejoin'], 'drafts':[],
            'audition':_bridge_saved_text(draft, program, beat), 'cutaway':[]}


def inspect(store, request, *, junctions=None):
    f._object(request, ('project', 'universe', 'episode', 'branch', 'timeline_revision'),
              ('action', 'scope_revision', 'turn', 'form', 'character', 'fragment', 'viewpoint', 'draft', 'source'))
    for key in ('turn', 'form', 'character', 'fragment', 'viewpoint', 'draft'):
        if key in request:
            checked_id(request[key], key.title())
    source = request.get('source', 'story')
    if source not in ('roast', 'story'):
        raise ValueError('Choose a story beat or the roast.')
    with store._connect() as c:
        c.execute('BEGIN')
        scope, head = f.SceneFragmentStore._scope(c, request)
        f.SceneFragmentStore._current(request, head)
        if request.get('scope_revision', scope['scope_revision']) != scope['scope_revision']:
            raise ValueError('Mind inspection scope changed.')
        draft = None
        plan = None
        if request.get('draft'):
            if not f._has(c, 'episode_drafts'):
                raise ValueError('No drafts in this episode.')
            draft = DraftStore.read_saved(c, scope['episode'], scope['branch'], request['draft'])
            writing = draft.get('writing_context') or {}
            if writing.get('fx06', {}).get('replay_minds'):
                source = 'roast'
            else:
                continuation = writing.get('continuation') or {}
                if continuation.get('kind') == 'scene-plan':
                    plan = continuation['plan']
                elif continuation.get('kind') != 'scene-bridge' or not continuation.get('turns'):
                    raise ValueError('This draft has no saved beat-by-beat Mind inputs.')
                source = 'story'
        elif source == 'story' and 'fragment' not in request:
            from .scene_plan import current
            plan = current(store, c, scope, head)
        if plan:
            if request.get('viewpoint'):
                raise ValueError('This replay has a fixed viewpoint and cast.')
            details = _planned_scene(request, plan, scene_bridges._junctions(store, c, scope['episode']) if not draft else {}, draft)
            saved = {key: draft.get(key) for key in ('id', 'source_revision', 'status', 'provider')} if draft else None
            return {'scope':scope, 'timeline_revision':head, 'saved_draft':saved, 'provider_calls':0, **details}
        story = None
        if source == 'story' and not draft:
            args = scope | {'timeline_revision': head}
            if 'fragment' in request:
                args['fragment'] = request['fragment']
            story = story_timeline.open_track(store, args, connection=c, include_media=False,
                                              include_inspection=True, include_clips=False)
        bridge = (draft is not None and source == 'story') or bool(story and story.get('inspection'))
        if (source == 'roast' or bridge) and request.get('viewpoint'):
            raise ValueError('This replay has a fixed viewpoint and cast.')
        if bridge:
            groups = story['inspection']['groups'] if not draft else {}
            details = _bridge(store, c, scope, head, request, story, groups, draft)
        else:
            groups = junctions() if junctions is not None else None
            if groups is None:
                groups = scene_bridges._junctions(store, c, scope['episode']) if store.scope()['kind'] == 'afm-starters' else {}
            if source == 'roast':
                details = _roast(store, c, scope, request, groups if not draft else {}, draft)
            else:
                details = _passage(store, c, scope, head, request, story, groups)
    saved = {key: draft.get(key) for key in ('id', 'source_revision', 'status', 'provider')} if draft else None
    return {'scope': scope, 'timeline_revision': head, 'saved_draft': saved, 'provider_calls': 0, **details}
