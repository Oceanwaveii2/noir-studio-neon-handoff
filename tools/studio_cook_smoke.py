"""Qualify the shared Cook writer and scan the installed book library."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_writer(writer, output):
    from prose_engine.cook import prepare_episode
    from prose_engine.episode_commands import EpisodeCommands
    from prose_engine.notebook import DraftStore, NotebookStore
    from prose_engine.providers.deepseek_session import DeepSeekSessionProvider
    from prose_engine.providers.session_registry import host_adapter, session_names
    from story_graph.episode_timeline import TimelineStore

    if writer not in session_names():
        raise ValueError('Select a configured session writer')
    handler = host_adapter(writer)
    output.mkdir(parents=True, exist_ok=False)
    timeline = TimelineStore(output / 'timeline.sqlite', project_id='cook-smoke', universe_id='fixture')
    timeline.create_episode('station', 'Station clock', 'main', 1)
    placeholder = '[Missing detail: Two concrete action sentences about the station clock and the empty platform.]'
    source = 'INT. STATION - DAY\n\n' + placeholder + '\n\nMara: “The clock stopped.”\n'
    timeline.save('station', 0, script=source, source_name='synthetic-cook-smoke')
    book = NotebookStore(timeline)
    notebook = book.open('station')
    spoken = '“The clock stopped.”'
    offset = source.index(spoken)
    mask = {'id': 'frozen-quote', 'start': offset, 'end': offset + len(spoken), 'value': 100,
            'hard': True, 'sha256': sha256(spoken.encode()).hexdigest()}
    book.save('station', notebook['revision'], 1, notebook['blocks'], 25, [mask])
    prepared = prepare_episode(timeline, {'episode': 'station', 'timeline_revision': 1})
    ledger = output / 'writer-usage.jsonl'
    provider = DeepSeekSessionProvider(session_handler=handler, max_calls=1, ledger=ledger,
                                      job_id='isolated-cook-smoke', recovery_scope='cook-smoke')
    provider.name = provider.model_name = writer
    commands = EpisodeCommands(timeline, books_root=ROOT / 'books', provider_factory=lambda: provider)
    request_id = 'cook-smoke-' + uuid4().hex
    action = {'episode': 'station', 'branch': 'main', 'revision': 1, 'notebook_revision': prepared['revision'],
              'start': source.index(placeholder), 'end': source.index(placeholder) + len(placeholder),
              'provider': writer, 'references': 'none', 'max_attempts': 1, 'max_input_bytes': 20_000,
              'max_output_chars': 800, 'request_id': request_id,
              'direction': 'Replace the bracketed placeholder with one short plain paragraph of observed action. Return only the finished paragraph.',
              'compositor_preparation': prepared['receipt']['id']}
    commands.execute('run.selection', action)
    state = commands.execute('run.status', {'episode': 'station', 'request_id': request_id})
    evidence = {'writer': writer, 'run_id': request_id, 'status': state['status'],
                'source_sha256': sha256(source.encode()).hexdigest(), 'preparation': prepared['receipt']['id'],
                'reason': state['reason']}
    attempts = []
    if provider.attempts.path.is_file():
        from contextlib import closing
        with closing(sqlite3.connect(provider.attempts.path)) as c:
            attempts = c.execute("SELECT id,state,response_text,response_sha256 FROM attempts ORDER BY updated").fetchall()
    evidence['attempts'] = len(attempts)
    evidence['attempt_states'] = [{'id': ident, 'status': status, 'response_sha256': stamp}
                                  for ident, status, _, stamp in attempts]
    if len(attempts) == 1 and state['status'] == 'COMPLETED' and state['generation_receipt']:
        draft = DraftStore(book).open('station', 'main', state['draft_id'])
        ident, status, raw, stamp = attempts[0]
        receipt = draft['writer_receipt']
        if (status == 'completed' and raw and sha256(raw.encode()).hexdigest() == stamp
                and receipt['attempt_id'] == ident and receipt['raw_response_sha256'] == stamp
                and draft['text'].strip() != placeholder and timeline.get_episode('station')['script'] == source):
            evidence.update(verified=True, draft_id=draft['id'], provider_calls=1, writer_receipt=receipt,
                            polish=draft['compositor_polish'])
    (output / 'receipt.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence.get('verified') else 1


def library_stress(books):
    import joblib
    import numpy as np
    from prose_engine.library_indexes import ACTIVE, INDEXES, catalog, digest, index_path, library_status

    source_map = catalog(books)
    readiness = library_status(books, 'gemini-session')
    pointer = books / ACTIVE
    expected = json.loads(pointer.read_text(encoding='utf-8')).get('hashes', {}) if pointer.is_file() else {}
    evidence = {'manifest_entries': len(source_map['sources']), 'catalog_sha256': source_map['fingerprint'],
                'nonblank_sources': sum(stamp != 'blank-or-missing' for stamp in source_map['sources'].values()),
                'usable_sources': readiness['usable_books'], 'eligible_sources': readiness['eligible_books'],
                'indexes': {}}
    integrity = True
    for backend in INDEXES:
        try:
            path = index_path(books, backend)
            index_status = readiness['indexes'][backend]
            if index_status['state'] == 'unavailable' and expected.get(INDEXES[backend]):
                expected_sha = expected[INDEXES[backend]]
                actual_sha = digest(path)
                if actual_sha != expected_sha:
                    integrity = False
                    evidence['indexes'][backend] = {'readiness': index_status, 'sha256': actual_sha,
                                                    'expected_sha256': expected_sha}
                    continue
            index = joblib.load(path)
            vectors = np.asarray(index['vectors'])
            rows = index['meta']
            if vectors.ndim != 2 or not len(rows) or len(rows) != len(index['texts']) or len(rows) != len(vectors):
                raise ValueError('Vector, text and provenance row counts differ')
            hits = []
            for start in range(0, len(vectors), 4096):
                if not np.isfinite(vectors[start:start + 4096]).all():
                    raise ValueError('Index contains nonfinite vectors')
            for query in (0, len(rows) // 2, len(rows) - 1):
                hit = int(np.argmax(vectors @ vectors[query]))
                hits.append(rows[hit].get('source_id') or rows[hit].get('book'))
            evidence['indexes'][backend] = {
                'vectors': len(rows), 'dimensions': int(vectors.shape[1]),
                'source_ids': len({row.get('source_id') or row.get('book') for row in rows}),
                'queries': len(hits), 'readiness': index_status,
            }
        except (ValueError, OSError, KeyError) as exc:
            integrity = False
            evidence['indexes'][backend] = {'error': str(exc)}
    evidence['catalog_and_index_scan_passed'] = integrity and evidence['manifest_entries'] == 190
    evidence['active_retrieval_ready'] = all(index['state'] == 'ready' for index in readiness['indexes'].values())
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence['catalog_and_index_scan_passed'] and evidence['active_retrieval_ready'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--writer')
    mode.add_argument('--library-stress', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        if args.library_stress:
            return library_stress(ROOT / 'books')
        if not args.out:
            parser.error('--writer requires a new --out directory')
        return run_writer(args.writer, args.out.resolve())
    except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error) as exc:
        print(f'Studio check failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
