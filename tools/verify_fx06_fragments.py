"""Verify the real FX06 and Spring Break inputs on new copies of a checkpoint."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from copy import deepcopy
from hashlib import sha256
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine.notebook import NotebookStore, joined, remap_masks
from story_graph.episode_timeline import TimelineStore
from story_graph.fx06_scene import PERFUME_LINE, read as pilot_read
from story_graph.scene_fragments import SceneFragmentStore, digest
from tools.studio_ui import StudioRequestHandler


ROOT = Path(__file__).resolve().parents[1]
NEURAL_DIR = ROOT / 'deliverables/NOIR_FX06_GAG_COLLECTION_20261116/Neural Graph'


def _json(path, payload):
    with path.open('x', encoding='utf-8') as out:
        out.write(json.dumps(payload, indent=2, ensure_ascii=False) + '\n')


def _fingerprint(path):
    with path.open('rb') as stream:
        return sha256(stream.read()).hexdigest()


def _workspace(checkpoint, out, source):
    out.mkdir(exist_ok=False)
    for name, expected in source['files'].items():
        prior = (checkpoint / name).resolve(strict=True)
        assert _fingerprint(prior) == expected
        with closing(sqlite3.connect(prior.as_uri()+'?mode=ro', uri=True)) as a, closing(sqlite3.connect(out/name)) as b:
            a.backup(b)
            assert b.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    return TimelineStore(out / 'timeline.sqlite')


@contextmanager
def _studio(directory, episode):
    with ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler) as server:
        server.timeline_path = directory / 'timeline.sqlite'
        server.initial_episode = episode
        server.timeline_only = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'

        def command(operation, payload):
            req = Request(origin + '/api/episode-command',
                          json.dumps({'action': 'scene.fragment.'+operation, **payload}).encode(),
                          headers={'Origin': origin, 'Content-Type': 'application/json'})
            with urlopen(req, timeout=10) as reply:
                result = json.load(reply)
            assert result['provider_calls'] == 0
            return result

        try:
            with urlopen(origin + '/scene-fragments?episode=' + episode, timeout=10) as reply:
                assert b'NOIR / SCENE GRAPHS' in reply.read()
            yield command
        finally:
            server.shutdown()
            thread.join()


def _rainee_spec(store, scope, declaration):
    with store._connect() as c:
        clip = pilot_read(c)['cutaway']
    manifest = json.loads((NEURAL_DIR/'source_manifest.json').read_text(encoding='utf-8'))['gag_source']
    sha = _fingerprint(NEURAL_DIR/'Complete Cutaway.mp4')
    assert sha == clip['sha256'] == manifest['original_sha256']
    start, end = clip['window_ms']
    assert 0 <= start < end <= manifest['duration_s']*1000
    sources = [
        {'id': 'complete-fusion', 'asset': 'complete-cutaway', 'sha256': sha, 'use': 'structure',
         'selector': {'kind': 'clip', 'clock': 'file_pts', 'track': 'video-0', 'unit': 'ms', 'start': start, 'end': end}},
        {'id': 'author-diagram', 'asset': 'fx06-author-override', 'sha256': _fingerprint(NEURAL_DIR/'Author Override.png'),
         'use': 'structure', 'selector': {'kind': 'diagram', 'unit': 'fraction_10000', 'region': [0, 0, 10000, 10000]}},
    ]
    SceneFragmentStore(store).register_evidence(scope, sources)
    spec = deepcopy(declaration)
    spec['title'] = 'Rainee split · source graph'
    spec['evidence'] = sources
    for ref, text in zip(sources, ('Complete cutaway · fusion reference', 'Author’s override diagram')):
        spec['nodes'].append({'id': ref['id'], 'kind': 'reference', 'label': text,
                              'passage': None, 'roles': [], 'evidence': [ref['id']]})
    split = next(n['id'] for n in spec['nodes'] if n['label'].startswith('Rainee splits'))
    rejoin = next(n['id'] for n in spec['nodes'] if n['label'].startswith('Francine stepped'))
    spec['edges'] += [{'from': 'complete-fusion', 'to': n, 'kind': 'influences'} for n in (split, rejoin)]
    spec['edges'].append({'from': 'author-diagram', 'to': split, 'kind': 'influences'})
    return spec


def _cli_export(docpath, timeline, request):
    _json(docpath, request)
    completed = subprocess.run([sys.executable, '-B', '-m', 'prose_engine', 'episode', 'scene.fragment.export',
                                '--timeline', str(timeline), '--request', str(docpath)], cwd=ROOT,
                               encoding='utf-8', capture_output=True, timeout=40)
    if completed.returncode:
        raise RuntimeError('Scene graph CLI export failed: ' + completed.stderr.strip())
    return json.loads(completed.stdout)


def _hard_bytes(text, masks):
    return {m['id']: text[m['start']:m['end']].encode('utf-8') for m in masks if m.get('hard')}


def _shift_notebook(store, notebook):
    episode = notebook['episode']
    old = joined(notebook['blocks'])
    sep = '\r\n' if '\r\n' in old else '\n'
    prefix = 'Scratch preface — résumé 🦊. This note is outside the imported scene.' + sep*2
    block = {'id': 'fx06-verification-preface', 'kind': 'narrator', 'speaker': None, 'form': None, 'text': prefix}
    new = prefix + old
    masks = remap_masks(old, new, notebook['masks'])
    saved = store.save(episode, notebook['revision'], notebook['timeline_revision'], [block, *notebook['blocks']],
                       notebook['default_protection'], masks)
    assert joined(saved['blocks']) == new
    assert saved['blocks'][1:] == notebook['blocks']
    assert _hard_bytes(old, notebook['masks']) == _hard_bytes(new, saved['masks'])
    return saved, prefix


def _check_copy(name, checkpoint, out, source):
    timeline = _workspace(checkpoint, out, source)
    ep = source['scene_source']
    original = timeline.get_episode(ep['episode'])
    text, revision = original['script'], original['head']
    assert digest(text) == ep['sha256'] and revision == ep['revision']
    identity = timeline.scope()
    scope = {'project': identity['project_id'], 'universe': identity['universe_id'],
             'episode': ep['episode'], 'branch': ep['branch']}
    notebooks = NotebookStore(timeline)
    before = notebooks.existing(ep['episode'])
    assert before and not before['stale'] and joined(before['blocks']) == text
    if name == 'rainee':
        assert PERFUME_LINE.encode('utf-8') in _hard_bytes(text, before['masks']).values()

    with _studio(out, ep['episode']) as command:
        request = scope | {'timeline_revision': revision}
        scenes = command('scenes', request)['scenes']
        if name == 'spring-break':
            scene = next(s for s in scenes if 'KITCHEN BRIEFING' in s['title'].upper())
            selection = {'scene': scene['id']}
        else:
            selection = {'start': 0, 'end': len(text)}
        request['selection'] = selection
        assert command('list', scope)['fragments'] == []
        preview = command('preview', request)['fragment']
        assert command('list', scope)['fragments'] == []
        rejected = []
        if name == 'rainee':
            spec = _rainee_spec(timeline, scope, preview['declaration'])
            wrong = deepcopy(spec)
            wrong['evidence'][0]['sha256'] = 'b3a4b608e96f2066b6bdf2426b07d2fd534165ec2450b3529135c1e108f2d514'
            try:
                command('import', request | {'declaration': wrong})
            except HTTPError as exc:
                with exc:
                    rejected.append(json.load(exc)['code'])
                assert rejected == ['wrong_edition']
            else:
                raise AssertionError('Earlier clip edition was accepted on the complete-cutaway selector')
            assert command('list', scope)['fragments'] == []
            request['declaration'] = spec
        result = command('import', request)
        old = result['fragment']
        assert result['status'] == 'IMPORTED'
        assert command('import', request)['status'] == 'REPLAYED'
        assert notebooks.existing(ep['episode']) == before
        inspect = scope | {'fragment': old['id']}
        reopened = command('open', inspect)
        assert reopened['fragment'] == old
        assert len(command('list', scope)['fragments']) == 1
        cli = _cli_export(out/'export-request.json', out/'timeline.sqlite', inspect)
        assert cli == command('export', inspect)
        _json(out/'original-graph.json', cli)

        edited, prefix = _shift_notebook(notebooks, before)
        assert command('open', inspect)['needs_rebind'] is True
        shift = command('rebind', inspect | {'fragment_revision': 1,
                                            'timeline_revision': edited['timeline_revision']})
        new = shift['fragment']
        assert shift['status'] == 'REBOUND' and not shift['needs_rebind']
        assert new['id'] == old['id'] and new['revision'] == 2
        assert new['remap']['delta'] == len(prefix)
        assert new['anchor']['text_sha256'] == old['anchor']['text_sha256']
        for key in ('nodes', 'roles', 'edges'):
            assert new['graph'][key] == old['graph'][key]
        for a, b in zip(old['graph']['passages'], new['graph']['passages'], strict=True):
            assert a['id'] == b['id'] and a['sha256'] == b['sha256']
            assert b['start'] - a['start'] == b['end'] - a['end'] == len(prefix)
        assert command('open', inspect | {'fragment_revision': 1})['fragment'] == old
        assert command('open', inspect)['fragment'] == new
        assert notebooks.existing(ep['episode']) == edited
        _json(out/'rebound-graph.json', command('export', inspect))

    check = TimelineStore(out/'timeline.sqlite')
    reopened = SceneFragmentStore(check).execute('scene.fragment.open', inspect)
    assert reopened['fragment'] == new
    return {'scope': scope, 'title': old['declaration']['title'], 'id': old['id'],
            'before': old['anchor'], 'after': new['anchor'], 'remap': new['remap'],
            'passages': len(new['graph']['passages']), 'nodes': len(new['graph']['nodes']),
            'roles': len(new['graph']['roles']), 'hard_locks_preserved': len(_hard_bytes(text, before['masks'])),
            'evidence': new['declaration']['evidence'], 'rejected': rejected,
            'studio_cli_equal': True, 'same_ids_and_passage_bytes': True, 'provider_calls': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new directory adjacent to the checkpoint')
    args = parser.parse_args(argv)
    checkpoint = args.checkpoint.resolve(strict=True)
    stage, out = checkpoint.parent, args.output.resolve()
    if out.parent != stage:
        parser.error('Keep verification copies next to their checkpoint')
    captured = json.loads(checkpoint.read_text(encoding='utf-8'))
    out.mkdir(exist_ok=False)
    receipts = {name: _check_copy(name, stage/'before'/name, out/name, captured['copies'][name])
                for name in ('rainee', 'spring-break')}
    _json(out/'receipt.json', receipts)
    for name, row in receipts.items():
        print(f"{name}: {row['passages']} passages, {row['remap']['delta']} code-point shift, graph IDs and source bytes unchanged")


if __name__ == '__main__':
    main()
