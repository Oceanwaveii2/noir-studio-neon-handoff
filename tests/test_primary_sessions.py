import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from prose_engine.providers import create_prose_provider
from prose_engine.providers.deepseek import BudgetExceeded
from prose_engine.providers.session_attempts import SessionAttemptError


class PrimarySessionTests(unittest.TestCase):
    def test_saved_scoped_request_cannot_reserve_again_in_another_job(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / 'usage.jsonl'
            journal = ledger.with_name(ledger.name + '.attempts.sqlite')
            with sqlite3.connect(journal) as db:
                db.executescript("""CREATE TABLE attempts (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, job TEXT NOT NULL,
                    scope TEXT NOT NULL, state TEXT NOT NULL, budget INTEGER NOT NULL,
                    updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    INSERT INTO attempts(id,provider,job,scope,state,budget)
                    VALUES ('older','codex-session','old-job','old-scope','remote_unknown',1);""")
            db.close()
            request = SimpleNamespace(request_id='scoped-' + '42' * 16)
            first = create_prose_provider('codex-session', ledger=ledger, max_calls=1,
                job_id='first', recovery_scope='before-moving', session_handler=lambda _: 'completed locally')
            self.assertEqual(first.generate_rewrite(request, 'a'), 'completed locally')
            restarted = create_prose_provider('codex-session', ledger=ledger, max_calls=1,
                job_id='second', recovery_scope='after-moving',
                session_handler=lambda _: self.fail('A reserved request was dispatched again'))
            with self.assertRaises(SessionAttemptError) as duplicate:
                restarted.generate_rewrite(request, 'a')
            self.assertEqual(duplicate.exception.attempt_id, first.last_attempt_id)
            attempts = first.attempts.list_attempts()
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]['state'], 'remote_unknown')
            self.assertIsNone(attempts[0]['request_id'])
            self.assertEqual(attempts[1]['request_id'], request.request_id)

    def test_timeout_cannot_redispatch_after_restart_or_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "usage.jsonl"
            calls = []
            def timeout(prompt):
                calls.append(prompt)
                raise TimeoutError()
            def make(job="stable"):
                return create_prose_provider("codex-session", session_handler=timeout,
                    ledger=ledger, job_id=job, recovery_scope="episode", max_calls=1)
            first = make()
            with self.assertRaises(SessionAttemptError) as lost:
                first.generate_rewrite(None, "private prompt")
            self.assertEqual(lost.exception.state, "remote_unknown")
            with self.assertRaises(SessionAttemptError):
                make("new-job").generate_rewrite(None, "duplicate")
            attempt = lost.exception.attempt_id
            first.attempts.reconcile(attempt, "cancel_requested")
            with self.assertRaises(SessionAttemptError):
                make().generate_rewrite(None, "duplicate")
            first.attempts.reconcile(attempt, "cancelled")
            with self.assertRaises(BudgetExceeded):
                make().generate_rewrite(None, "duplicate")
            self.assertEqual(calls, ["private prompt"])
            self.assertNotIn("private prompt", str(first.attempts.list_attempts()))

    def test_concurrent_scoped_jobs_cannot_both_dispatch(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(2) as pool:
            ready, release = Event(), Event()
            def handler(_):
                ready.set()
                if not release.wait(5):
                    raise TimeoutError()
                return "done"
            def make():
                return create_prose_provider("gemini-session", session_handler=handler,
                    ledger=Path(directory)/"usage.jsonl", recovery_scope="episode", max_calls=1)
            a, b = make(), make()
            future = pool.submit(a.generate_rewrite, None, "a")
            try:
                self.assertTrue(ready.wait(5))
                with self.assertRaises(SessionAttemptError) as denied:
                    b.generate_rewrite(None, "b")
                self.assertEqual(denied.exception.state, "started")
            finally:
                release.set()
            self.assertEqual(future.result(5), "done")

    def test_broken_journal_never_calls_handler(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "usage.jsonl"
            ledger.with_name(ledger.name + ".attempts.sqlite").write_text("not a database")
            provider = create_prose_provider("codex-session", ledger=ledger,
                session_handler=lambda _: self.fail("dispatched without durable reservation"))
            with self.assertRaisesRegex(SessionAttemptError, "Nothing was sent"):
                provider.generate_rewrite(None, "a")

    def test_completion_write_failure_leaves_unresolved_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = create_prose_provider("codex-session", ledger=Path(directory)/"usage.jsonl",
                session_handler=lambda _: "provider returned")
            with patch.object(provider.attempts, "finish", side_effect=OSError):
                with self.assertRaises(SessionAttemptError) as lost:
                    provider.generate_rewrite(None, "a")
            self.assertEqual(lost.exception.state, "remote_unknown")
            self.assertEqual(provider.attempts.list_attempts()[0]["state"], "started")
            with self.assertRaises(SessionAttemptError):
                provider.generate_rewrite(None, "a")

    def test_separate_handlers_and_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "usage.jsonl"
            codex = create_prose_provider("codex-session", session_handler=lambda p: "codex: " + p,
                                          max_calls=1, ledger=ledger)
            gemini = create_prose_provider("gemini-session", session_handler=lambda p: "gemini: " + p,
                                           max_calls=1, ledger=ledger)
            self.assertEqual(codex.generate_rewrite(None, "a"), "codex: a")
            self.assertEqual(gemini.generate_rewrite(None, "b"), "gemini: b")
            with self.assertRaises(BudgetExceeded):
                codex.generate_rewrite(None, "c")
            self.assertEqual([json.loads(line)["provider"] for line in ledger.read_text().splitlines()],
                             ["codex-session", "gemini-session"])

    def test_missing_session_never_falls_back(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "prose_engine.providers.primary_session.load_composer_bridge", return_value=None
        ):
            for name in ("codex-session", "gemini-session"):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "not connected"):
                    create_prose_provider(name)

    def test_handler_file_is_selected_for_the_named_session(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = Path(directory) / "handler.py"
            handler.write_text("def send(prompt):\n    return 'connected: ' + prompt\n")
            with patch.dict("os.environ", {"CODEX_SESSION_HANDLER": str(handler)}, clear=True), patch(
                "prose_engine.providers.primary_session.load_composer_bridge", return_value=None
            ):
                provider = create_prose_provider("codex-session", ledger=Path(directory) / "usage")
                self.assertEqual(provider.generate_rewrite(None, "test"), "connected: test")
                with self.assertRaisesRegex(ValueError, "gemini-session is not connected"):
                    create_prose_provider("gemini-session")
