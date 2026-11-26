"""Compile an explicitly prepared linear scene with author-supplied stage facts."""

import re

from story_graph import scene_fragments as f
from story_graph.universe_scope import verify_scope
from story_graph.world_laws import WorldLawStore

from .notebook import NotebookStore, joined, resolve


def current(store, c, scope, head):
    from .cook import current_preparation
    from .scene_bridges import _junctions

    if verify_scope(c)['kind'] != 'generic':
        return None
    prepared = current_preparation(c, scope['episode'], head)
    if not prepared or len(prepared['fragments']) != 1:
        return None
    if not f._has(c, 'episode_intake') or not c.execute(
            'SELECT 1 FROM episode_intake WHERE episode=? AND original IS NOT NULL', (scope['episode'],)).fetchone():
        return None
    book = NotebookStore.existing_in_connection(c, scope['episode'])
    script = joined(book['blocks'])
    if f.digest(script) != prepared['source_sha256']:
        return None
    blocks = [(block, block['text'].strip()) for block in book['blocks'] if block['text'].strip()]
    if not blocks or blocks[0][0]['kind'] != 'scene-heading':
        return None
    heading = blocks[0][1]
    if '\n' in heading or '\r' in heading:
        return None

    groups = _junctions(store, c, scope['episode'])
    cast, labels, beats = {}, {}, []
    for block, text in blocks[1:]:
        if block['kind'] == 'stage-direction' and '\n' not in text and '\r' not in text:
            beats.append((text, {}))
            continue
        if block['kind'] != 'character' or not beats:
            return None
        match = re.match(r'([A-Za-z][ A-Za-z0-9-]{0,39}):', text)
        character = block['speaker']
        group = groups.get(character)
        form = next((item for item in group.forms if item.id == (block['form'] or group.forms[0].id)), None) if group else None
        if not match or not form or (character in cast and cast[character]['form'] != form.id):
            return None
        label = match[1]
        if character in cast and cast[character]['label'] != label:
            return None
        cast[character] = {'character':character, 'form':form.id, 'label':label, 'location':'scene', 'mind':None}
        labels[form.id] = label
        beats[-1][1][character] = cast[character]
    if not beats or not cast or len({actor['label'] for actor in cast.values()}) != len(cast):
        return None

    turns = []
    for index, (stage, voices) in enumerate(beats, 1):
        speakers = [{'actor':key, **actor, 'required':True, 'mind':None, 'known':[],
                     'listeners':sorted(cast.keys() - {key})} for key, actor in voices.items()]
        turns.append({'id':f'beat-{index}', 'operation':'beat', 'stage':stage, 'phase':'after',
                      'before':cast, 'after':cast, 'speakers':speakers, 'relationships':[],
                      'revealed_forms':sorted(labels), 'rules':[], 'passage':None, 'frozen':False})
    laws = WorldLawStore.in_connection(c, project_id=scope['project'], universe_id=scope['universe'])
    plan = {'version':1, 'scope':scope, 'timeline_revision':head, 'notebook_revision':book['revision'],
            'source_sha256':prepared['source_sha256'], 'preparation':prepared['id'],
            'target':{'start':0,'end':len(script),'sha256':prepared['source_sha256'],
                      'protection':[[row['start'],row['end'],row['value']]
                                    for row in resolve(script, book['default_protection'], book['masks'])]},
            'frozen':None, 'fork':0, 'rejoin':{'start':len(script),'sha256':f.digest(''),'scene':None},
            'cutoff':0, 'replay':None, 'law_revision':laws['revision'],
            'turns':turns, 'scenes':[{'id':'scene','heading':heading,'location':None,
                                      'required_speakers':[],'beats':[turn['id'] for turn in turns]}],
            'form_labels':labels, 'exit':{}}
    return plan | {'id':f._id('scene-plan', plan)}
