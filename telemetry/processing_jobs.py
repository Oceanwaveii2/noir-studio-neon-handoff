"""Persistent activity for inspectable, local processing jobs."""
from contextlib import contextmanager
import json
from sqlite3 import OperationalError
from threading import Event, Thread
from time import time
from uuid import uuid4


LEASE_SECONDS = 8
TABLE = 'processing_jobs'
ACTIVE = ('QUEUED', 'RUNNING')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class Job:
    def __init__(self, connect, scope, kind, title, steps, inputs):
        self.connect = connect
        self.scope = _json(scope)
        self.data = {
            'id': 'job-' + uuid4().hex, 'scope': scope, 'kind': kind, 'title': title,
            'status': 'QUEUED', 'created_at': time(), 'inputs': inputs, 'outputs': {},
            'steps': [{'id': ident, 'stage': stage, 'label': label, 'status': 'QUEUED'}
                      for ident, stage, label in steps],
        }
        self.steps = {s['id']: s for s in self.data['steps']}
        self.stopped = Event()
        self.thread = Thread(target=self._renew, daemon=True, name='noir-job-lease')

    def __enter__(self):
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS processing_jobs (
                         id TEXT PRIMARY KEY, scope TEXT NOT NULL, touched REAL NOT NULL, payload TEXT NOT NULL)''')
            c.execute('CREATE INDEX IF NOT EXISTS processing_scope ON processing_jobs(scope)')
            c.execute('INSERT INTO processing_jobs VALUES(?,?,?,?)',
                      (self.data['id'], self.scope, time(), _json(self.data)))
        self.thread.start()
        return self

    def _renew(self):
        while not self.stopped.wait(1):
            try:
                with self.connect() as c:
                    c.execute('UPDATE processing_jobs SET touched=? WHERE id=?', (time(), self.data['id']))
            except OperationalError:
                # A short competing SQLite write can delay a heartbeat.
                continue

    def _save(self):
        with self.connect() as c:
            c.execute('UPDATE processing_jobs SET touched=?,payload=? WHERE id=?',
                      (time(), _json(self.data), self.data['id']))

    @contextmanager
    def step(self, ident, inputs=None):
        part = self.steps[ident]
        if part['status'] != 'QUEUED':
            raise ValueError('Processing step already resolved')
        started = time()
        self.data['status'] = 'RUNNING'
        part.update(status='RUNNING', started_at=started, inputs=inputs or {})
        self._save()
        outputs = {}
        try:
            yield outputs
        except Exception as exc:
            part.update(status='FAILED', error=_error(exc))
            raise
        else:
            part.update(status='COMPLETED', outputs=outputs)
        finally:
            part['finished_at'] = time()
            self._save()

    def skip(self, ident, reason):
        self.steps[ident].update(status='SKIPPED', reason=reason, finished_at=time())
        self._save()

    def __exit__(self, kind, error, traceback):
        self.stopped.set()
        self.thread.join()
        now = time()
        status = 'COMPLETED' if error is None else 'FAILED' if isinstance(error, Exception) else 'UNKNOWN'
        self.data.update(status=status, finished_at=now)
        if error:
            self.data['error'] = _error(error)
        for part in self.steps.values():
            if part['status'] == 'QUEUED':
                part.update(status='SKIPPED', reason='Step was not reached.', finished_at=now)
            elif part['status'] == 'RUNNING':
                part.update(status='UNKNOWN', reason='The step was interrupted.', finished_at=now)
        self._save()


def _error(error):
    return str(error)[:360] if isinstance(error, ValueError) else type(error).__name__


def read(c, scope, ident=None, *, now=None):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='processing_jobs' AND type='table'").fetchone():
        return []
    rows = c.execute('SELECT touched,payload FROM processing_jobs WHERE scope=? '
                     'AND (? IS NULL OR id=?) ORDER BY rowid DESC LIMIT 40', (_json(scope), ident, ident))
    now = time() if now is None else now
    result = []
    for row in rows:
        job = json.loads(row['payload'])
        end = job.get('finished_at', now)
        if job['status'] in ACTIVE and now - row['touched'] > LEASE_SECONDS:
            end = row['touched']
            job.update(status='UNKNOWN', finished_at=end, error='The worker stopped reporting.')
            for part in job['steps']:
                if part['status'] == 'RUNNING':
                    part.update(status='UNKNOWN', reason='Interrupted before a final receipt.', finished_at=end)
                elif part['status'] == 'QUEUED':
                    part.update(status='SKIPPED', reason='Step was not reached.', finished_at=end)
        job['elapsed_ms'] = max(0, round((end - job['created_at']) * 1000))
        for part in job['steps']:
            started = part.get('started_at')
            part['elapsed_ms'] = (max(0, round((part.get('finished_at', end) - started) * 1000))
                                  if started is not None else None)
        result.append(job)
    return result
