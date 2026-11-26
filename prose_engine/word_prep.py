"""Promote Word Prep into a revisioned notebook and its linked episode graph."""
from __future__ import annotations

import re
from hashlib import sha256
from uuid import uuid4

from .edit_receipts import EditReceipt, ensure
from .notebook import NotebookStore, joined


BLOCK_KINDS = {'narrator', 'character', 'scene-heading', 'stage-direction'}
GRAPH_KINDS = {'mind-form': 'character', 'world-law': 'world_law', 'beat-turn': 'beat'}
LAW_REF = re.compile(r'@law:([\w.-]+)', re.IGNORECASE)


def promote(timeline, request, form_graph=None):
    episode = request['episode']
    raw = request.get('nodes')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 500:
        raise ValueError('Choose a Word Prep document with 1 to 500 nodes')
    fields = {key: request[key] for key in ('timeline_revision', 'notebook_revision', 'nodes')}
    receipt = EditReceipt.make('word_prep.promote', episode, fields, request.get('request_id'))
    book = NotebookStore(timeline)
    with timeline._connect() as c:
        ensure(c)
        previous = receipt.read(c)
    if previous:
        return {'status': 'REPLAYED', 'receipt': previous, 'episode': episode}
    original = timeline.get_episode(episode)
    notebook = book.open(episode)
    if notebook['revision'] != fields['notebook_revision'] or original['head'] != fields['timeline_revision']:
        raise ValueError('The episode changed. Reload it before sending Word Prep.')
    graph = original['graph']
    groups = (form_graph.read()['junctions'] if form_graph else ())
    speakers = {label.casefold(): group['character_id'] for group in groups
                for label in (group['label'], group['character_id'])}
    old_text = joined(notebook['blocks'])
    blocks = list(notebook['blocks'])
    masks = list(notebook['masks'])
    added = []
    offset = len(old_text)
    previous_graph = None
    for node in raw:
        if not isinstance(node, dict) or not isinstance(node.get('kind'), str):
            raise ValueError('Invalid Word Prep node')
        kind, text, speaker = node['kind'], node.get('text'), node.get('speaker') or ''
        if kind not in BLOCK_KINDS | GRAPH_KINDS.keys() or not isinstance(text, str) or not isinstance(speaker, str):
            raise ValueError('Unknown Word Prep node type')
        if not text.strip():
            continue
        if len(text) > 40000 or len(speaker) > 45 or (speaker and (not speaker.isprintable() or speaker.strip() != speaker)):
            raise ValueError('Shorten the Word Prep node or its speaker label')
        ident = 'prep-' + uuid4().hex
        law = node.get('injected_law')
        laws = ([law] if isinstance(law, str) and re.fullmatch(r'[\w.-]{1,100}', law) else [])
        if kind == 'world-law':
            laws += LAW_REF.findall(text)
        data = {'prep_kind': kind, 'word_prep_source': receipt.key, 'source_node': str(node.get('id', ''))[:128],
                'law_refs': list(dict.fromkeys(laws))}
        if kind in BLOCK_KINDS:
            lead = '\n\n' if offset else ''
            cue = speaker + ': ' if kind == 'character' and speaker else ''
            block_text = lead + cue + text
            block = {'id': ident, 'kind': kind, 'speaker': speakers.get(speaker.casefold()) if kind == 'character' else None,
                     'form': None, 'source': None, 'text': block_text}
            if cue:
                block['cue_label'] = speaker
            blocks.append(block)
            added.append(block_text)
            start = offset + len(lead) + len(cue)
            weight = node.get('noise_mode')
            if weight in ('0', '50') or kind == 'character':
                value = 50 if weight == '50' else 100
                masks.append({'id': ident, 'start': start, 'end': start + len(text), 'value': value,
                              'sha256': sha256(text.encode()).hexdigest(), 'hard': False})
            offset += len(block_text)
            data['block_id'] = ident
            if block['speaker']:
                data['character_id'] = block['speaker']
        elif kind == 'mind-form':
            matches = [(group['character_id'], form['id']) for group in groups for form in group['forms']
                       if text.casefold() in (form['id'].casefold(), form['label'].casefold())]
            if len(matches) == 1:
                data.update(character_id=matches[0][0], form_id=matches[0][1])
        graph['nodes'].append({'id': ident, 'type': GRAPH_KINDS.get(kind, 'character' if kind == 'character' else 'beat'),
                               'title': speaker or text.strip()[:96], 'data': {**data, 'text': text}})
        if previous_graph:
            graph['edges'].append({'from': previous_graph, 'to': ident, 'kind': 'word_prep_sequence'})
        previous_graph = ident
    if previous_graph is None:
        raise ValueError('Write or paste text in Word Prep first')
    try:
        updated = book.save(episode, notebook['revision'], original['head'], blocks, notebook['default_protection'], masks,
                            _graph=graph, _receipt=receipt,
                            _edits=[(len(old_text), len(old_text), ''.join(added))] if added else [])
    except ValueError:
        with timeline._connect() as c:
            previous = receipt.read(c)
        if previous:
            return {'status': 'REPLAYED', 'receipt': previous, 'episode': episode}
        raise
    return {'status': 'APPLIED', 'episode': episode, 'notebook_revision': updated['revision'],
            'timeline_revision': updated['timeline_revision']}
