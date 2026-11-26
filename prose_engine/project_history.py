"""Replay committed editor changes in project order."""
from __future__ import annotations

import json

from story_graph import transaction_audit as journal
from story_graph.beat_rhythm import BeatRhythmStore, read as read_beat_rhythm
from .notebook import DraftStore, NotebookStore
from .timeline_commands import revision


def execute(timeline, action, request, *, form_graph=None, junctions=None):
    if action == 'history.open':
        with timeline._connect() as db:
            db.execute('BEGIN')
            return journal.project_history_state(db)
    if action not in ('history.undo', 'history.redo'):
        raise ValueError('Unknown project history command')
    direction = action.split('.')[1]
    undo = direction == 'undo'
    expected = revision(request, 'revision')
    notebooks = NotebookStore(timeline)
    drafts = DraftStore(notebooks)
    graph_junctions = junctions() if junctions is not None else None
    with timeline._connect() as db:
        if form_graph and form_graph.path and form_graph.path.is_file():
            journal.attach_history_store(db, form_graph.path, 'form_db')
        db.execute('BEGIN IMMEDIATE')
        state = journal.project_history_state(db)
        item = state[f'next_{direction}']
        if state['revision'] != expected or not item or item['tx_id'] != request.get('tx_id'):
            raise ValueError('Project history changed. Refresh and try again.')
        _replay(db, item, direction, timeline, notebooks, drafts, form_graph, graph_junctions)
        updated = journal.project_history_state(db)
        moved = updated['next_redo' if undo else 'next_undo']
        if not moved or moved['tx_id'] != item['tx_id']:
            raise ValueError('The editor history changed. Refresh and try again.')
        return {**updated, 'changed': item}


def _replay(db, item, direction, timeline, notebooks, drafts, form_graph, junctions):
    undo = direction == 'undo'
    domain, target, token = item['domain'], item['target'], item['token']
    mismatch = ValueError('The saved editor state no longer matches project history.')
    if domain == 'timeline':
        _, earlier, later = timeline._action_history_stacks(db)
        stack = earlier if undo else later
        if not stack or stack[-1].get('project_history_token') != token:
            raise mismatch
        timeline._step_history_locked(db, -1 if undo else 1, junctions=junctions,
                                      on_draft_favorite=drafts._apply_history_favorite_in_conn)
    elif domain in ('graph', 'timing'):
        before = json.loads(item['before_patch'])['revision']
        after = json.loads(item['after_patch'])['revision']
        source, dest = (after, before) if undo else (before, after)
        replay = timeline._replay_graph_revision if domain == 'graph' else BeatRhythmStore(timeline)._replay_structure_revision
        replay(db, target, source, dest)
        journal.step_project_edit(db, domain=domain, target=target, token=token, next_token=token, undo=undo)
    elif domain == 'beat_rhythm':
        episode = timeline._require_active(db, target)
        beat = json.loads(item['before_patch'])['beat']
        current = read_beat_rhythm(db, target, beat)['revision']
        rhythm = BeatRhythmStore(timeline)
        earlier, later = rhythm._history(db, target, beat, current)
        stack = earlier if undo else later
        if not stack or f'{beat}:{stack[-1]}' != token:
            raise mismatch
        rhythm._history_step(target, beat, episode['head'], current, direction, connection=db)
    elif domain == 'notebook':
        episode = timeline._require_active(db, target)
        head = notebooks._head(db, target)
        if head is None:
            raise mismatch
        earlier, later = notebooks._history(db, target, head['revision'])
        stack = earlier if undo else later
        if not stack or str(stack[-1]) != token:
            raise mismatch
        patch = item['before_patch' if undo else 'after_patch']
        notebooks._history_step(target, head['revision'], episode['head'], direction, connection=db,
                                graph_revision=json.loads(patch)['timeline_revision'])
    elif domain == 'forms' and form_graph and form_graph.path and form_graph.path.is_file():
        rev, data = form_graph._read(db, 'form_db')
        stack = data.get(f'_graph_{direction}', [])
        if not stack or stack[-1] != token:
            raise mismatch
        form_graph.change({'action': f'{direction}_graph', 'revision': rev}, _connection=db)
    else:
        raise mismatch
