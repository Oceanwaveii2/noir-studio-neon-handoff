"""
Project Gutenberg adapter.

Search uses the public `/ebooks/search/` page (Gutendex was unreachable from this
environment, but the site itself responds). Download uses the plain-text cache:
`https://www.gutenberg.org/cache/epub/<id>/pg<id>.txt`.

Gutenberg texts are public domain in the United States. Check your local
jurisdiction before redistributing.
"""

from __future__ import annotations

import html
import re
import time
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

_SEARCH_URL = "https://www.gutenberg.org/ebooks/search/?query={query}"
_CACHE_URL = "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
_FILES_URL = "https://www.gutenberg.org/files/{book_id}/{book_id}-0.txt"

_START = re.compile(
    r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)
_END = re.compile(
    r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE | re.DOTALL,
)


def strip_gutenberg_boilerplate(text: str) -> str:
    """Removes the Gutenberg header/footer, keeping the book body."""
    start = _START.search(text)
    if start:
        text = text[start.end() :]
    end = _END.search(text)
    if end:
        text = text[: end.start()]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


class GutenbergSource(BookSource):
    id = "gutenberg"
    name = "Project Gutenberg"
    license_policy = "Public domain in the US (Project Gutenberg); check local jurisdiction."
    enabled_by_default = True
    supports_download = True

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        import urllib.parse

        url = _SEARCH_URL.format(query=urllib.parse.quote(query))
        page = fetch_text(url)
        candidates: List[BookCandidate] = []
        blocks = re.findall(r'<li class="booklink">(.*?)</li>', page, re.S)
        for block in blocks:
            id_match = re.search(r'href="/ebooks/(\d+)"', block)
            title_match = re.search(r'<span class="title">(.*?)</span>', block, re.S)
            if not id_match or not title_match:
                continue
            book_id = id_match.group(1)
            title = html.unescape(re.sub("<.*?>", "", title_match.group(1))).strip()
            subtitle_match = re.search(r'<span class="subtitle">(.*?)</span>', block, re.S)
            subtitle = (
                html.unescape(re.sub("<.*?>", "", subtitle_match.group(1))).strip()
                if subtitle_match
                else ""
            )
            author = ""
            if " by " in subtitle:
                author = subtitle.split(" by ", 1)[1].strip()
            candidates.append(
                BookCandidate(
                    source=self.id,
                    source_id=book_id,
                    title=title,
                    author=author,
                    license=self.license_policy,
                    landing_url=f"https://www.gutenberg.org/ebooks/{book_id}",
                    download_url=_CACHE_URL.format(book_id=book_id),
                    formats={"txt": _CACHE_URL.format(book_id=book_id)},
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        urls = [candidate.download_url] if candidate.download_url else []
        urls += [
            _CACHE_URL.format(book_id=candidate.source_id),
            _FILES_URL.format(book_id=candidate.source_id),
        ]
        raw = ""
        last_error: Exception | None = None
        for url in dict.fromkeys(urls):
            try:
                raw = fetch_text(url)
                break
            except SourceError as exc:
                last_error = exc
        if not raw:
            raise SourceError(f"Gutenberg download failed for {candidate.source_id}: {last_error}")

        text = strip_gutenberg_boilerplate(raw)
        if len(text.split()) < 500:
            raise SourceError(
                f"Gutenberg text for {candidate.source_id} looks empty after boilerplate strip"
            )

        slug = slugify(f"{candidate.title} {candidate.author}")
        path = out_dir / f"{slug}.txt"
        path.write_text(text, encoding="utf-8")
        return FetchResult(candidate=candidate, path=path, text=text, sha256=sha256_text(text))

    def download_by_id(self, book_id: str, out_dir: Path, title: str = "") -> FetchResult:
        candidate = BookCandidate(
            source=self.id,
            source_id=str(book_id),
            title=title or f"gutenberg_{book_id}",
            license=self.license_policy,
            landing_url=f"https://www.gutenberg.org/ebooks/{book_id}",
        )
        return self.download(candidate, out_dir)

    @staticmethod
    def polite_delay(seconds: float = 0.4) -> None:
        time.sleep(seconds)
