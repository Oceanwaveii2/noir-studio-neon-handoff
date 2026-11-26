"""Concrete, advisory craft plans; never story events or pacing quality scores."""
from __future__ import annotations

import hashlib
import json
import re

from story_graph.beat_rhythm import defaults
from .diagnostics import ProseDiagnosticsAnalyzer as Diagnostics

METHOD = 'scoped-rhythm-guidance-v1'
INTERPRETATION = 'Advisory craft guidance, not a quality score, event timeline or mandatory sentence-length target.'

CONTROLS = {
    'pace': {
        'slow': 'Give existing perceptions and actions room to register; do not add events to make the passage longer.',
        'measured': 'Separate the existing actions clearly and keep their order; allow each turn to register.',
        'fast': 'Compress redundant connective wording and move directly between existing actions; do not omit facts.'},
    'pause': {
        'none': 'Avoid adding a pause or delay not present in the selected action.',
        'brief': 'Use a brief syntactic or paragraph break at an existing turn, without inventing a pause event.',
        'held': 'Let an existing moment hang through phrasing and paragraph space, not new story time or events.'},
    'cadence': {
        'flowing': 'Link compatible clauses smoothly while keeping the existing action order legible.',
        'varied': 'Vary sentence lengths around existing emphasis; avoid a mechanically repeated sentence pattern.',
        'punchy': 'Place existing emphasis near a sentence ending and trim explanation after it.',
        'staccato': 'Use concise separate sentences where meaning permits; preserve every exact lock and established fact.'},
    'transition': {
        'smooth': 'Connect the existing change of attention without repeating exposition or adding causal facts.',
        'abrupt': 'Make the existing turn clean and direct; do not invent an interruption.',
        'linger': 'Let the current established impression register before leaving it; do not advance the story.'},
    'comedy': {
        'setup': 'Make the existing comic expectation legible without adding a new gag or revealing a later payoff.',
        'delay': 'Delay emphasis through syntax around the existing material, not an invented action or event.',
        'payoff': 'Let an already-present comic turn land at the point of emphasis; do not manufacture a punchline.',
        'reaction': 'Give an already-present reaction its own space without inventing character behavior.',
        'escalation': 'Sharpen the progression of already-present comic turns; do not add a larger incident.',
        'release': 'Let an already-established comic release settle without explaining the joke or inventing relief.'}}

INTENTS = {
    'scene': ('Follow the existing entry without reintroducing the whole scene.',
              'Develop the current action without restarting the scene or anticipating later material.',
              'Leave this selected range at its existing boundary; do not invent a scene ending.'),
    'beauty': ('Orient attention to the beauty preparation or sensory focus already present.',
               'Let existing tactile or visual detail register in sequence; avoid stacking invented sensations.',
               'Carry the existing sensory impression into the boundary without adding an action.'),
    'comedy': ('Establish any existing comic expectation plainly; do not add a new setup.',
               'Space already-present setup and reaction so neither swallows the other; do not anticipate a later gag.',
               'Let an existing comic turn or reaction land without explanation; do not manufacture a payoff.'),
    'transformation': ('Use only anticipation and physical state already available at this beat.',
                       'Stage only currently established changes in their existing order; do not reveal a later form.',
                       'Let the currently established stage register; do not complete an unfinished transformation.'),
    'tension': ('Make the currently established pressure legible without inventing a threat.',
                'Shape the existing uncertainty through emphasis and withholding explanation, not withholding facts.',
                'Keep uncertainty or resolution exactly as established; do not invent a release.'),
    'dialogue': ('Enter the existing exchange without repeating its setup.',
                 'Keep existing turns and responses distinct; do not invent replies or change the speaker.',
                 'Let the existing final turn register without adding an answer.'),
    'quiet': ('Settle into the current established focus without adding exposition.',
              'Use breathing space around existing observations; do not invent reflection or private knowledge.',
              'Let the current impression remain without inventing closure.')}


def observe(text):
    """Reuses the existing lexical splitter; dialogue/abbreviations remain approximate."""
    sentences = Diagnostics.split_into_sentences(text)
    mean, sd = Diagnostics.compute_cadence(sentences)
    return {'word_count': Diagnostics.count_words(text), 'sentence_count': len(sentences),
            'paragraph_count': len([p for p in re.split(r'(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)', text) if p.strip()]),
            'mean_sentence_words': round(mean, 1), 'sentence_length_variation': round(sd, 1)}


def evidence(before, after):
    return {'method': 'lexical-cadence-v1', 'before': observe(before), 'after': observe(after),
            'interpretation': 'Descriptive only; approximate sentence splitting does not measure literary quality or prove pacing compliance.'}


def compile_guidance(packet, scene_function='scene', reference_features=None, reference_receipts=None, position=None, craft_mode='preserve'):
    if scene_function not in INTENTS:
        raise ValueError('Invalid rhythm scene function')
    if craft_mode not in ('preserve', 'expand'):
        raise ValueError('Invalid craft mode')
    if position is not None and (not isinstance(position, dict) or set(position) != {'index', 'count'} or
            any(type(position[k]) is not int for k in ('index', 'count')) or
            not 1 <= position['index'] <= position['count'] <= 8):
        raise ValueError('Invalid rhythm group position')
    profile = {**defaults(), **packet.beat_rhythm.get('profile', {})}
    cues = []
    if craft_mode != 'expand':
        for name, values in CONTROLS.items():
            if profile[name] in values:
                cues.append({'source': 'author:' + name, 'instruction': values[profile[name]]})
    if profile['tension_start'] is not None or profile['tension_end'] is not None:
        cues.append({'source': 'author:tension', 'instruction':
            f"Author tension endpoints: {profile['tension_start']} to {profile['tension_end']} (0–5; None means unset). "
            + ('Shape emotional and comedic escalation in that direction.' if craft_mode == 'expand'
               else 'Shape existing emphasis in that direction; these are not timestamps or permission to add events.')})
    neighbors = packet.beat_rhythm.get('edge_neighbors') if isinstance(packet.beat_rhythm, dict) and packet.beat_rhythm.get('status') == 'configured' else None
    if isinstance(neighbors, dict) and (neighbors.get('incoming') or neighbors.get('outgoing')):
        parts = []
        if neighbors.get('incoming'):
            in_beats = ', '.join(f"beat {n['beat']}" for n in neighbors['incoming'])
            parts.append(f'Carry pacing continuity from {in_beats}')
        if neighbors.get('outgoing'):
            out_beats = ', '.join(f"beat {n['beat']}" for n in neighbors['outgoing'])
            parts.append(f'Prepare structural transition toward {out_beats}')
        cues.append({'source': 'author:edge-transition', 'priority': 1, 'instruction':
            '; '.join(parts) + '. Structural pacing continuity only; do not reveal future story events.'})
    group = None
    if position is not None:
        index, count = position['index'], position['count']
        phase = 'single' if count == 1 else 'entry' if index == 1 else 'exit' if index == count else 'development'
        group = {**position, 'phase': phase, 'timing': 'ordinal only; does not advance the timeline cutoff'}
        cues.append({'source': 'group:continuity', 'instruction':
            f'Passage {index} of {count} in the selected range. Rewrite only this passage. '
            'Do not recap the scene, repeat an opening, invent an ending, or anticipate unseen passages. '
            'This ordinal is not evidence that any event has occurred.'})
    phase_index = 1 if group is None or group['phase'] in ('single', 'development') else 0 if group['phase'] == 'entry' else 2
    if craft_mode != 'expand' and (scene_function != 'scene' or group is not None):
        cues.append({'source': 'suggested:' + scene_function, 'instruction': INTENTS[scene_function][phase_index]})
    if not cues:
        cues.append({'source': 'neutral', 'instruction': 'No rhythm controls set. Follow the selected writing and author direction; do not impose a new tempo.'})
    if reference_features:
        if craft_mode == 'expand':
            cues.append({'source': 'eligible-reference', 'instruction':
                'Draw freely on the retrieved 190-book excerpts and cadence below to write richer, more vivid, non-robotic prose '
                'with varied sentence rhythm and fresh imagery in unlocked passages. World laws, character-node data, '
                'story-graph causal order, and exact locks govern story facts.'})
        else:
            cues.append({'source': 'eligible-reference', 'instruction':
                'Use the retrieved book excerpts and cadence below for sentence-variation and craft inspiration. '
                'Author pace, pause, cadence, world laws, and writing direction take precedence.'})
    if craft_mode == 'expand':
        cues.append({'source': 'craft-mode:expand', 'instruction':
            'EXPAND & ENRICH UNLOCKED PROSE: Preserve every 100%-locked span verbatim, but expand all unlocked prose with '
            'vivid sensory texture, comedic timing, physical staging, and distinct character voice grounded in the attached '
            'character-node notes, media annotations, and 190-book craft excerpts. Stay strictly inside the approved causal '
            'beat order, spatial presence, and world laws.'})
    cursor = packet.start
    for start, end, _ in packet.protected:
        if start > cursor:
            break
        cursor = max(cursor, end)
    fully_locked = cursor == packet.end
    if fully_locked:
        cues = [{'source': 'exact-protection', 'instruction': 'This whole selection is 100% protected. Return it verbatim, with no additions or deletions; all rhythm suggestions are suspended.'}]
    plan = {'schema_version': 1, 'method': METHOD, 'craft_mode': craft_mode, 'scene_function': scene_function, 'group': group,
            'precedence': 'World laws, scoped facts and exact locks first; explicit author direction and controls next; automatic craft suggestions and reference cadence last.',
            'fully_locked': fully_locked, 'cues': cues, 'source_observation': observe(packet.target),
            'reference_observation': reference_features,
            'reference_basis': [{'passage_id': r['passage_id'], 'source_id': r['source_id'],
                                 'excerpt_sha256': r['excerpt_sha256'],
                                 'library': {key:r.get(key) for key in ('index_sha256','policy_sha256','influence_sha256',
                                     'catalog_sha256','quality_sha256','release_pointer_sha256','encoder_binding_sha256')}}
                                for r in reference_receipts or []],
            'binding': {'context': packet.context.public() if packet.context else None,
                        'scope_snapshot_sha256': hashlib.sha256(json.dumps([packet.public(),packet.character_store_token,
                            packet.hidden_phrases],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                        'target_sha256': packet.target_sha256, 'start': packet.start, 'end': packet.end,
                        'rhythm_token': packet.beat_rhythm.get('token', 'none'),
                        'profile_sha256': hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                        'protection_revision': packet.protection_revision},
            'interpretation': INTERPRETATION}
    plan['id'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return plan


def group_guidance(plans):
    """No passage text or cross-passage narrative context is shared."""
    result = {'schema_version': 1, 'method': METHOD, 'scope': 'consecutive-beat-group',
              'passages': plans, 'interpretation': INTERPRETATION}
    result['id'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result
