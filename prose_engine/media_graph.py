"""Project originals and reusable segments linked to saved scenes, beats and form ports."""
from contextlib import ExitStack, contextmanager
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
import wave

from story_graph import scene_fragments as f
from story_graph.universe_scope import checked_id
from . import intake as documents, processing, scene_clips


COMMANDS = frozenset('scene.media.' + name for name in ('open', 'source', 'attach',
                    'override.preview', 'override.apply', 'override.clear'))
MAX_FILE = scene_clips.MAX_FILE
MAX_ASSETS = 128
MAX_PINS = 12
IMAGES = {'.png': ('PNG', 'image/png'), '.jpg': ('JPEG', 'image/jpeg'),
          '.jpeg': ('JPEG', 'image/jpeg'), '.webp': ('WEBP', 'image/webp')}
USES = {
    'document': ('reference',),
    'image': ('appearance', 'reference'),
    'audio': ('performance', 'timing', 'reference'),
    'video': ('cutaway', 'performance', 'timing', 'reference'),
}
PIN_ROLE_MAP = {
    'catalyst_trigger': 'cutaway',
    'relationship_chemistry': 'reference',
    'rhythm_timing': 'timing',
    'personality_mind': 'performance',
    'wardrobe_reference': 'appearance',
}
PURPOSE_TO_PIN_ROLE = {
    'cutaway': 'catalyst_trigger',
    'reference': 'relationship_chemistry',
    'timing': 'rhythm_timing',
    'performance': 'personality_mind',
    'appearance': 'wardrobe_reference',
}


def normalize_pin_role(role_or_purpose: str | None, kind: str | None = None) -> tuple[str, str]:
    """Map either a canonical UI pin role or a media_graph purpose into (purpose, pin_role)."""
    raw = str(role_or_purpose or '').strip()
    if raw in PIN_ROLE_MAP:
        pin_role = raw
        purpose = PIN_ROLE_MAP[raw]
    elif raw in PURPOSE_TO_PIN_ROLE:
        purpose = raw
        pin_role = PURPOSE_TO_PIN_ROLE[raw]
    else:
        return '', raw
    if kind and kind in USES and purpose not in USES[kind]:
        # Pick the primary supported purpose for this media kind while keeping the authored pin_role
        fallback = 'appearance' if (kind == 'image' and pin_role == 'wardrobe_reference') else (
            'performance' if (kind in ('audio', 'video') and pin_role == 'personality_mind') else USES[kind][0]
        )
        purpose = fallback if fallback in USES[kind] else USES[kind][0]
    return purpose, pin_role


def _namespace(scope):
    return f.encoded([scope['project'], scope['universe']])


def _schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS graph_media_assets (
                 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, payload TEXT NOT NULL, extracted TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS graph_media_segments (
                 id TEXT PRIMARY KEY, workspace TEXT NOT NULL, payload TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS graph_media_pins (
                 id TEXT PRIMARY KEY, episode TEXT NOT NULL REFERENCES episodes(id),
                 scope TEXT NOT NULL, payload TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS graph_media_pin_scope_key ON graph_media_pins(scope)')


def _root(store):
    folder = Path(store.path).resolve().with_suffix('.media')
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        raise ValueError('The media store must be a local workspace directory')
    return folder


def _kind(suffix):
    if suffix in documents.FORMATS:
        return 'document', 'application/octet-stream'
    if suffix in IMAGES:
        return 'image', IMAGES[suffix][1]
    if suffix == '.wav':
        return 'audio', 'audio/wav'
    if suffix in scene_clips._TYPES:
        return 'video', scene_clips._TYPES[suffix][0]
    raise ValueError('Choose a script or document, PNG/JPEG/WebP, WAV, or MP4/WebM')


def _digest(path):
    with path.open('rb') as file:
        return file_digest(file, 'sha256').hexdigest()


def _file(store, asset):
    suffix = asset['suffix']
    if _kind(suffix) != (asset['kind'], asset['mime']):
        raise ValueError('The saved source format changed')
    path = _root(store) / (f._sha(asset['sha256']) + suffix)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The original media is unavailable in this copy')
    stat = path.stat()
    if stat.st_size != asset['bytes'] or (
            stat.st_mtime_ns != asset['stored_mtime_ns'] and _digest(path) != asset['sha256']):
        raise ValueError('The original media no longer matches its saved fingerprint')
    return path


def _public(asset):
    return {key: value for key, value in asset.items() if key != 'stored_mtime_ns'}


def _stored(c, table, scope, ident):
    if not f._has(c, table):
        return None
    return c.execute(f'SELECT * FROM {table} WHERE workspace=? AND id=?', (_namespace(scope), ident)).fetchone()


def _asset(c, scope, ident):
    row = _stored(c, 'graph_media_assets', scope, checked_id(ident, 'Saved source'))
    if row is None:
        raise ValueError('Choose a source in this project and universe')
    return json.loads(row['payload']), row['extracted']


def _probe_audio(path):
    try:
        with wave.open(str(path), 'rb') as reader:
            samples = reader.getnframes()
            rate = reader.getframerate()
            channels = reader.getnchannels()
            size = channels * reader.getsampwidth()
            duration = samples * 1000 // rate if rate else 0
            if channels not in (1, 2) or not 50 <= duration <= 1_800_000:
                raise ValueError
            remaining = samples
            while remaining:
                count = min(remaining, 32768)
                if len(reader.readframes(count)) != count * size:
                    raise ValueError
                remaining -= count
    except (EOFError, wave.Error, ValueError) as exc:
        raise ValueError('Use a complete PCM WAV up to 30 minutes') from exc
    return {'duration_ms': duration, 'sample_rate': rate, 'channels': channels,
            'clock': 'file_pts', 'track': 'audio-0', 'method': 'pcm-header'}


def _analyze(path, name, suffix, kind):
    if kind == 'document':
        doc = documents._extract(name, path.read_bytes())
        return ({**doc.summary(), 'method': 'document-extraction'}, doc.text)
    if kind == 'image':
        from PIL import Image
        try:
            with Image.open(path) as image:
                if image.format != IMAGES[suffix][0] or image.width * image.height > 40_000_000:
                    raise ValueError
                width, height = image.size
                image.verify()
            with Image.open(path) as image:
                if image.getexif().get(274, 1) in (5, 6, 7, 8):
                    width, height = height, width
                image.load()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError('Use a readable image matching its type, up to 40 megapixels') from exc
        return {'width': width, 'height': height, 'unit': 'fraction_10000', 'method': 'image-header'}, None
    if kind == 'audio':
        return _probe_audio(path), None
    probe = scene_clips._probe(path, suffix)
    return {**probe, 'clock': 'file_pts', 'track': 'video-0', 'method': 'ffprobe'}, None


@contextmanager
def _staged(store, stream, length, suffix):
    directory = _root(store)
    directory.mkdir(exist_ok=True)
    temp = None
    try:
        digest = sha256()
        with NamedTemporaryFile(dir=directory, prefix='.incoming-', suffix=suffix, delete=False) as file:
            temp = Path(file.name)
            left = length
            while left:
                chunk = stream.read(min(512 * 1024, left))
                if not chunk:
                    raise ValueError('The media upload ended early')
                digest.update(chunk)
                file.write(chunk)
                left -= len(chunk)
        yield temp, digest.hexdigest()
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def upload(store, request, stream, length):
    name = documents._name(request.get('name'))
    with processing.begin(store, request, 'media-import', name, {'name': name, 'bytes': length}) as job, ExitStack() as staged:
        with job.step('receive') as result:
            suffix = Path(name).suffix.casefold()
            kind, mime = _kind(suffix)
            limit = documents.MAX_UPLOAD if kind == 'document' else MAX_FILE
            if type(length) is not int or not 1 <= length <= limit:
                raise ValueError('The media is empty or exceeds its file size limit')
            path, digest = staged.enter_context(_staged(store, stream, length, suffix))
            result.update(sha256=digest, bytes=length, kind=kind)
        return _finish_upload(store, request, job, name, suffix, kind, mime, length, path, digest)


def _finish_upload(store, request, job, name, suffix, kind, mime, length, path, digest):
    scope = job.data['scope']
    ident = f._id('media-source', _namespace(scope), digest)
    with store._connect() as c:
        found = _stored(c, 'graph_media_assets', scope, ident)
    if found:
        asset = json.loads(found['payload'])
        if asset['kind'] != kind:
            raise ValueError('These bytes are already registered as a different media type')
        _file(store, asset)
        job.skip('analysis', 'Reused the saved source analysis.')
        job.skip('save', 'The original source already exists.')
    else:
        with job.step('analysis', {'kind': kind, 'sha256': digest}) as result:
            analyzed, text = _analyze(path, name, suffix, kind)
            result.update(analyzed)
        with job.step('save', {'asset': ident}) as result:
            with store._connect() as c:
                c.execute('BEGIN IMMEDIATE')
                actual, _ = f.SceneFragmentStore._scope(c, request)
                if actual != scope:
                    raise ValueError('The project changed during import')
                _schema(c)
                found = _stored(c, 'graph_media_assets', scope, ident)
                if found:
                    asset = json.loads(found['payload'])
                    if asset['kind'] != kind:
                        raise ValueError('These bytes are already registered as a different media type')
                    _file(store, asset)
                else:
                    count = c.execute('SELECT count(*) FROM graph_media_assets WHERE workspace=?',
                                      (_namespace(scope),)).fetchone()[0]
                    if count >= MAX_ASSETS:
                        raise ValueError('The media library has reached its source limit')
                    destination = _root(store) / (digest + suffix)
                    if destination.is_symlink():
                        raise ValueError('Media storage is unavailable')
                    if destination.exists():
                        if _digest(destination) != digest:
                            raise ValueError('The saved original has different bytes')
                    else:
                        os.replace(path, destination)
                    asset = {'id': ident, 'name': name, 'suffix': suffix, 'kind': kind, 'mime': mime,
                             'sha256': digest, 'bytes': length, 'analysis': analyzed,
                             'stored_mtime_ns': destination.stat().st_mtime_ns}
                    c.execute('INSERT INTO graph_media_assets VALUES(?,?,?,?)',
                              (ident, _namespace(scope), f.encoded(asset), text))
            result.update(asset=ident, sha256=digest)
    job.data['outputs'] = {'asset': ident, 'sha256': digest}
    return {'asset': _public(asset), 'job': job.data['id'], 'provider_calls': 0}


def original(store, request):
    with store._connect() as c:
        scope, _ = f.SceneFragmentStore._scope(c, request)
        return original_in_scope(store, c, scope, request.get('id'))


def original_in_scope(store, c, scope, ident):
    asset, _ = _asset(c, scope, ident)
    return asset, _file(store, asset)


def _selector(asset, value):
    analysis = asset['analysis']
    kind = asset['kind']
    if kind == 'image':
        f._object(value, ('x', 'y', 'width', 'height'))
        x, y, w, h = (f._number(value[key], key) for key in ('x', 'y', 'width', 'height'))
        if w < 1 or h < 1 or x + w > 10000 or y + h > 10000:
            raise ValueError('The selected region is outside the image')
        return {'kind': 'region', 'unit': 'fraction_10000', **value}
    f._object(value, ('start', 'end'))
    if kind == 'document':
        start, end = f._range(value['start'], value['end'], analysis['characters'])
        if end - start > 6400:
            raise ValueError('Choose a text segment of up to 6,400 characters')
        return {'kind': 'text', 'start': start, 'end': end, 'unit': 'codepoint'}
    start, end = f._range(value['start'], value['end'], analysis['duration_ms'])
    if end - start > 90_000:
        raise ValueError('Choose a segment of at most 90 seconds')
    return {'kind': 'clip', 'start': start, 'end': end, 'unit': 'ms',
            'clock': analysis['clock'], 'track': analysis['track']}


def _target(store, c, scope, request):
    if sum(key in request for key in ('character', 'scene', 'beat')) != 1:
        raise ValueError('Choose one saved scene, beat, or form')
    if 'character' in request:
        return _form_target(store, c, scope, request)

    from .story_timeline import open_track
    view = open_track(store, scope | {k: request[k] for k in ('timeline_revision', 'fragment') if k in request},
                      connection=c, include_media=False)
    binding = {'timeline_revision': view['timeline_revision'], 'source_sha256': view['source_sha256']}
    if 'scene' in request:
        ident = checked_id(request['scene'], 'Story scene')
        scene = next((item for item in view['scenes'] if item['id'] == ident), None)
        if not scene or scene['passages_sha256'] != f._sha(request.get('scene_sha256')):
            raise ValueError('Choose the exact passages on the current saved scene')
        return {'kind': 'scene', 'scene': ident, 'label': scene['title'], **binding,
                'scene_sha256': scene['passages_sha256']}
    beat = checked_id(request['beat'], 'Story beat')
    matches = [(scene['id'], row) for scene in view['scenes'] for row in scene['beats'] if row['id'] == beat]
    if len(matches) != 1 or matches[0][1]['passage']['sha256'] != f._sha(request.get('passage_sha256')):
        raise ValueError('Choose the exact passage on the current saved beat')
    scene_id, row = matches[0]
    return {'kind': 'beat', 'scene': scene_id, 'beat': beat, 'label': row['label'], **binding,
            'passage': {k: v for k, v in row['passage'].items() if k != 'text'},
            'node': (row.get('destination') or {}).get('node'), 'replay': row.get('replay')}


def _form_target(store, c, scope, request):
    from .scene_bridges import _junctions
    character = checked_id(request['character'], 'Character')
    ident = checked_id(request.get('form'), 'Character form')
    group = _junctions(store, c, scope['episode']).get(character)
    form = next((item for item in group.forms if item.id == ident), None) if group else None
    if not form:
        raise ValueError('Choose an existing form in this character graph')
    return {'kind': 'form', 'character': character, 'form': ident,
            'port': f'{group.id}:form:{ident}', 'label': form.label}


def _target_key(target):
    return {key: value for key, value in target.items() if key != 'label'}


def _pin_scope(scope, target=None):
    if target and target['kind'] == 'form':
        return f.encoded([scope['project'], scope['universe'], target['port']])
    return f.encoded(scope)


def _segment(store, c, scope, request):
    if 'segment' in request:
        if any(key in request for key in ('asset', 'selector', 'purpose', 'pin_role', 'observation')):
            raise ValueError('Reuse the saved segment as it was recorded')
        row = _stored(c, 'graph_media_segments', scope, checked_id(request['segment'], 'Saved segment'))
        if not row:
            raise ValueError('Choose a saved segment in this project and universe')
        segment = json.loads(row['payload'])
        asset, _ = _asset(c, scope, segment['asset'])
    else:
        asset, _ = _asset(c, scope, request.get('asset'))
        selector = _selector(asset, request.get('selector'))
        role = request.get('pin_role')
        if role is not None and (not isinstance(role, str) or role not in PIN_ROLE_MAP):
            raise ValueError('Choose a supported typed pin role')
        purpose, pin_role = normalize_pin_role(role or request.get('purpose'), asset['kind'])
        if not purpose or purpose not in USES[asset['kind']]:
            raise ValueError('Choose a purpose supported by this media type')
        note = request.get('observation', '')
        if not isinstance(note, str) or len(note) > 380 or '\0' in note:
            raise ValueError('Use an observation of up to 380 characters')
        basis = {'asset': asset['id'], 'selector': selector, 'purpose': purpose,
                 'observation': note.strip(), 'analysis_method': asset['analysis']['method']}
        default_role = PURPOSE_TO_PIN_ROLE[purpose]
        legacy_id = f._id('media-segment', basis)
        legacy = _stored(c, 'graph_media_segments', scope, legacy_id)
        legacy_role = json.loads(legacy['payload']).get('pin_role', default_role) if legacy else default_role
        # Older segments used purpose alone. Keep their IDs and give distinct roles distinct IDs.
        ident = legacy_id if pin_role == legacy_role else f._id('media-segment', basis, pin_role)
        segment = {'id': ident, **basis, 'pin_role': pin_role}
    _file(store, asset)
    return segment


def attach(store, request):
    with processing.begin(store, request, 'media-attach', 'Attach media reference', {}) as job:
        scope = job.data['scope']
        with job.step('resolve', {key: request[key] for key in ('timeline_revision', 'beat', 'scene', 'character', 'form')
                                  if key in request}) as result:
            with store._connect() as c:
                c.execute('BEGIN')
                target = _target(store, c, scope, request)
            result.update(target)
        with job.step('segment') as result:
            with store._connect() as c:
                segment = _segment(store, c, scope, request)
            result.update(segment)
        with job.step('save') as result:
            basis = {'scope': scope, 'target': target, 'segment': segment['id']}
            key = _pin_scope(scope, target)
            pin = {'id': f._id('media-pin', key, _target_key(target), segment['id']), **basis}
            with store._connect() as c:
                c.execute('BEGIN IMMEDIATE')
                current, _ = f.SceneFragmentStore._scope(c, request)
                if current != scope or _target(store, c, scope, request) != target:
                    raise ValueError('The destination changed during attachment')
                _schema(c)
                existing = c.execute('SELECT payload FROM graph_media_pins WHERE id=?', (pin['id'],)).fetchone()
                if existing:
                    pin = json.loads(existing['payload'])
                else:
                    count = sum(_target_key(row['target']) == _target_key(target) for row in _pins(c, key))
                    if count >= MAX_PINS:
                        raise ValueError('This destination has reached its media link limit')
                    c.execute('INSERT OR IGNORE INTO graph_media_segments VALUES(?,?,?)',
                              (segment['id'], _namespace(scope), f.encoded(segment)))
                    c.execute('INSERT INTO graph_media_pins VALUES(?,?,?,?)',
                              (pin['id'], scope['episode'], key, f.encoded(pin)))
            result.update(pin=pin['id'], segment=segment['id'], reused=bool(existing))
        job.data['outputs'] = {'pin': pin['id'], 'segment': segment['id']}
        return {'pin': pin, 'segment': segment, 'job': job.data['id'], 'provider_calls': 0}


def _list(c, table, scope):
    if not f._has(c, table):
        return []
    return [json.loads(row['payload']) for row in c.execute(
        f'SELECT payload FROM {table} WHERE workspace=? ORDER BY rowid DESC', (_namespace(scope),))]


def _pins(c, key):
    if not f._has(c, 'graph_media_pins'):
        return []
    return [json.loads(row['payload']) for row in c.execute(
        'SELECT payload FROM graph_media_pins WHERE scope=? ORDER BY rowid', (key,))]


def _link(c, scope, pin):
    row = _stored(c, 'graph_media_segments', scope, pin['segment'])
    if row:
        segment = json.loads(row['payload'])
        asset, _ = _asset(c, scope, segment['asset'])
        return {'pin': pin['id'], 'segment': segment, 'asset': _public(asset)}


def project(c, scope, head, sha, scenes):
    pins = _pins(c, _pin_scope(scope))
    if not pins:
        return
    by_beat = {}
    for pin in pins:
        target = pin['target']
        if (target['timeline_revision'], target['source_sha256']) == (head, sha):
            by_beat.setdefault((target['scene'], target.get('beat')), []).append(pin)
    for scene in scenes:
        linked = [_link(c, scope, pin) for pin in by_beat.get((scene['id'], None), ())
                  if pin['target']['scene_sha256'] == scene['passages_sha256']]
        if items := [item for item in linked if item]:
            scene['media'] = items
        for row in scene['beats']:
            items = []
            for pin in by_beat.get((scene['id'], row['id']), ()):
                if any(row['passage'][key] != pin['target']['passage'][key] for key in ('start', 'end', 'sha256')):
                    continue
                dest = row.get('destination') or {}
                if (pin['target']['node'], pin['target']['replay']) != (dest.get('node'), row.get('replay')):
                    continue
                if item := _link(c, scope, pin):
                    items.append(item)
            if items:
                row['media'] = items


def execute(store, action, request):
    from . import media_overrides
    if action in media_overrides.COMMANDS:
        return media_overrides.execute(store, action, request)
    if action == 'scene.media.attach':
        return attach(store, request)
    with store._connect() as c:
        c.execute('BEGIN')
        scope, head = f.SceneFragmentStore._scope(c, request)
        if action == 'scene.media.source':
            asset, text = _asset(c, scope, request.get('asset'))
            _file(store, asset)
            return {'asset': _public(asset), 'text': text, 'provider_calls': 0}
        if action == 'scene.media.open':
            target = _target(store, c, scope, request) if any(key in request for key in ('character', 'scene', 'beat')) else None
            pins = _pins(c, _pin_scope(scope, target))
            if target:
                pins = [item for item in pins if _target_key(item['target']) == _target_key(target)]
            return {'scope': scope, 'timeline_revision': head, 'target': target,
                    'assets': [_public(asset) for asset in _list(c, 'graph_media_assets', scope)],
                    'segments': _list(c, 'graph_media_segments', scope), 'pins': pins,
                    'pin_role_map': dict(PIN_ROLE_MAP),
                    'overrides': media_overrides.for_pins(c, scope, pins), 'provider_calls': 0}
    raise ValueError('Unknown graph media command')
