"""Bounded planning between observed scene state and an authored join contract."""
from __future__ import annotations

from collections import deque
import re

from . import scene_fragments as f
from .universe_scope import checked_id


_FACT = re.compile(r'[a-z0-9_-]+(?::[a-z0-9_-]+){0,3}')
MAX_STATES = 2048
MAX_STEPS = 12


def facts(values, label):
    items = f._items(values, label, 96)
    if (any(not isinstance(x, str) or len(x) > 150 or not _FACT.fullmatch(x) for x in items)
            or len(set(items)) != len(items)):
        raise ValueError(label + ' requires distinct typed facts')
    return frozenset(items)


def problem(spec):
    f._object(spec, ('start', 'required', 'forbidden', 'actions', 'scenes'))
    start = facts(spec['start'], 'Initial state')
    required = facts(spec['required'], 'Join preconditions')
    forbidden = facts(spec['forbidden'], 'Join conflicts')
    if not required or required & forbidden:
        raise ValueError('A scene join needs consistent preconditions')
    scenes = {}
    for item in f._items(spec['scenes'], 'Candidate scene headings', 6):
        f._object(item, ('id', 'heading', 'location', 'speakers', 'required_speakers'))
        ident = checked_id(item['id'], 'Scene label')
        if ident in scenes or not item['heading'].startswith('### SCENE ') or '\n' in item['heading'] or '\r' in item['heading']:
            raise ValueError('Each scene needs a distinct, single-line heading')
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z][ A-Za-z0-9-]{0,39}', v)
               for k in ('speakers', 'required_speakers') for v in f._items(item[k], 'Speakers', 12)):
            raise ValueError('Enter bounded scene speaker labels')
        if not set(item['required_speakers']) <= set(item['speakers']):
            raise ValueError('A required speaker is unavailable')
        if not isinstance(item['location'], str) or not item['location'] or len(item['location']) > 100:
            raise ValueError('Scene needs a mapped location')
        scenes[ident] = item
    actions = {}
    for item in f._items(spec['actions'], 'Authorized bridge actions', 36):
        f._object(item, ('id', 'scene', 'needs', 'adds', 'drops', 'stage'), ('required_silence', 'audible_to_scene'))
        ident = checked_id(item['id'], 'Bridge action')
        if ident in actions or item['scene'] not in scenes:
            raise ValueError('Each bridge action needs a distinct ID and known scene')
        needs = facts(item['needs'], 'Action preconditions')
        adds, drops = facts(item['adds'], 'Action effects'), facts(item['drops'], 'Removed facts')
        silent = item.get('required_silence', False)
        audible = item.get('audible_to_scene', [])
        if type(silent) is not bool or not isinstance(audible, list) or any(
                label not in scenes[item['scene']]['speakers'] for label in audible) or silent and audible:
            raise ValueError('Invalid silent beat or offscreen speaker binding')
        if not (adds or drops or silent) or adds & drops or not drops <= needs:
            raise ValueError('Action effects require explicit, consistent mutations')
        stage = item['stage']
        if not isinstance(stage, str) or not 1 <= len(stage) <= 280 or any(x in stage for x in ('\r', '\n', ':')):
            raise ValueError('Each action needs one bounded visible stage direction')
        actions[ident] = (needs, adds, drops, item)
    return start, required, forbidden, actions, scenes


def _accepts(state, required, forbidden):
    return required <= state and not state & forbidden


def _replay(initial, actions, order):
    state, frames = initial, []
    for ident in order:
        needs, adds, drops, item = actions[ident]
        if not needs <= state:
            raise ValueError('Bridge action is premature: '+ident)
        state = (state - drops) | adds
        frames.append({'id': ident, 'scene': item['scene'], 'stage': item['stage'], 'state': sorted(state)})
    return state, frames


def compile_bridge(spec):
    """Find and replay a shortest allowed route, then group adjacent actions into scenes."""
    start, required, forbidden, actions, scenes = problem(spec)
    obligations = frozenset(k for k, (_, _, _, item) in actions.items() if item.get('required_silence'))
    queue = deque([(start, (), obligations)])
    seen = {(start, obligations)}
    while queue:
        state, order, remaining = queue.popleft()
        if not remaining and _accepts(state, required, forbidden):
            _, frames = _replay(start, actions, order)
            grouped = []
            for beat in frames:
                if not grouped or grouped[-1]['id'] != beat['scene']:
                    if any(scene['id'] == beat['scene'] for scene in grouped):
                        raise ValueError('A route returned to an earlier scene without a new scene boundary')
                    grouped.append({**scenes[beat['scene']], 'beats': []})
                grouped[-1]['beats'].append({k: beat[k] for k in ('id', 'stage')})
            return {'start': sorted(start), 'goal': sorted(required), 'forbidden': sorted(forbidden),
                    'scenes': grouped, 'frames': frames, 'exit': sorted(state), 'states_examined': len(seen)}
        if len(order) == MAX_STEPS:
            continue
        for ident, (needs, adds, drops, _) in actions.items():
            if needs <= state:
                following = (state - drops) | adds
                pending = remaining - {ident}
                if (following, pending) not in seen:
                    if len(seen) == MAX_STATES:
                        raise ValueError('Scene bridge exceeds its search budget')
                    seen.add((following, pending))
                    queue.append((following, (*order, ident), pending))
    raise ValueError('No authorized action sequence reaches the saved join')
