"""Compile an authored override against a pinned scene and replay it on a disposable world."""
from __future__ import annotations

from copy import deepcopy
import json
import re

from . import scene_fragments as f, source_timing
from .character_forms import AFM_JUNCTIONS
from .dag import BeatNode, BeatSequencer, CausalDAG, CycleError
from .models import Transaction
from .replay_world import SceneReplayWorld, transform_rules
from .typed_laws import active_laws, branch_points
from .universe_scope import checked_id
from .world_laws import WorldLawStore, check_laws


COMMANDS = frozenset('scene.override.' + action for action in ('preview', 'replay', 'open', 'list'))
MAX_STEPS = 96
EMPTY = {'schema_version': 1, 'events': [], 'overrides': []}
OPERATIONS = {
    'beat': (), 'release': ('severity',), 'notice': ('release',), 'line': ('observation',),
    'split': ('members',), 'intervene': (), 'rejoin': ('intervention',),
    'transform': ('avatar_id',), 'force': ('release',), 'group_release': ('after_reactivation',),
}
PATTERNS = {'invert_merge': 'split', 'reuse_merge': 'rejoin'}


def _error(code, message):
    raise f.SceneFragmentError(code, message)


def _version(value):
    if type(value) is not int or value != 1:
        _error('unsupported_version', 'Choose schema version 1 for scene replay')


def _bounded(value):
    if len(f.encoded(value).encode('utf-8')) > 64_000:
        _error('recipe_too_large', 'Scene replay input exceeds 64,000 bytes')


def _ids(values, label, limit=32):
    items = [checked_id(x, label) for x in f._items(values, label, limit)]
    if len(items) != len(set(items)):
        raise ValueError(f'{label} must be distinct')
    return items


def _rows(values, fields, limit=32, optional=()):
    rows = f._items(values, 'rows', limit)
    for row in rows:
        f._object(row, fields, optional)
    _ids([row['id'] for row in rows], 'Record ID', limit)
    return rows


def _branch_rules(profile,actors,nodes,split_anchors):
    rules=profile.get('branch_rules')
    if rules is None:
        return
    f._object(rules, ('transforms', 'reactivation'), ('intervention_forms', 'reactivated_group_force'))
    if profile['anchors']['transform']:
        raise ValueError('Use either legacy or branch-specific transformation anchors')

    def known_form(actor, form):
        ident = checked_id(actor, 'Actor ID')
        frm = checked_id(form, 'Form ID')
        known = AFM_JUNCTIONS.get(ident)
        return ident in actors and known and any(f.id == frm for f in known.forms)

    for row in _rows(rules['transforms'], ('id', 'actor', 'from_form', 'node', 'needs_reunion'),
                     optional=('requires_actor_form',)):
        actor=checked_id(row['actor'],'Form owner')
        known=AFM_JUNCTIONS.get(actor)
        allowed={v.id:v.kind for v in known.forms} if known else {}
        if (actor not in actors or actor=='haley' or allowed.get(row['id'])!='transformation'
                or allowed.get(row['from_form']) not in ('base','transformation') or row['from_form']==row['id']
                or row['node'] not in nodes or row['node'] in split_anchors
                or type(row['needs_reunion']) is not bool or (row['needs_reunion'] and actor!=profile['root'])):
            raise ValueError('A branch transformation needs a known actor, predecessor and passage')
        if 'requires_actor_form' in row:
            source = f._object(row['requires_actor_form'], ('actor', 'form'))
            if not known_form(source['actor'], source['form']) or source['actor'] == actor:
                raise ValueError('A transformation power source must name another actor and a known form')
    if 'intervention_forms' in rules:
        forms = rules['intervention_forms']
        if (not isinstance(forms, dict) or not set(forms) <= set(profile['interveners']) or
                not all(known_form(actor, form) for actor, form in forms.items())):
            raise ValueError('Intervention forms must name known forms of authorized interveners')
    split=rules['reactivation']
    if split is not None:
        f._object(split,('node','form','release'))
        checked_id(split['release'],'Split trigger release')
        owned={row['id'] for row in rules['transforms'] if row['actor']==profile['root']}
        if not profile['members'] or split['form'] not in owned or split['node'] not in nodes or split['node'] in split_anchors:
            raise ValueError('A repeat split needs its own passage, transformed form and force release')
    if 'reactivated_group_force' in rules:
        group = f._object(rules['reactivated_group_force'], ('node', 'visible_from', 'destination'))
        first = profile['force']
        sources = _ids(group['visible_from'], 'Group reaction location')
        if (not split or not isinstance(first, dict) or sources != [first.get('destination')]
                or group['node'] not in nodes or group['node'] in (*split_anchors, split['node'])
                or group['destination'] not in profile['locations'] or group['destination'] in sources):
            raise ValueError('A group release needs a new passage and a second destination after the first force reaction')


def _profile(profile, fragment):
    f._object(profile, ('schema_version', 'id', 'root', 'cutoff', 'locations', 'actors', 'portals', 'members',
                        'interveners', 'anchors', 'protected_line', 'emission', 'force', 'patterns'),('branch_rules',))
    _bounded(profile)
    _version(profile['schema_version'])
    checked_id(profile['id'], 'Replay profile')
    f._number(profile['cutoff'], 'Timeline cutoff')
    locations = _ids(profile['locations'], 'Location ID')
    actors = {r['id']: r['location'] for r in _rows(profile['actors'], ('id', 'location'))}
    root = checked_id(profile['root'], 'Root character ID')
    if root not in actors or any(loc not in locations for loc in actors.values()):
        raise ValueError('The root and actors must have a starting scene location')
    portals = _rows(profile['portals'], ('id', 'from', 'to', 'allows_scent', 'allows_sound', 'permeability'))
    pairs = set()
    for row in portals:
        a, b, p = row['from'], row['to'], row['permeability']
        pair = frozenset((a, b))
        if (a == b or a not in locations or b not in locations or pair in pairs
                or type(row['allows_scent']) is not bool or type(row['allows_sound']) is not bool
                or type(p) not in (int, float) or not 0 <= p <= 1):
            raise ValueError('Portal must have unique connected locations and valid sensory settings')
        pairs.add(pair)
    members = _rows(profile['members'], ('id', 'mind'), 16)
    minds = [r['mind'] for r in members]
    if any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?', x)
           or len(x) > 100 for x in minds) or len(set(minds)) != len(minds):
        raise ValueError('Each manifestation needs a distinct Mind port ID')
    if any(row['id'] in actors for row in members):
        raise ValueError('Manifestations must be distinct from the initial actors')
    helpers = _ids(profile['interveners'], 'Intervener ID')
    if root in helpers or set(helpers) - actors.keys():
        raise ValueError('Interveners must be other present actors')
    nodes = {n['id'] for n in fragment['graph']['nodes'] if n['kind'] not in ('reference', 'heading')}
    anchors = f._object(profile['anchors'], ('split', 'rejoin', 'transform'))
    pair = (anchors['split'], anchors['rejoin'])
    if bool(members) != all(x in nodes for x in pair) or (members and (len(members)<2 or not helpers or pair[0]==pair[1])):
        raise ValueError('Split and rejoin must have distinct destination anchors and authorized manifestations')
    if not members and any(x is not None for x in pair):
        raise ValueError('An empty family cannot authorize split anchors')
    transformations = anchors['transform']
    if not isinstance(transformations, dict):
        raise ValueError('Transformations must map form IDs to destination node IDs')
    family = AFM_JUNCTIONS.get(root)
    known = {form.id for form in family.forms if form.kind == 'transformation'} if family else set()
    if set(transformations) - known or any(x not in nodes or x in pair for x in transformations.values()):
        raise ValueError('A transformation must bind an existing form to a separate destination node')
    _branch_rules(profile,actors,nodes,pair)
    root_forms={form for actor,form in transform_rules(profile) if actor==root}
    exact = profile['protected_line']
    if exact is not None:
        f._object(exact, ('lock', 'speaker', 'node'))
        checked_id(exact['lock'], 'Protected line ID')
        if exact['speaker'] not in actors or exact['node'] not in nodes:
            raise ValueError('The protected line needs a present speaker and a saved passage')
    emission = profile['emission']
    if emission is not None:
        f._object(emission, ('form', 'strength'))
        if emission['form'] not in {root, *root_forms}:
            raise ValueError('Emission must attach to a scoped form')
        for value in f._object(emission['strength'], ('normal', 'severe')).values():
            checked_id(value, 'Scent ID')
    effect = profile['force']
    if effect is not None:
        f._object(effect, ('form', 'recipient', 'visible_from', 'destination'))
        receiving = _ids(effect['visible_from'], 'Reaction location')
        if (effect['form'] not in root_forms or effect['recipient'] == root or effect['recipient'] not in actors
                or not receiving or set(receiving) - set(locations) or effect['destination'] not in locations):
            raise ValueError('Force reaction must name a scoped form, a recipient and legal locations')
    evidence = {e['id']: e for e in fragment['declaration']['evidence']}
    for pattern in _rows(profile['patterns'], ('id', 'shape', 'arity')):
        source = evidence.get(pattern['id'])
        if (not source or source['use'] != 'structure' or source['selector']['kind'] != 'clip'
                or pattern['shape'] != 'many_to_one' or not 2 <= f._number(pattern['arity'], 'Pattern arity') <= 16):
            raise ValueError('A borrowed merge pattern must cite registered structural clip evidence')
    return profile


def _event(event):
    f._object(event, ('id', 'node', 'op', 'actor', 'after', 'args'))
    for key in ('id', 'node'):
        checked_id(event[key], key)
    if event['id'] == 'entry':
        raise ValueError('The entry frame is reserved')
    _ids(event['after'], 'Prerequisite event', MAX_STEPS)
    if event['actor'] is not None:
        checked_id(event['actor'], 'Actor ID')
    if not isinstance(event['op'], str) or event['op'] not in {*OPERATIONS, 'pattern_slot'}:
        _error('unknown_operation', 'Choose a supported scene transition')
    if not isinstance(event['args'], dict):
        raise ValueError('Transition arguments must be an object')
    return event


def _prepare_recipe(fragment, profile, recipe):
    _bounded(recipe)
    f._object(recipe, ('schema_version', 'events', 'overrides'))
    _version(recipe['schema_version'])
    events, receipts, presentation = {}, [], []
    for item in f._items(recipe['events'], 'events', MAX_STEPS):
        event = _event(deepcopy(item))
        if event['id'] in events:
            _error('duplicate_event', 'Scene event IDs must be unique')
        events[event['id']] = event
    overrides = f._items(recipe['overrides'], 'overrides', MAX_STEPS)
    for step in overrides:
        f._object(step, ('id', 'mode'), ('event', 'evidence', 'at', 'operator'))
    _ids([s['id'] for s in overrides], 'Override ID', MAX_STEPS)
    evidence = {e['id']: e for e in fragment['declaration']['evidence']}
    patterns = {p['id']: p for p in profile['patterns']}
    influences = {(reference, edge['to']) for edge in fragment['graph']['edges'] if edge['kind'] == 'influences'
                  for node in fragment['graph']['nodes'] if node['id'] == edge['from'] and node['kind'] == 'reference'
                  for reference in node['evidence']}
    expected = {
        'insert_event': ('event',), 'present': ('evidence', 'at'),
        'borrow_pattern': ('evidence', 'at', 'operator'),
    }
    for step in overrides:
        mode = step['mode']
        if not isinstance(mode, str) or mode not in expected:
            _error('unknown_override', 'Unknown scene override mode')
        f._object(step, ('id', 'mode', *expected[mode]))
        if mode == 'insert_event':
            event = _event(deepcopy(step['event']))
            if event['id'] in events or event['op'] == 'pattern_slot':
                _error('duplicate_event', 'An event insertion needs a new ID and an explicit destination action')
            events[event['id']] = event
            receipts.append({'id': step['id'], 'mode': mode, 'event': event['id'], 'result': 'destination_event'})
    if len(events) > MAX_STEPS:
        raise ValueError('Too many events in this scene')
    for step in overrides:
        mode = step['mode']
        if mode == 'insert_event':
            continue
        source = evidence.get(checked_id(step['evidence'], 'Evidence ID'))
        event = events.get(checked_id(step['at'], 'Landing event ID'))
        if not source or source['selector']['kind'] != 'clip' or source['use'] not in ('structure','timing') or not event:
            _error('unbound_override', 'Override needs a registered clip and a destination event')
        meta = {'id': step['id'], 'mode': mode, 'event': event['id'], 'evidence': source}
        if mode == 'present':
            presentation.append(meta)
            receipts.append(meta | {'result': 'audience_only'})
            continue
        op = PATTERNS.get(checked_id(step['operator'], 'Pattern operator'))
        pattern = patterns.get(step['evidence'])
        if (event['op'] != 'pattern_slot' or op is None or not pattern
                or (source['id'], event['node']) not in influences):
            _error('unbound_pattern', 'Pattern must match an authored slot and a saved influence edge')
        if op == 'split' and len(_ids(event['args'].get('members'), 'Manifestation ID', 16)) != pattern['arity']:
            _error('pattern_arity', 'The destination cast does not match the borrowed split shape')
        event['op'] = op
        if op == 'rejoin':
            # The sequencer verifies how many destination bodies actually remain.
            event['pattern_arity'] = pattern['arity']
        receipts.append(meta | {'result': op, 'operator': step['operator'], 'transfer': 'shape_only',
                                'excluded': ['donor_cast', 'donor_cause', 'donor_rules', 'donor_dialogue']})
    if any(e['op'] == 'pattern_slot' for e in events.values()):
        _error('unresolved_slot', 'An authored pattern slot is missing its override binding')
    receipt_order = {step['id']: i for i, step in enumerate(overrides)}
    return events, sorted(receipts, key=lambda r: receipt_order[r['id']]), presentation


def _locked_line(c, fragment, script, node, rule, laws):
    scope = fragment['scope']
    if not f._has(c, 'notebook_heads'):
        _error('lock_missing', 'The protected line needs a matching saved notebook')
    row = c.execute('''SELECT r.payload FROM notebook_heads h JOIN notebook_revisions r
                       ON r.episode=h.episode AND r.revision=h.head
                       WHERE h.episode=? AND r.timeline_revision=?''',
                    (scope['episode'], fragment['anchor']['timeline_revision'])).fetchone()
    book = json.loads(row['payload']) if row else None
    if not book or ''.join(b['text'] for b in book['blocks']) != script:
        _error('lock_missing', 'The protected line needs a matching saved notebook')
    passages = {p['id']: p for p in fragment['graph']['passages']}
    p = passages[node['passage']]
    mask = next((m for m in book['masks'] if m['id'] == rule['lock']), None)
    if (not mask or not mask.get('hard') or mask['value'] != 100
            or not p['start'] <= mask['start'] < mask['end'] <= p['end']):
        _error('lock_missing', 'The named exact lock must fall inside the pinned dialogue passage')
    text = script[mask['start']:mask['end']]
    if f.digest(text) != mask['sha256']:
        _error('lock_changed', 'The protected line no longer matches its saved bytes')
    if check_laws(text, laws):
        _error('law_conflict', 'The protected line conflicts with a scoped world law; its bytes were preserved')
    return {'lock': mask['id'], 'sha256': mask['sha256']}


def _compile(c, fragment, script, profile, events, laws):
    world_ids = {person['id'] for person in profile['actors']} | {row['id'] for row in profile['members']}
    nodes = {n['id']: n for n in fragment['graph']['nodes'] if n['kind'] not in ('reference', 'heading')}
    passage = {p['id']: p for p in fragment['graph']['passages']}
    if any(e['node'] not in nodes for e in events.values()):
        _error('wrong_anchor', 'Replay events must land on a destination passage node')
    groups = {}
    for e in events.values():
        groups.setdefault(passage[nodes[e['node']]['passage']]['start'], []).append(e['id'])
    before = {}
    previous = []
    for offset in sorted(groups):
        for ident in groups[offset]:
            before[ident] = previous
        previous = groups[offset]
    # Ordering relationships in the saved source graph may add prerequisites.
    # Presentation and influence edges never become causal dependencies.
    by_anchor = {}
    for e in events.values():
        by_anchor.setdefault(e['node'], []).append(e['id'])
    graph_pre = {k: [] for k in events}
    for edge in fragment['graph']['edges']:
        if edge['kind'] not in f.ORDERING:
            continue
        src, dst = edge['from'], edge['to']
        if edge['kind'] == 'requires':
            src, dst = dst, src
        for ident in by_anchor.get(dst, ()):
            graph_pre[ident].extend(by_anchor.get(src, ()))

    dag, reveals = CausalDAG(), {}
    trans=transform_rules(profile)
    policy=profile.get('branch_rules') or {}
    repeat=policy.get('reactivation')
    for ident, event in events.items():
        op, actor, node, args = (event[k] for k in ('op', 'actor', 'node', 'args'))
        params = dict(f._object(args, OPERATIONS[op]))
        dependencies = [*before[ident], *graph_pre[ident], *event['after']]
        if op != 'beat' and actor not in world_ids:
            _error('unknown_actor', f'Event {ident} needs a scoped actor')
        if op == 'release' and params['severity'] not in ('normal', 'severe'):
            _error('invalid_release', 'Specify a normal or severe authored release')
        for field, needs in {'notice': ('release', 'release'), 'line': ('observation', 'notice'),
                             'rejoin': ('intervention', 'intervene'), 'force': ('release', 'release')}.items():
            if op == field:
                key, expected = needs
                prior = events.get(checked_id(params[key], 'Action evidence'))
                valid = (expected, 'group_release') if op == 'force' else (expected,)
                if not prior or prior['op'] not in valid:
                    _error('missing_prerequisite', f'{ident} needs an earlier {expected} event')
                dependencies.append(prior['id'])
        if op == 'group_release':
            rule = policy.get('reactivated_group_force')
            trigger = events.get(checked_id(params['after_reactivation'], 'Source split'))
            if not rule or not repeat or node != rule['node'] or actor != profile['root']:
                _error('wrong_anchor', 'The group release needs its own authorized passage and family')
            if not trigger or trigger['op'] != 'split' or trigger['node'] != repeat['node'] or trigger['actor'] != actor:
                _error('missing_prerequisite', 'The group release needs the authorized repeat split')
            dependencies.append(trigger['id'])
        may_reactivate=op=='split' and repeat and node==repeat['node']
        if op in ('split', 'rejoin') and node!=profile['anchors'][op] and not may_reactivate:
            _error('wrong_anchor', f'{op.title()} is outside its authored destination passage')
        if op == 'split':
            _ids(params['members'], 'Manifestation ID', 16)
            if may_reactivate:
                cause=events.get(repeat['release'])
                if not cause or cause['op']!='release' or cause['actor']!=actor:
                    _error('missing_prerequisite', 'This repeat split needs its own authored release')
                dependencies.append(cause['id'])
                hits=[e['id'] for e in events.values() if e['op']=='force' and e['args'].get('release')==cause['id']]
                if len(hits)!=1:
                    _error('missing_prerequisite', 'This repeat split needs that release’s checked reaction')
                dependencies.extend(hits)
                params['reactivate']=True
        if op == 'rejoin' and 'pattern_arity' in event:
            params['pattern_arity'] = event['pattern_arity']
        if op == 'line':
            rule = profile['protected_line']
            if not rule or node != rule['node'] or actor != rule['speaker'] or nodes[node]['kind'] != 'dialogue':
                _error('wrong_anchor', 'The protected response must use its own speaker and source dialogue')
            params.update(_locked_line(c, fragment, script, nodes[node], rule, laws))
        if op == 'transform':
            form = checked_id(params['avatar_id'], 'Destination form')
            rule=trans.get((actor,form))
            if rule is None or rule['node']!=node or form in reveals.get(actor,{}):
                _error('early_form', 'The requested form can only activate once at its pinned transformation')
            reveals.setdefault(actor,{})[form] = ident
        if any(k not in events or k == ident for k in dependencies):
            _error('missing_prerequisite', f'Event {ident} has an unknown or self-referencing dependency')
        txns = [] if op == 'beat' else [Transaction('scene_'+op, actor, profile['root'], params)]
        dag.add_beat(BeatNode(ident, ident, fragment['id'], '', primary_character=actor,
                             dependencies=list(dict.fromkeys(dependencies)), transactions=txns))
    try:
        order = dag.validate()
    except CycleError as exc:
        raise f.SceneFragmentError('causal_cycle', 'Override order conflicts with its source or prerequisites') from exc
    return dag, order, reveals


def _run(world, dag, order, events):
    sequencer = BeatSequencer(dag, world)
    frames = [{'event': 'entry', 'node': None, 'operation': 'entry', 'state': world.projection(), 'effects': []}]
    for ident in order:
        try:
            log = sequencer.execute_beat(ident)
        except (RuntimeError, ValueError) as exc:
            _error('blocked_transition', str(exc))
        frames.append({'event': ident, 'node': events[ident]['node'], 'operation': events[ident]['op'],
                       'state': world.projection(), 'effects': [txn['state_deltas'] for txn in log['transaction_results']]})
    return frames


def _unpack(row):
    if f.digest(row['payload']) != row['sha256']:
        _error('replay_digest', 'Scene replay record failed its fingerprint check')
    return json.loads(row['payload'])


class SceneReplayStore:
    """Scope and immutable candidate receipts; no canonical timeline or manuscript writes."""

    def __init__(self, timeline):
        self.timeline = timeline
        self.fragments = f.SceneFragmentStore(timeline)

    def install_profile(self, request, profile):
        """Trusted copy setup, not a public route for inventing world laws or cast permissions."""
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            scope, head = self.fragments._scope(c, request)
            fragment, _, _ = self.fragments.pinned_replay(c, scope, head, request)
            body = {'scope': scope, 'fragment': fragment['id'], 'profile': _profile(profile, fragment)}
            payload = f.encoded(body)
            c.execute('''CREATE TABLE IF NOT EXISTS scene_replay_profiles(
                episode TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY(episode,id), FOREIGN KEY(episode) REFERENCES episodes(id))''')
            row = c.execute('SELECT * FROM scene_replay_profiles WHERE episode=? AND id=?', (scope['episode'], profile['id'])).fetchone()
            if row and _unpack(row) != body:
                raise ValueError('Replay profiles are immutable; choose a new profile ID')
            if row is None:
                c.execute('INSERT INTO scene_replay_profiles VALUES(?,?,?,?)',
                          (scope['episode'], profile['id'], payload, f.digest(payload)))

    def execute(self, action, request):
        if action not in COMMANDS:
            raise ValueError('Unknown scene override command')
        op = action.rsplit('.', 1)[-1]
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE' if op == 'replay' else 'BEGIN')
            scope, head = self.fragments._scope(c, request)
            ep = scope['episode']
            has_runs = f._has(c, 'scene_replay_receipts')
            if op == 'list':
                rows = c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? ORDER BY rowid LIMIT 100', (ep,)) if has_runs else ()
                items = []
                for row in rows:
                    value = _unpack(row)
                    if value['scope'] == scope:
                        items.append({k:value[k] for k in ('id','title','profile','timeline_revision','world_sha256')})
                return {'receipts': items, 'provider_calls': 0}
            if op == 'open':
                ident = checked_id(request.get('receipt'), 'Replay receipt')
                row = c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?', (ep, ident)).fetchone() if has_runs else None
                if not row or (value := _unpack(row))['scope'] != scope:
                    _error('unknown_replay', 'Replay receipt is not saved in this episode and branch')
                return {'status': 'OPENED', 'receipt': value, 'historical': value['timeline_revision'] != head,
                        'provider_calls': 0}
            fragment, script, graph_sha = self.fragments.pinned_replay(c, scope, head, request)
            pid = checked_id(request.get('profile'), 'Replay profile')
            prof = c.execute('SELECT * FROM scene_replay_profiles WHERE episode=? AND id=?', (ep, pid)).fetchone() if f._has(c, 'scene_replay_profiles') else None
            if not prof:
                _error('profile_missing', 'This scene has no registered replay profile of that name')
            registered = _unpack(prof)
            if registered['scope'] != scope or registered['fragment'] != fragment['id']:
                _error('wrong_scope', 'Replay profile belongs to another scene or branch')
            profile = _profile(registered['profile'], fragment)
            law = WorldLawStore.in_connection(c, project_id=scope['project'], universe_id=scope['universe'])
            if f._number(request.get('law_revision'), 'World law revision') != law['revision']:
                _error('stale_laws', 'World law revision changed; reopen and preview again')
            laws = active_laws(law['laws'], branch_points(c, ep, profile['cutoff']), scope['branch'])
            if violations := check_laws(script[fragment['anchor']['start']:fragment['anchor']['end']], laws):
                if profile['protected_line']:
                    # Validate protected bytes first so a conflict can identify a frozen line.
                    _locked_line(c, fragment, script, next(n for n in fragment['graph']['nodes']
                                 if n['id'] == profile['protected_line']['node']), profile['protected_line'], laws)
                _error('law_conflict', 'The selected source conflicts with scoped world laws: ' +
                       ', '.join(sorted({key for key, _ in violations})))
            approved = [e for e in self.timeline._resolve_rows(c, ep, profile['cutoff'])
                        if source_timing.visible_to(e, None)]
            recipe = request.get('recipe', EMPTY)
            events, steps, presentation = _prepare_recipe(fragment, profile, recipe)
            dag, order, reveals = _compile(c, fragment, script, profile, events, laws)
            frames = _run(SceneReplayWorld(profile, reveals), dag, order, events)
            recipe_sha = f.digest(f.encoded(recipe))
            basis = {'schema_version': 1, 'scope': scope, 'timeline_revision': head, 'fragment': fragment['id'],
                     'fragment_revision': fragment['revision'], 'graph_sha256': graph_sha, 'profile': pid,
                     'profile_sha256': prof['sha256'], 'recipe_sha256': recipe_sha,
                     'law_revision': law['revision'], 'timeline_cutoff': profile['cutoff'],
                     'history_sha256': f.digest(f.encoded(approved)), 'approved_event_ids': [e['id'] for e in approved]}
            body = basis | {'id': f._id('scene-replay', basis), 'title': fragment['declaration']['title'],
                            'frames': frames, 'overrides': steps, 'presentation': presentation,
                            'world_sha256': f.digest(f.encoded(frames)), 'writes_canon': False}
            if op == 'preview':
                return {'status': 'PREVIEW', 'receipt': body, 'provider_calls': 0}
            c.execute('''CREATE TABLE IF NOT EXISTS scene_replay_receipts(
                episode TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
                PRIMARY KEY(episode,id), FOREIGN KEY(episode) REFERENCES episodes(id))''')
            row = c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?', (ep, body['id'])).fetchone()
            if row:
                if _unpack(row) != body:
                    _error('replay_drift', 'Replaying saved inputs produced a different result')
                return {'status': 'REPLAYED', 'receipt': body, 'provider_calls': 0}
            payload = f.encoded(body)
            c.execute('INSERT INTO scene_replay_receipts VALUES(?,?,?,?)', (ep, body['id'], payload, f.digest(payload)))
            return {'status': 'SAVED', 'receipt': body, 'provider_calls': 0}
