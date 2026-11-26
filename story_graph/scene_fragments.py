"""Versioned, source-bound scene graphs. Import never applies story effects."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
import hashlib
import json
import re

from .beat_map import map_episode
from .universe_scope import checked_id, verify_scope


VERSION = 1
MAX_BYTES = 80_000
MAX_ITEMS = 250
MAX_EDGES = 750
NODE_KINDS = frozenset({'heading', 'narration', 'dialogue', 'direction', 'event', 'reference', 'unclassified'})
ORDERING = frozenset({'sequence', 'requires', 'causes'})
EDGE_KINDS = ORDERING | {'reveals', 'influences'}
COMMANDS = frozenset('scene.fragment.' + a for a in ('scenes', 'list', 'preview', 'import', 'open', 'export', 'rebind'))
_CUE = re.compile(r"^([\w][\w .’'\-]{0,46}):[ \t]*\S", re.UNICODE)
_SHA = re.compile(r'[a-f0-9]{64}')
_SLUGLINE = re.compile(r"^(?:#{1,6}\s+)?\**(INT/EXT\.|EXT/INT\.|I/E\.|INT\.|EXT\.)[ \t]+(.+)", re.I)
_DAY_PART = re.compile(
    r"\s+[-–—]\s+(?:day|night|dawn|dusk|morning|afternoon|evening|continuous|later|sunset|sunrise|\d{1,2}:\d{2})\b",
    re.I,
)


def _location(title):
    """Only a reported slugline supplies a location."""
    match = _SLUGLINE.match(title)
    if not match:
        return None
    setting = _DAY_PART.split(match[2].rstrip('*'), maxsplit=1)[0].strip()
    return {'label':setting, 'slugline':title, 'side':match[1].upper()} if setting else None


class SceneFragmentError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def encoded(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('Scene graph must be valid JSON') from exc


def _id(prefix, *basis):
    return prefix + '-' + digest(encoded(basis))[:32]


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('Expected scene fields: ' + ', '.join(required))
    return value


def _items(value, label, limit=MAX_ITEMS):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f'{label} must be a list with at most {limit} entries')
    return value


def _indexed(value, label, validate):
    rows = {}
    for item in _items(value, label):
        row = validate(item)
        key = checked_id(row['id'], f'{label} ID')
        if key in rows:
            raise SceneFragmentError('duplicate_id', f'Duplicate {label} ID: {key}')
        rows[key] = row
    return rows


def _label(value, limit=180):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValueError(f'Graph labels must contain 1–{limit} characters')
    return value


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('Expected an exact SHA-256 fingerprint')
    return value


def _number(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer ≥ {minimum}')
    return value


def _range(start, end, limit):
    start = _number(start, 'Range start')
    end = _number(end, 'Range end')
    if not start < end <= limit:
        raise ValueError('Scene range must fit its exact source')
    return start, end


def _whole_lines(text, start, end):
    # CRLF is one separator even though stored offsets are Unicode code points.
    if any(0 < x < len(text) and text[x-1:x+1] == '\r\n' for x in (start, end)):
        return False
    return ((start == 0 or text[start-1] in '\r\n') and
            (end == len(text) or text[end] in '\r\n' or text[end-1] in '\r\n'))


def _selection(text, start, end):
    start, end = _range(start, end, len(text))
    if not _whole_lines(text, start, end):
        raise SceneFragmentError('partial_line', 'Select complete source lines or choose a mapped scene')
    target = text[start:end]
    if not target.strip() or len(target.encode('utf-8')) > MAX_BYTES:
        raise ValueError(f'Scene needs nonempty source text of at most {MAX_BYTES} UTF-8 bytes')
    return target


def _evidence(value):
    row = _object(value, ('id', 'asset', 'sha256', 'selector', 'use'),
                  ('label', 'observation', 'source_window_ms'))
    checked_id(row['asset'], 'Asset ID')
    _sha(row['sha256'])
    if row['use'] not in ('structure', 'timing', 'appearance', 'preview'):
        raise ValueError('Choose a supported source use')
    if 'label' in row:
        _label(row['label'])
    if 'observation' in row:
        _label(row['observation'], 380)
    if 'source_window_ms' in row:
        bounds = _items(row['source_window_ms'], 'Original source time range', 2)
        if len(bounds) != 2:
            raise ValueError('Enter the start and end on the original source clock')
        _range(*bounds, 86_400_000)
    sel = row['selector']
    if isinstance(sel, dict) and sel.get('kind') == 'clip':
        _object(sel, ('kind', 'clock', 'track', 'unit', 'start', 'end'))
        if sel['clock'] != 'file_pts' or sel['unit'] != 'ms':
            raise ValueError('Clip selector must use the registered file clock in milliseconds')
        checked_id(sel['track'], 'Track ID')
        _range(sel['start'], sel['end'], 86_400_000)
    else:
        _object(sel, ('kind', 'region', 'unit'))
        xywh = sel['region']
        if (sel['kind'] != 'diagram' or sel['unit'] != 'fraction_10000' or not isinstance(xywh, list)
                or len(xywh) != 4 or any(type(v) is not int or not 0 <= v <= 10_000 for v in xywh)
                or min(xywh[2:]) == 0 or xywh[0]+xywh[2] > 10_000 or xywh[1]+xywh[3] > 10_000):
            raise ValueError('Diagram needs an in-bounds region in 1/10000 units')
    return row


def _references(values, known, label):
    seen = set()
    for key in _items(values, label):
        key = checked_id(key, label)
        if key not in known:
            raise SceneFragmentError('unknown_reference', f'Unknown {label}: {key}')
        if key in seen:
            raise SceneFragmentError('duplicate_id', f'Duplicate {label}: {key}')
        seen.add(key)


def _check_dag(nodes, edges):
    next_nodes = {key: [] for key in nodes}
    incoming = dict.fromkeys(nodes, 0)
    for edge in edges:
        if edge['kind'] in ORDERING:
            # A requires B means B must be considered before A.
            a, b = ((edge['to'], edge['from']) if edge['kind'] == 'requires'
                    else (edge['from'], edge['to']))
            next_nodes[a].append(b)
            incoming[b] += 1
    ready = deque(k for k, count in incoming.items() if count == 0)
    count = 0
    while ready:
        count += 1
        for after in next_nodes[ready.popleft()]:
            incoming[after] -= 1
            if not incoming[after]:
                ready.append(after)
    if count != len(nodes):
        raise SceneFragmentError('causal_cycle', 'Scene graph contains a sequence or dependency cycle')


def validate_declaration(value, target, catalog):
    """Declarative interchange payloads contain data only, never runtime effects."""
    _object(value, ('schema_version', 'title', 'passages', 'roles', 'nodes', 'edges', 'evidence'))
    if type(value['schema_version']) is not int or value['schema_version'] != VERSION:
        raise ValueError('Unsupported scene graph schema version')
    if len(encoded(value).encode('utf-8')) > MAX_BYTES:
        raise ValueError(f'Scene graph exceeds {MAX_BYTES} UTF-8 bytes')
    _label(value['title'])

    def passage(row):
        _object(row, ('id', 'start', 'end', 'sha256'))
        a, b = _range(row['start'], row['end'], len(target))
        if not target[a:b].strip() or digest(target[a:b]) != _sha(row['sha256']):
            raise SceneFragmentError('passage_mismatch', 'Passage does not match its exact source text')
        return row

    def role(row):
        _object(row, ('id', 'label'), ('character_hint', 'form_hint'))
        _label(row['label'])
        for key in ('character_hint', 'form_hint'):
            if key in row:
                checked_id(row[key], key)
        if 'form_hint' in row and 'character_hint' not in row:
            raise ValueError('A form hint needs a character hint')
        return row

    passages = _indexed(value['passages'], 'passage', passage)
    roles = _indexed(value['roles'], 'role', role)
    sources = _indexed(value['evidence'], 'evidence', _evidence)
    for key, row in sources.items():
        saved = catalog.get(key)
        if saved is None:
            raise SceneFragmentError('unregistered_evidence', f'Evidence is not registered for this episode: {key}')
        if saved['sha256'] != row['sha256']:
            raise SceneFragmentError('wrong_edition', f'Evidence edition does not match the registered file: {key}')
        if saved != row:
            raise SceneFragmentError('selector_mismatch', f'Evidence selector or permitted use differs from the registered source: {key}')

    def node(row):
        _object(row, ('id', 'kind', 'label', 'passage', 'roles', 'evidence'))
        if not isinstance(row['kind'], str) or row['kind'] not in NODE_KINDS:
            raise ValueError('Unsupported scene node kind')
        _label(row['label'])
        _references(row['roles'], roles, 'role')
        _references(row['evidence'], sources, 'evidence')
        if row['kind'] == 'reference':
            if row['passage'] is not None or not row['evidence']:
                raise ValueError('A reference node needs evidence and has no destination passage')
        else:
            _references([row['passage']], passages, 'passage')
        return row

    nodes = _indexed(value['nodes'], 'node', node)
    if not passages or not any(n['kind'] != 'reference' for n in nodes.values()):
        raise ValueError('A graph needs a destination passage and a source-bound node')
    seen = set()
    for edge in _items(value['edges'], 'edges', MAX_EDGES):
        _object(edge, ('from', 'to', 'kind'))
        _references([edge['from']], nodes, 'node')
        _references([edge['to']], nodes, 'node')
        kind = edge['kind']
        if not isinstance(kind, str) or kind not in EDGE_KINDS or edge['from'] == edge['to']:
            raise ValueError('Choose a valid edge between distinct nodes')
        if kind != 'influences' and any(nodes[edge[k]]['kind'] == 'reference' for k in ('from', 'to')):
            raise SceneFragmentError('reference_effect', 'Source references can influence a scene; they cannot become destination events')
        key = (edge['from'], edge['to'], kind)
        if key in seen:
            raise ValueError('Duplicate scene edge')
        seen.add(key)
    _check_dag(nodes, value['edges'])
    return value


def _saved_metadata(c, episode, revision, script):
    if not _has(c, 'notebook_heads'):
        return []
    row = c.execute('''SELECT r.payload FROM notebook_heads h JOIN notebook_revisions r
                      ON r.episode=h.episode AND r.revision=h.head
                      WHERE h.episode=? AND r.timeline_revision=?''', (episode, revision)).fetchone()
    if not row:
        return []
    blocks = json.loads(row['payload'])['blocks']
    if ''.join(b['text'] for b in blocks) != script:
        return []
    cursor, spans = 0, []
    for b in blocks:
        end = cursor + len(b['text'])
        if end > cursor:
            spans.append((cursor, end, b))
        cursor = end
    return spans


def _automatic(mapping, text, start, end, title, blocks):
    bounds = [(b['start'], b['end'], False) for b in mapping['beats']]
    for scene in mapping['scenes']:
        if heading := scene.get('heading_range'):
            bounds.append((heading['start'], heading['end'], True))
    offsets = [x[0] for x in blocks]
    # Paragraph geometry sets the scene window. A saved notebook can still
    # contain separate dialogue and narration blocks inside one paragraph.
    parts = []
    for a, b, heading in sorted(bounds):
        a, b = max(a, start), min(b, end)
        if a >= b:
            continue
        cuts = [] if heading else [x for x in offsets[bisect_right(offsets, a):bisect_left(offsets, b)]
                                    if text[x-1:x+1] != '\r\n']
        points = [a, *cuts, b]
        parts.extend((lo, hi, heading) for lo, hi in zip(points, points[1:]))
    passages, nodes, roles, edges = [], [], {}, []
    kinds = {'narrator': 'narration', 'character': 'dialogue',
             'scene-heading': 'heading', 'stage-direction': 'direction'}
    for a, b, heading in parts:
        raw = text[a:b]
        if not raw.strip():
            continue
        i = bisect_right(offsets, a) - 1
        block = blocks[i][2] if i >= 0 and b <= blocks[i][1] else {}
        cue = _CUE.match(raw.strip()) if not heading else None
        kind = 'heading' if heading else kinds.get(block.get('kind'), 'dialogue' if cue else 'unclassified')
        actor = block.get('speaker') if kind == 'dialogue' else None
        actor = actor if isinstance(actor, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', actor) else None
        label = block.get('cue_label') or (cue[1] if cue else (actor.replace('_', ' ').title() if actor else None))
        assigned = []
        if kind == 'dialogue' and label:
            form = block.get('form') if actor else None
            rid = _id('cue', actor or label.casefold(), form)
            row = {'id': rid, 'label': label}
            if actor:
                row['character_hint'] = actor
            if isinstance(form, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', form):
                row['form_hint'] = form
            roles.setdefault(rid, row)
            assigned = [rid]
        passage, node = f'p{len(passages)+1}', f'n{len(nodes)+1}'
        passages.append({'id': passage, 'start': a-start, 'end': b-start, 'sha256': digest(raw)})
        if nodes:
            edges.append({'from': nodes[-1]['id'], 'to': node, 'kind': 'sequence'})
        nodes.append({'id': node, 'kind': kind, 'label': raw.strip().splitlines()[0][:150],
                      'passage': passage, 'roles': assigned, 'evidence': []})
    return {'schema_version': VERSION, 'title': title, 'passages': passages, 'nodes': nodes,
            'roles': list(roles.values()), 'edges': edges, 'evidence': []}


def _has(c, table):
    return c.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone() is not None


class SceneFragmentStore:
    def __init__(self, timeline):
        self.timeline = timeline

    @staticmethod
    def _scope(c, request):
        scope = {k: checked_id(request.get(k), k.title()) for k in ('project', 'universe', 'episode', 'branch')}
        identity = verify_scope(c, project_id=scope['project'], universe_id=scope['universe'])
        ep = c.execute('SELECT head,branch,status FROM episodes WHERE id=?', (scope['episode'],)).fetchone()
        if ep is None or ep['branch'] != scope['branch'] or ep['status'] == 'archived':
            raise SceneFragmentError('wrong_scope', 'Scene fragment requires an open episode on its saved branch')
        return scope | {'scope_revision': identity['scope_revision']}, ep['head']

    @staticmethod
    def _source(c, episode, revision):
        row = c.execute('SELECT script,script_sha256 FROM revisions WHERE episode=? AND revision=?',
                        (episode, revision)).fetchone()
        if row is None or digest(row['script']) != row['script_sha256']:
            raise SceneFragmentError('source_digest', 'Episode source is missing or does not match its saved fingerprint')
        return row['script'], row['script_sha256']

    @staticmethod
    def _current(request, head):
        rev = _number(request.get('timeline_revision'), 'Saved timeline revision')
        if rev != head:
            raise SceneFragmentError('stale_timeline', 'Episode changed; use its current saved revision')
        return rev

    @staticmethod
    def _scene_ranges(mapping):
        beats = {p['id']: p for p in mapping['beats']}
        for scene in mapping['scenes']:
            parts = [beats[p] for p in scene['beats']]
            if h := scene.get('heading_range'):
                parts = [h, *parts]
            if parts:
                yield {'id': scene['id'], 'title': scene['title'][:180],
                       'start': parts[0]['start'], 'end': parts[-1]['end']}

    @staticmethod
    def _catalog(c, episode):
        if not _has(c, 'scene_fragment_evidence'):
            return {}
        return {r['id']: json.loads(r['payload']) for r in c.execute(
            'SELECT id,payload FROM scene_fragment_evidence WHERE episode=?', (episode,))}

    def register_evidence(self, request, records):
        """Trusted local ingest: verify media outside the importer before registering selectors.

        This is intentionally absent from public commands. No user request can name a file.
        """
        source = _indexed(records, 'evidence', _evidence)
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            scope, _ = self._scope(c, request)
            previous = self._catalog(c, scope['episode'])
            if any(k in previous and previous[k] != v for k, v in source.items()):
                raise ValueError('Registered evidence is immutable; use a new evidence ID for a different edition or selector')
            c.execute('''CREATE TABLE IF NOT EXISTS scene_fragment_evidence(
                         episode TEXT NOT NULL REFERENCES episodes(id), id TEXT NOT NULL,
                         payload TEXT NOT NULL, PRIMARY KEY(episode,id))''')
            c.executemany('INSERT INTO scene_fragment_evidence VALUES(?,?,?)',
                          ((scope['episode'], k, encoded(v)) for k, v in source.items() if k not in previous))

    @staticmethod
    def _schema(c):
        c.execute('''CREATE TABLE IF NOT EXISTS scene_fragment_revisions(
             episode TEXT NOT NULL REFERENCES episodes(id), fragment TEXT NOT NULL,
             revision INTEGER NOT NULL, binding_key TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
             sha256 TEXT NOT NULL, PRIMARY KEY(episode,fragment,revision))''')

    @staticmethod
    def _record(row):
        if digest(row['payload']) != row['sha256']:
            raise SceneFragmentError('graph_digest', 'Stored scene graph does not match its fingerprint')
        return json.loads(row['payload'])

    @staticmethod
    def _binding(scope, anchor, spec):
        return digest(encoded([scope, anchor, spec]))

    @staticmethod
    def _insert(c, body, binding):
        payload = encoded(body)
        c.execute('INSERT INTO scene_fragment_revisions VALUES(?,?,?,?,?,?)',
                  (body['scope']['episode'], body['id'], body['revision'], binding, payload, digest(payload)))

    def _persist(self, c, body, binding, head):
        self._schema(c)
        row = c.execute('SELECT * FROM scene_fragment_revisions WHERE binding_key=?', (binding,)).fetchone()
        if row:
            existing = self._record(row)
            latest = self._find(c, body['scope']['episode'], existing['id'])
            return self._public(existing, head, latest['revision'], 'REPLAYED')
        self._insert(c, body, binding)
        return self._public(body, head, body['revision'], 'IMPORTED')

    @staticmethod
    def _find(c, episode, ident, revision=None):
        if _has(c, 'scene_fragment_revisions'):
            query = 'SELECT * FROM scene_fragment_revisions WHERE episode=? AND fragment=?'
            if revision is None:
                return c.execute(query+' ORDER BY revision DESC LIMIT 1', (episode, ident)).fetchone()
            return c.execute(query+' AND revision=?', (episode, ident, revision)).fetchone()
        return None

    @staticmethod
    def _anchor(revision, source_sha, text, start, end):
        return {'timeline_revision': revision, 'source_sha256': source_sha, 'text_sha256': digest(text),
                'start': start, 'end': end, 'unit': 'codepoint'}

    def _target_at(self, c, body):
        a = body['anchor']
        script, sha = self._source(c, body['scope']['episode'], a['timeline_revision'])
        text = _selection(script, a['start'], a['end'])
        if sha != a['source_sha256'] or digest(text) != a['text_sha256']:
            raise SceneFragmentError('passage_mismatch', 'Stored scene no longer matches its original source')
        return text, script

    def pinned_replay(self, c, scope, head, request):
        """Read a current graph and intact source on the replay caller's snapshot."""
        self._current(request, head)
        ident = checked_id(request.get('fragment'), 'Fragment ID')
        revision = _number(request.get('fragment_revision'), 'Graph revision', 1)
        row = self._find(c, scope['episode'], ident)
        if row is None or row['revision'] != revision:
            raise SceneFragmentError('stale_fragment', 'Open the current scene graph revision to replay it')
        body = self._record(row)
        if body['scope'] != scope:
            raise SceneFragmentError('wrong_scope', 'Scene graph belongs to another scope')
        if body['anchor']['timeline_revision'] != head:
            raise SceneFragmentError('stale_anchor', 'Update passage positions before replaying this graph')
        _, script = self._target_at(c, body)
        return self._public(body, head, revision, 'OPENED')['fragment'], script, row['sha256']

    @staticmethod
    def _public(body, current_timeline_revision, current_graph_revision, status):
        spec, scene = body['declaration'], body['id']
        base = body['anchor']['start']
        keys = {many: {item['id']: _id(many[:-1], scene, item['id']) for item in spec[many]}
                for many in ('passages', 'nodes', 'roles')}
        material = {'roles': [v | {'key': v['id'], 'id': keys['roles'][v['id']]} for v in spec['roles']],
                    'passages': [v | {'key': v['id'], 'id': keys['passages'][v['id']],
                                     'start': v['start']+base, 'end': v['end']+base} for v in spec['passages']],
                    'nodes': [v | {'key': v['id'], 'id': keys['nodes'][v['id']],
                                  'roles': [keys['roles'][k] for k in v['roles']],
                                  'passage': keys['passages'].get(v['passage'])} for v in spec['nodes']],
                    'edges': [v | {k: keys['nodes'][v[k]] for k in ('from', 'to')} for v in spec['edges']]}
        return {'status': status, 'fragment': body | {'graph': material, 'location': _location(spec['title'])},
                'timeline_head': current_timeline_revision, 'fragment_head': current_graph_revision,
                'needs_rebind': body['anchor']['timeline_revision'] != current_timeline_revision,
                'provider_calls': 0}

    def _make_graph(self, scope, rev, sha, start, end, text, spec, catalog):
        validate_declaration(spec, text, catalog)
        anchor = self._anchor(rev, sha, text, start, end)
        binding = self._binding(scope, anchor, spec)
        body = {'schema_version': VERSION, 'id': _id('scene-fragment', binding), 'revision': 1,
                'scope': scope, 'anchor': anchor, 'declaration': spec, 'remap': None,
                'story_time': 'unresolved', 'reader_reveals': 'declarative'}
        return body, binding

    def prepare_scenes(self, c, scope, mapping):
        """Save the typed, source-ordered graphs within the notebook transaction."""
        episode, rev = scope['episode'], mapping['revision']
        script, source_sha = self._source(c, episode, rev)
        if source_sha != mapping['source_sha256']:
            raise SceneFragmentError('source_digest', 'The Beat Map edition changed during preparation')
        blocks = _saved_metadata(c, episode, rev, script)
        offsets = [span[0] for span in blocks]
        catalog = self._catalog(c, episode)
        scenes = {scene['id']: scene for scene in mapping['scenes']}
        beats = {beat['id']: beat for beat in mapping['beats']}
        prepared = []
        for item in self._scene_ranges(mapping):
            a, b = item['start'], item['end']
            source = _selection(script, a, b)
            scene = scenes[item['id']]
            relevant = {'scenes':[scene], 'beats':[beats[key] for key in scene['beats']]}
            parts = blocks[max(0, bisect_right(offsets, a) - 1):bisect_left(offsets, b)]
            spec = _automatic(relevant, script, a, b, item['title'], parts)
            body, binding = self._make_graph(scope, rev, source_sha, a, b, source, spec, catalog)
            saved = self._persist(c, body, binding, rev)['fragment']
            prepared.append({'scene':item['id'], 'id':saved['id'], 'revision':saved['revision'],
                             'title':item['title'], 'anchor':saved['anchor'], 'location':saved['location'],
                             'nodes':len(spec['nodes']), 'edges':len(spec['edges'])})
        return prepared

    def _prepare(self, c, scope, rev, request):
        ep = scope['episode']
        script, sha = self._source(c, ep, rev)
        selection = request.get('selection')
        selected = []
        data = request.get('declaration')
        mapping = (map_episode(self.timeline, ep, rev, _connection=c)
                   if data is None or (isinstance(selection, dict) and 'scene' in selection) else None)
        if isinstance(selection, dict) and set(selection) == {'scene'}:
            selected = [v for v in self._scene_ranges(mapping) if v['id'] == selection['scene']]
            if not selected:
                raise ValueError('Choose a scene from the current saved episode')
            start, end = selected[0]['start'], selected[0]['end']
        else:
            _object(selection, ('start', 'end'))
            start, end = selection['start'], selection['end']
        text = _selection(script, start, end)
        if data is None:
            title = selected[0]['title'] if selected else 'Selected scene'
            data = _automatic(mapping, script, start, end, title, _saved_metadata(c, ep, rev, script))
        return self._make_graph(scope, rev, sha, start, end, text, data, self._catalog(c, ep))

    def _rebind(self, c, scope, timeline_head, previous, request):
        rev = self._current(request, timeline_head)
        expected = _number(request.get('fragment_revision'), 'Expected graph revision', 1)
        a, old_revision = previous['anchor'], previous['revision']
        if expected != old_revision and not (a['timeline_revision'] == rev and previous['remap']
                                            and previous['remap']['from_fragment_revision'] == expected):
            raise SceneFragmentError('stale_fragment', 'Scene graph changed; reopen the latest graph revision')
        text, previous_script = self._target_at(c, previous)
        if a['timeline_revision'] == rev:
            return self._public(previous, timeline_head, old_revision, 'UNCHANGED')
        script, sha = self._source(c, scope['episode'], rev)
        if sha == a['source_sha256']:
            start = a['start']
        else:
            if previous_script.find(text) != a['start'] or previous_script.find(text, a['start'] + 1) >= 0:
                raise SceneFragmentError('ambiguous_anchor', 'The original revision contained identical scenes; choose a new scene explicitly')
            start = script.find(text)
            if start >= 0 and script.find(text, start + 1) >= 0:
                raise SceneFragmentError('ambiguous_anchor', 'Scene anchor has multiple exact matches; choose a new scene explicitly')
        end = start + len(text)
        if start == -1 or not _whole_lines(script, start, end):
            raise SceneFragmentError('changed_anchor', 'The original scene text no longer matches exactly; import a new scene revision')
        anchor = self._anchor(rev, sha, text, start, end)
        body = previous | {'revision': old_revision+1, 'anchor': anchor,
                           'remap': {'from_fragment_revision': old_revision, 'from': a, 'to': anchor,
                                     'delta': start-a['start'], 'method': 'exact-unique' if sha != a['source_sha256'] else 'unchanged-edition'}}
        binding = self._binding(scope, anchor, body['declaration'])
        if c.execute('SELECT 1 FROM scene_fragment_revisions WHERE binding_key=?', (binding,)).fetchone():
            raise SceneFragmentError('binding_exists', 'This source revision already has the same saved graph; reopen it instead')
        self._insert(c, body, binding)
        return self._public(body, timeline_head, body['revision'], 'REBOUND')

    def execute(self, action, request):
        if action not in COMMANDS:
            raise ValueError('Unknown scene fragment command')
        op = action.rsplit('.', 1)[-1]
        episode = request.get('episode')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE' if op in ('import', 'rebind') else 'BEGIN')
            scope, head = self._scope(c, request)
            if op == 'scenes':
                rev = self._current(request, head)
                mapping = map_episode(self.timeline, episode, rev, _connection=c)
                return {'scenes': list(self._scene_ranges(mapping)), 'scope': scope,
                        'timeline_head': head, 'provider_calls': 0}
            if op == 'list':
                rows = []
                if _has(c, 'scene_fragment_revisions'):
                    rows = c.execute('''SELECT r.* FROM scene_fragment_revisions r JOIN
                        (SELECT fragment,max(revision) AS revision FROM scene_fragment_revisions
                         WHERE episode=? GROUP BY fragment) h ON r.fragment=h.fragment AND r.revision=h.revision
                        WHERE r.episode=? ORDER BY r.rowid DESC LIMIT 100''', (episode, episode))
                fragments = []
                for row in rows:
                    value = self._record(row)
                    if value['scope'] == scope:
                        fragments.append({k: value[k] for k in ('id', 'revision', 'anchor')}
                                         | {'title': value['declaration']['title']})
                return {'fragments': fragments, 'timeline_head': head, 'provider_calls': 0}
            if op in ('preview', 'import'):
                rev = self._current(request, head)
                body, binding = self._prepare(c, scope, rev, request)
                if op == 'preview':
                    return self._public(body, head, None, 'PREVIEW')
                return self._persist(c, body, binding, head)
            ident = checked_id(request.get('fragment'), 'Fragment ID')
            latest = self._find(c, episode, ident)
            if latest is None:
                raise SceneFragmentError('unknown_fragment', 'Scene graph is not saved in this episode')
            previous = self._record(latest)
            if previous['scope'] != scope:
                raise SceneFragmentError('wrong_scope', 'Scene graph scope changed')
            if op == 'rebind':
                return self._rebind(c, scope, head, previous, request)
            wanted = request.get('fragment_revision')
            if wanted is not None:
                wanted = _number(wanted, 'Graph revision', 1)
                found = self._find(c, episode, ident, wanted)
                if found is None:
                    raise SceneFragmentError('unknown_fragment', 'Scene graph revision does not exist')
                previous = self._record(found)
                if previous['scope'] != scope:
                    raise SceneFragmentError('wrong_scope', 'Scene graph scope changed')
            self._target_at(c, previous)
            result = self._public(previous, head, latest['revision'], 'EXPORTED' if op == 'export' else 'OPENED')
            if op == 'export':
                result['source_receipt'] = {'sha256': digest(encoded(previous)),
                                            'original_passage_bytes_preserved': True}
            return result
