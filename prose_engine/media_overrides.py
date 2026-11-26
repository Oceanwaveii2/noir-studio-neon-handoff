"""Compile saved media into bounded writing guidance for an exact graph destination."""
from __future__ import annotations

import json
import re
import unicodedata

from story_graph import scene_fragments as f
from story_graph.scene_override import _unpack
from story_graph.universe_scope import checked_id
from story_graph.world_laws import check_laws
from . import media_graph, media_signal


TABLE = 'graph_media_overrides'
COMMANDS = frozenset('scene.media.override.' + part for part in ('preview', 'apply', 'clear'))
USES = ('timing', 'performance', 'appearance')
MAX_CUES = 4
PAUSE = re.compile(r'(?:the |a )?(longest )?(?:pause|quiet interval|gap)(?: from (?:this|the) clip)?')
PERFORMANCE = re.compile(r"(?:the )?(?:(.+?)'s )?(delivery|performance|voice|sound)")
APPEARANCE = re.compile(r'(?:the )?(?:appearance|dress|clothing|costume|outfit)')
DIALOGUE = re.compile(r'(?:(.+?) )?(?:replies to|responds to|speaks to|answers|replies|speaks)(?: (.+))?')
ATTRIBUTION = re.compile(r'(speaker|emitter): ([^.!?\n]{1,64})\. (?:presentation: (woman|man)\. )?observation: (.+)', re.I)


class Unresolved(ValueError):
    """The source evidence or one of the roles cannot support this direction."""


def _normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().replace('’', "'")
                    .replace('_', ' ').replace('-', ' ').split())


def _intent(text):
    text = _normalized(f._label(text, 260)).rstrip('.!?')
    start = re.match(r'^(?:use|borrow|match) (.+)$', text)
    if not start:
        raise Unresolved('Start with Use, Borrow, or Match and name what to transfer.')
    parts = re.split(r' (before|after) ', start[1], maxsplit=1)
    aspect, _, actor = parts[0].partition(' for ')
    listener = ''
    position = None
    if len(parts) > 1:
        position, turn = parts[1:]
        match = DIALOGUE.fullmatch(turn)
        if match:
            speaker, listener = match.groups()
            if speaker and speaker not in ('she', 'he', 'they'):
                if actor and speaker != actor:
                    raise Unresolved('The direction names two different recipients for this cue.')
                actor = speaker
            elif speaker and not actor:
                raise Unresolved('Name the speaker receiving the cue.')
        elif turn != 'the reply':
            raise Unresolved('Name the current reply and listener, or use before the reply.')
    if match := PAUSE.fullmatch(aspect):
        return {'use': 'timing', 'longest': bool(match[1]), 'actor': actor, 'listener': listener,
                'position': position or 'before'}
    if position:
        raise Unresolved('Before and after are supported for pause directions.')
    if APPEARANCE.fullmatch(aspect):
        return {'use': 'appearance', 'actor': actor, 'listener': ''}
    if match := PERFORMANCE.fullmatch(aspect):
        role = 'emitter' if match[2] == 'sound' else 'speaker'
        return {'use': 'performance', 'actor': actor, 'listener': '', 'role': role, 'subject': match[1]}
    raise Unresolved('Choose a pause, an observed performance, or an appearance detail.')


def _source_policy(c, scope, digest, purpose):
    if f._has(c, 'scene_fragment_evidence'):
        for row in c.execute('SELECT payload FROM scene_fragment_evidence'):
            evidence = json.loads(row['payload'])
            if evidence['sha256'] == digest and evidence['use'] == 'preview':
                raise Unresolved('This scene reference is available for preview only.')
    # Re-importing the same bytes must preserve the saved library's restrictions.
    if not f._has(c, 'scene_mind_support'):
        return
    for row in c.execute('SELECT payload,sha256 FROM scene_mind_support'):
        body = _unpack(row)
        if any(body['scope'][field] != scope[field] for field in ('project', 'universe')):
            continue
        matches = [item for item in body['library']['items'] if item['content_sha256'] == digest]
        if matches and (purpose != 'timing' or not all(item['writing_eligible'] for item in matches)):
            raise Unresolved('This indexed source is restricted to its saved library purpose.')


def _evidence(path, segment, intent):
    use = intent['use']
    selector = segment['selector']
    if use == 'timing':
        try:
            spans = media_signal.interior_pauses(path, selector['start'], selector['end'])
        except ValueError as exc:
            raise Unresolved(str(exc)) from exc
        if not spans:
            raise Unresolved('No bounded quiet interval was measured inside the selected range.')
        if len(spans) > 1 and (not intent['longest'] or spans[0]['duration_ms'] == spans[1]['duration_ms']):
            raise Unresolved('Several quiet intervals fit. Narrow the range or ask for the longest pause.')
        timing = {'method': media_signal.METHOD, 'track': 'audio-0', 'quiet_interval': spans[0]}
        if note := segment.get('observation'):
            timing['observation'] = note
        return timing
    note = segment['observation']
    if use == 'appearance':
        if not note:
            raise Unresolved('Save an observation of the visible appearance in this image region.')
        return {'method': 'author-image-observation', 'observation': note}
    match = ATTRIBUTION.fullmatch(note)
    if not match or match[1].casefold() != intent['role']:
        raise Unresolved(f'The source {intent["role"]} is unconfirmed. A filename or reaction cannot identify them.')
    subject = intent['subject']
    if subject in ('woman', 'man'):
        if subject != _normalized(match[3] or ''):
            raise Unresolved('The observed source role does not support that presentation criterion.')
    elif subject and subject not in (intent['role'], _normalized(match[2])):
        raise Unresolved('The attributed source role belongs to a different participant.')
    return {'method': 'author-attributed-observation', 'role': intent['role'], 'subject': match[2],
            'presentation': match[3], 'observation': match[4]}


def _bridge_beat(bridge, head, beat):
    for scene in bridge['program']['scenes']:
        for action in scene['beats']:
            if action['id'] == beat:
                row = next(turn for turn in bridge['turns'] if turn['beat'] == beat)
                return {'kind': 'planned', 'bridge': bridge['binding'], 'timeline_revision': head,
                        'scene': scene['id'], 'beat': beat, 'stage_sha256': f.digest(action['stage'])}, row
    raise Unresolved('Choose an action in the saved bridge plan.')


def _exact_beat(store, c, scope, head, request, pin=None):
    from .story_timeline import open_track
    f.SceneFragmentStore._current(request, head)
    beat = checked_id(request.get('beat'), 'Destination beat')
    fragment = request.get('fragment')
    if not fragment and pin and pin.get('node') and not pin.get('replay'):
        fragment = pin['scene']
    view = open_track(store, scope | {'timeline_revision': head} | ({'fragment': fragment} if fragment else {}),
                      connection=c, include_media=False)
    matching = [(scene, row) for scene in view['scenes'] for row in scene['beats'] if row['id'] == beat]
    if len(matching) != 1 or matching[0][1]['passage']['sha256'] != f._sha(request.get('passage_sha256')):
        raise Unresolved('The exact saved passage is unavailable at this destination.')
    scene, row = matching[0]
    if row['kind'] in ('frozen', 'retained'):
        raise Unresolved('Choose a beat inside the editable story, before the retained rejoin.')
    passage = {key: value for key, value in row['passage'].items() if key != 'text'}
    target = {'kind': 'beat', 'timeline_revision': head, 'source_sha256': view['source_sha256'],
              'scene': scene['id'], 'beat': beat, 'passage': passage,
              'node': (row.get('destination') or {}).get('node'), 'replay': row.get('replay')}
    peers = [other for scene in view['scenes'] for other in scene['beats'] if other is not row]
    if any(other['passage']['start'] < passage['end'] and passage['start'] < other['passage']['end'] for other in peers):
        raise Unresolved('Multiple graph beats share this passage. Choose a uniquely anchored beat.')
    return target, row, scene['passages_sha256'], view.get('fragment')


def _destination(store, c, scope, head, pin, request):
    from . import scene_bridges
    supplied = request.get('destination')
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError('Choose a saved beat as the direction destination')
        f.SceneFragmentStore._current(supplied, head)
    if supplied and 'bridge' in supplied:
        if pin['kind'] != 'form':
            raise Unresolved('Choose a form reference to direct an exact planned bridge turn.')
        record, stamp = scene_bridges._read(c, scope['episode'], checked_id(supplied['bridge'], 'Bridge ID'))
        binding = {'bridge': record['id'], 'sha256': stamp}
        slot = record['slot']
        identity = {'project_id': scope['project'], 'universe_id': scope['universe'],
                    'scope_revision': scope['scope_revision']}
        bridge = scene_bridges.project(store, c, identity, scope['episode'], scope['branch'], head, record['cutoff'],
                                      slot['start'], slot['end'], None, binding)
        return (*_bridge_beat(bridge, head, checked_id(supplied.get('beat'), 'Destination beat')), None)
    if pin['kind'] != 'beat' and not supplied:
        raise Unresolved('Choose an exact saved beat for this scene or form reference.')
    fields = supplied or {'timeline_revision': pin['timeline_revision'], 'beat': pin['beat'],
                          'passage_sha256': pin['passage']['sha256']}
    target, row, scene_sha, fragment = _exact_beat(store, c, scope, head, fields, pin)
    if pin['kind'] == 'beat' and target != media_graph._target_key(pin):
        raise Unresolved('A beat reference can only direct its attached passage.')
    if pin['kind'] == 'scene' and any(pin[key] != target[key] for key in ('scene', 'timeline_revision', 'source_sha256')):
        raise Unresolved('The beat is outside the attached scene.')
    if pin['kind'] == 'scene' and pin['scene_sha256'] != scene_sha:
        raise Unresolved('The saved scene passages have changed.')
    return target, row, fragment


def _roles(store, c, scope, row):
    from .scene_bridges import _junctions
    groups = _junctions(store, c, scope['episode'])
    forms = {form.id: (owner, form.label) for owner, group in groups.items() for form in group.forms}
    roles = []
    for ident, active in row.get('actors', {}).items():
        form = active['form']
        owner, label = forms.get(form, (ident, form.replace('-', ' ').replace('_', ' ').title()))
        # The bridge compiles these aliases as its actual dialogue ports.
        if form == 'nurse_pamela_franny_anderson':
            label = 'Nurse Franny'
        names = {_normalized(x) for x in (owner, ident, form, label, forms.get(form, ('', label))[1])}
        roles.append((names, {'actor': ident, 'character': owner, 'form': form, 'label': label,
                             'location': active['location']}))
    return roles


def _recipient(roles, alias, name):
    matches = [value for names, value in roles if alias in names]
    if len(matches) != 1:
        raise Unresolved(f'{name} does not resolve to one active role at this beat.')
    return matches[0]


def _cast(store, c, scope, pin, row, intent):
    roles = _roles(store, c, scope, row) if (intent['actor'] or intent['listener'] or pin['kind'] == 'form') else []
    actor = _recipient(roles, intent['actor'], 'The recipient') if intent['actor'] else None
    if pin['kind'] == 'form':
        form = [role for _, role in roles if (role['character'], role['form']) == (pin['character'], pin['form'])]
        if len(form) != 1 or (actor and actor != form[0]):
            raise Unresolved('This exact form is not active as the recipient at this beat.')
        actor = form[0]
    if not actor and intent['use'] != 'timing':
        raise Unresolved('Name an active recipient for this observation.')
    listener = _recipient(roles, intent['listener'], 'The listener') if intent['listener'] else None
    if listener and (not actor or listener == actor or listener['location'] != actor['location']):
        raise Unresolved('The graph does not establish this speaker and listener together at this beat.')
    if actor and 'speakers' in row and intent['use'] != 'appearance' and actor['label'] not in row['speakers']:
        raise Unresolved('This turn does not allow dialogue for that actor.')
    return {'actor': actor, 'listener': listener}


def _lookup(c, scope, ident):
    if not f._has(c, 'graph_media_pins'):
        raise ValueError('Choose media already attached to the graph')
    row = c.execute('SELECT scope,payload FROM graph_media_pins WHERE id=?',
                    (checked_id(ident, 'Graph media pin'),)).fetchone()
    if not row:
        raise ValueError('Choose media already attached to the graph')
    pin = json.loads(row['payload'])
    if row['scope'] != media_graph._pin_scope(scope, pin['target']):
        raise ValueError('This media pin belongs to another episode or branch')
    return pin


def _plan(store, c, scope, head, request):
    pin = _lookup(c, scope, request.get('pin'))
    linked = media_graph._link(c, scope, pin)
    if not linked:
        raise Unresolved('This link has no recoverable source segment.')
    segment = linked['segment']
    asset, _ = media_graph._asset(c, scope, segment['asset'])
    intent = _intent(request.get('direction'))
    if segment['purpose'] != intent['use']:
        raise Unresolved('Use a segment saved with this purpose. A reference or audience cutaway stays separate.')
    target, row, fragment = _destination(store, c, scope, head, pin['target'], request)
    cast = _cast(store, c, scope, pin['target'], row, intent)
    _source_policy(c, scope, asset['sha256'], intent['use'])
    try:
        path = media_graph._file(store, asset)
    except (OSError, ValueError) as exc:
        raise Unresolved('The original media is missing or its content has changed.') from exc
    basis = {'scope': scope, 'target': target, 'fragment': fragment, 'pin': pin['id'], 'segment': segment['id'],
             'asset': asset['id'], 'source_sha256': asset['sha256'], 'selector': segment['selector'],
             'use': intent['use'], 'position': intent.get('position'), **cast}
    slot = f._id('media-slot', scope, pin['id'], target)
    return slot, basis, path, segment, intent


def _active(c, scope, slot=None):
    if not f._has(c, TABLE):
        return []
    rows = c.execute('SELECT payload FROM graph_media_overrides WHERE scope=? AND enabled=1 '
                     'AND (? IS NULL OR slot=?) ORDER BY id', (f.encoded(scope), slot, slot))
    return [json.loads(row['payload']) for row in rows]


def _previous(c, scope, slot):
    rows = _active(c, scope, slot)
    return rows[0]['id'] if rows else None


def execute(store, action, request):
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE' if action.endswith('.clear') else 'BEGIN')
        scope, head = f.SceneFragmentStore._scope(c, request)
        if action.endswith('.clear'):
            ident = checked_id(request.get('override'), 'Media direction')
            if f._has(c, TABLE):
                c.execute('UPDATE graph_media_overrides SET enabled=0 WHERE scope=? AND id=?', (f.encoded(scope), ident))
            return {'status': 'CLEARED', 'provider_calls': 0}
        try:
            slot, basis, path, segment, intent = _plan(store, c, scope, head, request)
            previous = _previous(c, scope, slot)
        except Unresolved as exc:
            return {'status': 'UNRESOLVED', 'reason': str(exc), 'provider_calls': 0}
    try:
        evidence = _evidence(path, segment, intent)
    except Unresolved as exc:
        return {'status': 'UNRESOLVED', 'reason': str(exc), 'provider_calls': 0}
    body = basis | {'direction': request['direction'].strip(), 'evidence': evidence}
    receipt = body | {'id': f._id('media-override', body)}
    if action.endswith('.preview'):
        return {'status': 'READY', 'override': receipt, 'previous': previous, 'provider_calls': 0}
    if request.get('plan') != receipt['id'] or 'previous' not in request:
        raise ValueError('Use the exact media direction preview')
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        current_scope, current_head = f.SceneFragmentStore._scope(c, request)
        if (current_scope, current_head) != (scope, head) or _plan(store, c, scope, head, request)[1] != basis:
            raise ValueError('The direction source or destination changed. Preview it again.')
        current = _previous(c, scope, slot)
        if current == receipt['id']:
            return {'status': 'SAVED', 'override': receipt, 'provider_calls': 0}
        if current != request['previous']:
            raise ValueError('This media direction changed. Preview it again.')
        c.execute('''CREATE TABLE IF NOT EXISTS graph_media_overrides (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, slot TEXT NOT NULL, payload TEXT NOT NULL, enabled INTEGER NOT NULL)''')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS graph_media_active_override ON graph_media_overrides(scope,slot) WHERE enabled=1')
        c.execute('UPDATE graph_media_overrides SET enabled=0 WHERE scope=? AND slot=? AND enabled=1',
                  (f.encoded(scope), slot))
        c.execute('INSERT INTO graph_media_overrides VALUES (?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET enabled=1',
                  (receipt['id'], f.encoded(scope), slot, f.encoded(receipt)))
    return {'status': 'SAVED', 'override': receipt, 'provider_calls': 0}


def for_pins(c, scope, pins):
    selected = {pin['id'] for pin in pins}
    return [item for item in _active(c, scope) if item['pin'] in selected]


def _in_range(store, c, scope, head, start, end, item, bridge):
    target = item['target']
    if target['timeline_revision'] != head:
        return None
    if target['kind'] == 'planned':
        if not bridge or bridge.get('kind') != 'scene-bridge' or bridge['binding'] != target['bridge']:
            return None
        verified, row = _bridge_beat(bridge, head, target['beat'])
    else:
        if (bridge and bridge.get('kind') == 'scene-bridge') or not target['passage']['start'] <= start < end <= target['passage']['end']:
            return None
        request = {'beat': target['beat'], 'timeline_revision': head, 'passage_sha256': target['passage']['sha256'],
                   'fragment': item['fragment']}
        verified, row, _, _ = _exact_beat(store, c, scope, head, request)
    return row if verified == target else None


def project(store, c, scope, head, start, end, viewpoint, forms, scene, bridge, hidden, laws):
    active = {(owner, form['id']) for owner, group in forms.items() for form in group['forms']
              if form['status'] == 'active'}
    if scene:
        active.update((scene['root'], actor['form_id']) for actor in scene['active_cast'])
    selected = []
    for item in _active(c, scope):
        actor = item['actor']
        if viewpoint and actor and actor['character'] != viewpoint:
            continue
        try:
            row = _in_range(store, c, scope, head, start, end, item, bridge)
            if row is None:
                continue
            if actor or item['listener']:
                roles = [role for _, role in _roles(store, c, scope, row)]
                recipients = [role for role in (actor, item['listener']) if role]
                if any(role not in roles for role in recipients):
                    continue
                if item['target']['kind'] == 'beat' and any((role['character'], role['form']) not in active for role in recipients):
                    continue
            if actor and item['use'] != 'appearance' and 'speakers' in row and actor['label'] not in row['speakers']:
                continue
            pin = _lookup(c, scope, item['pin'])
            linked = media_graph._link(c, scope, pin)
            if not linked or linked['segment']['id'] != item['segment'] or linked['asset']['sha256'] != item['source_sha256']:
                continue
            _source_policy(c, scope, item['source_sha256'], item['use'])
            media_graph.original_in_scope(store, c, scope, item['asset'])
        except (OSError, ValueError):
            continue
        note = item['evidence'].get('observation', '')
        if any(phrase.strip().casefold() in note.casefold() for phrase in hidden
               if isinstance(phrase, str) and len(phrase.strip()) >= 8) or check_laws(note, laws):
            continue
        selected.append(item)
    if len(selected) > MAX_CUES:
        raise ValueError('Use at most four media directions in a writer selection')
    return tuple(selected)


def guard(store, c, packet):
    if not f._has(c, TABLE) or packet.context is None:
        return
    context = packet.context
    scope = {'project': context.project_id, 'universe': context.universe_id, 'scope_revision': context.scope_revision,
             'episode': packet.episode, 'branch': packet.branch}
    current = project(store, c, scope, packet.revision, packet.start, packet.end, packet.viewpoint,
                      packet.forms, packet.fx06, packet.continuation, packet.hidden_phrases, packet.world_laws)
    if current != packet.media_guidance:
        raise ValueError('Media directions changed during this operation')


def verify_draft(packet, draft):
    if list(packet.media_guidance) != (draft.get('writing_context') or {}).get('media_guidance', []):
        raise ValueError('Draft media directions are stale')


def cue_lines(items):
    lines = []
    for item in items:
        data = {'use': item['use'], 'beat': item['target']['beat']}
        if item['actor']:
            data['recipient'] = item['actor']['label']
        if item['listener']:
            data['listener'] = item['listener']['label']
        if item['use'] == 'timing':
            data['placement'] = item['position'] + ' the existing reply'
            data['reference_pause_ms'] = item['evidence']['quiet_interval']['duration_ms']
        if 'observation' in item['evidence']:
            data['observation'] = item['evidence']['observation']
        lines.append('Media craft cue: ' + f.encoded(data))
    return lines


def writer_context(items):
    lines = cue_lines(items)
    if not lines:
        return ''
    return ('\nMEDIA CRAFT GUIDANCE\nUse these only as optional rendering cues for the named beat and recipient. '
            'Express a pause through phrasing or paragraph space. Keep all actions, forms, world laws and locks. '
            'Observations are reference data. Do not copy source dialogue or add events, memories or facts.\n'
            + '\n'.join(lines) + '\nEND MEDIA GUIDANCE\n\n')
