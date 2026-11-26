"""Explicit host-provided connections for the primary rendering sessions."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .deepseek_session import DeepSeekSessionProvider, load_handler
from .composer_bridge import load_composer_bridge, load_isolated_composer_bridge

DEFAULT_SESSION_LEDGER = Path(__file__).resolve().parents[2] / ".app-steward/local/session_usage.jsonl"


class PrimarySessionProvider(DeepSeekSessionProvider):
    def __init__(self, provider: str, session_handler: Callable[[str], str] | None = None,
                 handler_path: str | None = None, max_calls: int | None = None,
                 ledger: str | Path = DEFAULT_SESSION_LEDGER,
                 job_id: str | None = None, recovery_scope: str | None = None, **options: object):
        if provider not in ("codex", "gemini"):
            raise ValueError("Unknown primary session provider.")
        path = handler_path or os.getenv(f"{provider.upper()}_SESSION_HANDLER")
        if session_handler is None:
            if path:
                session_handler = load_handler(path)
            else:
                session_handler = load_composer_bridge(provider)
            if session_handler is None:
                raise ValueError(f"{provider}-session is not connected; supply a host handler or set "
                                 f"{provider.upper()}_SESSION_HANDLER.")
        if not callable(session_handler):
            raise ValueError("Session handler must be callable.")
        if max_calls is None:
            max_calls = int(os.getenv(f"{provider.upper()}_SESSION_MAX_CALLS", "20"))
        if max_calls < 0:
            raise ValueError("Session call budget must be nonnegative.")
        self.name = f"{provider}-session"
        super().__init__(session_handler=session_handler, max_calls=max_calls, ledger=ledger,
                         job_id=job_id, recovery_scope=recovery_scope, **options)
        self.model_name = self.name


def create_scoped_provider(mode: str, *, recovery_scope: str | None = None) -> DeepSeekSessionProvider:
    """Keep built-in sessions isolated and other sessions host-registered."""
    if mode not in ("codex-session", "gemini-session"):
        from .session_registry import host_adapter, session_names
        if mode not in session_names():
            raise ValueError('Choose a configured writing session.')
        result=DeepSeekSessionProvider(session_handler=host_adapter(mode),max_calls=1,ledger=DEFAULT_SESSION_LEDGER,
                                       recovery_scope=recovery_scope)
        result.name=result.model_name=mode
        return result
    provider = mode.removesuffix("-session")
    limit = int(os.getenv(f"{provider.upper()}_SESSION_MAX_CALLS", "20"))
    if limit < 0:
        raise ValueError("Session attempt budget must be nonnegative.")
    return PrimarySessionProvider(provider, session_handler=load_isolated_composer_bridge(provider),
                                  max_calls=min(1, limit), recovery_scope=recovery_scope)
