"""Model providers for the standalone engine."""

import os
from typing import Any, Optional

from .base import BaseProseProvider
from .edits import EditsProvider
from .deepseek import DeepSeekProvider
from .deepseek_session import DeepSeekSessionProvider
from .local_llm import DEFAULT_LOCAL_MODEL, LocalTransformersProvider
from .mock_provider import MockProseProvider
from .primary_session import PrimarySessionProvider


def create_prose_provider(
    mode: str = "mock",
    api_key: Optional[str] = None,
    session_handler: Optional[Any] = None,
    model_name: Optional[str] = None,
    **kwargs: Any,
) -> BaseProseProvider:
    """Factory helper to instantiate a configured model provider."""
    normalized_mode = (mode or "mock").lower().strip()
    if normalized_mode in ("codex-session", "gemini-session"):
        return PrimarySessionProvider(
            normalized_mode.removesuffix("-session"), session_handler=session_handler, **kwargs
        )
    if normalized_mode in ("deepseek-session", "deepseek_session"):
        return DeepSeekSessionProvider(
            session_handler=session_handler, model_name=model_name or "deepseek-session", **kwargs
        )
    if normalized_mode == "deepseek":
        return DeepSeekProvider(model_name=model_name or "deepseek-chat", **kwargs)
    if normalized_mode == "local":
        return LocalTransformersProvider(
            model_name=model_name or DEFAULT_LOCAL_MODEL, **kwargs
        )
    if normalized_mode == "edits":
        edits_path = kwargs.pop("edits_path", None) or os.getenv("PROSE_EDITS_PATH")
        if not edits_path:
            raise ValueError("provider 'edits' needs edits_path (CLI: --edits FILE)")
        return EditsProvider(edits_path, model_name=model_name or "local-edits")
    if normalized_mode == "mock":
        return MockProseProvider(model_name=model_name or "synthetic-mock-v1", **kwargs)
    raise ValueError(
        f"Unknown provider mode: '{mode}'. Core modes: 'mock', 'edits', 'local', 'deepseek', 'deepseek-session', 'codex-session', 'gemini-session'."
    )


__all__ = [
    "BaseProseProvider",
    "MockProseProvider",
    "LocalTransformersProvider",
    "EditsProvider",
    "DeepSeekProvider",
    "DeepSeekSessionProvider",
    "create_prose_provider",
]
