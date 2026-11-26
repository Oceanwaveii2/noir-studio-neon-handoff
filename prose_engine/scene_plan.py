"""Compile the editable scene and its writing turns from an approved replay."""

import re
from collections import defaultdict

from story_graph import character_relationships, scene_branches, scene_bridge, scene_fragments as fragments
from story_graph import source_timing
from story_graph.typed_laws import active_laws, branch_points
from story_graph.universe_scope import checked_id, verify_scope
from story_graph.world_laws import WorldLawStore, check_laws

from . import scene_bridges
from .notebook import resolve as resolve_masks


COMMAND = 'scene.plan.open'
TABLE = 'scene_writing_plans'
LIMITS = {'input_bytes': 28_000, 'output_chars': 8_000}
_LABELS = {
    'francine': 'Francine', 'nurse_pamela_franny_anderson': 'Nurse Franny',
    'peter_griffin_celestial_variant': 'Rainee Peter Griffen',
}
_NEW_EVENT = re.compile(
    r'\b(?:transform(?:s|ed|ing)?|morph(?:s|ed|ing)?|reunites?|recombines?|'
    r'splits? into|fuses? into|turns? into|changes? into|passes? gas|farts?|'
    r'lets? out a blast|releases? another blast|knocks? [^.!?]{1,30} down)\b', re.I)


def register(store, request, *, heading, turns, scents):
    """Register authored dialogue permissions against the saved replay on this branch."""
    with store._connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        scope, head = fragments.SceneFragmentStore._scope(connection, request)
        record, stamp = scene_bridges._read(connection, scope['episode'], request['bridge'])
        policy = {'version': 1, 'bridge': record['id'], 'bridge_sha256': stamp,
                  'heading': heading, 'turns': turns, 'scents': scents}
        body = fragments.encoded(policy)
        connection.execute('''CREATE TABLE IF NOT EXISTS scene_writing_plans (
            episode TEXT PRIMARY KEY REFERENCES episodes(id), payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
        previous = connection.execute('SELECT sha256 FROM scene_writing_plans WHERE episode=?',
                                      (scope['episode'],)).fetchone()
        stamp = fragments.digest(body)
        if previous and previous['sha256'] != stamp:
            raise ValueError('A different set of turn permissions is already registered for this copy')
        if not previous:
            scene_bridges._resolve(store, connection, scope, head, record)
            _compile(store, connection, scope, head, policy)
            connection.execute('INSERT INTO scene_writing_plans VALUES (?,?,?)',
                               (scope['episode'], body, stamp))


def _source(store, connection, scope, head, record, replay):
    registry = fragments.SceneFragmentStore(store)
    row = registry._find(connection, scope['episode'], replay['fragment'], replay['fragment_revision'])
    if not row or row['sha256'] != replay['graph_sha256']:
        raise ValueError('The scene plan lost its verified source graph')
    fragment = registry._record(row)
    if fragment['scope'] != scope:
        raise ValueError('The scene source belongs to another branch')
    text, original = registry._target_at(connection, fragment)
    script, stamp = registry._source(connection, scope['episode'], head)
    anchor = fragment['anchor']
    at = anchor['start']
    historical = False
    if stamp != anchor['source_sha256']:
        at = script.find(text)
        if original.find(text) != anchor['start'] or original.find(text, anchor['start'] + 1) >= 0:
            raise ValueError('The recorded scene anchor was ambiguous')
        if at != -1 and script.find(text, at + 1) != -1:
            raise ValueError('The scene anchor is ambiguous in the current manuscript')
        historical = at == -1
        if not historical and not fragments._whole_lines(script, at, at + len(text)):
            raise ValueError('The replay passage changed. Rebind its story beats before generating again.')
    parent = record['parent']
    parent_text = scene_bridges._parent(store, connection, parent, scope, record['cutoff'])
    exact = parent['frozen']
    book = scene_branches._book(connection, scope, head, script, exact)
    mask = next(mask for mask in book['masks'] if mask['id'] == exact['id'])
    offset = mask['start'] - exact['start'] if historical else at - anchor['start']
    frozen = {**exact, 'start': exact['start'] + offset, 'end': exact['end'] + offset}
    fork = parent['fork'] + offset
    if (any(mask[key] != frozen[key] for key in ('start', 'end')) or
            script[frozen['end']:fork] != parent_text[exact['end']:parent['fork']]):
        raise ValueError('The current exact lock does not cover the replay’s original fork occurrence')
    retained = parent_text[parent['join']:]
    join = len(script) - len(retained)
    if not script.endswith(retained) or fragments.digest(retained) != record['retained_sha256']:
        raise ValueError('The retained Roger rejoin changed')
    if historical:
        # The analyzed replay remains pinned to its verified source revision.
        # The current manuscript contributes a separate region after the lock.
        history_start = anchor['start']
        current_start = history_start + offset
        if (not 0 <= current_start <= frozen['start'] < fork < join or
                original[history_start:parent['fork']] != script[current_start:fork] or
                fragments.digest(original[exact['start']:exact['end']]) != exact['sha256']):
            raise ValueError('The frozen prefix no longer identifies the source replay')
        public = registry._public(fragment, head, fragment['revision'], 'OPENED')['fragment']
    else:
        public = registry._public(fragment | {'anchor': anchor | {'start': at, 'end': at + len(text)}},
                                  head, fragment['revision'], 'OPENED')['fragment']
    body = script[fork:join]
    start = fork + len(body) - len(body.lstrip())
    end = fork + len(body.rstrip())
    if not fork <= start < end <= join or (not historical and not start < public['anchor']['end'] <= end):
        raise ValueError('The saved fork, replay passage and retained scene are out of order')
    masks = [[max(start, value['start']), min(end, value['end']), value['value']]
             for value in resolve_masks(script, book['default_protection'], book['masks'])
             if value['start'] < end and value['end'] > start]
    target = {'start': start, 'end': end, 'sha256': fragments.digest(script[start:end]), 'protection': masks}
    notebook_revision = connection.execute('SELECT head FROM notebook_heads WHERE episode=?',
                                          (scope['episode'],)).fetchone()['head']
    source_window = (parent['fork'], anchor['end'], exact, anchor) if historical else None
    return public, target, frozen, fork, join, stamp, notebook_revision, source_window


def _actors(state, groups, root, labels):
    result = {}
    ports = {entry['id']: entry['mind'] for entry in state.get('manifestations', ())}
    for actor, value in state['actors'].items():
        character = root if actor in ports else actor
        form = value['form']
        group = groups.get(character)
        linked = next((entry.link for entry in group.forms if entry.id == form), None) if group else None
        if actor in ports and (not linked or linked.kind != 'digital_mind' or linked.node_id != ports[actor]):
            raise ValueError(f'{labels[form]} needs its registered Digital Mind link')
        result[actor] = {'form': form, 'location': value['location'], 'character': character,
                         'label': labels.get(form, character_relationships.form_name(
                             {'character': character, 'form': form}, labels)),
                         'mind': linked.node_id if linked else None}
    return result


def _tactic(actor, seed, groups, laws, known_forms, labels):
    form = actor['form']
    group = groups.get(actor['character'])
    if seed is None and (group is None or form not in group.mind_behaviors):
        return None
    authored = group.mind_behaviors.get(form) if group else None
    conditional = seed.get('tendencies') if seed else None
    if conditional:
        guidance = ([authored] if authored else []) + [
            f"When {move['when']}, try to {move['try']}." for move in conditional
        ] + [seed['constraint']]
    else:
        guidance = [authored] if authored else seed['guidance'] if seed else []
    if not guidance:
        return None
    source = (f'form-graph:data:{group.id}:form:{form}' if authored else seed['source_sha256'])
    text = ' '.join(guidance)
    if check_laws(text, laws) or _mentions_unavailable(text, known_forms, labels):
        return {'mind': actor['mind'], 'status': 'withheld', 'source': source}
    card = {'mind': actor['mind'], 'form': form, 'source': source, 'guidance': guidance,
            'origin': 'author' if authored else 'source'}
    if conditional:
        card.update(tendencies=conditional, constraint=seed['constraint'], evidence=seed['evidence'],
                    port=seed['port'], donor=seed['donor'], author_guidance=authored)
    return card | {'revision': fragments.digest(fragments.encoded(card))}


def _mentions_unavailable(text, available, labels):
    return any(form not in available and re.search(r'(?<!\w)' + re.escape(label) + r'(?!\w)', text, re.I)
               for form, label in labels.items())


def _turn(scope, ident, operation, stage, before, after, phase, voices, listeners, required,
          knowledge, known_forms, cards, groups, laws, labels, kind):
    cast = before if phase == 'before' else after
    if (any(actor not in cast for actor in (*voices, *listeners)) or
            len(set(voices)) != len(voices) or not set(required) <= set(voices)):
        raise ValueError(f'{ident} has a speaker or listener unavailable on this turn')
    forms = defaultdict(list)
    for actor in cast.values():
        forms[actor['character']].append(actor['form'])
    edges = character_relationships.project(forms, groups, kind=kind, episode=scope['episode'],
                                            branch=scope['branch'], beat=ident, laws=laws)
    speakers = []
    for actor in voices:
        info = cast[actor]
        allowed_listeners = [other for other in listeners if other != actor]
        speakers.append({'actor': actor, 'label': info['label'], 'form': info['form'],
                         'character': info['character'], 'listeners': allowed_listeners,
                         'required': actor in required, 'known': knowledge.get(actor, []),
                         'mind': _tactic(info, cards.get(info['form']), groups, laws, known_forms, labels)})
    if len({speaker['label'] for speaker in speakers}) != len(speakers):
        raise ValueError(f'{ident} has ambiguous dialogue labels')
    return {'id': ident, 'operation': operation, 'stage': stage, 'phase': phase,
            'before': before, 'after': after, 'speakers': speakers, 'relationships': list(edges),
            'revealed_forms': sorted(known_forms), 'rules': []}


def _replay_turns(scope, policy, replay, fragment, target, frozen, groups, cards, laws, labels, kind, source_window):
    frames = replay['frames']
    intents = policy['turns']
    if set(intents) != {frame['event'] for frame in frames}:
        raise ValueError('Register explicit speaker permissions for every replay beat')
    nodes = {node['id']: node['passage'] for node in fragment['graph']['nodes']}
    passages = {item['id']: {key: item[key] for key in ('start', 'end', 'sha256')}
                for item in fragment['graph']['passages']}
    root = frames[0]['state']['root']
    before = _actors(frames[0]['state'], groups, root, labels)
    previous = frames[0]['state']
    known = {actor['form'] for actor in before.values()}
    start, end, source_lock, historical_anchor = source_window or (target['start'], target['end'], frozen, None)
    turns = []
    for frame in frames:
        ident, after = frame['event'], _actors(frame['state'], groups, root, labels)
        voice = intents[ident]
        fragments._object(voice, ('phase', 'stage', 'speakers', 'listeners', 'required'))
        phase, stage = voice['phase'], voice['stage']
        if phase not in ('before', 'after'):
            raise ValueError('A dialogue turn must say when in the transition it is heard')
        source = passages.get(nodes.get(frame['node']))
        editable = source and start <= source['start'] < source['end'] <= end
        if bool(editable) != bool(stage):
            raise ValueError(f'{ident} needs a stage direction on its writable passage')
        if stage and ('\n' in fragments._label(stage, 280) or '\r' in stage or ':' in stage):
            raise ValueError('Use one plain stage direction line per beat')
        active_state = previous if phase == 'before' else frame['state']
        revealed = known if phase == 'before' else known | {actor['form'] for actor in after.values()}
        turn = _turn(scope, ident, frame['operation'], stage, before, after, phase,
                     voice['speakers'], voice['listeners'], voice['required'], active_state['knowledge'],
                     revealed, cards, groups, laws, labels, kind)
        turn['passage'] = (source | {key:historical_anchor[key] for key in ('timeline_revision', 'source_sha256')}
                           if source and historical_anchor else source)
        turn['frozen'] = bool(source and source['start'] <= source_lock['start'] < source_lock['end'] <= source['end'])
        for effect in frame['effects']:
            release = effect.get('release')
            for emitter in release.get('emitters', ()) if release else ():
                actor = after[emitter]
                rule = policy['scents'].get(actor['form'])
                if rule and rule['mind'] == actor['mind']:
                    if check_laws(rule['scent'], laws):
                        raise ValueError('A local character scent conflicts with a configured world law')
                    turn['rules'].append({'form': actor['form'], 'mind': actor['mind'],
                                          'label': actor['label'], **rule})
        turns.append(turn)
        known.update(actor['form'] for actor in after.values())
        before, previous = after, frame['state']
    return turns, known


def _replay_basis(connection, scope, policy):
    record, stamp = scene_bridges._read(connection, scope['episode'], policy['bridge'])
    if record['scope'] != scope or stamp != policy['bridge_sha256']:
        raise ValueError('The scene plan belongs to another saved bridge or branch')
    replay, replay_stamp = scene_branches._replay(connection, scope, record['replay'])
    if replay_stamp != record['replay_sha256'] or replay['timeline_cutoff'] != record['cutoff']:
        raise ValueError('The scene plan’s replay version changed')
    return record, replay, replay_stamp


def preparation_sockets(connection, scope):
    policy = _policy(connection, scope['episode'])
    if policy is None:
        return None
    record, replay, stamp = _replay_basis(connection, scope, policy)
    root = replay['frames'][0]['state']['root']
    return {'replay': replay['id'], 'replay_sha256': stamp, 'graph_sha256': replay['graph_sha256'],
            'fragment': replay['fragment'], 'fragment_revision': replay['fragment_revision'],
            'beats': {frame['event']: frame['node'] for frame in replay['frames'] if frame['node']},
            'forms': [{'character': root, 'form': card['form'], 'mind': card['mind'], 'label': card['label']}
                      for card in record['cast']]}


def _compile(store, connection, scope, head, policy):
    from . import scene_plan_inputs
    record, replay, replay_stamp = _replay_basis(connection, scope, policy)
    fragment, target, frozen, fork, join, script_sha, notebook, source_window = _source(
        store, connection, scope, head, record, replay)
    law = WorldLawStore.in_connection(connection, project_id=scope['project'], universe_id=scope['universe'])
    visible = [event for event in store._resolve_rows(connection, scope['episode'], record['cutoff'])
               if source_timing.visible_to(event, None)]
    if (law['revision'] != replay['law_revision'] or
            fragments.digest(fragments.encoded(visible)) != replay['history_sha256']):
        raise ValueError('The laws or visible history changed. Replay the scene again.')
    laws = active_laws(law['laws'], branch_points(connection, scope['episode'], record['cutoff']), scope['branch'])
    kind = verify_scope(connection, project_id=scope['project'], universe_id=scope['universe'])['kind']
    groups = scene_bridges._junctions(store, connection, scope['episode'])
    cards = {card['form']: card for card in record['cast']}
    labels = _LABELS | {ident: card['label'] for ident, card in cards.items()}
    if any(form not in cards or rule['mind'] != cards[form]['mind'] or rule['trigger'] != 'personal_gas_release'
           for form, rule in policy['scents'].items()):
        raise ValueError('A local rule must belong to its registered emitting form and Mind')
    inputs = scene_plan_inputs.read(connection, scope, replay_stamp)
    if inputs:
        cards.update(scene_plan_inputs.mind_cards(inputs))
    turns, known = _replay_turns(scope, policy, replay, fragment, target, frozen, groups, cards, laws, labels, kind,
                                source_window)
    solved = scene_bridge.compile_bridge(record['program'])
    raw, _ = scene_bridges._turns(record, replay, solved, groups)
    root = replay['frames'][0]['state']['root']
    last = replay['frames'][-1]['state']
    before = turns[-1]['after']
    departure = []
    for row, frame in zip(raw[len(turns):], solved['frames']):
        # The departure program carries the same split bodies and their locations.
        active = last | {'actors': row['actors']}
        after = _actors(active, groups, root, labels)
        by_label = {data['label']: actor for actor, data in after.items()}
        voices = [by_label[label] for label in row['speakers']]
        departure.append(_turn(scope, row['beat'], 'bridge', frame['stage'], before, after, 'after',
                               voices, voices, (), last['knowledge'], known, cards, groups, laws, labels, kind))
        before = after
    scenes = [{'id': 'cutaway', 'heading': policy['heading'], 'location': None,
               'beats': [turn['id'] for turn in turns if turn['stage']], 'required_speakers': []}]
    scenes.extend({**scene, 'beats': [beat['id'] for beat in scene['beats']]} for scene in solved['scenes'])
    plan = {'version': 1, 'scope': scope, 'timeline_revision': head, 'notebook_revision': notebook,
            'source_sha256': script_sha, 'target': target, 'fork': fork, 'frozen': frozen,
            'rejoin': {'start': join, 'sha256': record['retained_sha256'], 'scene': 'Roger'},
            'cutoff': record['cutoff'], 'replay': replay['id'], 'replay_sha256': replay_stamp,
            'source_graph_sha256': replay['graph_sha256'], 'law_revision': law['revision'],
            'turns': [*turns, *departure], 'scenes': scenes, 'exit': solved['exit'],
            'form_labels': labels}
    if inputs:
        scene_plan_inputs.populate(store, connection, scope, plan, inputs, fragment, replay,
                                   solved, record['cast'], policy['scents'])
    plan['id'] = fragments._id('scene-plan', plan)
    return plan


def _policy(connection, episode):
    if not fragments._has(connection, TABLE):
        return None
    row = connection.execute('SELECT * FROM scene_writing_plans WHERE episode=?',
                             (episode,)).fetchone()
    return scene_branches._unpack(row) if row else None


def current(store, connection, scope, head):
    policy = _policy(connection, scope['episode'])
    if policy:
        return _compile(store, connection, scope, head, policy)
    from .prepared_scene_plan import current as prepared_plan
    return prepared_plan(store, connection, scope, head)


def open_plan(store, request):
    with store._connect() as connection:
        connection.execute('BEGIN')
        scope, head = fragments.SceneFragmentStore._scope(connection, request)
        fragments.SceneFragmentStore._current(request, head)
        plan = current(store, connection, scope, head)
        if plan is None:
            raise ValueError('This episode has no registered scene writing plan')
        return {'plan': plan, 'provider_calls': 0}


def project(store, connection, identity, episode, branch, head, beat, start, end, viewpoint, binding):
    scope = scene_bridges._scope(identity, episode, branch)
    plan = current(store, connection, scope, head)
    fragments._object(binding, ('scene_plan',), ('polish_draft', 'guidance'))
    if binding.get('guidance') not in (None, 'plain'):
        raise ValueError('Choose the full scene guidance or the plain comparison')
    if not plan or binding['scene_plan'] != plan['id']:
        raise ValueError('The saved scene plan changed. Reopen the scene to use its current turns.')
    if (beat, start, end, viewpoint) != (plan['cutoff'], plan['target']['start'], plan['target']['end'], None):
        raise ValueError('Select the full planned passage between the frozen line and retained rejoin')
    # No single active form can represent an entire transformation scene.
    forms = sorted({actor['form'] for turn in plan['turns'] for actor in turn['after'].values()})
    continuation = {'kind': 'scene-plan', 'binding': binding, 'plan': plan, 'limits': LIMITS,
                    'active_forms': {}, 'known_forms': forms, 'cast': plan['form_labels'], 'scents': {}}
    if 'polish_draft' in binding:
        continuation['polish'] = _polish_source(connection, plan, binding['polish_draft'])
    return continuation


def _polish_source(connection, plan, ident):
    from .notebook import DraftStore
    scope = plan['scope']
    rough = DraftStore.read_saved(connection, scope['episode'], scope['branch'], checked_id(ident, 'Rough draft'))
    prior = rough.get('writing_context', {}).get('continuation') or {}
    target = plan['target']
    if (rough['status'] != 'PROPOSED' or prior.get('kind') != 'scene-plan' or prior.get('polish')
            or prior.get('plan') != plan or rough['source_sha256'] != target['sha256']
            or rough['notebook_revision'] != plan['notebook_revision']
            or not rough.get('text') or _validate_slots(plan, rough['text'])):
        raise ValueError('Choose a validated rough draft for this exact saved Turn Ledger')
    return {'draft': ident, 'sha256': fragments.digest(rough['text']), 'text': rough['text']}


def guard(store, connection, packet):
    scope = scene_bridges._scope({'project_id': packet.context.project_id, 'universe_id': packet.context.universe_id,
                                 'scope_revision': packet.context.scope_revision}, packet.episode, packet.branch)
    plan = current(store, connection, scope, packet.revision)
    if plan != packet.continuation['plan']:
        raise ValueError('The scene boundaries, turn permissions or Mind guidance changed')
    if (rough := packet.continuation.get('polish')) and _polish_source(connection, plan, rough['draft']) != rough:
        raise ValueError('The saved rough draft changed during polish')


def _scene_lines(plan):
    by_id = {turn['id']: turn for turn in plan['turns']}
    for scene in plan['scenes']:
        yield scene, [(by_id[ident]['stage'], by_id[ident]) for ident in scene['beats']]


def writer_context(continuation, media_guidance=(), *, craft_cards=()):
    """Render only the dialogue guidance applicable to each permitted turn."""
    from .media_overrides import cue_lines
    plan = continuation['plan']
    use_inputs = continuation.get('binding', {}).get('guidance') != 'plain'
    craft_by_beat = {card['beat']: card['turn']['direction'] for card in craft_cards}
    output = ['\nSAVED SCENE PLAN',
              'Return the scene headings, required stage facts and location lines in the given order, exactly as written. '
              'After a required stage fact, write fresh physical actions or reactions as Action Name: action. '
              'Start every physical action line with the literal word Action. For example, Action Ada: She steadies her hand. '
              'Use only the listed action names. An action can respond to the event without repeating or adding a transition, release or impact. '
              'Use at least one crafted action in each scene. When three Minds share a required exchange, give them distinct reactions. '
              'Write dialogue as Name: dialogue using only eligible speakers. Use each required speaker where indicated. '
              'Each scene-wide required speaker must speak an actual line in that scene, even if they already have an action. '
              'Silent turns may carry actions. '
              + ('Use Mind tactics as conditional guidance for that speaker only. ' if use_inputs else '')
              + 'Earlier turns cannot use facts learned later. Stop at the end of the last beat. Return scene text only.']
    for scene, lines in _scene_lines(plan):
        output.append(scene['heading'])
        if scene['location']:
            output.append(scene['location'])
        if scene['required_speakers']:
            output.append('Required somewhere in this scene: ' + ', '.join(scene['required_speakers']))
        for line, turn in lines:
            output.append(f'\n{line}')
            if turn.get('structure', {}).get('kind') == 'cutaway':
                shape = {'invert_merge': 'Use the reverse of a convergence for the three-way split.',
                         'reuse_merge': 'Use a three-to-one convergence for the reunion.'}
                output.append('[Cutaway shape only · ' + shape[turn['structure']['operator']] + ']')
            if not turn['speakers']:
                output.append('[No dialogue]')
            cast = turn[turn['phase']]
            output.append('[Action names · ' + ', '.join(actor['label'] for actor in cast.values()) + ']')
            for speaker in turn['speakers']:
                listeners = ', '.join(cast[actor]['label'] for actor in speaker['listeners'])
                content = speaker['label'] + (' (required)' if speaker['required'] else '')
                if listeners:
                    content += ' to ' + listeners
                if speaker['known']:
                    content += ' | witnessed: ' + ', '.join(speaker['known'])
                behavior = (speaker['mind'] or {}).get('guidance', ()) if use_inputs else ()
                if behavior:
                    content += ' | ' + ' | '.join(behavior)
                output.append('[' + content + ']')
            if turn['speakers'] and turn['relationships']:
                voices = {(entry['character'], entry['form']) for entry in turn['speakers']}
                couples = set()
                for edge in turn['relationships']:
                    if (edge['from']['character'], edge['from']['form']) in voices:
                        names = [character_relationships.form_name(edge[side], plan['form_labels']) for side in ('from', 'to')]
                        couples.add(' and '.join(sorted(names)))
                        if 'override' in edge:
                            output.append(character_relationships.override_line(edge, plan['form_labels']))
                if couples:
                    output.append('[Spouses in this beat: ' + ', '.join(sorted(couples)) + ']')
            for rule in turn['rules']:
                output.append(f'[{rule["label"]}’s release scent is {rule["scent"]}.]')
            if use_inputs:
                for cue in turn.get('timing', ()):
                    output.append(f'[Timing and reaction only · {cue["direction"]}]')
            if direction := craft_by_beat.get(turn['id']):
                output.append(f'[Book craft · {direction}]')
            for cue in media_guidance:
                if cue['target'].get('beat') == turn['id']:
                    output.extend(cue_lines([cue]))
    return '\n'.join(output) + '\n'


def _validate_slots(plan, text, layout=None):
    lines = iter((i, line.rstrip('\r\n')) for i, line in enumerate(text.splitlines(keepends=True)) if line.strip())
    index, line = next(lines, (-1, None))
    for scene, stages in _scene_lines(plan):
        if line != scene['heading']:
            return ['Keep every planned scene heading and its position']
        if layout is not None:
            layout[index] = ('scene-heading', None, None)
        index, line = next(lines, (-1, None))
        if scene['location']:
            if line != scene['location']:
                return ['Keep the planned scene location']
            if layout is not None:
                layout[index] = ('scene-heading', None, None)
            index, line = next(lines, (-1, None))
        spoken = set()
        for stage, turn in stages:
            if line != stage:
                return [f'Keep the planned stage direction at {turn["id"]}']
            if layout is not None:
                layout[index] = ('stage-direction', None, None)
            index, line = next(lines, (-1, None))
            allowed = {entry['label']: entry for entry in turn['speakers']}
            active = {entry['label']: entry for entry in turn.get(turn.get('phase', 'after'), {}).values()}
            said = set()
            while line is not None and (match := scene_bridges._SPEAKER.fullmatch(line)):
                name, dialogue = match.groups()
                if name.startswith('Action '):
                    actor = active.get(name.removeprefix('Action '))
                    if actor is None:
                        return [f'{name} is unavailable at {turn["id"]}']
                    if len(dialogue) > 300 or _NEW_EVENT.search(dialogue) or _mentions_unavailable(
                            dialogue, {entry['form'] for entry in active.values()}, plan['form_labels']):
                        return [f'Action adds a new event, inactive form or overlong line at {turn["id"]}']
                    if layout is not None:
                        layout[index] = ('action', actor['character'], actor['form'])
                    index, line = next(lines, (-1, None))
                    continue
                if name not in allowed:
                    return [f'{name} cannot speak at {turn["id"]}']
                if _mentions_unavailable(dialogue, turn['revealed_forms'], plan['form_labels']):
                    return [f'Dialogue reveals an unavailable form at {turn["id"]}']
                if len(dialogue) > 300:
                    return [f'Dialogue exceeds the turn budget at {turn["id"]}']
                said.add(name)
                if layout is not None:
                    voice = allowed[name]
                    layout[index] = ('character', voice['character'], voice['form'])
                index, line = next(lines, (-1, None))
            if any(speaker['required'] and name not in said for name, speaker in allowed.items()):
                return [f'A required speaker is missing at {turn["id"]}']
            spoken.update(said)
        if not set(scene['required_speakers']) <= spoken:
            return [f'A required speaker is missing from {scene["id"]}']
    return [] if line is None else ['End the proposal before the retained Roger scene']


def validate_output(continuation, text, *, layout=None):
    plan = continuation['plan']
    rough = continuation.get('polish')
    candidate = {} if rough and layout is None else layout
    issues = _validate_slots(plan, text, candidate)
    if rough and not issues:
        original = {}
        if _validate_slots(plan, rough['text'], original) or list(original.values()) != list(candidate.values()):
            return ['Polish must keep every action and dialogue line with its original actor and beat']
    return issues


def proposal_lines(continuation, text):
    layout = {}
    if issues := validate_output(continuation, text, layout=layout):
        raise ValueError(issues[0])
    lines = []
    for index, text_line in enumerate(text.splitlines(keepends=True)):
        if index not in layout and lines:
            lines[-1]['text'] += text_line
            continue
        kind, speaker, form = layout.get(index, ('narrator', None, None))
        if kind == 'action':
            kind, speaker, form = 'stage-direction', None, None
        lines.append({'kind':kind, 'speaker':speaker, 'form':form, 'text':text_line})
    return lines
