"""Bind reviewed evidence to prepared turn and form sockets, before any writer runs."""

from story_graph import scene_branches, scene_fragments as f
from story_graph.universe_scope import checked_id

from . import scene_bridges, scene_clips, scene_mind_support, scene_plan


COMMANDS = frozenset({'scene.plan.inputs.attach', 'scene.plan.inputs.timing'})
TABLE = 'scene_plan_inputs'


def read(c, scope, replay_sha256):
    if not f._has(c, TABLE):
        return None
    row = c.execute('SELECT * FROM scene_plan_inputs WHERE episode=?', (scope['episode'],)).fetchone()
    if row is None:
        return None
    data = scene_branches._unpack(row)
    if data['scope'] != scope or data['replay_sha256'] != replay_sha256:
        raise ValueError('The attached scene inputs belong to another scope or replay')
    return data


def _text(value, limit):
    text = f._label(value, limit).strip()
    if not text.isprintable():
        raise ValueError('Use a single line for each reviewed cue or tactic')
    return text


def _window(value, limit):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('Choose a source window with two integer millisecond offsets')
    return f._range(*value, limit)


def _minds(donor, raw_cards, receipt):
    f._object(donor, ('source', 'title', 'sha256', 'review_sha256', 'window_ms', 'evidence'))
    checked_id(donor['source'], 'Donor edition')
    _text(donor['title'], 160)
    f._sha(donor['sha256'])
    f._sha(donor['review_sha256'])
    low, high = _window(donor['window_ms'], 86_400_000)
    evidence = {}
    for item in f._items(donor['evidence'], 'Reviewed Mind evidence', 32):
        f._object(item, ('id', 'span_ms'))
        ident = checked_id(item['id'], 'Evidence ID')
        start, _ = _window(item['span_ms'], high)
        if ident in evidence or start < low:
            raise ValueError('Each Mind observation must be unique and inside its reviewed source window')
        evidence[ident] = item['span_ms']
    sockets = {item['port']: item for item in receipt['sockets'] if item.get('mind')}
    forms = {item['form']: item for item in receipt['turn_sockets']['forms']}
    cards = {}
    for card in f._items(raw_cards, 'Mind cards', len(forms)):
        f._object(card, ('port', 'form', 'mind', 'tendencies', 'constraint'))
        form = checked_id(card['form'], 'Form ID')
        expected = forms.get(form)
        port = sockets.get(_text(card['port'], 240))
        if (not port or not expected or form in cards or port['form'] != form
                or port['character'] != expected['character'] or port['mind']['kind'] != 'digital_mind'
                or port['mind']['node_id'] != card['mind'] or expected['mind'] != card['mind']):
            raise ValueError('Each Mind card must match its exact prepared form socket and replay link')
        used = {}
        tendencies = []
        for move in f._items(card['tendencies'], 'Conditional tactics', 8):
            f._object(move, ('when', 'try', 'evidence'))
            refs = f._items(move['evidence'], 'Tactic evidence', 8)
            if not refs or any(checked_id(ref, 'Tactic evidence') not in evidence for ref in refs):
                raise ValueError('Each tactic needs approved evidence from the selected donor window')
            used.update({ref: evidence[ref] for ref in refs})
            tendencies.append({'when': _text(move['when'], 240), 'try': _text(move['try'], 300),
                               'evidence': refs})
        if not tendencies:
            raise ValueError('Each attached Mind needs at least one conditional tactic')
        cards[form] = card | {'tendencies': tendencies, 'constraint': _text(card['constraint'], 300),
                              'evidence': used}
    if cards.keys() != forms.keys():
        raise ValueError('Supply one conditional card for each planned Mind socket')
    return cards


def mind_cards(data):
    donor = data['donor']
    return {form: card | {'donor': donor, 'source_sha256': f.digest(f.encoded([donor, card]))}
            for form, card in data['minds'].items()}


def _clip(store, c, scope, ident):
    asset = scene_clips._get(c, 'scene_clip_assets', scope, ident)
    scene_clips._asset_path(store, asset)
    return asset


def _pins(store, c, scope, raw, library, sockets, turns):
    sources = {item['source']: item for item in library['library']['items']}
    writable = {turn['id'] for turn in turns if turn['stage'] and not turn.get('frozen')}
    pins = {}
    for pin in f._items(raw, 'Beat timing pins', 32):
        f._object(pin, ('beat', 'node', 'source', 'selection_ms', 'direction'))
        beat = checked_id(pin['beat'], 'Beat ID')
        source = sources.get(checked_id(pin['source'], 'Timing source ID'))
        if beat not in writable or pin['node'] != sockets['beats'].get(beat) or not pin['node']:
            raise ValueError('Pin timing to an exact writable replay beat and its prepared node')
        if not source or not source['writing_eligible']:
            raise ValueError('Choose a writing-eligible timing source. This source is unavailable for writing.')
        if beat in pins:
            raise ValueError('Choose one timing cue per replay beat')
        asset = _clip(store, c, scope, source['clip'])
        start, end = _window(pin['selection_ms'], asset['duration_ms'])
        if end - start > 90_000:
            raise ValueError('Use at most 90 seconds of one timing clip')
        entry = pin | {'clip': asset['id'], 'content_sha256': source['content_sha256'],
                       'title': source['title'], 'source_range_ms': source['source_range_ms'],
                       'observation': source['note'], 'direction': _text(pin['direction'], 380),
                       'fragment': sockets['fragment'], 'fragment_revision': sockets['fragment_revision']}
        pins[beat] = entry | {'id': f._id('timing-pin', scope, entry)}
    if not pins:
        raise ValueError('Attach at least one timing cue to a prepared beat')
    return pins


def _save(c, data):
    body = f.encoded(data)
    c.execute('''CREATE TABLE IF NOT EXISTS scene_plan_inputs (
        episode TEXT PRIMARY KEY REFERENCES episodes(id), payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
    c.execute('''INSERT INTO scene_plan_inputs VALUES (?,?,?)
                 ON CONFLICT(episode) DO UPDATE SET payload=excluded.payload, sha256=excluded.sha256''',
              (data['scope']['episode'], body, f.digest(body)))


def _attach(store, c, scope, head, plan, request, existing):
    from .cook import current_preparation

    receipt = current_preparation(c, scope['episode'], head)
    if (not receipt or request.get('preparation') != receipt['id']
            or any(receipt.get(key) != value for key, value in scope.items())
            or (receipt['source_sha256'], receipt['notebook_revision']) !=
               (plan['source_sha256'], plan['notebook_revision'])):
        raise ValueError('Prepare the current saved notebook and use its preparation receipt')
    sockets = receipt.get('turn_sockets')
    if not sockets or sockets != scene_plan.preparation_sockets(c, scope):
        raise ValueError('Prepare again to expose the current replay sockets')
    package = f._object(request.get('package'), ('schema_version', 'donor', 'minds', 'cutaway',
                                                  'timing_library', 'timing_pins', 'scent_rules'))
    if type(package['schema_version']) is not int or package['schema_version'] != 1:
        raise ValueError('Choose a version 1 scene input package')
    package_sha256 = f.digest(f.encoded(package))
    if existing:
        if existing['package_sha256'] != package_sha256:
            raise ValueError('A different source package is already attached to this scene')
        return existing
    minds = _minds(package['donor'], package['minds'], receipt)
    cast = [{'form_id': item['form'], 'node_id': item['mind'], 'speaker': item['label']}
            for item in sockets['forms']]
    library = scene_mind_support.save_library(c, store, scope, package['scent_rules'],
                                              package['timing_library'], cast)
    pins = _pins(store, c, scope, package['timing_pins'], library, sockets, plan['turns'])
    cutaway = _clip(store, c, scope, package['cutaway'])
    return {'scope': scope, 'replay_sha256': sockets['replay_sha256'], 'preparation': receipt['id'],
            'package_sha256': package_sha256, 'donor': {key: value for key, value in package['donor'].items()
                                                       if key != 'evidence'},
            'minds': minds, 'cutaway': cutaway['id'], 'library_sha256': library['sha256'],
            'pins': pins, 'disabled': []}


def _toggle(request, data):
    pin = checked_id(request.get('pin'), 'Timing pin')
    enabled = request.get('enabled')
    if not data or not any(item['id'] == pin for item in data['pins'].values()) or type(enabled) is not bool:
        raise ValueError('Choose a saved timing pin and its intended attachment state')
    disabled = set(data['disabled'])
    if enabled:
        disabled.discard(pin)
    else:
        disabled.add(pin)
    return data | {'disabled': sorted(disabled)}


def execute(store, action, request):
    if action not in COMMANDS:
        raise ValueError('Unknown scene input command')
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        scope, head = f.SceneFragmentStore._scope(c, request)
        f.SceneFragmentStore._current(request, head)
        plan = scene_plan.current(store, c, scope, head)
        if not plan or request.get('scene_plan') != plan['id']:
            raise ValueError('The saved scene plan changed. Reopen its Turn Ledger.')
        existing = read(c, scope, plan['replay_sha256'])
        data = (_attach(store, c, scope, head, plan, request, existing)
                if action == 'scene.plan.inputs.attach' else _toggle(request, existing))
        if data != existing:
            _save(c, data)
            plan = scene_plan.current(store, c, scope, head)
        return {'plan': plan, 'provider_calls': 0}


def populate(store, c, scope, plan, data, fragment, replay, solved, cast, scents):
    """Trace only the influence consumed by the approved replay or the planned writer."""
    library = scene_mind_support.read(c, scope)
    if not library or library['sha256'] != data['library_sha256']:
        raise ValueError('The scene lost its verified timing and scent library')
    local = {rule['form']: rule for rule in library['rules']}
    if {form: {'trigger': rule['trigger'], 'scent': rule['scent'], 'mind': rule['mind'],
               'source': rule['source_url']} for form, rule in local.items()} != scents:
        raise ValueError('Attached scent rules must agree with the authorized release rules')
    binds = scene_bridges._import_bindings(fragment, replay, solved, cast)
    asset = _clip(store, c, scope, data['cutaway'])
    turns = {turn['id']: turn for turn in plan['turns']}
    for edge in binds['cutaway']:
        evidence = edge['evidence']
        if evidence['sha256'] != asset['content_sha256'] or edge['operator'] not in ('invert_merge', 'reuse_merge'):
            raise ValueError('Use the exact Complete Cutaway edition already authorized on the replay')
        selector = evidence['selector']
        f._range(selector['start'], selector['end'], asset['duration_ms'])
        turns[edge['event']]['structure'] = edge | {'kind': 'cutaway', 'clip': asset['id'],
                                                    'mode': 'shape_only'}
    for prior, frame in zip(replay['frames'], replay['frames'][1:]):
        if frame['operation'] in ('transform', 'intervene'):
            turns[frame['event']]['structure'] = {'kind': 'authored_replay', 'replay': replay['id'],
                                                  'node': frame['node'], 'after': prior['event']}
    for turn in turns.values():
        for rule in turn['rules']:
            rule['library'] = library['library']['id']
            rule['port'] = data['minds'][rule['form']]['port']
    pin_states = {}
    for beat, pin in data['pins'].items():
        enabled = pin['id'] not in data['disabled']
        pin_states[beat] = pin | {'enabled': enabled}
        if enabled:
            asset = _clip(store, c, scope, pin['clip'])
            if asset['content_sha256'] != pin['content_sha256']:
                raise ValueError('The timing pin lost its selected clip edition')
            turns[beat]['timing'] = [pin]
    items = library['library']['items']
    plan['inputs'] = {'preparation': data['preparation'], 'package_sha256': data['package_sha256'],
                      'donor': data['donor'],
                      'library': {'title': library['library']['title'], 'eligible': sum(r['writing_eligible'] for r in items),
                                  'audition_only': sum(not r['writing_eligible'] for r in items)},
                      'pins': pin_states}
