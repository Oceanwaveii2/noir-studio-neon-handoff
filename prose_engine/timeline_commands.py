"""Shared, revision-checked Timeline operations and immutable commit receipts."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
import re

from story_graph.director import fingerprint
from story_graph.universe_scope import verify_scope
from .notebook import DraftStore, NotebookStore

EPISODE_FIELDS = ('id', 'title', 'branch', 'position', 'status', 'head')
MUTATIONS = frozenset({
    'timeline.move', 'timeline.rename', 'timeline.cover.set', 'timeline.archive', 'timeline.restore',
    'timeline.undo', 'timeline.redo',
})
GUARDED = frozenset({'timeline.move', 'timeline.rename', 'timeline.archive'})
ACTIONS = MUTATIONS | {'timeline.catalog', 'timeline.history', 'timeline.cover.open', 'timeline.preview'}
_KEY = re.compile(r'[A-Za-z0-9_.:-]{1,125}\Z')
_MIME = {'PNG':'image/png', 'JPEG':'image/jpeg', 'WEBP':'image/webp'}


def revision(request, key):
    value = request.get(key)
    if type(value) is not int or value < 0:
        raise ValueError(f'Saved {key} is required')
    return value


def cover_version(value):
    return sha256(value.encode('utf-8')).hexdigest() if value else None


def cover_image(timeline, value):
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError('Cover decoding is unavailable in this installation.') from exc

    timeline._validate_cover(value)
    header, encoded = value.split(',', 1)
    try:
        with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as image:
            if (header != 'data:'+_MIME.get(image.format, '')+';base64'
                    or not 0 < image.width*image.height <= 20_000_000
                    or getattr(image, 'n_frames', 1) != 1):
                raise ValueError('Choose a still PNG, JPEG or WebP image under 20 megapixels.')
            image.load()
            return image.copy()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError('The selected file is not a complete cover image.') from exc


def catalog_in_conn(timeline, c, *, details=False):
    scope = verify_scope(c)
    history = timeline._history_summary(*timeline._action_history_stacks(c))
    rows = c.execute("SELECT * FROM episodes WHERE status!='archived' ORDER BY branch,position,id").fetchall()
    branches = [dict(row) for row in c.execute('SELECT * FROM branches ORDER BY id')]
    result = {'episodes': [
        {**{k:r[k] for k in EPISODE_FIELDS}, 'cover_version':cover_version(r['cover']),
         'embedded_cover':bool(r['cover'] and r['cover'].startswith('data:image/'))}
        for r in rows], 'branches':[b['id'] for b in branches], 'workspace':scope, 'history':history}
    if details:
        repairs = timeline.repair_flags(c)
        archived = c.execute("SELECT * FROM episodes WHERE status='archived' ORDER BY branch,position,id")
        result.update(cards=[dict(row, cover_version=cover_version(row['cover']), timeline_repair=repairs.get(row['id'], []))
                             for row in timeline._cards_in_conn(c)], branch_records=branches,
                      archived_cards=[dict(row) for row in archived])
    return result


def _verify(c, request):
    return verify_scope(c, project_id=request.get('project'), universe_id=request.get('universe'))


def _episode(c, request, timeline, *, restore=False):
    episode, branch = request.get('episode'), request.get('branch')
    timeline._required(episode, 'episode')
    timeline._required(branch, 'branch')
    row = c.execute('SELECT * FROM episodes WHERE id=?', (episode,)).fetchone() if restore else timeline._require_active(c, episode)
    if row is None or row['branch'] != branch:
        raise ValueError('That episode is on a different branch or no longer exists.')
    return row


def execute(timeline, action, request, *, junctions=None):
    if action == 'timeline.history':
        return timeline.history_state()
    if action == 'timeline.preview':
        command = request.get('command')
        if not isinstance(command, str) or command not in GUARDED:
            raise ValueError('Choose an episode move, rename, or soft-removal to preview')
        with timeline._connect() as c:
            c.execute('BEGIN')
            scope = _verify(c, request)
            return _preview(timeline, c, command, request, scope)
    if action in ('timeline.catalog', 'timeline.cover.open'):
        with timeline._connect() as c:
            c.execute('BEGIN')
            _verify(c, request)
            if action == 'timeline.catalog':
                return catalog_in_conn(timeline, c, details=request.get('details') is True)
            row = _episode(c, request, timeline)
            value = row['cover']
            version = cover_version(value)
            if not value or not value.startswith('data:image/') or version != request.get('cover_version'):
                raise ValueError('This cover changed or has no embedded image.')
        picture = cover_image(timeline, value).convert('RGBA')
        picture.thumbnail((540, 360))
        out = BytesIO()
        picture.save(out, format='PNG')
        return {'version':version, 'png':base64.b64encode(out.getvalue()).decode('ascii')}
    if action not in MUTATIONS:
        raise ValueError('Unknown timeline command')
    return _mutate(timeline, action, request, junctions)


def _preview(timeline, c, action, request, scope):
    expected = revision(request, 'expected_revision')
    if timeline._action_history_stacks(c)[0] != expected:
        raise ValueError('Timeline changed elsewhere. Refresh and try again.')
    row = _episode(c, request, timeline)
    placement = {key: request[key] for key in ('after', 'direction', 'position') if request.get(key) is not None}
    report = timeline.timeline_impact(c, action, row['id'], revision(request, 'episode_revision'), placement)
    if action == 'timeline.rename':
        title = request.get('title')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 160 or not title.isprintable():
            raise ValueError('Use a printable episode title up to 160 characters')
        report['proposed_title'] = title.strip()
    report['command'] = action
    report['episode'] = row['id']
    report['token'] = fingerprint([scope, expected, row['head'], placement, report])
    return report


def _mutate(timeline, action, request, junctions):
    expected = revision(request, 'expected_revision')
    undo_redo = action in ('timeline.undo', 'timeline.redo')
    fields = {'expected_revision':expected}
    if not undo_redo:
        fields.update(episode=request.get('episode'), branch=request.get('branch'),
                      episode_revision=revision(request, 'episode_revision'))
    if action == 'timeline.move':
        placement = {k:request[k] for k in ('after','direction','position') if request.get(k) is not None}
        if len(placement) != 1:
            raise ValueError('Specify one placement target, direction, or position')
        fields.update(placement)
    if action == 'timeline.cover.set':
        fields.update(cover=request['cover'], cover_version=request['cover_version'])
    if action == 'timeline.rename':
        fields.update(title=request.get('title'))
    if request.get('preview_token') is not None:
        fields.update(preview_token=request['preview_token'], disconnect=request.get('disconnect') is True)
    checksum = fingerprint([action, fields])
    key = request.get('request_id', checksum)
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError('Invalid timeline request ID')
    # Form and notebook stores are prepared outside the write lock. The actual
    # history transition and its receipt are committed in the same transaction.
    drafts = DraftStore(NotebookStore(timeline)) if undo_redo else None
    forms = junctions() if undo_redo and junctions else None
    with timeline._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        scope = _verify(c, request)
        c.execute('''CREATE TABLE IF NOT EXISTS timeline_command_receipts(
            key TEXT PRIMARY KEY, checksum TEXT NOT NULL, outcome TEXT NOT NULL)''')
        previous = c.execute('SELECT checksum,outcome FROM timeline_command_receipts WHERE key=?', (key,)).fetchone()
        if previous:
            if previous['checksum'] != checksum:
                raise ValueError('This request ID already belongs to a different timeline change')
            receipt = json.loads(previous['outcome'])
            return _result(receipt, catalog_in_conn(timeline, c), replayed=True)
        if timeline._action_history_stacks(c)[0] != expected:
            raise ValueError('Timeline changed elsewhere. Refresh and try again.')
        if undo_redo:
            name = action.removeprefix('timeline.')
            outcome = timeline._step_history_locked(c, -1 if name=='undo' else 1, expected_revision=expected,
                junctions=forms, on_draft_favorite=drafts._apply_history_favorite_in_conn)
            episode, kind, notice = (outcome[k] for k in ('episode_id','kind','notice'))
            # Cover images already live in the history table; never duplicate the
            # image bytes in an operation receipt or a lightweight response.
            item = {k:v for k,v in outcome['item'].items() if k not in ('cover','previous_cover')}
        else:
            row = _episode(c, fields, timeline, restore=action=='timeline.restore')
            episode = row['id']
            if row['head'] != fields['episode_revision']:
                raise ValueError('Episode changed; refresh and try again')
            name = kind = action.rsplit('.', 1)[1]
            item = {'kind':kind, 'id':episode}
            flags = []
            if action in GUARDED:
                preview = _preview(timeline, c, action, fields, scope)
                token = fields.get('preview_token')
                if token is not None and token != preview['token']:
                    raise ValueError('Timeline impact changed. Open a new preview.')
                if preview['hard_locks']:
                    raise ValueError(preview['hard_locks'][0])
                flags = preview['broken_edges']
                if flags and (token is None or not fields.get('disconnect')):
                    raise ValueError('Preview the timeline impact and choose whether to disconnect the blocking links.')
            if action == 'timeline.move':
                timeline._move_episode_locked(c, episode, row['head'], **placement)
                notice = 'Episode order saved.'
            elif action == 'timeline.rename':
                title = preview['proposed_title']
                if title != row['title']:
                    c.execute('UPDATE episodes SET title=? WHERE id=?', (title, episode))
                    timeline._push_history_locked(c, {**item, 'title': title, 'previous_title': row['title']})
                notice = 'Episode title saved.'
            elif action == 'timeline.cover.set':
                if cover_version(row['cover']) != fields['cover_version']:
                    raise ValueError('The cover changed. Refresh and try again.')
                cover_image(timeline, fields['cover'])
                timeline._set_cover_locked(c, episode, row['head'], row['cover'], fields['cover'])
                name = kind = 'cover'
                item['kind'] = kind
                notice = 'Cover saved.'
            else:
                archive = action == 'timeline.archive'
                timeline._set_archived_locked(c, episode, row['head'], archive)
                notice = 'Episode removed.' if archive else 'Episode restored.'
            if flags:
                timeline._set_disconnected_flags(c, flags, disconnected=True)
                tip, undo, redo = timeline._action_history_stacks(c)
                undo[-1]['disconnected_flags'] = flags
                timeline._write_action_history(c, tip, undo, redo)
                item['disconnected_flags'] = flags
        state = catalog_in_conn(timeline, c)
        tip = state['history']['revision']
        receipt = {'id':key, 'request_action':action, 'action':name, 'kind':kind, 'episode_id':episode,
                   'notice':notice, 'timeline_history_revision':tip, 'changed':tip != expected, 'item':item}
        c.execute('INSERT INTO timeline_command_receipts VALUES(?,?,?)',
                  (key, checksum, json.dumps(receipt, ensure_ascii=False, allow_nan=False)))
        return _result(receipt, state)


def _result(receipt, state, *, replayed=False):
    return {**{k:receipt[k] for k in ('action','kind','episode_id','notice','changed','item')},
            'status':'REPLAYED' if replayed else 'APPLIED', 'receipt':receipt,
            'state':state, 'history':state['history'], 'episode':receipt['episode_id']}
