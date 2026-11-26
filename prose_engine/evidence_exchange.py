"""Branch-scoped, metadata-only exchange with an independent mining app."""
from __future__ import annotations

import json
import re

from story_graph import scene_branches as branches, scene_fragments as f
from story_graph.universe_scope import checked_id, verify_scope

COMMANDS = frozenset('scene.exchange.' + name for name in ('offer', 'submit', 'receipt', 'list'))
SCOPE = ('project', 'universe', 'episode', 'branch', 'scope_revision')
TIMING_PAIR = ('depicted_three_to_one', 'payoff_hold')
APPEARANCE_FIELDS = ('wardrobe', 'silhouette', 'color', 'prop')
_TOKEN = re.compile(r'[A-Za-z0-9_:-]{1,140}')


def _token(value):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError('Expected a bounded source, job, Mind or evidence ID')
    return value


def _key(scope, result):
    return (*(scope[name] for name in SCOPE), result)


def _scope(request):
    return {k: checked_id(request[k], k.title()) for k in SCOPE[:-1]} | {
        'scope_revision': f._number(request['scope_revision'], 'Scope revision')}


def _admit(catalog):
    """Validate locally registered evidence, before making it available to Miner."""
    f._object(catalog, ('clip', 'evidence', 'draft', 'visual'))
    clip = f._object(catalog['clip'], ('id', 'sha256', 'duration_us'))
    _token(clip['id'])
    f._sha(clip['sha256'])
    duration = f._number(clip['duration_us'], 'Clip duration in microseconds', 1)
    seen = set()
    for item in f._items(catalog['evidence'], 'Evidence', 32):
        f._object(item, ('id', 'range_us', 'observation', 'method', 'actor_identity', 'speaker_identity'))
        ident = _token(item['id'])
        if ident in seen:
            raise ValueError('Duplicate registered evidence ID')
        seen.add(ident)
        start, end = f._items(item['range_us'], 'Source range', 2)
        f._range(start, end, duration)
        if (item['observation'], item['method']) not in (
                (TIMING_PAIR[0], 'sampled_boundary'), (TIMING_PAIR[1], 'sampled_extent')):
            raise ValueError('Only sampled visible transition and hold ranges can be registered')
        if item['actor_identity'] is not None or item['speaker_identity'] is not None:
            raise ValueError('This exchange does not establish donor actor or speaker identity')
    if not seen:
        raise ValueError('Register sampled evidence first')
    if catalog['visual'] is not None:
        visual = f._object(catalog['visual'], ('id', 'sha256', 'region'))
        _token(visual['id'])
        f._sha(visual['sha256'])
        left, top, right, bottom = f._items(visual['region'], 'Normalized visual region', 4)
        f._range(left, right, 10_000)
        f._range(top, bottom, 10_000)
    checked_id(catalog['draft'], 'Saved draft')
    return catalog


def _schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS scene_exchange_catalogs(
        project TEXT NOT NULL, universe TEXT NOT NULL, episode TEXT NOT NULL, branch TEXT NOT NULL,
        scope_revision INTEGER NOT NULL, result TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY(project,universe,episode,branch,scope_revision,result))""")
    c.execute("""CREATE TABLE IF NOT EXISTS scene_exchange_receipts(
        seq INTEGER PRIMARY KEY, project TEXT NOT NULL, universe TEXT NOT NULL, episode TEXT NOT NULL,
        branch TEXT NOT NULL, scope_revision INTEGER NOT NULL, result TEXT NOT NULL,
        id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, request_id TEXT NOT NULL,
        request_sha256 TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        UNIQUE(project,universe,episode,branch,scope_revision,result,kind,request_id),
        FOREIGN KEY(project,universe,episode,branch,scope_revision,result)
          REFERENCES scene_exchange_catalogs(project,universe,episode,branch,scope_revision,result))""")
    c.execute("""CREATE INDEX IF NOT EXISTS scene_exchange_page
        ON scene_exchange_receipts(project,universe,episode,branch,scope_revision,result,seq)""")


_WHERE = 'project=? AND universe=? AND episode=? AND branch=? AND scope_revision=? AND result=?'


def _current(timeline, c, scope, result):
    live, head = f.SceneFragmentStore._scope(c, scope)
    if scope != live:
        raise ValueError('The saved universe scope changed; open a new branch result')
    return branches.resolve(timeline, c, scope, head, result)


def install_catalog(timeline, scope, result, catalog):
    """Trusted local registration. There is no HTTP action to replace authority or evidence."""
    f._object(scope, SCOPE)
    scope = _scope(scope)
    checked_id(result, 'Saved branch result')
    raw = f.encoded(_admit(catalog))
    with timeline._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        _record, result_sha, _, _ = _current(timeline, c, scope, result)
        _writer(c, scope, result, result_sha, _record['world_sha256'], catalog['draft'])
        _schema(c)
        key = _key(scope, result)
        existing = c.execute('SELECT payload,sha256 FROM scene_exchange_catalogs WHERE '+_WHERE, key).fetchone()
        if existing:
            if (existing['payload'], existing['sha256']) != (raw, f.digest(raw)):
                raise ValueError('A different evidence catalog is already registered for that branch result')
        else:
            c.execute('INSERT INTO scene_exchange_catalogs VALUES(?,?,?,?,?,?,?,?)', (*key, raw, f.digest(raw)))


def install_appearance(timeline, scope, result, catalog):
    """Add versioned visual evidence without replacing the original timing authority."""
    f._object(scope, SCOPE)
    scope = _scope(scope)
    checked_id(result, 'Saved branch result')
    f._object(catalog, ('schema_version', 'image', 'evidence'))
    if type(catalog['schema_version']) is not int or catalog['schema_version'] != 1:
        raise ValueError('Use appearance catalog schema 1')
    image = f._object(catalog['image'], ('id', 'sha256', 'width', 'height'))
    _token(image['id'])
    f._sha(image['sha256'])
    if f._number(image['width'], 'Image width', 1) * f._number(image['height'], 'Image height', 1) > 20_000_000:
        raise ValueError('Choose an appearance image up to 20 megapixels')
    seen = set()
    for item in f._items(catalog['evidence'], 'Appearance evidence', 16):
        f._object(item, ('id', 'region', 'field', 'observation'))
        ident = _token(item['id'])
        if ident in seen or item['field'] not in APPEARANCE_FIELDS:
            raise ValueError('Use distinctly named, typed visible details')
        seen.add(ident)
        left, top, right, bottom = f._items(item['region'], 'Normalized image region', 4)
        f._range(left, right, 10_000)
        f._range(top, bottom, 10_000)
        if not f._label(item['observation'], 200).strip():
            raise ValueError('Enter a visible appearance observation')
    if not seen:
        raise ValueError('Register at least one observed region')
    raw = f.encoded(catalog)
    key = _key(scope, result)
    with timeline._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        record, stamp, _, _ = _current(timeline, c, scope, result)
        timing = c.execute('SELECT payload,sha256 FROM scene_exchange_catalogs WHERE '+_WHERE, key).fetchone() \
            if f._has(c, 'scene_exchange_catalogs') else None
        if not timing:
            raise ValueError('Register the original branch exchange catalog first')
        _writer(c, scope, result, stamp, record['world_sha256'], _checked(timing)['draft'])
        c.execute('''CREATE TABLE IF NOT EXISTS scene_exchange_appearance (
            project TEXT NOT NULL, universe TEXT NOT NULL, episode TEXT NOT NULL, branch TEXT NOT NULL,
            scope_revision INTEGER NOT NULL, result TEXT NOT NULL, timing_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY(project,universe,episode,branch,scope_revision,result),
            FOREIGN KEY(project,universe,episode,branch,scope_revision,result)
              REFERENCES scene_exchange_catalogs(project,universe,episode,branch,scope_revision,result))''')
        prior = c.execute('SELECT timing_sha256,payload,sha256 FROM scene_exchange_appearance WHERE '+_WHERE,
                          key).fetchone()
        if prior and tuple(prior) != (timing['sha256'], raw, f.digest(raw)):
            raise ValueError('A different appearance catalog is already registered for the saved result')
        if not prior:
            c.execute('INSERT INTO scene_exchange_appearance VALUES(?,?,?,?,?,?,?,?,?)',
                      (*key, timing['sha256'], raw, f.digest(raw)))
    return f.digest(raw)


def _checked(row):
    if f.digest(row['payload']) != row['sha256']:
        raise ValueError('Stored exchange data does not match its receipt digest')
    return json.loads(row['payload'])


def _writer(c, scope, result, result_sha, world_sha, draft_id):
    def read(ident):
        row = c.execute('SELECT status,payload FROM episode_drafts WHERE id=? AND episode=? AND branch=?',
                        (ident, scope['episode'], scope['branch'])).fetchone()
        if not row:
            raise ValueError('The registered writer receipt is unavailable in this branch')
        draft = json.loads(row['payload'])
        continuation = (draft.get('writing_context') or {}).get('continuation', {})
        if (draft.get('id') != ident or draft.get('project_id') != scope['project'] or
                draft.get('universe_id') != scope['universe'] or
                continuation.get('binding') != {'result': result, 'sha256': result_sha} or
                continuation.get('lineage', {}).get('world_sha256') != world_sha or
                not isinstance(draft.get('text'), str)):
            raise ValueError('The registered writer receipt does not match the saved branch result')
        return draft, {'draft': ident, 'status': checked_id(row['status'], 'Draft status'),
                       'provider': _token(draft['provider']), 'draft_text_sha256': f.digest(draft['text']),
                       'attempt_id': _token(draft['attempt_id']) if draft.get('attempt_id') else None}

    draft, view = read(draft_id)
    if parent := draft.get('parent'):
        _, view['parent'] = read(checked_id(parent, 'Parent draft'))
    return view


def _basis(timeline, c, scope, result, catalog, junctions):
    record, stamp, frame, _ = _current(timeline, c, scope, result)
    state = frame['state']
    cast = (junctions or {}).get(state['root'])
    links = {form.id: form.link for form in cast.forms} if cast else {}
    targets = []
    for manifestation in state['manifestations']:
        form, mind = manifestation['id'], manifestation['mind']
        link = links.get(form)
        if not link or link.kind != 'digital_mind' or link.node_id != mind:
            raise ValueError('The corresponding active Digital Mind link is missing or changed')
        targets.append({'form': checked_id(form, 'Active form'), 'mind': _token(mind)})
    if not targets:
        raise ValueError('The saved terminal frame has no active linked manifestations')
    return {'result_sha256': stamp, 'world_sha256': record['world_sha256'],
            'timeline_revision': record['timeline_revision'], 'law_revision': record['law_revision'],
            'terminal_event': checked_id(record['terminal_event'], 'Terminal event'),
            'frozen_dialogue_sha256': f._sha(record['exact_dialogue']['sha256']),
            'targets': targets, 'writer': _writer(c, scope, result, stamp, record['world_sha256'], catalog['draft'])}


def _card(request, offer):
    job = f._object(request['source_job'], ('id', 'sha256'))
    # This is source provenance, not a new authority or identity assertion.
    if job['sha256'] != offer['clip']['sha256'] or _token(job['id']) != 'mining:job:'+job['sha256'][:16]:
        raise ValueError('Miner job source does not match the offered clip edition')
    target = f._object(request['target'], ('form', 'mind'))
    if target not in offer['basis']['targets']:
        raise ValueError('Choose an exact form and Mind active in this saved result')
    if request['cue'] != 'hold_after_change':
        raise ValueError('This exchange accepts only the typed hold-after-change timing cue')
    evidence = f._items(request['evidence'], 'Cited evidence', 2)
    indexed = {item['id']: item for item in offer['evidence']}
    cited = [indexed.get(_token(ident)) for ident in evidence]
    if (len(cited) != 2 or not all(cited) or tuple(x['observation'] for x in cited) != TIMING_PAIR or
            cited[0]['range_us'][1] > cited[1]['range_us'][0]):
        raise ValueError('Cite a registered transition followed by a distinct sampled hold on the same file clock')
    visual = offer['visual']
    if request['visual'] is not None and (not visual or request['visual'] != visual['id']):
        raise ValueError('Choose only the registered visual reference')
    start, end = cited[1]['range_us']
    return {'kind': 'timing', 'cue': request['cue'], 'target': target, 'source_job': job, 'evidence': cited,
            'observed_hold_us': end - start, 'visual': visual if request['visual'] else None,
            'use': 'timing_only', 'influence': 'proposed', 'writes_canon': False}


def _appearance_card(request, offer):
    image = offer['image']
    job = f._object(request['source_job'], ('id', 'sha256'))
    if job != {'id': 'mining:job:'+image['sha256'][:16], 'sha256':image['sha256']}:
        raise ValueError('Miner job source does not match the offered image')
    target = f._object(request['target'], ('form', 'mind'))
    if target not in offer['basis']['targets']:
        raise ValueError('Choose an exact form and Mind active in this saved result')
    cited = f._items(request['evidence'], 'Cited appearance region', 1)
    evidence = next((item for item in offer['evidence'] if cited == [item['id']]), None)
    if not evidence or request['cue'] != 'observe_appearance' or request['visual'] != image['id']:
        raise ValueError('Cite one registered appearance observation and its original image')
    return {'kind':'appearance', 'cue':request['cue'], 'target':target, 'source_job':job, 'evidence':[evidence],
            'visual':{'id':image['id'], 'sha256':image['sha256'], 'region':evidence['region']},
            'use':'appearance_only', 'influence':'proposed', 'writes_canon':False}


def _envelope(row, state):
    receipt = _checked(row)
    return {'receipt': receipt, 'sha256': row['sha256'], 'state': state}


def _find(c, key, ident, *, kind=None):
    checked_id(ident, 'Exchange receipt')
    row = c.execute('SELECT * FROM scene_exchange_receipts WHERE '+_WHERE+' AND id=?', (*key, ident)).fetchone()
    if not row or (kind and row['kind'] != kind):
        raise LookupError('Exchange receipt was not found in this saved branch')
    return row


def execute(timeline, action, request, *, junctions=None):
    if action not in COMMANDS:
        raise ValueError('Unknown scene exchange action')
    command = action.rsplit('.', 1)[1]
    required = {
        'offer': ('request_id',), 'submit': ('request_id', 'offer', 'offer_sha256', 'source_job', 'target',
                                            'cue', 'evidence', 'visual'),
        'receipt': ('receipt',), 'list': (),
    }
    optional = ('after', 'limit') if command == 'list' else ('protocol', 'purpose') if command in ('offer', 'submit') else ()
    f._object(request, (*SCOPE, 'result', *required[command]), optional)
    protocol = request.get('protocol', 1)
    purpose = request.get('purpose', 'timing')
    if type(protocol) is not int or (protocol, purpose) not in ((1, 'timing'), (2, 'appearance')):
        raise ValueError('Use protocol 1 for timing or protocol 2 for appearance')
    scope, result = _scope(request), checked_id(request['result'], 'Saved branch result')
    key = _key(scope, result)
    write = command in ('offer', 'submit')
    with timeline._connect() as c:
        c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        verify_scope(c, project_id=scope['project'], universe_id=scope['universe'])
        catalog_row = c.execute('SELECT payload,sha256 FROM scene_exchange_catalogs WHERE '+_WHERE,
                                key).fetchone() if f._has(c, 'scene_exchange_catalogs') else None
        if not catalog_row:
            raise LookupError('No exchange is registered for that saved branch')
        if command == 'receipt':
            return _envelope(_find(c, key, request['receipt']), 'OPENED')
        if command == 'list':
            after = f._number(request.get('after', 0), 'Page cursor')
            limit = f._number(request.get('limit', 20), 'Page limit', 1)
            if limit > 64 or after > 2**63-1:
                raise ValueError('Use a bounded exchange page')
            rows = c.execute('SELECT seq,id,kind,sha256 FROM scene_exchange_receipts WHERE '+_WHERE+
                             ' AND seq>? ORDER BY seq LIMIT ?', (*key, after, limit+1)).fetchall()
            return {'receipts': [{k: row[k] for k in ('id', 'kind', 'sha256')} for row in rows[:limit]],
                    'next': rows[limit-1]['seq'] if len(rows) > limit else None}
        ident = checked_id(request['request_id'], 'Exchange request ID')
        request_sha = f.digest(f.encoded(request))
        prior = c.execute('SELECT * FROM scene_exchange_receipts WHERE '+_WHERE+' AND kind=? AND request_id=?',
                          (*key, command, ident)).fetchone()
        if prior:
            if prior['request_sha256'] != request_sha:
                raise ValueError('Exchange request ID is already bound to different data')
            return _envelope(prior, 'REPLAYED')
        catalog = _checked(catalog_row)
        appearance = None
        if protocol == 2:
            registered = c.execute('SELECT payload,sha256 FROM scene_exchange_appearance WHERE '+_WHERE+
                                   ' AND timing_sha256=?', (*key, catalog_row['sha256'])).fetchone() \
                if f._has(c, 'scene_exchange_appearance') else None
            if not registered:
                raise LookupError('No appearance evidence is registered for that saved branch result')
            appearance = _checked(registered)
        if command == 'submit':
            row = _find(c, key, request['offer'], kind='offer')
            if f._sha(request['offer_sha256']) != row['sha256']:
                raise ValueError('The offer digest must match the stored receipt')
            offer = _checked(row)
            if offer['protocol'] != protocol or offer.get('purpose', 'timing') != purpose:
                raise ValueError('The proposal must use the offered evidence protocol and purpose')
            card = _appearance_card(request, offer) if appearance else _card(request, offer)
        basis = _basis(timeline, c, scope, result, catalog, junctions() if junctions else None)
        body = {'protocol': protocol, 'id': f._id('scene-exchange', *key, command, ident),
                'kind': command, 'request_id': ident, 'scope': scope, 'result': result, 'basis': basis,
                'catalog_sha256': catalog_row['sha256'], 'provider_calls': 0, 'writes_canon': False}
        if appearance:
            body |= {'purpose':'appearance', 'appearance_sha256':registered['sha256']}
        if command == 'offer':
            if appearance:
                body |= {'image':appearance['image'], 'evidence':appearance['evidence']}
            else:
                body |= {'clip': catalog['clip'] | {'clock': 'file_pts'}, 'evidence': catalog['evidence'],
                         'visual': catalog['visual']}
        else:
            if (basis != offer['basis'] or catalog_row['sha256'] != offer['catalog_sha256'] or
                    body.get('appearance_sha256') != offer.get('appearance_sha256')):
                raise ValueError('The branch, Mind links, writer receipt or evidence changed after this offer')
            body |= {'offer': {'id': row['id'], 'sha256': row['sha256']}, 'card': card,
                     'unresolved_identities': len(card['evidence'])}
        payload = f.encoded(body)
        stamp = f.digest(payload)
        c.execute("""INSERT INTO scene_exchange_receipts
            (project,universe,episode,branch,scope_revision,result,id,kind,request_id,request_sha256,payload,sha256)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (*key, body['id'], command, ident, request_sha, payload, stamp))
        return {'receipt': body, 'sha256': stamp, 'state': 'SAVED'}
