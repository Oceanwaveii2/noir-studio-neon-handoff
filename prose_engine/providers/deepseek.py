"""
DeepSeek provider (OpenAI-compatible API) with a spend guard.

Key resolution: DEEPSEEK_API_KEY, then local_secrets.json ("deepseek_api_key").

Budget: DEEPSEEK_MAX_CALLS (default 20) and DEEPSEEK_BUDGET_TOKENS (default 20000).
Every call is appended to eval/api_usage.jsonl. When either cap is reached the provider raises
BudgetExceeded instead of spending more.

    python -m prose_engine condition --file scene.md --provider deepseek ...
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..models import ProseRewriteRequest
from .base import BaseProseProvider

DEFAULT_MODEL = "deepseek-chat"
SYSTEM_PROMPT = (
    "You are a screenwriter doing a line edit. Rewrite the paragraph so it is physical and "
    "specific, keep every fact, name and line of dialogue, and match the reference voice. "
    "Return only the rewritten paragraph."
)


class BudgetExceeded(RuntimeError):
    """Raised before a call that would exceed the configured spend caps."""


def _project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path(__file__).resolve().parents[2]


def load_deepseek_key() -> Optional[str]:
    key = os.getenv("DEEPSEEK_API_KEY")
    if key:
        return key.strip()
    path = _project_root() / "local_secrets.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        key = data.get("deepseek_api_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    return None


class DeepSeekProvider(BaseProseProvider):
    name = "deepseek"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        temperature: float = 0.8,
        max_new_tokens: int = 400,
        max_calls: Optional[int] = None,
        budget_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        transport: Optional[Callable] = None,
        ledger: str | Path = "eval/api_usage.jsonl",
        **_: object,
    ):
        super().__init__(model_name=model_name)
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens
        self.max_calls = max_calls if max_calls is not None else int(os.getenv("DEEPSEEK_MAX_CALLS", "20"))
        self.budget_tokens = (
            budget_tokens if budget_tokens is not None
            else int(os.getenv("DEEPSEEK_BUDGET_TOKENS", "20000"))
        )
        self.api_key = api_key or load_deepseek_key()
        if not self.api_key:
            raise ValueError(
                "No DeepSeek key: set DEEPSEEK_API_KEY or add \"deepseek_api_key\" to local_secrets.json"
            )
        self.url = "https://api.deepseek.com/chat/completions"
        self.transport = transport
        if isinstance(ledger, (str, Path)) and not Path(ledger).is_absolute() and str(ledger) == "eval/api_usage.jsonl":
            try:
                from ..paths import asset
                self.ledger = asset("telemetry", "eval", "api_usage.jsonl")
            except Exception:
                self.ledger = Path(ledger)
        else:
            self.ledger = Path(ledger)
        self.calls = 0
        self.tokens = 0
        self._load_spent_today()

    def _load_spent_today(self) -> None:
        """Caps are per UTC day across processes: count today's ledger rows."""
        if not self.ledger.is_file():
            return
        today = datetime.now(timezone.utc).date().isoformat()
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("ts", "")).startswith(today):
                self.calls += 1
                self.tokens += int(row.get("prompt_tokens", 0)) + int(row.get("completion_tokens", 0))

    def _check_budget(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"call budget reached ({self.calls}/{self.max_calls})")
        if self.tokens >= self.budget_tokens:
            raise BudgetExceeded(f"token budget reached ({self.tokens}/{self.budget_tokens})")

    def _post(self, payload: dict) -> dict:
        if self.transport is not None:
            return self.transport(payload)
        import httpx

        response = httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()

    def _record(self, usage: dict) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": self.model_name,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "calls": self.calls,
            "tokens": self.tokens,
        }
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def generate_rewrite(self, request: ProseRewriteRequest, prompt: str) -> str:
        self._check_budget()
        data = self._post(
            {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_new_tokens,
            }
        )
        usage = data.get("usage") or {}
        self.calls += 1
        self.tokens += int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))
        self._record(usage)
        return (data["choices"][0]["message"]["content"] or "").strip()
