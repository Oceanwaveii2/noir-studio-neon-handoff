"""Zero-dependency direct Gemini REST provider (fast path when GEMINI_API_KEY / GOOGLE_API_KEY is set)."""
from __future__ import annotations

import json
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_DIRECT_MODEL = "gemini-2.5-flash"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def direct_api_key() -> str:
    return (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()


def direct_api_available() -> bool:
    return bool(direct_api_key())


def generate_direct(
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout_s: int = 120,
    temperature: float = 0.85,
) -> str:
    """Call Gemini REST generateContent directly without spawning an external CLI process."""
    key = direct_api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not set.")
    chosen_model = (model or os.environ.get("NOIR_GEMINI_DIRECT_MODEL") or DEFAULT_DIRECT_MODEL).strip()
    url = _ENDPOINT.format(model=chosen_model, key=key)
    body = {
        "contents": [{"role": "user", "parts": [{"text": str(prompt)}]}],
        "generationConfig": {"temperature": float(temperature)},
    }
    req = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=max(15, int(timeout_s))) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Gemini direct API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Gemini direct API network error: {exc.reason}") from exc

    candidates = payload.get("candidates") or ()
    if not candidates:
        raise RuntimeError("Gemini direct API returned no candidates.")
    parts = ((candidates[0].get("content") or {}).get("parts")) or ()
    text = "".join(str(p.get("text") or "") for p in parts).strip()
    if not text:
        raise RuntimeError("Gemini direct API returned empty text.")
    return text
