"""Offline edits provider: rewrites come from a local JSON file, never a network call."""

import json
from pathlib import Path
from typing import Dict

from ..models import ProseRewriteRequest
from .base import BaseProseProvider


class EditsProvider(BaseProseProvider):
    """Serves rewrites keyed by the exact original paragraph text."""

    name = "edits"

    def __init__(self, edits_path: str | Path, model_name: str = "local-edits"):
        super().__init__(model_name=model_name)
        entries = json.loads(Path(edits_path).read_text(encoding="utf-8"))
        self._by_original: Dict[str, str] = {}
        for entry in entries:
            original = (entry.get("original") or "").strip()
            text = (entry.get("text") or "").strip()
            if original and text:
                self._by_original[original] = text

    def generate_rewrite(self, request: ProseRewriteRequest, prompt: str) -> str:
        return self._by_original.get(request.original_text.strip(), request.original_text)
