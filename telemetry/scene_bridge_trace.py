"""Append-only structural evidence for a scoped scene bridge run."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock
from time import perf_counter


def stamp(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def read_trace(path):
    rows = []
    with Path(path).open(encoding='utf-8') as stream:
        for raw in stream:
            item = json.loads(raw)
            digest = item.pop('sha256')
            expected = rows[-1]['sha256'] if rows else None
            if (item['sequence'] != len(rows)+1 or item['previous_sha256'] != expected
                    or (rows and item['run'] != rows[0]['run']) or stamp(item) != digest):
                raise ValueError('The scene trace failed its sequence or digest check')
            rows.append(item | {'sha256': digest})
    return rows


class Trace:
    """Only the run owner writes events; helpers share this instance across threads."""

    def __init__(self, path, run):
        self.path = Path(path)
        self.run = run
        self.lock = Lock()
        self.scope = {}
        rows = read_trace(path) if self.path.is_file() else []
        if rows and rows[0]['run'] != run:
            raise ValueError('A different scene run owns this trace')
        self.sequence = len(rows)
        self.previous = rows[-1]['sha256'] if rows else None

    def emit(self, stage, status, *, case='spring-break', mode='local', parent=None,
             elapsed_ms=None, **evidence):
        with self.lock:
            sequence = self.sequence + 1
            ident = f'{self.run}:{sequence:04d}'
            item = {'schema': 'noir.scene-bridge.trace/1', 'event': ident, 'run': self.run,
                    'sequence': sequence, 'utc': datetime.now(timezone.utc).isoformat(),
                    'previous_sha256': self.previous, 'parent_event': parent, 'case': case,
                    'mode': mode, 'stage': stage, 'status': status, 'elapsed_ms': elapsed_ms,
                    'scope': dict(self.scope), 'evidence': evidence}
            item['sha256'] = stamp(item)
            with self.path.open('a', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(item, ensure_ascii=False, separators=(',', ':'))+'\n')
                stream.flush()
                os.fsync(stream.fileno())
            self.sequence, self.previous = sequence, item['sha256']
            return ident

    @contextmanager
    def span(self, stage, *, case='spring-break', mode='local', parent=None, **inputs):
        started = perf_counter()
        ident = self.emit(stage, 'STARTED', case=case, mode=mode, parent=parent, **inputs)
        outputs = {}
        try:
            yield ident, outputs
        except Exception as exc:
            self.emit(stage, 'FAILED', case=case, mode=mode, parent=ident,
                      elapsed_ms=round((perf_counter()-started)*1000, 2), error=type(exc).__name__)
            raise
        else:
            self.emit(stage, 'CHECKED', case=case, mode=mode, parent=ident,
                      elapsed_ms=round((perf_counter()-started)*1000, 2), **outputs)
