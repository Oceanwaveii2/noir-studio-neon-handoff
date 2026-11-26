"""Read a source-bound story track independently of prose generation."""
from __future__ import annotations

from collections import defaultdict
from contextlib import nullcontext
import json
import re

from story_graph import scene_branches, scene_bridge, scene_fragments as fragments, source_timing
from story_graph.world_laws import WorldLawStore
from . import scene_bridges, scene_clips


COMMAND = 'scene.timeline.open'


def _passage(script, start, end):
    fragments._range(start, end, len(script))
    text = script[start:end]
    return {'start': start, 'end': end, 'unit': 'codepoint',
            'sha256': fragments.digest(text), 'text': text}


def _saved_line(script, start, end, line):
    matches = list(re.finditer(r'^' + re.escape(line) + r'(?=\r?$)', script[start:end], re.M))
    if len(matches) != 1:
        raise ValueError('A saved bridge stage no longer has one exact manuscript line')
    match = matches[0]
    return _passage(script, start + match.start(), start + match.end())


def _asset_available(store, asset, start, end):
    if not asset or not (0 <= start < end <= asset['duration_ms']):
        return False
    try:
        scene_clips._asset_path(store, asset)
    except (OSError, ValueError):
        return False
    return True


def _clip_row(store, asset, *, start, end, purpose, ident, sha, name, **extra):
    available = _asset_available(store, asset, start, end)
    return {'id': ident, 'purpose': purpose, 'name': asset['name'] if asset else name,
            'start_ms': start, 'end_ms': end, 'source_sha256': sha,
            'clip': asset['id'] if available else None, **extra}


def _add_pins(store, rows, pins, assets):
    claimed = set()
    for row in rows:
        dest = row.get('destination')
        if not dest:
            continue
        for pin in pins.get(dest['node'], ()):
            frame = pin['frame']
            if (pin['id'] in claimed or pin['destination'] != dest or (
                    frame and frame != {'receipt': row.get('replay'), 'event': row['id']})):
                continue
            claimed.add(pin['id'])
            asset = assets.get(pin['clip'])
            if asset and asset['content_sha256'] != pin['content_sha256']:
                asset = None
            row['clips'].append(_clip_row(store, asset, start=pin['start_ms'], end=pin['end_ms'],
                                        purpose=pin['purpose'], ident=pin['id'], sha=pin['content_sha256'],
                                        name='Saved clip', note=pin['note'], character=pin['character'],
                                        observation_source='author' if pin['note'] else None))


def _scene_label(title):
    return re.sub(r'^#+\s*', '', title).strip()


def _fragment_rows(fragment, graph_sha, script, head, frames=(), turns=None, frozen=None):
    passages = {p['id']: p for p in fragment['graph']['passages']}
    nodes = {n['id']: n for n in fragment['graph']['nodes']
             if n['passage'] and n['kind'] not in ('heading', 'reference')}
    order = [(frame['event'], nodes[frame['node']], frame['operation'], frame['effects'])
             for frame in frames if frame['node'] in nodes] if frames else [
                 (n['id'], n, n['kind'], []) for n in sorted(nodes.values(),
                                                            key=lambda n: passages[n['passage']]['start'])]
    rows = []
    for ident, node, operation, effects in order:
        passage = passages[node['passage']]
        exact = _passage(script, passage['start'], passage['end'])
        if exact['sha256'] != passage['sha256']:
            raise ValueError('A story beat no longer matches its saved passage')
        label = node['label']
        if frames and sum(frame['node'] == node['id'] for frame in frames) > 1:
            label = ident.replace('-', ' ').capitalize()
        locked = frozen is not None and all(exact[k] == frozen[k] for k in ('start', 'end', 'sha256'))
        rows.append({'id': ident, 'label': label, 'kind': 'frozen' if locked else node['kind'],
                     'passage': exact, 'clips': [], 'operation': operation, 'effects': effects,
                     'actors': (turns or {}).get(ident, {}).get('actors', {}),
                     'destination': {'fragment': fragment['id'], 'fragment_revision': fragment['revision'],
                                     'node': node['id'], 'timeline_revision': head, 'graph_sha256': graph_sha,
                                     'start': exact['start'], 'end': exact['end'],
                                     'passage_sha256': exact['sha256']}})
    return rows


def _rebound_replay(c, scope, head, original):
    """Only the original world program and its exact rebound may supply the route."""
    if head == original['timeline_revision']:
        return original
    mutable = {'id', 'timeline_revision', 'fragment_revision', 'graph_sha256'}
    expected = {k: v for k, v in original.items() if k not in mutable}
    matches = []
    for row in c.execute('SELECT * FROM scene_replay_receipts WHERE episode=?', (scope['episode'],)):
        candidate = scene_branches._unpack(row)
        if candidate['timeline_revision'] == head and {
                k: v for k, v in candidate.items() if k not in mutable} == expected:
            matches.append(candidate)
    if len(matches) != 1:
        raise ValueError('Rebind the saved cutaway to this manuscript revision before following its story track')
    return matches[0]


def _drafts(c, scope, binding, applied_text):
    if not fragments._has(c, 'episode_drafts'):
        return []
    drafts = []
    for row in c.execute('SELECT id,status,payload FROM episode_drafts WHERE episode=? AND branch=?',
                         (scope['episode'], scope['branch'])):
        value = json.loads(row['payload'])
        if ((value.get('writing_context') or {}).get('continuation') or {}).get('binding') == binding:
            drafts.append({'id': row['id'], 'status': row['status'], 'source_revision': value['source_revision'],
                           'in_manuscript': bool(row['status'] == 'PROPOSED' and applied_text and
                                                 (value.get('text') or '').rstrip('\r\n') == applied_text)})
    return drafts


def _bridge_route(store, c, scope, head, script, bridge_row, assets, include_inspection):
    record = scene_branches._unpack(bridge_row)
    if record['scope'] != scope:
        raise ValueError('The story track belongs to its saved branch')
    parent = record['parent']
    source = scene_bridges._parent(store, c, parent, scope, record['cutoff'])
    tail = source[parent['join']:]
    join = len(script) - len(tail)
    if (script[:parent['fork']] != source[:parent['fork']] or not script.endswith(tail)
            or fragments.digest(tail) != record['retained_sha256']):
        raise ValueError('The frozen fork or retained destination changed')
    frozen = parent['frozen']
    scene_branches._book(c, scope, head, script, frozen)
    original, stamp = scene_branches._replay(c, scope, record['replay'])
    if stamp != record['replay_sha256']:
        raise ValueError('The bridge replay changed')
    replay = _rebound_replay(c, scope, head, original)
    fragment, _, graph_sha = fragments.SceneFragmentStore(store).pinned_replay(c, scope, head, replay)
    law = WorldLawStore.in_connection(c, project_id=scope['project'], universe_id=scope['universe'])
    visible = [row for row in store._resolve_rows(c, scope['episode'], record['cutoff'])
               if source_timing.visible_to(row, None)]
    if (graph_sha != replay['graph_sha256'] or law['revision'] != replay['law_revision']
            or fragments.digest(fragments.encoded(visible)) != replay['history_sha256']):
        raise ValueError('The graph, laws or visible history changed after the saved cutaway')
    compiled = scene_bridge.compile_bridge(record['program'])
    if scene_bridges._import_bindings(fragment, replay, compiled, record['cast'])['cutaway'] != record['imports']['cutaway']:
        raise ValueError('The cutaway connections no longer match the saved story track')
    groups = scene_bridges._junctions(store, c, scope['episode']) if include_inspection else None
    turns, minds = scene_bridges._project_turns(store, c, record, replay, compiled, junctions=groups)
    turns = {turn['beat']: turn for turn in turns}
    replay_rows = _fragment_rows(fragment, graph_sha, script, head, replay['frames'], turns, frozen)
    first = next((index for index, row in enumerate(replay_rows) if row['kind'] == 'frozen'), None)
    if first is None:
        raise ValueError('The story track cannot find the exact frozen fork line')
    replay_rows = replay_rows[first:]
    by_event = {row['id']: row for row in replay_rows}
    by_hash = {asset['content_sha256']: asset for asset in assets.values()}
    for row in replay_rows:
        row['replay'] = replay['id']
    for edge in record['imports']['cutaway']:
        evidence = edge['evidence']
        selector = evidence['selector']
        if selector['kind'] == 'clip':
            by_event[edge['event']]['clips'].append(_clip_row(
                store, by_hash.get(evidence['sha256']), start=selector['start'], end=selector['end'],
                purpose='structure', ident=evidence['id'] + '-' + edge['event'], sha=evidence['sha256'],
                name=evidence['asset'], operator=edge['operator'], selector=selector, source_edge=edge['from']))
    scenes = [{'id': 'cutaway', 'title': 'Cutaway', 'beats': replay_rows}]
    start = record['slot']['start']
    written = script[start:join].rstrip('\r\n')
    binding = {'bridge': record['id'], 'sha256': bridge_row['sha256']}
    applied = written != scene_bridges.SLOT and bool(written)
    drafts = _drafts(c, scope, binding, written if applied else '')
    if applied:
        if not any(draft['in_manuscript'] for draft in drafts):
            raise ValueError('The bridge text no longer matches a saved variant of this route')
        cursor = start
        frames = {frame['id']: frame for frame in compiled['frames']}
        for scene in compiled['scenes']:
            heading = _saved_line(script, cursor, join, scene['heading'])
            rows = []
            cursor = heading['end']
            for beat in scene['beats']:
                exact = _saved_line(script, cursor, join, beat['stage'])
                cursor = exact['end']
                rows.append({'id': beat['id'], 'label': beat['id'].replace('-', ' ').capitalize(),
                             'kind': 'bridge', 'passage': exact, 'clips': [],
                             'actors': turns[beat['id']]['actors'], 'state': frames[beat['id']]['state']})
            scenes.append({'id': scene['id'], 'title': _scene_label(scene['heading']), 'beats': rows})
    line_end = join + len(tail.splitlines()[0])
    destination = _passage(script, join, line_end)
    scenes.append({'id': 'retained', 'title': _scene_label(destination['text']), 'beats': [
        {'id': 'retained-join', 'label': 'Retained scene', 'kind': 'retained', 'clips': [],
         'passage': destination, 'actors': {}}]})
    route = {'scenes': scenes, 'bridge_state': 'applied' if applied else 'planned', 'drafts': drafts,
             'bridge': binding, 'replay': replay['id'],
             'retained': {'episode': parent['episode'], 'revision': parent['revision'], 'start': parent['join'],
                          'sha256': record['retained_sha256']}}
    if include_inspection:
        route['inspection'] = {'turns': turns, 'minds': minds, 'replay': replay, 'program': compiled,
                               'slot': record['slot'], 'cutoff': record['cutoff'], 'groups': groups,
                               'seed_cards': record['cast'], 'imports': record['imports']}
    return route


def _fragment_route(store, c, scope, head, script, request):
    registry = fragments.SceneFragmentStore(store)
    want = request.get('fragment')
    available = registry.execute('scene.fragment.list', scope)['fragments']
    choices = [row for row in available if row['anchor']['timeline_revision'] == head]
    if not want and len(choices) == 1:
        want = choices[0]['id']
    if not want and choices:
        from .cook import current_preparation
        prepared = current_preparation(c, scope['episode'], head)
        available_ids = {choice['id'] for choice in choices}
        if prepared:
            want = next((item['id'] for item in prepared['fragments'] if item['id'] in available_ids), None)
    if want is None:
        from story_graph.beat_map import map_episode

        beat_map = map_episode(store, scope['episode'], head, _connection=c)
        rows = {
            beat['id']: {'id': beat['id'], 'label': f"Passage {beat['number']}", 'kind': 'passage',
                         'passage': _passage(script, beat['start'], beat['end']),
                         'clips': [], 'actors': {}}
            for beat in beat_map['beats']
        }
        return {'scenes': [{'id': scene['id'], 'title': scene['title'],
                            'beats': [rows[ident] for ident in scene['beats']]}
                           for scene in beat_map['scenes'] if scene['beats']], 'fragments': choices}
    fragments.checked_id(want, 'Saved scene graph')
    row = registry._find(c, scope['episode'], want)
    if row is None:
        raise ValueError('Open a saved scene graph in this episode')
    body = registry._record(row)
    if body['scope'] != scope or body['anchor']['timeline_revision'] != head:
        raise ValueError('Rebind this scene graph to the current manuscript first')
    registry._target_at(c, body)
    fragment = registry._public(body, head, body['revision'], 'OPENED')['fragment']
    rows = _fragment_rows(fragment, row['sha256'], script, head)
    return {'scenes': [{'id': want, 'title': body['declaration']['title'], 'beats': rows}],
            'fragment': want, 'fragments': choices}


def open_track(store, request, *, connection=None, include_media=True, include_inspection=False, include_clips=True):
    registry = fragments.SceneFragmentStore(store)
    fragments._object(request, ('project', 'universe', 'episode', 'branch', 'timeline_revision'),
                      ('action', 'fragment', 'scope_revision'))
    with (nullcontext(connection) if connection is not None else store._connect()) as c:
        if connection is None:
            c.execute('BEGIN')
        scope, head = registry._scope(c, request)
        registry._current(request, head)
        if request.get('scope_revision', scope['scope_revision']) != scope['scope_revision']:
            raise ValueError('The story timeline scope changed')
        script, sha = registry._source(c, scope['episode'], head)
        assets = {a['id']: a for a in scene_clips._rows(c, 'scene_clip_assets', scope)} if include_clips else {}
        bridge = c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (scope['episode'],)).fetchone() \
            if fragments._has(c, scene_bridges.TABLE) else None
        route = (_bridge_route(store, c, scope, head, script, bridge, assets, include_inspection)
                 if bridge and not request.get('fragment') else
                 _fragment_route(store, c, scope, head, script, request))
        if include_clips:
            pins = defaultdict(list)
            for pin in scene_clips._rows(c, 'scene_clip_pins', scope, True):
                pins[pin['destination']['node']].append(pin)
            _add_pins(store, (row for scene in route['scenes'] for row in scene['beats']), pins, assets)
        for scene in route['scenes']:
            scene['passages_sha256'] = fragments.digest(fragments.encoded([
                [row['id'], row['passage']['start'], row['passage']['end'], row['passage']['sha256']]
                for row in scene['beats']]))
        if include_media:
            from .media_graph import project
            project(c, scope, head, sha, route['scenes'])
    return {'scope': scope, 'timeline_revision': head, 'source_sha256': sha, **route, 'provider_calls': 0}
