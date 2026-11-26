"""Explicit bridge to an existing, separately installed Narrative Composer."""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

BRIDGE_CONFIG = Path(__file__).resolve().parents[2] / ".app-steward/local/primary-session-bridge.json"
DEFAULT_GEMINI_TIMEOUT_S = 240


def _gemini_timeout_seconds() -> int:
    raw = os.environ.get("NOIR_GEMINI_TIMEOUT", str(DEFAULT_GEMINI_TIMEOUT_S)).strip()
    try:
        val = int(raw)
    except ValueError:
        val = DEFAULT_GEMINI_TIMEOUT_S
    return max(60, min(600, val))


def _timeout_runner():
    timeout_s = _gemini_timeout_seconds()

    def _run(args, *pargs, **kwargs):
        patched = list(args)
        for idx in range(len(patched) - 1):
            if patched[idx] == "--print-timeout":
                patched[idx + 1] = f"{timeout_s}s"
                break
        kwargs["timeout"] = timeout_s + 15
        return subprocess.run(patched, *pargs, **kwargs)

    return _run


def bridge_config() -> Path:
    """Use the workstation's trusted adapter setup from a standalone install."""
    return Path(os.environ.get('NOIR_COMPOSER_BRIDGE_CONFIG') or BRIDGE_CONFIG)


def load_composer_bridge(provider: str):
    config_path = bridge_config()
    if not config_path.is_file():
        return None
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["composer_root"]).resolve()
    package = root / "narrative_composer"
    if not (package / "__init__.py").is_file():
        raise ValueError("Configured Narrative Composer installation is unavailable.")
    # Do not silently attach a different installation already imported by the host.
    loaded = sys.modules.get("narrative_composer")
    if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(package):
        raise ValueError("A different Narrative Composer installation is already loaded.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if provider == "gemini":
        from .gemini_direct import direct_api_available, generate_direct
        if direct_api_available() and os.environ.get("NOIR_FORCE_CLI_GEMINI", "").strip() != "1":
            timeout_s = _gemini_timeout_seconds()
            return lambda prompt: generate_direct(prompt, timeout_s=timeout_s)
        module = importlib.import_module("narrative_composer.gemini_session")
        state = config_path.parent / "gemini-u75-session.json"
        session = module.GeminiCliSession(state)
        if hasattr(session, "runner"):
            session.runner = _timeout_runner()
        model_override = os.environ.get("NOIR_GEMINI_MODEL", "gemini-3.8-flash-medium").strip()
        if model_override and hasattr(session, "model"):
            session.model = model_override
        if not session.executable:
            raise ValueError("Antigravity CLI is unavailable.")
        return lambda prompt: session.run(prompt, label="Narrative Engine proposal")
    if provider == "codex":
        module = importlib.import_module("narrative_composer.prose.providers.codex_session")
        client = module.CodexSessionProseProvider()
        return lambda prompt: client.generate_rewrite(SimpleNamespace(request_id=uuid4().hex), prompt)
    raise ValueError("Unknown session provider.")


def load_isolated_composer_bridge(provider: str):
    """Use the configured Composer's restricted clients without resuming shared history."""
    config_path = bridge_config()
    if not config_path.is_file():
        raise ValueError("The primary session bridge is not configured.")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(config["composer_root"]).resolve()
    package = root / "narrative_composer"
    if not (package / "__init__.py").is_file():
        raise ValueError("Configured Narrative Composer installation is unavailable.")
    loaded = sys.modules.get("narrative_composer")
    if loaded is not None and not Path(loaded.__file__).resolve().is_relative_to(package):
        raise ValueError("A different Narrative Composer installation is already loaded.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if provider == "gemini":
        from .gemini_direct import direct_api_available, generate_direct
        if direct_api_available() and os.environ.get("NOIR_FORCE_CLI_GEMINI", "").strip() != "1":
            timeout_s = _gemini_timeout_seconds()
            return lambda prompt: generate_direct(prompt, timeout_s=timeout_s)
        module = importlib.import_module("narrative_composer.gemini_session")
        state = config_path.parent / "scoped-sessions" / ("gemini-" + uuid4().hex + ".json")
        if state.exists():
            raise ValueError("Fresh session destination unexpectedly exists.")
        session = module.GeminiCliSession(state)
        if hasattr(session, "runner"):
            session.runner = _timeout_runner()
        model_override = os.environ.get("NOIR_GEMINI_MODEL", "gemini-3.8-flash-medium").strip()
        if model_override and hasattr(session, "model"):
            session.model = model_override
        if not session.executable:
            raise ValueError("Antigravity CLI is unavailable.")
        return lambda prompt: session.run(prompt, label="Scoped narrative proposal")
    if provider == "codex":
        module = importlib.import_module("narrative_composer.prose.providers.codex_session")
        client = module.CodexSessionProseProvider()
        return lambda prompt: client.generate_rewrite(SimpleNamespace(request_id=uuid4().hex), prompt)
    raise ValueError("Unknown session provider.")
