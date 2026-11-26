"""
DeepSeek session provider: the host injects a handler, the repo stores no credentials.

The handler is any callable `send(prompt: str) -> str` that talks to a DeepSeek session the host
already owns (browser cookies, an automation bridge, a local proxy). This mirrors the Gemini
session transport.

Resolution order:
  1. `session_handler=` keyword (in-process)
  2. `DEEPSEEK_SESSION_HANDLER` = path to a .py file exposing `send(prompt) -> str`
  3. error

Spend guard: session calls are billed to whatever owns the session, so only the call count is
capped (`max_calls`, default 20). Token counts are unknown and not recorded.

    DEEPSEEK_SESSION_HANDLER=C:/path/to/my_deepseek_session.py \
      python -m prose_engine condition --file scene.md --provider deepseek-session
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from ..models import ProseRewriteRequest
from .base import BaseProseProvider
from .session_attempts import AttemptJournal, SessionAttemptError


def load_handler(path: str | Path) -> Callable[[str], str]:
    target = Path(path)
    if not target.is_file():
        raise ValueError(f"session handler not found: {target}")
    spec = importlib.util.spec_from_file_location("deepseek_session_handler", target)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    handler = getattr(module, "send", None)
    if not callable(handler):
        raise ValueError(f"{target} must expose send(prompt) -> str")
    return handler


class DeepSeekSessionProvider(BaseProseProvider):
    name = "deepseek-session"

    def __init__(
        self,
        session_handler: Optional[Callable[[str], str]] = None,
        handler_path: Optional[str] = None,
        max_calls: Optional[int] = None,
        ledger: str | Path = "eval/session_usage.jsonl",
        job_id: str | None = None,
        recovery_scope: str | None = None,
        shared_budget: bool = False,
        max_prompt_bytes: int | None = None,
        **_: object,
    ):
        super().__init__(model_name="deepseek-session")
        path = handler_path or os.getenv("DEEPSEEK_SESSION_HANDLER")
        if session_handler is not None:
            self.handler = session_handler
        elif path:
            self.handler = load_handler(path)
        else:
            raise ValueError(
                "deepseek-session needs a handler: pass session_handler= or set "
                "DEEPSEEK_SESSION_HANDLER to a .py file exposing send(prompt)"
            )
        self.max_calls = max_calls if max_calls is not None else int(os.getenv("DEEPSEEK_MAX_CALLS", "20"))
        if type(self.max_calls) is not int or self.max_calls < 0:
            raise ValueError("Session attempt budget must be a nonnegative integer.")
        self.calls = 0
        self.last_attempt_id = None
        self.last_response_sha256 = None
        self.ledger = Path(ledger)
        self.job_id = job_id or uuid4().hex
        self.recovery_scope = recovery_scope or job_id or "standalone"
        self.shared_budget = shared_budget
        self.max_prompt_bytes = max_prompt_bytes
        self.attempts = AttemptJournal(self.ledger.with_name(self.ledger.name + ".attempts.sqlite"))

    def generate_rewrite(self, request: ProseRewriteRequest, prompt: str) -> str:
        self.last_attempt_id = None
        self.last_response_sha256 = None
        encoded = prompt.encode('utf-8')
        if self.max_prompt_bytes is not None and len(encoded) > self.max_prompt_bytes:
            raise SessionAttemptError('Writer prompt exceeds the configured byte limit; nothing was sent.',state='rejected')
        request_id = getattr(request, 'request_id', None)
        scoped_id = request_id if isinstance(request_id, str) and re.fullmatch(r'scoped-[0-9a-f]{32}', request_id) else None
        try:
            attempt, self.calls = self.attempts.reserve(self.name, self.job_id, self.recovery_scope,
                self.max_calls, shared_budget=self.shared_budget, request_id=scoped_id,
                prompt_sha256=sha256(encoded).hexdigest())
            self.last_attempt_id = attempt
        except (OSError, sqlite3.Error) as exc:
            raise SessionAttemptError("Could not reserve an attempt. Nothing was sent.") from exc
        try:
            raw = self.handler(prompt)
        except BaseException as exc:
            self._finish(attempt, "remote_unknown")
            if not isinstance(exc, Exception):
                raise
            raise SessionAttemptError("The provider outcome is unknown. Check the attempt before retrying.",
                                      state="remote_unknown", attempt_id=attempt) from exc
        if not isinstance(raw, str) or not raw.strip():
            self._finish(attempt, "failed", response_text=raw if isinstance(raw, str) else None)
            raise SessionAttemptError("The provider returned no usable text.", state="failed", attempt_id=attempt)
        text = raw if getattr(request, "protected_spans", None) else raw.strip()
        self._finish(attempt, "completed", response_text=raw)
        self.last_response_sha256 = sha256(raw.encode('utf-8')).hexdigest()
        try:
            with self.ledger.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                    "provider": self.name, "calls": self.calls, "chars": len(text),
                    "attempt_id": attempt, "job_id": self.job_id}) + "\n")
        except OSError:
            logging.getLogger(__name__).warning("Attempt %s completed; optional usage receipt could not be written.", attempt)
        return text

    def recover_rewrite(self, request, prompt_sha256, journal_id, job_id):
        """Read a reply for a persisted draft without contacting the handler."""
        if self.shared_budget and job_id != self.job_id:
            raise SessionAttemptError('The original writer window is unavailable.', state='remote_unknown')
        recovered = self.attempts.recover(request.request_id, provider=self.name, prompt_sha256=prompt_sha256,
                                          journal_id=journal_id, job=self.job_id if self.shared_budget else None)
        if recovered is None:
            return None
        self.last_attempt_id, raw = recovered
        self.last_response_sha256 = sha256(raw.encode('utf-8')).hexdigest()
        return raw if request.protected_spans else raw.strip()

    def _finish(self, attempt, state, *, response_text=None):
        try:
            self.attempts.finish(attempt, state, response_text=response_text)
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise SessionAttemptError("Could not record the provider outcome. Reconcile the attempt before retrying.",
                                      state="remote_unknown", attempt_id=attempt) from exc
