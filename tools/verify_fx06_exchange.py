"""Exercise the real FX06 handoff across independent Noir and Deep Miner processes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
from time import monotonic, perf_counter, sleep

from prose_engine.evidence_exchange import install_catalog
from story_graph import scene_branches, scene_fragments
from story_graph.episode_timeline import TimelineStore
from story_graph.fx06_scene import PERFUME_LINE, PETER
from tools.register_fx06_exchange import load_catalog, sha
from tools.verify_fx06_mind_drafts import DBS, backup, put, studio

ROOT = Path(__file__).resolve().parents[1]
ANSWERS = ROOT/'deliverables'/'NOIR_FX06_PILOT_20261116'
RELAPSE = {'project': 'noir-fx06-pilot', 'universe': 'american-foxy-mom', 'scope_revision': 1,
           'episode': 'fx06-nurse-relapse-scene', 'branch': 'fx06-nurse-relapse'}
HOLDS = RELAPSE | {'episode': 'fx06-nurse-peter-scene', 'branch': 'fx06-nurse-peter'}
RESULT = 'scene-branch-result-434246da3b854959ffab8ff830fdb573'
SIBLING = 'scene-branch-result-681909ecf865d8f161a414bd85c155ea'
DRAFT = 'branch-recheck-eb4c52a6e8fc059fd1f8968674b553d3'
ATTEMPT = 'fx06-minds-fx06-08-continuation-from-saved-relapse'
FORM = 'rainee-split-2'
POINTER = ROOT/'.app-steward/local/studio/active_workspace.json'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def read(path):
    return json.loads(path.read_text('utf-8'))


def run(base, *args, ok=True):
    p = subprocess.run([sys.executable, '-B', '-m', *map(str, args)], cwd=base,
                       encoding='utf-8', errors='replace', capture_output=True, timeout=35, creationflags=FLAGS)
    if ok and p.returncode != 0:
        raise RuntimeError(f'{args[0]} failed ({p.returncode}): {p.stderr}')
    if not ok and p.returncode == 0:
        raise AssertionError(f'{args[0]} should reject this request')
    return p.stdout.strip() if ok else p.stderr.strip()


def miner(base, step, job, ident, *args, ok=True):
    response = run(base, 'dev_miner.cli', 'noir-exchange', step, job, '--request-id', ident, *args, ok=ok)
    return json.loads(response) if ok else response


def wire(port, ticket, method, path, data=None, headers=None):
    with closing(HTTPConnection('127.0.0.1', port, timeout=15)) as connection:
        raw = scene_fragments.encoded(data).encode('utf-8') if data is not None else None
        connection.request(method, path, raw, {'Content-Type': 'application/json',
                           'Authorization': 'Bearer '+ticket['token']} | (headers or {}))
        with connection.getresponse() as r:
            return r.status, json.load(r)


def send(port, ticket, verb, payload, *, expected=200, path='/v1/exchange', headers=None):
    status, data = wire(port, ticket, 'POST', path, {'action': 'scene.exchange.'+verb, 'request': payload}, headers)
    if status != expected:
        raise AssertionError((verb, status, expected, data))
    return data


def port_for_run():
    with closing(socket.socket()) as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


@contextmanager
def service(workspace, private, port, log_name):
    private.mkdir(exist_ok=True)
    main_ticket, evidence_ticket = private/'workspace.json', private/'miner.json'
    with (private/log_name).open('x', encoding='utf-8') as log:
        p = subprocess.Popen(
            [sys.executable, '-B', '-m', 'prose_engine.service_daemon', '--timeline', str(workspace/'timeline.sqlite'),
             '--forms', str(workspace/'character-forms.sqlite'), '--books', str(ROOT/'books'), '--port', str(port),
             '--ticket', str(main_ticket), '--exchange-ticket', str(evidence_ticket), '--exchange-result', RESULT],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=FLAGS)
        try:
            until = monotonic()+20
            while monotonic() < until:
                if p.poll() is not None:
                    log.flush()
                    raise RuntimeError(f'Noir service exited: {(private/log_name).read_text("utf-8")}')
                if main_ticket.is_file() and evidence_ticket.is_file():
                    try:
                        master, limited = read(main_ticket), read(evidence_ticket)
                        status, ready = wire(port, master, 'GET', '/v1/status')
                    except (ConnectionError, json.JSONDecodeError):
                        pass
                    else:
                        if status == 200 and ready.get('pid') == p.pid:
                            yield master, limited, evidence_ticket, ready
                            return
                sleep(.08)
            raise RuntimeError('The independent service did not become ready')
        finally:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=12)


def _story_stamp(workspace):
    """Compare full story/form state and schema without giving transport tables write authority."""
    stamp = sha256()
    for name in DBS:
        path = workspace/name
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)) as c:
            for table, schema in c.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'scene_exchange_%' ORDER BY name"
            ).fetchall():
                stamp.update(repr((name, table, schema)).encode('utf-8'))
                sql_name = '"' + table.replace('"', '""') + '"'
                stamps = sorted(sha256(repr(row).encode('utf-8')).digest() for row in c.execute(
                    'SELECT * FROM '+sql_name))
                for digest in stamps:
                    stamp.update(digest)
    return stamp.hexdigest()


def _story_frame(workspace):
    timeline = TimelineStore(workspace/'timeline.sqlite')
    with timeline._connect() as c:
        outputs = {}
        for expected_scope, ident in ((RELAPSE, RESULT), (HOLDS, SIBLING)):
            scope, head = scene_fragments.SceneFragmentStore._scope(c, expected_scope)
            result, _, frame, source = scene_branches.resolve(timeline, c, scope, head, ident)
            assert source.count(PERFUME_LINE) == 1
            assert result['exact_dialogue']['sha256'] == scene_fragments.digest(PERFUME_LINE)
            state = frame['state']
            outputs[ident] = {'terminal': result['terminal_event'], 'world': result['world_sha256'],
                              'root_form': state['root_form'], 'forms': [x['id'] for x in state['manifestations']],
                              'dialogue_sha256': result['exact_dialogue']['sha256']}
        assert outputs[SIBLING]['root_form'] == PETER and not outputs[SIBLING]['forms']
        assert FORM in outputs[RESULT]['forms'] and len(outputs[RESULT]['forms']) == 3
    return outputs


def _journal_backup(source, dest):
    dest.mkdir()
    (dest/'derived').mkdir()
    shutil.copyfile(source/'manifest.json', dest/'manifest.json')
    db = 'derived/noir-exchange.sqlite'
    with closing(sqlite3.connect((source/db).as_uri()+'?mode=ro', uri=True)) as a, closing(sqlite3.connect(dest/db)) as b:
        a.backup(b)
        assert b.execute('PRAGMA integrity_check').fetchone() == ('ok',)


def _reject_checks(port, owner, limited, queued):
    branch = RELAPSE | {'result': RESULT}
    wrong_scope = HOLDS | {'result': RESULT}
    for status, body in (
        wire(port, limited, 'GET', '/v1/episodes'),
        wire(port, limited, 'POST', '/v1/command', {'action': 'run.start', 'request': branch}),
        wire(port, limited, 'POST', '/v1/command', {'action': 'draft.apply', 'request': branch}),
        wire(port, owner, 'POST', '/v1/exchange', {'action': 'scene.exchange.list', 'request': branch}),
    ):
        assert status == 403 and 'error' in body
    send(port, limited, 'list', branch, expected=403, headers={'Origin': 'http://example.invalid'})
    send(port, limited, 'list', HOLDS | {'result': SIBLING}, expected=404)
    send(port, limited, 'list', wrong_scope, expected=404)
    send(port, limited, 'list', branch | {'scope_revision': 0}, expected=404)
    send(port, limited, 'list', branch | {'limit': 65}, expected=400)
    send(port, limited, 'list', branch | {'after': 2**64}, expected=400)
    status, _ = wire(port, limited, 'POST', '/v1/exchange', {'action': 'run.start', 'request': branch})
    assert status == 404

    bad = {
        'wrong_edition': {'source_job': {'id': 'mining:job:b3a4b608e96f2066', 'sha256': '0'*64}},
        'inactive_target': {'target': {'form': PETER, 'mind': queued['target']['mind']}},
        'wrong_link': {'target': queued['target'] | {'mind': 'other-mind'}},
        'false_clock': {'evidence': ['complete-cutaway:117400:117500', queued['evidence'][1]]},
        'reordered_samples': {'evidence': list(reversed(queued['evidence']))},
        'unregistered_visual': {'visual': 'current-look'},
        'changed_offer': {'offer_sha256': 'f'*64},
        'injected_dialogue': {'draft_text': 'not allowed'},
        'asserted_canon': {'writes_canon': True},
        'identity_claim': {'speaker_identity': 'not established'},
    }
    for case, change in bad.items():
        send(port, limited, 'submit', queued | {'request_id': 'reject-'+case} | change, expected=400)
    return ['writer and draft routes denied', 'owner and evidence tokens are distinct',
            'cross-origin request denied', 'sibling and prior epoch denied', 'bounded page enforced',
            'writer command denied inside evidence route', *bad]


def _scale(port, limited, queued, count, workers=6):
    def submit(index, retry):
        t = perf_counter()
        reply = send(port, limited, 'submit', queued | {'request_id': f'stress-{index:05d}'})
        return index, retry, reply['state'], reply['receipt']['id'], reply['sha256'], perf_counter()-t

    start = perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        jobs = [pool.submit(submit, index, retry) for index in range(count) for retry in (False, True)]
        results = [job.result() for job in jobs]
    elapsed = perf_counter()-start
    keys = {}
    for index, _, _, ident, digest, _ in results:
        assert keys.setdefault(index, (ident, digest)) == (ident, digest)
    assert sum(row[2] == 'SAVED' for row in results) == count
    assert sum(row[2] == 'REPLAYED' for row in results) == count
    times = sorted(r[-1] for r in results)
    return {'distinct_proposals': count, 'duplicate_replays': count, 'requests': len(results), 'workers': workers,
            'elapsed_seconds': round(elapsed, 3), 'requests_per_second': round(len(results)/elapsed, 1),
            'p50_ms': round(times[len(times)//2]*1000, 1), 'p95_ms': round(times[int(len(times)*.95)-1]*1000, 1)}


def _pages(port, ticket):
    rows, seen, cursor, pages = [], set(), 0, 0
    while cursor is not None:
        page = send(port, ticket, 'list', RELAPSE | {'result': RESULT, 'limit': 31, 'after': cursor})
        pages += 1
        for row in page['receipts']:
            assert row['id'] not in seen
            seen.add(row['id'])
            rows.append(row)
        following = page['next']
        assert following is None or following > cursor
        cursor = following
    return rows, pages


def verify(origin, before, out, miner_root, clip, diagram, stress):
    origin, before, out, miner_root, clip, diagram = (p.resolve() for p in (origin, before, out, miner_root, clip, diagram))
    out.mkdir(exist_ok=False)
    initial = {p.name: sha(p) for p in (origin/'timeline.sqlite', origin/'character-forms.sqlite', POINTER, clip, diagram)}
    working, job, private = out/'noir', out/'miner-job', out/'private'
    scope_path = out/'scope.json'
    put(scope_path, RELAPSE)
    backup(before, working)
    before_story = _story_stamp(working)
    frames = _story_frame(working)
    catalog = load_catalog(ANSWERS, clip, diagram, DRAFT)
    assert [r['range_us'] for r in catalog['evidence']] == [[13_666_000, 13_766_000], [13_966_000, 15_066_000]]
    install_catalog(TimelineStore(working/'timeline.sqlite'), RELAPSE, RESULT, catalog)
    run(miner_root, 'dev_miner.cli', 'new', clip, '--out', job, '--name', 'FX06 exchange only')
    port = port_for_run()
    with service(working, private, port, 'initial.log') as (master, limited, ticket, first):
        assert first['writer']['limit'] == first['writer']['used'] == 0
        assert not any(session['enabled'] for session in first['writer']['sessions'])
        offer = miner(miner_root, 'pull', job, 'offer-cutaway', '--ticket', ticket, '--scope', scope_path, '--result', RESULT)
        offer_id = offer['receipt']['id']
        basis = offer['receipt']['basis']
        assert {target['form'] for target in basis['targets']} == set(frames[RESULT]['forms'])
        assert basis['writer']['parent']['attempt_id'] == ATTEMPT and basis['writer']['draft'] == DRAFT
        assert basis['writer']['status'] == 'PROPOSED' and basis['writer']['parent']['status'] == 'BLOCKED'
        assert 'not the workspace ticket' in miner(
            miner_root, 'pull', job, 'reject-ticket', '--ticket', private/'workspace.json',
            '--scope', scope_path, '--result', RESULT, ok=False)
        for ident in ('real-proposal', 'lost-ack'):
            queued = miner(miner_root, 'queue', job, ident, '--offer', offer_id, '--form', FORM)
            assert queued['state'] == 'PENDING'
        normal = miner(miner_root, 'push', job, 'real-proposal', '--ticket', ticket)
        assert normal['state'] == 'SAVED' and normal['receipt']['card']['observed_hold_us'] == 1_100_000
        assert normal['receipt']['provider_calls'] == 0 and normal['receipt']['card']['writes_canon'] is False
        matched = miner(miner_root, 'compare', job, 'real-proposal', '--ticket', ticket)
        assert matched['state'] == 'MATCHED' and matched['sha256'] == normal['sha256']
        lost = miner(miner_root, 'inspect', job, 'lost-ack')
        assert lost['state'] == 'PENDING' and lost['local'] is None
        rejects = _reject_checks(port, master, limited, lost['request'])
        # The server commits, but the Miner outbox deliberately never gets this response.
        committed = send(port, limited, 'submit', lost['request'])
        assert committed['state'] == 'SAVED'
        send(port, limited, 'submit', lost['request'] | {'visual': None}, expected=400)
        rejects.append('changed repeat ID')
        put(out/'offer.json', offer)
        put(out/'proposal.json', normal)
        put(out/'reply-not-seen-by-miner.json', committed)
    offline = miner(miner_root, 'push', job, 'lost-ack', '--ticket', ticket, ok=False)
    assert 'refus' in offline.lower() or 'actively' in offline.lower(), offline
    assert miner(miner_root, 'inspect', job, 'lost-ack')['state'] == 'PENDING'
    with service(working, private, port, 'restarted.log') as (_, limited, ticket, restarted):
        assert restarted['instance'] != first['instance']
        replay = miner(miner_root, 'push', job, 'lost-ack', '--ticket', ticket)
        assert replay['state'] == 'REPLAYED' and replay['sha256'] == committed['sha256']
        assert replay['receipt'] == committed['receipt']
        assert miner(miner_root, 'compare', job, 'lost-ack', '--ticket', ticket)['state'] == 'MATCHED'
        load = _scale(port, limited, lost['request'], stress)
        page_rows, pages = _pages(port, limited)
        assert len(page_rows) == stress+3 and sum(r['kind'] == 'offer' for r in page_rows) == 1
        send(port, limited, 'receipt', HOLDS | {'result': RESULT, 'receipt': normal['receipt']['id']}, expected=404)
    assert _story_stamp(working) == before_story and _story_frame(working) == frames

    pair = out/'paired-backup'
    pair.mkdir()
    backup(working, pair/'noir')
    _journal_backup(job, pair/'miner-job')
    restored = out/'restored'
    restored.mkdir()
    backup(pair/'noir', restored/'noir')
    _journal_backup(pair/'miner-job', restored/'miner-job')
    restored_port = port_for_run()
    receipt_request = RELAPSE | {'result': RESULT, 'receipt': normal['receipt']['id']}
    cli_input = out/'receipt-request.json'
    put(cli_input, receipt_request)
    cli = json.loads(run(ROOT, 'prose_engine.cli', 'episode', 'scene.exchange.receipt',
                         '--timeline', restored/'noir'/'timeline.sqlite', '--request', cli_input))
    assert cli['sha256'] == normal['sha256'] and cli['receipt'] == normal['receipt']
    with studio(restored/'noir', RELAPSE['episode']) as (command, _):
        gui = command('scene.exchange.receipt', receipt_request)
        assert gui['sha256'] == normal['sha256'] and gui['receipt'] == normal['receipt']
    with service(restored/'noir', restored/'private', restored_port, 'restored.log') as (_, ticket_new, ticket_path, _):
        assert ticket_new['workspace'] != limited['workspace']
        assert wire(restored_port, limited, 'POST', '/v1/exchange',
                    {'action': 'scene.exchange.receipt', 'request': receipt_request})[0] == 403
        for ident, expected in (('lost-ack', committed), ('real-proposal', normal)):
            restored_ack = miner(miner_root, 'compare', restored/'miner-job', ident, '--ticket', ticket_path)
            assert restored_ack['receipt'] == expected['receipt'] and restored_ack['sha256'] == expected['sha256']
        assert _pages(restored_port, ticket_new) == (page_rows, pages)
        assert _story_stamp(restored/'noir') == before_story and _story_frame(restored/'noir') == frames
        # A new timeline revision on a disposable second copy makes new submissions stale.
        timeline = TimelineStore(restored/'noir'/'timeline.sqlite')
        current = timeline.get_episode(RELAPSE['episode'])
        timeline.save(RELAPSE['episode'], current['head'], graph=current['graph'])
        stale = send(restored_port, ticket_new, 'submit', lost['request'] | {'request_id': 'reject-stale'},
                     expected=400)
        assert 'changed' in stale['error'].lower()
        assert send(restored_port, ticket_new, 'receipt', receipt_request)['sha256'] == normal['sha256']
    final = {p.name: sha(p) for p in (origin/'timeline.sqlite', origin/'character-forms.sqlite', POINTER, clip, diagram)}
    assert initial == final
    evidence = {
        'result': RESULT, 'scope': RELAPSE, 'acceptance': 'VERIFIED_ON_COPIES',
        'operator': 'Independent Deep Miner dev-miner CLI and Noir loopback service',
        'source_sha256': catalog['clip']['sha256'], 'source_ranges_us': [x['range_us'] for x in catalog['evidence']],
        'offer': offer['sha256'], 'proposal': normal['sha256'], 'recovered_proposal': committed['sha256'],
        'writer': basis['writer'], 'card': normal['receipt']['card'], 'unresolved_source_identities': 2,
        'boundary_rejections': rejects + ['offline send remains pending', 'copy needs a new evidence ticket',
                                           'a new timeline revision blocks new evidence but keeps prior receipts readable'],
        'reopened_adapters': ['Noir CLI', 'Studio command API', 'Deep Miner CLI', 'Noir local service'],
        'frames': frames, 'full_story_and_form_state_preserved': True,
        'story_state_sha256': before_story, 'original_and_active_pointer_preserved': True,
        'provider_calls': 0, 'scale': load | {'paged_records': len(page_rows), 'pages': pages,
                                              'preserved_through_restore': True},
        'restore': 'Both SQLite journals backed up, integrity checked, restored to new paths and reopened',
    }
    put(out/'VERIFICATION.json', evidence)
    print(json.dumps(evidence, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('origin', 'before', 'out', 'miner-root', 'clip', 'diagram'):
        p.add_argument('--'+arg, required=True, type=Path)
    p.add_argument('--stress', type=int, choices=range(1, 1025), metavar='1..1024', default=256)
    args = p.parse_args()
    verify(args.origin, args.before, args.out, args.miner_root, args.clip, args.diagram, args.stress)


if __name__ == '__main__':
    main()
