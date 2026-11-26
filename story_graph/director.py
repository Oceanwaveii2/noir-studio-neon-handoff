"""Source-bound episode outline and advisory pacing proposals."""
from __future__ import annotations

import hashlib
import json
import re

from . import beat_rhythm, source_timing
from .beat_map import map_episode


MAX_BEATS = 8
_ACT = re.compile(r'^\s*(?:#{1,6}\s*)?(?:\*\*)?((?:(?:ACT)\s+[IVXLC\d]+\b|PROLOGUE\b|EPILOGUE\b)[^\r\n]*)',
                  re.IGNORECASE | re.MULTILINE)
_CONTROLS = ('pace', 'pause', 'tension_start', 'tension_end', 'cadence', 'comedy', 'transition')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _mapping(store, request, connection=None):
    result = map_episode(store, request['episode'], request['revision'],
                         viewpoint=request.get('viewpoint') or None, _connection=connection)
    for key, expected in (('project', result['project_id']), ('universe', result['universe_id']),
                          ('branch', result['branch']), ('source_sha256', result['source_sha256'])):
        if request.get(key) != expected:
            raise ValueError('Episode scope changed; reopen its director plan')
    if request.get('anchor_token') is not None and request['anchor_token'] != result['anchor_token']:
        raise ValueError('Passage anchors changed; reopen the director plan')
    return result


def select(mapping, ids):
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_BEATS
            or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids))):
        raise ValueError('Choose between 1 and 8 different passage beats')
    positions = {b['id']: i for i, b in enumerate(mapping['beats'])}
    if any(i not in positions for i in ids):
        raise ValueError('Beat selection is stale; refresh the map')
    indices = [positions[i] for i in ids]
    beats = [mapping['beats'][i] for i in indices]
    if indices != list(range(indices[0], indices[0]+len(indices))) or len({b['scene_id'] for b in beats}) != 1:
        raise ValueError('Choose consecutive beats within one scene')
    return beats


def _graph_number(node):
    data = node.get('data', {})
    number = data.get('beat')
    if type(number) is int and number > 0:
        return number
    matched = re.match(r'^beat_(\d+)_', node['id']) if data.get('source') == 'foxy_mo2_dag' else None
    return int(matched[1]) if matched else None


def _outline(store, c, mapping):
    row = c.execute('SELECT script,graph FROM revisions WHERE episode=? AND revision=?',
                    (mapping['episode'], mapping['revision'])).fetchone()
    script, graph = row['script'], json.loads(row['graph'])
    act_headers = [(m.start(1), m[1].strip()) for m in _ACT.finditer(script)]
    acts = [{'id': 'episode', 'title': 'Episode', 'source_start': 0, 'scenes': []}]
    acts.extend({'id': f'act-{index}', 'title': title, 'source_start': offset, 'scenes': []}
                for index, (offset, title) in enumerate(act_headers, 1))
    nodes = {}
    for node in graph.get('nodes', []):
        if node.get('type') == 'beat' and (number := _graph_number(node)) is not None:
            nodes.setdefault(number, []).append(node)
    viewpoint = mapping['viewpoint']
    profiles, events, linked = {}, {}, {}
    by_passage = {}
    for passage in mapping['beats']:
        number = passage['scope_beat']
        if number not in profiles:
            profiles[number] = beat_rhythm.read(c, mapping['episode'], number, graph)
            events[number] = [e['id'] for e in store._resolve_rows(c, mapping['episode'], number)
                              if e['episode'] == mapping['episode'] and e['beat'] == number
                              and e['viewpoint'] is None and source_timing.visible_to(e, viewpoint)]
        rhythm = profiles[number]
        anchored = passage['timing'] in ('source-verified', 'reviewed')
        node = None
        if anchored and len(nodes.get(number, [])) == 1:
            node = nodes[number][0]
            linked.setdefault(node['id'], []).append(passage)
        data = node.get('data', {}) if node else {}
        by_passage[passage['id']] = {
            'id': passage['id'], 'number': passage['number'], 'scene': passage['scene_id'],
            'start': passage['start'], 'end': passage['end'], 'text_sha256': fingerprint(passage['text']),
            'cutoff': number, 'timing': passage['timing'], 'anchor': passage['anchor'],
            'goal': data.get('goal') or (node.get('title') if node else None),
            'actor': data.get('primary_character'), 'obstacle': data.get('obstacle'),
            'basis': 'bound graph beat' if node else 'manuscript range',
            'rhythm': {key: rhythm['profile'][key] for key in _CONTROLS},
            'rhythm_token': rhythm['token'],
            'reveal': {'event_ids_at_cutoff': events[number] if anchored else [],
                       'source_boundary': passage['anchor'].get('source_cut'),
                       'audience': viewpoint or 'reader'},
        }
    for scene in mapping['scenes']:
        ids = scene['beats']
        if not ids:
            continue
        offset = scene.get('heading_range', {}).get('start', by_passage[ids[0]]['start'])
        act = next(x for x in reversed(acts) if x['source_start'] <= offset)
        act['scenes'].append({'id': scene['id'], 'title': scene['title'],
                              'beats': [by_passage[ident] for ident in ids]})
    links=[]
    for edge in graph.get('edges', []):
        left, right = linked.get(edge['from']), linked.get(edge['to'])
        if left and right and left[-1]['end'] <= right[0]['start'] and edge.get('type') in ('dependency', 'setup_payoff'):
            links.append({'from': left[-1]['id'], 'to': right[0]['id'], 'kind': edge['type']})
    base = {k: mapping[k] for k in ('episode', 'branch', 'revision', 'source_sha256', 'graph_sha256',
                                    'project_id', 'universe_id', 'anchor_token', 'viewpoint')}
    return {**base, 'acts': [a for a in acts if a['scenes']], 'links': links}, by_passage


def _tempo(direction, index, count):
    chunks = re.split(r'\bthen\b|\bfollowed by\b|;', direction.casefold(), maxsplit=1)
    phrase = chunks[0] if len(chunks) == 1 or index < (count + 1)//2 else chunks[-1]
    controls = {}
    if re.search(r'\b(?:linger|slow|slower|breathe|quieter)\b', phrase):
        controls.update(pace='slow', pause='held', cadence='flowing')
    elif re.search(r'\b(?:fast|faster|tighten|compress|accelerate|quicker|frantic)\b', phrase):
        controls.update(pace='fast', pause='none', cadence='punchy')
    if re.search(r'\b(?:hold|held|pause|silence)\b', phrase):
        controls['pause'] = 'held'
    if re.search(r'(?:heighten|build|increase)\s+(?:the\s+)?tension', phrase):
        controls['tension_end'] = 4
    if re.search(r'(?:lower|reduce|ease)\s+(?:the\s+)?tension', phrase):
        controls['tension_end'] = 1
    if re.search(r'\b(?:joke|punchline|comic|comedy)\b', direction.casefold()):
        controls['comedy'] = 'payoff' if index == count-1 else ('setup' if index == 0 else 'delay')
    return controls


def plan(store, request, *, proposal=False):
    with store._connect() as c:
        c.execute('BEGIN')
        mapping = _mapping(store, request, c)
        outline, beats = _outline(store, c, mapping)
        outline['schema_version'] = 1
        outline['id'] = fingerprint(outline)
        if not proposal:
            return outline
        picked = select(mapping, request.get('beats'))
        direction = request.get('direction', '')
        if not isinstance(direction, str) or len(direction) > 500:
            raise ValueError('Writing direction must be text up to 500 characters')
        choices = []
        for i, item in enumerate(picked):
            current = beats[item['id']]
            controls = _tempo(direction, i, len(picked))
            changes = {key: {'before': current['rhythm'][key], 'after': new}
                       for key, new in controls.items() if current['rhythm'][key] != new}
            choices.append({'beat': current, 'controls': controls, 'changes': changes})
        selection = set(request['beats'])
        provisional = {'schema_version': 1, 'outline_id': outline['id'], 'direction': direction,
                       'scene': picked[0]['scene_id'], 'choices': choices,
                       'affected': [item['beat']['id'] for item in choices if item['changes'] or direction.strip()],
                       'dependencies': [link for link in outline['links'] if selection & {link['from'],link['to']}],
                       'constraints': ['Keep source order and reveal boundaries', 'Preserve all exact locks and scoped story rules']}
        return {**provisional, 'id': fingerprint(provisional)}
