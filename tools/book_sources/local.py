"""
Local import and explicit-URL adapters.

`LocalSource` is for files the user already owns. `ExternalUrlSource` is a deliberately
manual adapter: it only downloads when the caller explicitly acknowledges the rights.
It is not a shadow-library scraper and is disabled by default.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from .base import (
    BookCandidate,
    BookSource,
    FetchResult,
    SourceError,
    fetch_text,
    sha256_text,
    slugify,
)


class LocalSource(BookSource):
    id = "local"
    name = "Local files"
    license_policy = "User-supplied; the user is responsible for the rights."
    enabled_by_default = True
    supports_download = True

    def __init__(self, directory: str | Path = "books/incoming"):
        self.directory = Path(directory)

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        terms = [term for term in query.lower().split() if term]
        candidates: List[BookCandidate] = []
        if not self.directory.is_dir():
            return candidates
        for path in sorted(self.directory.iterdir()):
            if path.suffix.lower() not in {".txt", ".pdf", ".epub"}:
                continue
            if terms and not all(term in path.stem.lower() for term in terms):
                continue
            candidates.append(
                BookCandidate(
                    source=self.id,
                    source_id=str(path),
                    title=path.stem,
                    license=self.license_policy,
                    landing_url=str(path),
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        source = Path(candidate.source_id)
        if not source.is_file():
            raise SourceError(f"local file missing: {source}")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / source.name
        if target.resolve() != source.resolve():
            shutil.copy2(source, target)
        text = source.read_text(encoding="utf-8", errors="replace") if source.suffix == ".txt" else ""
        return FetchResult(
            candidate=candidate,
            path=target,
            text=text,
            sha256=sha256_text(text) if text else "",
        )


class ExternalUrlSource(BookSource):
    id = "external_url"
    name = "Explicit URL (rights acknowledged)"
    license_policy = "User-provided URL; the user confirms the rights and the source's terms."
    enabled_by_default = False
    supports_download = True

    def __init__(self, allow_downloads: bool = False):
        self.allow_downloads = allow_downloads

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        return []

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        if not self.allow_downloads:
            raise SourceError(
                "external URL downloads are disabled: pass --i-have-rights and confirm the "
                "source's terms before enabling them"
            )
        text = fetch_text(candidate.download_url or candidate.source_id, timeout=60)
        slug = slugify(candidate.title or "external_book")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{slug}.txt"
        path.write_text(text, encoding="utf-8")
        return FetchResult(candidate=candidate, path=path, text=text, sha256=sha256_text(text))
