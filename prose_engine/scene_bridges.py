"""Propose prose for a saved, source-bound route into an existing scene."""
from __future__ import annotations

import json
import re

from story_graph import scene_branches, scene_bridge, scene_fragments as f, source_timing
from story_graph import character_relationships as relationships
from story_graph.typed_laws import active_laws, branch_points
from story_graph.universe_scope import checked_id, verify_scope
from story_graph.world_laws import WorldLawStore
from . import processing

COMMANDS = frozenset('scene.bridge.' + name for name in ('open', 'preview', 'save', 'run', 'recheck'))
LIMITS = {'input_bytes': 17_500, 'output_chars': 5_800}
PROVIDER = 'codex-session'
SLOT = '[Write the bridge into the saved next scene.]'
TABLE = 'scene_bridge_specs'
FIELDS = ('project', 'universe', 'episode', 'branch', 'scope_revision')
_SPEAKER = re.compile(r'([A-Za-z][ A-Za-z0-9-]{0,39}):[ \t]+(\S.*)')
_FORBIDDEN = re.compile(r'\b(?:shocker|hot scoomp|[fh]ot scoop|rutgers|transform(?:s|ed|ing)?|'
                        r'(?:fused|merged|recombined|morphed|reverted)|stan smith|peter griffin)\b', re.I)


def _scope(identity, episode, branch):
    return {'project': identity['project_id'], 'universe': identity['universe_id'],
            'episode': episode, 'branch': branch, 'scope_revision': identity['scope_revision']}


def _read(c, episode, ident):
    checked_id(ident, 'Saved bridge')
    row = c.execute('SELECT * FROM scene_bridge_specs WHERE episode=? AND id=?',
                    (episode, ident)).fetchone() if f._has(c, TABLE) else None
    if not row:
        raise ValueError('No bridge is registered in this episode')
    return scene_branches._unpack(row), row['sha256']


def _parent(store, c, parent, child, cutoff):
    f._object(parent, ('episode', 'branch', 'revision', 'text_sha256', 'graph_sha256',
                       'fork', 'frozen', 'join', 'source_evidence'))
    parent_scope = child | {'episode': parent['episode'], 'branch': parent['branch']}
    actual, head = f.SceneFragmentStore._scope(c, parent_scope)
    if actual != parent_scope or head != parent['revision']:
        raise ValueError('The parent episode changed after the fork')
    scene_branches._lineage(c, child, parent_scope, cutoff)
    source, digest = f.SceneFragmentStore._source(c, parent['episode'], head)
    graph = c.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',
                      (parent['episode'], head)).fetchone()['graph']
    if (digest, f.digest(graph)) != (parent['text_sha256'], parent['graph_sha256']):
        raise ValueError('The real parent script or source graph changed')
    f._range(parent['fork'], parent['join'], len(source))
    exact = f._object(parent['frozen'], ('id', 'start', 'end', 'sha256'))
    f._range(exact['start'], exact['end'], parent['fork'])
    if (f.digest(source[exact['start']:exact['end']]) != exact['sha256'] or
            (source[exact['end']:parent['fork']].strip() not in ('', '"', '”'))):
        raise ValueError('The fork must immediately follow the exact protected line')
    if not source[parent['join']:].startswith('### SCENE ') or source[parent['join']-1] != '\n':
        raise ValueError('The join must start at the saved destination scene heading')
    seen = set()
    for item in f._items(parent['source_evidence'], 'Source evidence', 32):
        f._object(item, ('id', 'start', 'end', 'sha256'))
        label = checked_id(item['id'], 'Source evidence')
        f._range(item['start'], item['end'], len(source))
        if label in seen or f.digest(source[item['start']:item['end']]) != item['sha256']:
            raise ValueError('A join requirement no longer has an exact source anchor')
        seen.add(label)
    if not seen:
        raise ValueError('Register source evidence for the destination conditions')
    return source


def _import_bindings(fragment, replay, solved, cast):
    # A source node can influence only the replay events it is wired to.
    graph = fragment['graph']
    nodes = {n['id']: n for n in graph['nodes']}
    frames = {frame['event']: frame for frame in replay['frames']}
    edges = {(e['from'], e['to']) for e in graph['edges'] if e['kind'] == 'influences'}
    cutaway = []
    used = set()
    for step in replay['overrides']:
        if step.get('transfer') != 'shape_only':
            continue
        evidence = step['evidence']
        dest = frames[step['event']]['node']
        refs = [n['id'] for n in nodes.values() if n['kind'] == 'reference' and
                evidence['id'] in n['evidence'] and (n['id'], dest) in edges]
        if len(refs) != 1 or not nodes[dest]['passage']:
            raise ValueError('A cutaway importer must bind one exact source node to each destination passage')
        used.add((refs[0], dest))
        cutaway.append({'from': refs[0], 'to': dest, 'passage': nodes[dest]['passage'],
                        'event': step['event'], 'operator': step['operator'], 'evidence': evidence})
    if not cutaway or edges != used:
        raise ValueError('Unbound or unused influences cannot reach this bridge')
    minds = []
    for actor in cast:
        targets = [{'scene': s['id'], 'beats': [b['id'] for b in s['beats']]}
                   for s in solved['scenes'] if actor['label'] in s['speakers']]
        if not targets:
            raise ValueError('A Mind importer needs a scoped active-speaker scene')
        minds.append({'mind': actor['mind'], 'form': actor['form'], 'source_sha256': actor['source_sha256'],
                      'targets': targets})
    return {'fragment': fragment['id'], 'fragment_revision': fragment['revision'],
            'cutaway': cutaway, 'minds': minds, 'next_scene': 'retained-without-imports'}


def _resolve(store, c, scope, head, record):
    if scope != record['scope'] or head != record['timeline_revision']:
        raise ValueError('The bridge belongs to its original branch and saved notebook revision')
    replay, digest = scene_branches._replay(c, scope, record['replay'])
    if digest != record['replay_sha256'] or replay['timeline_revision'] != head:
        raise ValueError('The cutaway replay is stale')
    cutoff = record['cutoff']
    parent = record['parent']
    source = _parent(store, c, parent, scope, cutoff)
    fragment, script, graph_sha = f.SceneFragmentStore(store).pinned_replay(c, scope, head, replay)
    law = WorldLawStore.in_connection(c, project_id=scope['project'], universe_id=scope['universe'])
    approved = [row for row in store._resolve_rows(c, scope['episode'], cutoff) if source_timing.visible_to(row, None)]
    if (graph_sha != replay['graph_sha256'] or law['revision'] != replay['law_revision'] or
            replay['history_sha256'] != f.digest(f.encoded(approved)) or replay['timeline_cutoff'] != cutoff):
        raise ValueError('The current graph, laws or visible history changed after the cutaway replay')
    exact = parent['frozen']
    book = scene_branches._book(c, scope, head, script, exact)
    slot = record['slot']
    start, end = f._range(slot['start'], slot['end'], len(script))
    tail = source[parent['join']:]
    if (script[:parent['fork']] != source[:parent['fork']] or script[start:end] != SLOT
            or script.count(SLOT) != 1 or script[end:].lstrip('\r\n') != tail
            or fragment['anchor']['end'] > start or script[fragment['anchor']['end']:start].strip()
            or f.digest(tail) != record['retained_sha256']):
        raise ValueError('The saved source prefix, bridge slot or retained scenes changed')
    masks = {m['id']: m for m in book['masks']}
    target = masks.get(record['editable_mask'])
    if (not target or (target['start'], target['end'], target['value'], target.get('hard', False)) !=
            (start, end, 25, False) or masks[exact['id']]['start'] != exact['start']
            or masks[exact['id']]['end'] != exact['end']):
        raise ValueError('The fork or the editable bridge no longer has its saved protection')
    frame = replay['frames'][-1]
    world = frame['state']
    cast = record['cast']
    ports = {item['id']: item['mind'] for item in world['manifestations']}
    if len(cast) != len(ports) or {m['form']: m['mind'] for m in cast} != ports:
        raise ValueError('The active manifestations no longer match their source Mind bindings')
    observed = {f'at:{actor_id}:{actor["location"]}' for actor_id, actor in world['actors'].items()}
    observed |= {f'form:{actor_id}:{actor["form"]}' for actor_id, actor in world['actors'].items()}
    stated = set(record['program']['start'])
    if not observed <= stated or {x for x in stated if x.startswith('form:')} != {x for x in observed if x.startswith('form:')}:
        raise ValueError('Bridge start does not reflect the cutaway exit state')
    for atom in observed:
        if atom.startswith('at:') and sum(x.startswith(atom.rsplit(':', 1)[0]+':') for x in stated) != 1:
            raise ValueError('An actor cannot start the bridge in two places')
    solved = scene_bridge.compile_bridge(record['program'])
    if not solved['scenes'] or solved['exit'] != record['exit']:
        raise ValueError('The stored bridge no longer reaches the saved join')
    imports = _import_bindings(fragment, replay, solved, cast)
    if 'imports' in record and imports != record['imports']:
        raise ValueError('The saved importer bindings changed')
    return solved, replay, imports


def install(store, request, *, parent, replay, slot, editable_mask, cast, program):
    """Register a branch-local plan after replay. No API can introduce transition authority."""
    if not cast or len(cast) > 16:
        raise ValueError('Register the exact active Mind bindings before planning a bridge')
    for actor in cast:
        f._object(actor, ('form', 'mind', 'label', 'guidance', 'source_sha256'))
        checked_id(actor['form'], 'Bound manifestation')
        f._sha(actor['source_sha256'])
        if (not isinstance(actor['mind'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+:[A-Za-z0-9_-]+', actor['mind'])
                or not isinstance(actor['label'], str) or not re.fullmatch(r'[A-Za-z][ A-Za-z0-9-]{0,39}', actor['label'])
                or any(not isinstance(x, str) or len(x)>250 for x in f._items(actor['guidance'], 'Mind guidance', 3))):
            raise ValueError('Register bounded, source-backed Mind cards')
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        scope, head = f.SceneFragmentStore._scope(c, request)
        saved, stamp = scene_branches._replay(c, scope, replay)
        source = _parent(store, c, parent, scope, saved['timeline_cutoff'])
        solved = scene_bridge.compile_bridge(program)
        record = {'schema_version': 1, 'scope': scope, 'timeline_revision': head, 'parent': parent,
                  'replay': replay, 'replay_sha256': stamp, 'cutoff': saved['timeline_cutoff'], 'slot': slot,
                  'editable_mask': checked_id(editable_mask, 'Mask'), 'cast': cast, 'program': program,
                  'exit': solved['exit'], 'retained_sha256': f.digest(source[parent['join']:])}
        _, _, record['imports'] = _resolve(store, c, scope, head, record)
        record['id'] = f._id('scene-bridge', record)
        payload = f.encoded(record)
        c.execute('''CREATE TABLE IF NOT EXISTS scene_bridge_specs (
            episode TEXT PRIMARY KEY REFERENCES episodes(id), id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
        row = c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (scope['episode'],)).fetchone()
        if row and scene_branches._unpack(row) != record:
            raise ValueError('This episode already owns a different bridge')
        if not row:
            c.execute('INSERT INTO scene_bridge_specs VALUES (?,?,?,?)',
                      (scope['episode'], record['id'], payload, f.digest(payload)))
    return record


def _turns(record, replay, solved, junctions, *, universe_kind=None, laws=()):
    cards = {}
    root_id = replay['frames'][0]['state']['root']
    root = junctions.get(root_id)
    forms = {x.id: x for x in root.forms} if root else {}
    for source in record['cast']:
        card = dict(source)
        form = forms.get(card['form'])
        if form:
            if not form.link or form.link.node_id != card['mind']:
                raise ValueError('The saved manifestation Mind link has changed')
            if form.id in root.mind_behaviors:
                card['guidance'] = [root.mind_behaviors[form.id]]
        card['revision'] = f.digest(f.encoded(card))
        cards[card['form']] = card

    def row(ident, actors, ports, speakers=()):
        active = {}
        active_forms = {}
        for key, actor in actors.items():
            form_id = actor['form']
            owner = root_id if key in ports else key
            active_forms.setdefault(owner, []).append(form_id)
            group = junctions.get(key)
            linked = next((x.link for x in group.forms if x.id == form_id), None) if group else None
            card = cards.get(form_id) if form_id in ports else None
            if card and ports[form_id] != card['mind']:
                raise ValueError('Replay names a different Mind for this manifestation')
            active[key] = dict(actor, mind=ports.get(form_id) or (linked.node_id if linked else None),
                               mind_revision=card['revision'] if card else None)
        turn = {'beat': ident, 'actors': active, 'speakers': list(speakers)}
        if universe_kind == 'afm-starters':
            scope = record['scope']
            edges = relationships.project(active_forms, junctions, kind=universe_kind,
                                          episode=scope['episode'], branch=scope['branch'], beat=ident, laws=laws)
            if edges:
                turn['relationships'] = list(edges)
        return turn

    turns = []
    for frame in replay['frames']:
        state = frame['state']
        ports = {m['id']: m['mind'] for m in state['manifestations']}
        turns.append(row(frame['event'], state['actors'], ports))
    scenes = {scene['id']: scene for scene in solved['scenes']}
    actions = {action['id']: action for action in record['program']['actions']}
    for frame in solved['frames']:
        action = actions[frame['id']]
        triples = [x.split(':') for x in frame['state'] if x.count(':') == 2]
        locations = {key: value for kind, key, value in triples if kind=='at'}
        forms_by_actor = {key: value for kind, key, value in triples if kind=='form'}
        actors = {key: {'location': place, 'form': forms_by_actor.get(key, key)} for key, place in locations.items()}
        eligible = []
        for key, actor in actors.items():
            form_id = actor['form']
            label = cards[form_id]['label'] if form_id in cards else (
                'Nurse Franny' if form_id=='nurse_pamela_franny_anderson' else key.title())
            audible = label in action.get('audible_to_scene', [])
            if audible or actor['location'] == frame['scene'] or (actor['location']=='sedan' and frame['scene']=='driveway'):
                if label in scenes[frame['scene']]['speakers'] and 'car:departed' not in frame['state']:
                    eligible.append(label)
        turns.append(row(frame['id'], actors, ports, [] if action.get('required_silence') else sorted(eligible)))
    return turns, list(cards.values())


def scoped_form_store(c, graph, episode):
    """Expose forms from this episode's signed bridge, including older portable copies."""
    from dataclasses import replace
    from story_graph.character_forms import AFM_JUNCTIONS, CharacterForm, FormLink
    from story_graph.form_graph_store import FormGraphStore
    from story_graph.source_imports import junctions, merge_junctions
    groups = merge_junctions(graph.imported, junctions(c, {}))
    nodes = dict(graph.builtins)
    row = c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (episode,)).fetchone() if f._has(c, TABLE) else None
    if row:
        record = scene_branches._unpack(row)
        group = groups.get('rainee', AFM_JUNCTIONS['rainee'])
        forms = {form.id: form for form in group.forms}
        for card in record['cast']:
            link = FormLink('digital_mind', card['mind'])
            form = forms.get(card['form']) or CharacterForm(card['form'], card['label'], 'transformation', after='rainee')
            forms[form.id] = replace(form, link=form.link or link)
            nodes.setdefault(link.node_id, {'id':link.node_id, 'kind':link.kind, 'label':card['label']})
        groups['rainee'] = replace(group, forms=tuple(forms.values()))
    return FormGraphStore(graph.path, list(nodes.values()), imported=groups)


def _junctions(store, c, episode):
    from story_graph.form_graph_store import FormGraphStore
    return scoped_form_store(c, FormGraphStore(store.form_graph_path), episode).junctions()


def _project_turns(store, c, record, replay, solved, *, junctions=None):
    scope = record['scope']
    identity = verify_scope(c, project_id=scope['project'], universe_id=scope['universe'])
    laws = WorldLawStore.in_connection(c, project_id=scope['project'], universe_id=scope['universe'])['laws']
    allowed = active_laws(laws, branch_points(c, scope['episode'], record['cutoff']), scope['branch'])
    groups = _junctions(store, c, scope['episode']) if junctions is None else junctions
    return _turns(record, replay, solved, groups,
                  universe_kind=identity['kind'], laws=allowed)


def stage_form_view(timeline, episode, graph):
    """Project saved routing at the episode entry without editing the graph store."""
    from story_graph.character_forms import CharacterJunction

    with timeline._connect() as c:
        saved = dict(timeline._require_active(c, episode))
        events = timeline._resolve_rows(c, episode, 0)
    branch, position = saved['branch'], saved['position']
    override = bool(saved.get('time_travel_override'))
    for group in graph['junctions']:
        junction = CharacterJunction.from_record(group)
        approved, active = set(), None
        for event in events:
            if event.get('form_character') == junction.character_id and event.get('form_id'):
                approved.add(event['form_id'])
                if event.get('form_action') == 'active':
                    active = event['form_id']
        routed, lineage = junction.route_at(episode, branch, position, time_travel_override=override)
        projection = junction.project(approved=approved | lineage, active=routed or active, planning=True,
                                      episode_pos=position, time_travel_override=override)
        for form, scoped in zip(group['forms'], projection['forms'], strict=True):
            form.update(episode_status=scoped['status'], episode_gate=scoped['gate'])
    graph['stage_scope'] = {'episode': episode, 'branch': branch, 'position': position}
    return graph


def form_graph_view(store, episode, graph):
    """Add the episode's replay cast and per-beat form statuses to the graph view."""
    from . import scene_plan
    with store._connect() as c:
        c.execute('BEGIN')
        row = (c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (episode,)).fetchone()
               if f._has(c, TABLE) else None)
        record = scene_branches._unpack(row) if row else None
        if record:
            scope, head = f.SceneFragmentStore._scope(c, record['scope'])
        else:
            identity = verify_scope(c)
            saved = store._require_active(c, episode)
            scope, head = _scope(identity, episode, saved['branch']), saved['head']
        try:
            plan = scene_plan.current(store, c, scope, head)
        except ValueError as exc:
            return {**graph, 'beats': [], 'scene_plan_error': str(exc)}
        if plan:
            turns = [{'beat': turn['id'], 'actors': turn['after'],
                      'speakers': [speaker['label'] for speaker in turn['speakers']]}
                     for turn in plan['turns']]
            forms = {form['port_id']:form['id'] for group in graph['junctions'] for form in group['forms']}
            beats = []
            for turn in turns:
                active = {actor['form'] for actor in turn['actors'].values()}
                beats.append({'id': turn['beat'], 'label': turn['beat'].replace('-', ' ').capitalize(),
                              'forms': {port:'active' if form in active else 'planning_only'
                                        for port,form in forms.items()}})
            return {**graph, 'scene_plan': plan, 'beats': beats,
                    'bridge_cast': {'scope': scope, 'revision': head, 'turns': turns,
                                    'retained_sha256': plan['rejoin']['sha256']}}
        if not record:
            return None
        replay, stamp = scene_branches._replay(c, record['scope'], record['replay'])
        if stamp != record['replay_sha256']:
            raise ValueError('Bridge replay changed')
        turns, cards = _project_turns(store, c, record, replay, scene_bridge.compile_bridge(record['program']))
    cast = {'scope': record['scope'], 'revision': record['timeline_revision'], 'turns': turns,
            'minds': cards, 'retained_sha256': record['retained_sha256']}
    beats = []
    forms = [form for group in graph['junctions'] for form in group['forms']]
    for turn in turns:
        active = {actor['form'] for actor in turn['actors'].values()}
        statuses = {form['port_id']: 'active' if form['id'] in active else 'planning_only' for form in forms}
        beats.append({'id': turn['beat'], 'label': turn['beat'], 'forms': statuses})
    return {**graph, 'beats': beats, 'bridge_cast': cast}


def project(store, c, identity, episode, branch, head, beat, start, end, viewpoint, binding):
    f._object(binding, ('bridge', 'sha256'))
    scope = _scope(identity, episode, branch)
    record, stamp = _read(c, episode, binding['bridge'])
    slot = record['slot']
    if binding['sha256'] != stamp or (beat, start, end, viewpoint) != (record['cutoff'], slot['start'], slot['end'], None):
        raise ValueError('The writer may only fill the saved bridge slot')
    solved, replay, imports = _resolve(store, c, scope, head, record)
    actors = replay['frames'][-1]['state']['actors']
    turns, minds = _project_turns(store, c, record, replay, solved)
    labels = {item['form']:item['label'] for item in minds}
    eligible = {turn['beat']: turn['speakers'] for turn in turns}
    for mind in imports['minds']:
        for target in mind['targets']:
            target['beats'] = [beat for beat in target['beats'] if labels[mind['form']] in eligible[beat]]
        mind['targets'] = [target for target in mind['targets'] if target['beats']]
    active = {ident:item['form'] for ident,item in actors.items() if ident not in labels}
    return {'kind': 'scene-bridge', 'binding': binding, 'limits': LIMITS, 'program': solved,
            'turns': turns, 'minds': minds, 'cast': labels, 'active_forms': active,
            'known_forms': sorted(active.values()), 'scents': {}, 'imports': imports,
            'frozen_sha256': record['parent']['frozen']['sha256'],
            'retained_sha256': record['retained_sha256'], 'replay_world_sha256': replay['world_sha256']}


def guard(store, c, packet):
    context = packet.context
    identity = {'project_id': context.project_id, 'universe_id': context.universe_id,
                'scope_revision': context.scope_revision}
    current = project(store, c, identity, packet.episode, packet.branch, packet.revision, packet.beat,
                      packet.start, packet.end, packet.viewpoint, packet.continuation['binding'])
    if current != packet.continuation:
        raise ValueError('The fork, replay or Roger handoff changed')


def speaking_relationship(edge, speakers, labels):
    return all(relationships.form_name(edge[side], labels) in speakers for side in ('from', 'to'))


def writer_context(bridge, media_guidance=()):
    parts = ['\nBRIDGE: the cutaway already happened. Begin just after the three Rainees roast Haley. '
             'The world-state program below is the result of running the graph. Write only action-bound '
             'dialogue for these missing scenes. Do not replay the cutaway or write the Roger scene. '
             'The car leaves at the end and the existing next scene starts outside.\n']
    parts.append('Three current, distinct Rainee Minds:\n' + '\n'.join(
        '- ' + a['label'] + ': ' + ' | '.join(a['guidance']) for a in bridge['minds']))
    parts.append('\nKeep Nurse Franny active and all three women separate. No flashbacks, extra characters, '
                 'form changes, renewed blasts, or outside story events. Francine drives. The four are all in '
                 'the family sedan when it leaves. Haley, Stella and Roger stay outside. The dialogue is '
                 'fast, playful and short. Give each character a reason to act and keep their voices distinct. '
                 'No sexual descriptions.\nReturn only the Markdown below. Retain every heading, location and '
                 'stage direction EXACTLY and in order. Between stage directions add brief dialogue lines in the '
                 'form Name: words. Dialogue must not add actions or change any state. No unlabelled narration, '
                 'code fences or explanation. Every listed required speaker must speak at least once in its scene.\n')
    turns = {turn['beat']: turn for turn in bridge['turns']}
    labels = {'nurse_pamela_franny_anderson': 'Nurse Franny', **bridge['cast']}
    inherited = {}
    local = {}
    for frame in bridge['program']['frames']:
        beat = frame['id']
        speakers = turns[beat]['speakers']
        for edge in turns[beat].get('relationships', []):
            if not speaking_relationship(edge, speakers, labels):
                continue
            key = (edge['from']['form'], edge['to']['form'])
            inherited.setdefault(key, edge)
            if 'override' in edge:
                local.setdefault(beat, []).append(relationships.override_line(edge, labels))
    if inherited:
        parts.append(relationships.writer_context(inherited.values(), labels, include_overrides=False))
    if media_guidance:
        from .media_overrides import cue_lines
        parts.append('Use media craft cues only as optional rendering guidance at their named turn. '
                     'Adapt phrasing or space around existing dialogue. Preserve exact stage directions and story state.\n')
        for cue in media_guidance:
            local.setdefault(cue['target']['beat'], []).extend(cue_lines([cue]))
    for scene in bridge['program']['scenes']:
        stages = []
        for beat in scene['beats']:
            ident = beat['id']
            allowed = ', '.join(turns[ident]['speakers']) or 'silence'
            stages.append('\n'.join([beat['stage'], '[Following dialogue: ' + allowed + ']', *local.get(ident, [])]))
        parts.append('\n' + scene['heading'] + '\n' + scene['location'] + '\n' +
                     '\n\n'.join(stages) + '\n' +
                     'Allowed speakers: ' + ', '.join(scene['speakers']) +
                     '. Required: ' + ', '.join(scene['required_speakers']) + '.')
    return '\n'.join(parts)+'\n'


def validate_output(bridge, text):
    if len(text) > LIMITS['output_chars']:
        return ['Bridge output exceeds its character budget']
    if _FORBIDDEN.search(text) or SLOT in text:
        return ['Bridge includes an out-of-scope form, plot event or placeholder']
    parts = [line.strip() for line in text.splitlines() if line.strip()]
    scenes = bridge['program']['scenes']
    headings = [i for i, line in enumerate(parts) if re.match(r'^#{1,6}\s', line)]
    if not headings or len(headings) != len(scenes) or headings[0] != 0:
        return ['Return only the planned bridge scenes in order']
    permissions = {turn['beat']: turn['speakers'] for turn in bridge.get('turns', [])}
    for i, (begin, scene) in enumerate(zip(headings, scenes)):
        end = headings[i+1] if i+1 < len(headings) else len(parts)
        anchors = [scene['heading'], scene['location'], *(b['stage'] for b in scene['beats'])]
        present, speakers, lines = [], set(), set()
        for line in parts[begin:end]:
            match = _SPEAKER.fullmatch(line)
            if not match:
                present.append(line)
                continue
            name, body = match.groups()
            index = len(present) - 3
            if permissions and (not 0 <= index < len(scene['beats']) or
                                name not in permissions[scene['beats'][index]['id']]):
                return ['Speaker is unavailable at this beat']
            if (name not in scene['speakers'] or len(body) > 300 or not any(c.isalpha() for c in body)
                    or body.casefold() in lines or re.search(r'\bflower shop died\b', body, re.I)):
                return ['Bridge dialogue uses an unavailable speaker, repeats a line or exceeds its boundary']
            if len(lines) >= 14:
                return ['Bridge dialogue exceeds the scene budget']
            speakers.add(name)
            lines.add(body.casefold())
        if present != anchors or not set(scene['required_speakers']) <= speakers:
            return ['A bridge changed a mapped action or omitted a required speaker']
        if i == len(scenes)-1 and parts[end-1] != anchors[-1]:
            return ['End the bridge at the mapped departure, before the retained scene']
    return []


def _recheck(store, drafts, scope, head, binding, draft_id, plan, preview, junctions):
    """Validate an unchanged returned candidate; keep its blocked attempt as a parent."""
    from sqlite3 import IntegrityError
    from .scoped_pipeline import build_packet, validate_output
    original = drafts.open(scope['episode'], scope['branch'], draft_id)
    attempt = original.get('attempt_id')
    text = original['text']
    if (original['status'] != 'BLOCKED' or not attempt or not isinstance(text, str) or
            (original.get('writing_run') or {}).get('id') != plan):
        raise ValueError('Choose the returned, blocked draft for this plan')
    if original.get('reference_receipts'):
        raise ValueError('Book-guided responses need a new validated proposal. The returned draft remains available.')
    packet = build_packet(store, scope['episode'], original['beat'], head, original['start'], original['end'],
                          None, junctions() if junctions else None, project_id=scope['project'],
                          universe_id=scope['universe'], branch=scope['branch'], continuation_binding=binding)
    public = packet.public()
    if (public != original['writing_context'] or public != preview['scope']
            or packet.character_store_token != original['character_store_token']
            or original['rhythm_guidance'] != preview['rhythm_guidance']):
        raise ValueError('The original writer scope changed; its response is retained')
    if issues := validate_output(packet, text):
        raise ValueError('; '.join(issues))
    digest = f.digest(text)
    ident = f._id('bridge-recheck', original['id'], digest, plan)
    run = {'kind':'bridge-output-recheck','candidate_sha256':digest,'original_attempt_id':attempt,'plan':plan}
    try:
        drafts.start(packet, original['provider'], parent=original['id'], draft_id=ident, writing_run=run,
                     request_budget={'max_provider_calls':0,'token_limit':None}, scene_function='comedy',
                     rhythm_guidance=preview['rhythm_guidance'],
                     proposal={'text':text,'issue':{'kind':'saved-output-recheck'},
                               'rhythm_evidence':original.get('rhythm_evidence')})
        duplicate = False
    except IntegrityError:
        saved = drafts.open(scope['episode'],scope['branch'],ident)
        if (saved['status'] != 'PROPOSED' or saved['parent'] != original['id']
                or saved.get('writing_run') != run or saved['text'] != text):
            raise ValueError('A different saved draft owns this recheck')
        duplicate = True
    return {'status':'PROPOSED','draft_id':ident,'parent':original['id'],'candidate_sha256':digest,
            'attempt_id':attempt,'provider_calls':0,'replayed':duplicate}


def _offline_receipt(c, scope, ident, run, text):
    if not f._has(c, 'episode_drafts'):
        return None
    row = c.execute('SELECT status,payload FROM episode_drafts WHERE episode=? AND branch=? AND id=?',
                    (scope['episode'], scope['branch'], ident)).fetchone()
    if not row:
        return None
    saved = json.loads(row['payload'])
    if row['status'] != 'PROPOSED' or saved.get('writing_run') != run or saved['text'] != text:
        raise ValueError('A different draft owns this offline save')
    return {'status': 'PROPOSED', 'draft_id': ident, 'bridge': run['bridge'], 'plan': run['plan'],
            'candidate_sha256': run['candidate_sha256'], 'origin': 'imported', 'provider_calls': 0, 'replayed': True}


def _save_offline(store, drafts, scope, record, binding, preview, ident, run, text, junctions, job):
    from sqlite3 import IntegrityError
    from .scoped_pipeline import build_packet, validate_output

    with processing.step(job, 'validate', {'candidate_sha256': run['candidate_sha256']}) as checked:
        slot = record['slot']
        packet = build_packet(store, scope['episode'], record['cutoff'], record['timeline_revision'],
                              slot['start'], slot['end'], junctions=junctions() if junctions else None,
                              project_id=scope['project'], universe_id=scope['universe'],
                              branch=scope['branch'], continuation_binding=binding)
        if packet.public() != preview['scope']:
            raise ValueError('The saved bridge input changed. Open its current preview.')
        if issues := validate_output(packet, text):
            raise ValueError('; '.join(issues))
        checked.update(validated=True)
    with processing.step(job, 'save', {'draft': ident}) as result:
        try:
            drafts.start(packet, 'offline-bridge', draft_id=ident, writing_run=run, scene_function='comedy',
                         rhythm_guidance=preview['rhythm_guidance'],
                         request_budget={'max_provider_calls': 0, 'token_limit': None},
                         proposal={'text': text, 'issue': {'kind': 'offline-bridge'}})
        except (IntegrityError, ValueError):
            with store._connect() as c:
                if saved := _offline_receipt(c, scope, ident, run, text):
                    result.update(draft=ident, replayed=True)
                    return saved
            raise
        result.update(draft=ident, status='PROPOSED')
    return {'status': 'PROPOSED', 'draft_id': ident, 'bridge': run['bridge'], 'plan': run['plan'],
            'candidate_sha256': run['candidate_sha256'], 'origin': 'imported', 'provider_calls': 0, 'replayed': False}


def execute(store, action, request, *, junctions=None, provider_factory=None, provider_resolver=None, books_root=None):
    options = {'junctions': junctions, 'provider_factory': provider_factory, 'provider_resolver': provider_resolver,
               'books_root': books_root}
    if action != 'scene.bridge.save':
        return _execute(store, action, request, **options)
    with processing.begin(store, request, 'bridge-save', 'Save offline bridge draft', {}) as job:
        job.skip('writer', 'Using supplied dialogue. No story provider was called.')
        result = _execute(store, action, request, job=job, **options)
        job.data['outputs'] = {'draft': result['draft_id'], 'replayed': result['replayed'],
                               'candidate_sha256': result['candidate_sha256']}
        return result


def _execute(store, action, request, *, junctions, provider_factory, provider_resolver, books_root, job=None):
    from .notebook import DraftStore, NotebookStore
    from .providers.session_attempts import SessionAttemptError
    from .scoped_service import _selection_identity, _selection_replay, execute_scoped
    if action not in COMMANDS:
        raise ValueError('Unknown scene bridge action')
    op = action.rsplit('.', 1)[1]
    optional = ('action', 'references') if op in ('preview', 'run') else ('action',)
    tail = {'run': ('plan',), 'recheck': ('plan', 'draft'), 'save': ('plan', 'text')}.get(op, ())
    f._object(request, (*FIELDS, 'bridge', *tail), optional)
    with processing.step(job, 'source') as checked, store._connect() as c:
        c.execute('BEGIN')
        scope, head = f.SceneFragmentStore._scope(c, request)
        record, stamp = _read(c, scope['episode'], request['bridge'])
        if record['scope'] != scope or scope['scope_revision'] != request['scope_revision']:
            raise ValueError('This bridge belongs to another saved scope')
        binding = {'bridge': record['id'], 'sha256': stamp}
        checked.update(bridge=record['id'], timeline_revision=head)
        if op == 'save':
            text = request['text']
            if not isinstance(text, str) or not text.strip() or len(text) > LIMITS['output_chars']:
                raise ValueError('Enter an offline draft within the bridge character budget')
            saved_plan = checked_id(request['plan'], 'Saved bridge plan')
            run = {'kind': 'bridge-offline', 'bridge': record['id'], 'plan': saved_plan,
                   'candidate_sha256': f.digest(text)}
            ident = f._id('bridge-offline', binding, run)
            if saved := _offline_receipt(c, scope, ident, run, text):
                return saved
        if op != 'open':
            _resolve(store, c, scope, head, record)
    if op == 'open':
        store_drafts = DraftStore(NotebookStore(store))
        drafts = [d for d in store_drafts.list(scope['episode'], scope['branch'])
                  if (((d.get('writing_context') or {}).get('continuation') or {}).get('binding') == binding)]
        return {'binding': binding, 'current': head == record['timeline_revision'],
                'replay': record['replay'], 'join': record['parent']['join'], 'imports': record['imports'],
                'drafts': [{k: d[k] for k in ('id', 'status', 'source_revision')} for d in drafts],
                'provider_calls': 0}
    incoming = scope | {'revision': head, 'beat': record['cutoff'], 'start': record['slot']['start'],
                        'end': record['slot']['end'], 'provider': PROVIDER, 'references': request.get('references', 'none'),
                        'scene_function': 'comedy'}
    if incoming['references'] != 'none':
        incoming['reference_delivery'] = request.get('reference_delivery', 'excerpt')
    args = {'junctions': junctions, 'continuation_binding': binding, 'books_root': books_root}
    with processing.step(job, 'context') as assembled:
        preview = execute_scoped(store, 'rhythm-preview', incoming, **args)
        if preview['rhythm_guidance']['fully_locked'] or preview['prompt_bytes'] > LIMITS['input_bytes']:
            raise ValueError('The bridge is locked or exceeds its one-call input budget')
        plan = f._id('scene-bridge-plan', binding, preview['scope'], preview['rhythm_guidance']['id'])
        assembled.update(plan=plan, prompt_bytes=preview['prompt_bytes'])
        if op == 'preview':
            return preview | {'plan': plan}
        if plan != request['plan']:
            raise ValueError('The bridge plan changed; reopen its current preview')
    if op == 'recheck':
        return _recheck(store, DraftStore(NotebookStore(store)), scope, head, binding,
                        request['draft'], plan, preview, junctions) | {'bridge':record['id']}
    if op == 'save':
        return _save_offline(store, DraftStore(NotebookStore(store)), scope, record, binding, preview,
                             ident, run, text, junctions, job)
    if provider_factory is None and provider_resolver is not None:
        provider_factory = lambda: provider_resolver(PROVIDER, scope['episode'])
    generation = incoming | {'request_id': plan, 'rhythm_plan_id': preview['rhythm_guidance']['id']}
    try:
        result = execute_scoped(store, 'generate', generation, **args, provider_factory=provider_factory,
                                expected_clip_scope=preview['scope'])
    except SessionAttemptError as exc:
        # The selection journal can be read after a lost send without invoking the writer again.
        result = _selection_replay(store, _selection_identity(store, 'generate', generation), generation)
        if not result:
            raise ValueError('The writer is unavailable and no retry was sent') from exc
        return result | {'bridge':record['id'], 'plan':plan, 'attempt_state':exc.state,
                         'attempt_id':exc.attempt_id, 'provider_calls':None if result['status']=='UNKNOWN' else 0}
    return result | {'bridge': record['id'], 'plan': plan, 'provider_calls': 0 if result.get('replayed') else 1}
