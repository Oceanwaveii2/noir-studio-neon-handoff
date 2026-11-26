"""Local attempt reservations and recoverable writer responses."""
from contextlib import closing, contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3
from uuid import uuid4

from .deepseek import BudgetExceeded


class SessionAttemptError(RuntimeError):
    def __init__(self, message, *, state="blocked", attempt_id=None):
        super().__init__(message)
        self.state = state
        self.attempt_id = attempt_id


class AttemptJournal:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, job TEXT NOT NULL,
                scope TEXT NOT NULL, state TEXT NOT NULL, budget INTEGER NOT NULL,
                updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, request_id TEXT,
                prompt_sha256 TEXT, response_text TEXT, response_sha256 TEXT)""")
            columns = {row[1] for row in db.execute('PRAGMA table_info(attempts)')}
            for name in ('request_id', 'prompt_sha256', 'response_text', 'response_sha256'):
                if name not in columns:
                    db.execute(f'ALTER TABLE attempts ADD COLUMN {name} TEXT')
            db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS scoped_attempt_request ON attempts(request_id)
                          WHERE request_id IS NOT NULL''')
            yield db

    def identity(self):
        """Bind an in-flight draft to this journal, even before its first send."""
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS journal_identity (id TEXT NOT NULL)')
            row = db.execute('SELECT id FROM journal_identity').fetchone()
            if row:
                return row[0]
            ident = uuid4().hex
            db.execute('INSERT INTO journal_identity VALUES (?)', (ident,))
            return ident

    def reserve(self, provider, job, scope, limit, *, shared_budget=False, request_id=None, prompt_sha256=None):
        with self.transaction() as db:
            if request_id is not None:
                previous = db.execute('SELECT id,state FROM attempts WHERE request_id=?', (request_id,)).fetchone()
                if previous:
                    raise SessionAttemptError('This writer request already has an attempt. Reopen its saved draft.',
                                              state=previous[1], attempt_id=previous[0])
            relation = '(job=? OR (provider=? AND scope=?))' if shared_budget else 'provider=? AND (job=? OR scope=?)'
            search = (job,provider,scope) if shared_budget else (provider,job,scope)
            pending = db.execute(f"""SELECT id, state FROM attempts WHERE {relation}
                AND state IN ('started','remote_unknown','cancel_requested') LIMIT 1""", search).fetchone()
            if pending:
                raise SessionAttemptError("An earlier attempt is unresolved. Check its outcome before retrying.",
                                          state=pending[1], attempt_id=pending[0])
            if shared_budget:
                count, cap = db.execute('SELECT count(*), min(budget) FROM attempts WHERE job=?',(job,)).fetchone()
            else:
                count, cap = db.execute("SELECT count(*), min(budget) FROM attempts WHERE provider=? AND job=?",
                                        (provider, job)).fetchone()
            budget = limit if cap is None else min(limit, cap)
            if count >= budget:
                raise BudgetExceeded(f"Session attempt budget reached ({count}/{budget})")
            attempt = uuid4().hex
            db.execute("""INSERT INTO attempts (id,provider,job,scope,state,budget,request_id,prompt_sha256)
                          VALUES (?,?,?,?,'started',?,?,?)""",
                       (attempt, provider, job, scope, budget, request_id, prompt_sha256))
        return attempt, count + 1

    def bind_window(self, job, policy):
        """A restarted local service cannot silently widen the same window."""
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS writing_windows (job TEXT PRIMARY KEY, policy TEXT NOT NULL)')
            row=db.execute('SELECT policy FROM writing_windows WHERE job=?',(job,)).fetchone()
            if row and row[0] != policy:
                raise ValueError('Saved writer window has a different budget or provider list')
            db.execute('INSERT OR IGNORE INTO writing_windows VALUES (?,?)',(job,policy))

    def _transition(self, attempt, state, allowed):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM attempts WHERE id=?", (attempt,)).fetchone()
            if not row or row[0] not in allowed:
                raise ValueError("Unknown attempt or invalid state transition")
            db.execute("UPDATE attempts SET state=?, updated=CURRENT_TIMESTAMP WHERE id=?", (state, attempt))

    def finish(self, attempt, state, *, response_text=None):
        if state not in {"completed", "failed", "remote_unknown"}:
            raise ValueError("Invalid provider result")
        digest = sha256(response_text.encode('utf-8')).hexdigest() if response_text is not None else None
        with self.transaction() as db:
            updated = db.execute("""UPDATE attempts SET state=?, response_text=?, response_sha256=?,
                                    updated=CURRENT_TIMESTAMP WHERE id=? AND state='started'""",
                                 (state, response_text, digest, attempt))
            if updated.rowcount != 1:
                raise ValueError("Unknown attempt or invalid state transition")

    def recover(self, request_id, *, provider, prompt_sha256, journal_id, job=None):
        """Return a verified reply or prove that the original journal has no reservation."""
        with self.transaction() as db:
            identity = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_identity'").fetchone()
            if not identity or not db.execute('SELECT 1 FROM journal_identity WHERE id=?', (journal_id,)).fetchone():
                raise SessionAttemptError('The original writer journal is unavailable.', state='remote_unknown')
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM attempts WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            return None
        attempt = row['id']
        if (row['provider'] != provider or row['prompt_sha256'] != prompt_sha256
                or (job is not None and row['job'] != job)):
            raise SessionAttemptError('The saved attempt does not match this writer request.',
                                      state='remote_unknown', attempt_id=attempt)
        if row['state'] != 'completed':
            message = ('The writer did not return usable text.' if row['state'] == 'failed'
                       else 'The earlier writer response is unconfirmed. No request was repeated.')
            raise SessionAttemptError(message, state=row['state'], attempt_id=attempt)
        raw = row['response_text']
        if raw is None or sha256(raw.encode('utf-8')).hexdigest() != row['response_sha256']:
            raise SessionAttemptError('The writer completed, but its original response is unavailable or damaged.',
                                      state='remote_unknown', attempt_id=attempt)
        return attempt, raw

    def reconcile(self, attempt, state):
        """Operator action after checking the transport; does not contact the provider."""
        allowed = {
            "remote_unknown": {"started"},
            "cancel_requested": {"remote_unknown"},
            "cancelled": {"remote_unknown", "cancel_requested"},
            "completed": {"remote_unknown", "cancel_requested"},
            "failed": {"remote_unknown", "cancel_requested"},
        }
        if state not in allowed:
            raise ValueError("Invalid recovery state")
        self._transition(attempt, state, allowed[state])

    def list_attempts(self):
        if not self.path.is_file():
            return []
        with self.transaction() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("""SELECT id,provider,job,scope,state,budget,updated,
                           request_id,prompt_sha256,response_sha256 FROM attempts ORDER BY rowid""")]


def inspect_attempts(args):
    import json

    journal = AttemptJournal(args.ledger + ".attempts.sqlite")
    try:
        if args.attempt or args.state or args.checked:
            if not (args.attempt and args.state and args.checked):
                raise ValueError("Reconciliation requires --attempt, --state and --checked")
            journal.reconcile(args.attempt, args.state)
        print(json.dumps(journal.list_attempts(), indent=2))
    except (OSError, sqlite3.Error, ValueError) as exc:
        import sys
        print(f"Attempt journal: {exc}", file=sys.stderr)
        return 1
    return 0
