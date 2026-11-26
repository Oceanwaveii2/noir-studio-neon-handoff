"""Reviewed passage/event associations. Reads never create tables or infer timing."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from . import source_timing
from .universe_scope import verify_scope


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def heads(c, episode):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='passage_anchor_revisions'").fetchone():
        return []
    return [json.loads(r['payload']) for r in c.execute('''SELECT r.payload FROM passage_anchor_revisions r
        JOIN (SELECT id,MAX(revision) revision FROM passage_anchor_revisions WHERE episode=? GROUP BY id) h
        ON r.id=h.id AND r.revision=h.revision ORDER BY r.id''', (episode,))]


def ledger_token(c, episode):
    return fingerprint(heads(c, episode))


def evidence(store, c, episode, event_id, viewpoint):
    event = c.execute('SELECT * FROM events WHERE id=? AND episode=?', (event_id, episode)).fetchone()
    if (event is None or event['status'] != 'approved' or not event['permitted'] or
            not event['source_id'].strip() or not event['reviewer'].strip() or
            (event['viewpoint'] is not None and event['viewpoint'] != viewpoint)):
        raise ValueError('Choose approved, permitted same-episode evidence visible to this viewpoint')
    beat = event['beat']
    if episode == source_timing.EPISODE and event_id == source_timing.EVENT and source_timing.managed(c):
        beat = source_timing.AWAKENING_BEAT
    rows = [r for r in store._resolve_rows(c, episode, beat) if source_timing.visible_to(r, viewpoint)]
    if not any(r['id'] == event_id and r['episode'] == episode for r in rows):
        raise ValueError('Evidence is outside the episode branch')
    return beat, fingerprint(rows)


def _check_source_boundary(c, episode, event_id, passage):
    if episode == source_timing.EPISODE and event_id == source_timing.EVENT and source_timing.managed(c):
        cut = source_timing.cut_for(passage['start'], passage['end'])
        if cut is None or cut.beat < source_timing.AWAKENING_BEAT:
            raise ValueError('The awakening is not established at the start of this passage')


def basis(mapping, passage, identity):
    return {'project_id': identity['project_id'], 'universe_id': identity['universe_id'],
            'scope_revision': identity['scope_revision'], 'branch': mapping['branch'],
            'revision': mapping['revision'], 'source_name': mapping['source_name'],
            'source_sha256': mapping['source_sha256'], 'graph_sha256': mapping['graph_sha256'],
            'start': passage['start'], 'end': passage['end'], 'text_sha256': fingerprint(passage['text'])}


def project(store, c, mapping, viewpoint=None):
    identity = verify_scope(c)
    records = heads(c, mapping['episode'])
    token = fingerprint(records)
    source_cuts = source_timing.windows(c, mapping['episode'])
    counts = {}
    for passage in mapping['beats']:
        key = fingerprint(passage['text']); counts[key] = counts.get(key, 0) + 1
    last_beat_by_scene = {}
    last_event_by_scene = {}
    for passage in mapping['beats']:
        current = basis(mapping, passage, identity)
        matches = [r for r in records if r['viewpoint'] == viewpoint and r['basis']['text_sha256'] == current['text_sha256']]
        state = 'unverified'; record = None; cutoff = 0
        cut = source_timing.cut_for(passage['start'], passage['end'], source_cuts)
        if matches:
            if len(matches) != 1 or counts[current['text_sha256']] != 1:
                state = 'ambiguous'
            else:
                record = matches[0]
                state = 'unbound' if record['action'] == 'unbind' else 'stale'
                if record['action'] == 'bind' and record['basis'] == current:
                    try:
                        _check_source_boundary(c, mapping['episode'], record['event'], passage)
                        beat, digest = evidence(store, c, mapping['episode'], record['event'], viewpoint)
                        if beat == record['beat'] and digest == record['evidence_sha256']:
                            state, cutoff = 'reviewed', beat
                    except ValueError:
                        pass
        if state in ('unverified', 'unbound') and cut:
            state, cutoff = 'source-verified', cut.beat
        passage['scope_beat'] = cutoff
        passage['timing'] = state
        passage['anchor'] = {'id': record['id'] if record else None,
                             'revision': record['revision'] if record else 0, 'token': token,
                             'passage': passage['id'], 'viewpoint': viewpoint, 'status': state,
                             'beat': cutoff}
        if state == 'source-verified':
            passage['anchor']['source_cut'] = cut.public()
        scene_id = passage['scene_id']
        if state == 'reviewed':
            if cutoff >= last_beat_by_scene.get(scene_id, 0):
                last_beat_by_scene[scene_id] = cutoff
                last_event_by_scene[scene_id] = record['event']
            passage['scene_inferred_beat'] = cutoff
            passage['scene_inferred_event'] = record['event']
        else:
            passage['scene_inferred_beat'] = last_beat_by_scene.get(scene_id, 0)
            passage['scene_inferred_event'] = last_event_by_scene.get(scene_id)
    for scene in mapping['scenes']:
        scene_passages = [b for b in mapping['beats'] if b['scene_id'] == scene['id']]
        reviewed_beats = [b['scope_beat'] for b in scene_passages if b['timing'] == 'reviewed']
        scene['reviewed_count'] = len(reviewed_beats)
        scene['source_verified_count'] = sum(b['timing'] == 'source-verified' for b in scene_passages)
        scene['unverified_count'] = sum(1 for b in scene_passages if b['timing'] == 'unverified')
        scene['inferred_beat_range'] = [min(reviewed_beats), max(reviewed_beats)] if reviewed_beats else [0, 0]
    mapping['anchor_token'] = token
    mapping['viewpoint'] = viewpoint
    return mapping


def check(store, c, episode, revision, start, end, beat, viewpoint, expected=None):
    """Reconstruct on the caller's transaction, including atomic draft apply guards."""
    from .beat_map import map_episode
    mapping = map_episode(store, episode, revision, viewpoint=viewpoint, _connection=c)
    selected = [p for p in mapping['beats'] if p['start'] == start and p['end'] == end]
    affected = [p for p in mapping['beats'] if p['start'] < end and start < p['end']
                and p['timing'] not in ('unverified', 'source-verified')]
    if expected is None and not affected and not (selected and selected[0]['timing'] == 'source-verified'):
        return None  # Existing explicit timeline operations on unassigned text remain supported.
    if len(selected) != 1:
        raise ValueError('Anchored writing requires one complete mapped passage; use a beat group')
    passage = selected[0]
    if passage['timing'] in ('stale', 'ambiguous'):
        raise ValueError('Passage anchor is stale or ambiguous; explicitly rebind before writing')
    source_default = passage['timing'] == 'source-verified' and beat == 0 and expected is None
    if (beat != passage['scope_beat'] and not source_default) or (expected is not None and expected != passage['anchor']):
        raise ValueError('Passage anchor changed; refresh the beat map')
    return passage['anchor']


class BeatAnchorStore:
    def __init__(self, timeline):
        self.timeline = timeline

    def open(self, episode, revision, *, viewpoint=None):
        from .beat_map import map_episode
        with self.timeline._connect() as c:
            c.execute('BEGIN')
            mapping = map_episode(self.timeline, episode, revision, viewpoint=viewpoint, _connection=c)
            events = []
            for row in c.execute('SELECT * FROM events WHERE episode=? ORDER BY beat,id', (episode,)):
                try:
                    beat, _ = evidence(self.timeline, c, episode, row['id'], viewpoint)
                    resolved = next(ev for ev in self.timeline._resolve_rows(c, episode, beat) if ev['id'] == row['id'])
                    events.append({k: resolved[k] for k in ('id', 'beat', 'content', 'source_id', 'reviewer')})
                except ValueError:
                    pass
            history = []
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='passage_anchor_revisions'").fetchone():
                history = [json.loads(r['payload']) for r in c.execute(
                    'SELECT payload FROM passage_anchor_revisions WHERE episode=? ORDER BY id,revision DESC',(episode,))]
            return {'mapping': mapping, 'events': sorted(events, key=lambda event: (event['beat'], event['id'])),
                    'history': [r for r in history if r['viewpoint'] == viewpoint]}

    def _insert_revisions(self, c, records):
        c.execute('''CREATE TABLE IF NOT EXISTS passage_anchor_revisions(
            id TEXT NOT NULL, revision INTEGER NOT NULL, episode TEXT NOT NULL REFERENCES episodes(id),
            payload TEXT NOT NULL, PRIMARY KEY(id,revision))''')
        for record in records:
            c.execute('INSERT INTO passage_anchor_revisions VALUES(?,?,?,?)',
                      (record['id'], record['revision'], record['episode'], json.dumps(record, ensure_ascii=False)))

    def _bind_scene_records(self, c, request, mapping, identity, viewpoint, reviewer):
        """Build append-only bind revisions for unverified passages in one scene."""
        scene_id = str(request.get('scene') or '').strip()
        if not scene_id and request.get('passage'):
            matched = next((b for b in mapping['beats'] if b['id'] == request['passage']), None)
            if matched is not None:
                scene_id = matched['scene_id']
        if not any(scene['id'] == scene_id for scene in mapping['scenes']):
            raise ValueError('Scene is missing')
        explicit_event_id = str(request.get('event') or '').strip() or None
        explicit = (explicit_event_id, *evidence(self.timeline, c, request['episode'], explicit_event_id, viewpoint)) if explicit_event_id else None
        text_counts = {}
        for item in mapping['beats']:
            text_counts[item['text']] = text_counts.get(item['text'], 0) + 1
        existing_heads = heads(c, request['episode'])
        records = []
        for item in mapping['beats']:
            if item['scene_id'] != scene_id or item['timing'] != 'unverified' or text_counts.get(item['text']) != 1:
                continue
            target_event_id = explicit_event_id or item.get('scene_inferred_event')
            if not target_event_id:
                continue
            _check_source_boundary(c, request['episode'], target_event_id, item)
            event_id, beat, digest = explicit if explicit else (target_event_id, *evidence(self.timeline, c, request['episode'], target_event_id, viewpoint))
            old = next((r for r in existing_heads if r['id'] == item['anchor']['id']), None)
            records.append({
                'id': old['id'] if old else 'anchor-' + uuid4().hex,
                'revision': old['revision'] + 1 if old else 1,
                'episode': request['episode'],
                'action': 'bind',
                'reviewer': reviewer,
                'viewpoint': viewpoint,
                'event': event_id,
                'beat': beat,
                'evidence_sha256': digest,
                'reason': 'reviewed_scene_bind' if explicit_event_id else 'reviewed_scene_propagation',
                'basis': basis(mapping, item, identity),
            })
        if not records:
            raise ValueError('Bind at least one passage in this scene or choose an approved event first')
        return records

    @staticmethod
    def _anchor_stacks(c, anchor_id):
        rows = c.execute(
            'SELECT revision, payload FROM passage_anchor_revisions WHERE id=? ORDER BY revision',
            (anchor_id,),
        ).fetchall()
        undo_stack = [None]
        redo_stack = []
        by_rev = {}
        for r in rows:
            payload = json.loads(r['payload'])
            by_rev[r['revision']] = payload
            op = payload.get('history_op', payload.get('action'))
            if op == 'undo':
                if len(undo_stack) > 1:
                    redo_stack.append(undo_stack.pop())
            elif op == 'redo':
                if redo_stack:
                    undo_stack.append(redo_stack.pop())
            else:
                undo_stack.append(r['revision'])
                redo_stack.clear()
        return undo_stack, redo_stack, by_rev

    def change(self, action, request):
        from .beat_map import map_episode
        if action not in ('bind', 'unbind', 'undo', 'redo', 'bind_scene'):
            raise ValueError('Unknown anchor action')
        history_op = action if action in ('undo', 'redo') else None
        reviewer = request.get('reviewer')
        if not isinstance(reviewer, str) or not 1 <= len(reviewer.strip()) <= 100:
            raise ValueError('A reviewer identity is required')
        viewpoint = request.get('viewpoint') or None
        if viewpoint is not None and (not isinstance(viewpoint, str) or not viewpoint.strip()):
            raise ValueError('Invalid viewpoint')
        bound_count = None
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            identity = verify_scope(c, project_id=request['project'], universe_id=request['universe'])
            mapping = map_episode(self.timeline, request['episode'], request['revision'], viewpoint=viewpoint, _connection=c)
            if request['branch'] != mapping['branch'] or request['source_sha256'] != mapping['source_sha256']:
                raise ValueError('Source or branch changed; refresh the beat map')
            if request.get('expected_token') != mapping['anchor_token']:
                raise ValueError('Anchor history changed; refresh before editing')
            if action == 'bind_scene':
                records = self._bind_scene_records(c, request, mapping, identity, viewpoint, reviewer.strip())
                self._insert_revisions(c, records)
                bound_count = len(records)
            else:
                passage = next((p for p in mapping['beats'] if p['id'] == request['passage']), None)
                if passage is None or passage['timing'] == 'ambiguous':
                    raise ValueError('Passage is missing or ambiguous')
                if sum(p['text'] == passage['text'] for p in mapping['beats']) != 1:
                    raise ValueError('Duplicate passage is ambiguous; clarify its saved text first')
                old = next((r for r in heads(c, request['episode']) if r['id'] == passage['anchor']['id']), None)
                if action != 'bind' and old is None:
                    raise ValueError('Passage has no binding history')
                event_id = request.get('event')
                restored = None
                if history_op is not None:
                    undo_stack, redo_stack, by_rev = self._anchor_stacks(c, old['id'])
                    if history_op == 'undo':
                        if len(undo_stack) <= 1:
                            raise ValueError('Nothing to undo for passage')
                        target_rev = undo_stack[-2]
                        restored = by_rev[target_rev] if target_rev is not None else None
                    else:
                        if not redo_stack:
                            raise ValueError('Nothing to redo for passage')
                        target_rev = redo_stack[-1]
                        restored = by_rev[target_rev]
                    action = restored['action'] if restored else 'unbind'
                    # Undo/redo cannot launder an old source assertion onto a new revision.
                    if restored and action == 'bind' and restored['basis'] != basis(mapping, passage, identity):
                        raise ValueError('Prior binding source is stale; use explicit rebind')
                    event_id = restored['event'] if restored else None
                if action == 'bind':
                    _check_source_boundary(c, request['episode'], event_id, passage)
                    beat, digest = evidence(self.timeline, c, request['episode'], event_id, viewpoint)
                else:
                    beat, digest = 0, None
                if history_op is not None and action == 'bind' and restored and digest != restored['evidence_sha256']:
                    raise ValueError('Prior binding evidence is stale; use explicit rebind')
                record = {'id': old['id'] if old else 'anchor-' + uuid4().hex,
                          'revision': old['revision'] + 1 if old else 1, 'episode': request['episode'],
                          'action': action, 'reviewer': reviewer.strip(), 'viewpoint': viewpoint,
                          'event': event_id if action == 'bind' else None, 'beat': beat, 'evidence_sha256': digest,
                          'basis': basis(mapping, passage, identity)}
                if history_op is not None:
                    record['history_op'] = history_op
                self._insert_revisions(c, [record])
        opened = self.open(request['episode'], request['revision'], viewpoint=viewpoint)
        if bound_count is not None:
            opened['bound_count'] = bound_count
        return opened
