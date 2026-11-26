"""
Shared types for the book-source adapters.

A source is a catalog plus a fetch path. Sources must declare their license policy.
Only public-domain / open-access sources are enabled by default; the generic URL
adapter requires an explicit rights acknowledgement.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DEFAULT_UA = "NarrativeEngineBookFinder/1.0 (local research corpus; public-domain sources)"


class SourceError(RuntimeError):
    """Raised when a source cannot search or fetch."""


def fetch_bytes(url: str, timeout: int = 30, retries: int = 2) -> bytes:
    last: Optional[Exception] = None
    for _attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - surfaced as SourceError
            last = exc
    raise SourceError(f"fetch failed: {url}: {last}")


def fetch_text(url: str, timeout: int = 30, retries: int = 2) -> str:
    return fetch_bytes(url, timeout=timeout, retries=retries).decode("utf-8", "replace")


def slugify(value: str, limit: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return (slug or "book")[:limit]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BookCandidate:
    source: str
    source_id: str
    title: str
    author: str = ""
    year: str = ""
    language: str = "en"
    license: str = "public-domain"
    landing_url: str = ""
    download_url: str = ""
    formats: Dict[str, str] = field(default_factory=dict)
    themes: Sequence[str] = ()
    score: float = 0.0
    reasons: Sequence[str] = ()

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "author": self.author,
            "year": self.year,
            "language": self.language,
            "license": self.license,
            "landing_url": self.landing_url,
            "download_url": self.download_url,
            "formats": dict(self.formats),
            "themes": list(self.themes),
            "score": round(float(self.score), 4),
            "reasons": list(self.reasons),
        }


@dataclass
class FetchResult:
    candidate: BookCandidate
    path: Path
    text: str
    sha256: str

    @property
    def chars(self) -> int:
        return len(self.text)


class BookSource(ABC):
    id: str = "base"
    name: str = "base"
    license_policy: str = "unknown"
    enabled_by_default: bool = False
    supports_download: bool = True

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        raise NotImplementedError

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        raise SourceError(f"{self.name} does not support direct download")

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "license_policy": self.license_policy,
            "enabled_by_default": self.enabled_by_default,
            "supports_download": self.supports_download,
        }
