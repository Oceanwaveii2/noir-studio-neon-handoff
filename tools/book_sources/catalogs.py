"""
Catalog adapters that are metadata-first: Open Library, Internet Archive, Google Books,
and open-access catalogs (DOAB, OAPEN, OpenStax, National Academies Press).

Only Open Library, Internet Archive and Google Books have machine-readable search here.
The open-access catalogs return a search entry with a landing URL; their APIs differ and
are deliberately not scraped until their terms are reviewed.
"""

from __future__ import annotations

import json
import urllib.parse
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

_UA_HINT = "Check the source's terms and license before downloading."


class OpenLibrarySource(BookSource):
    id = "openlibrary"
    name = "Open Library"
    license_policy = "Metadata; links to Internet Archive scans. Item licenses vary."
    enabled_by_default = True
    supports_download = False

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        fields = "title,author_name,first_publish_year,ia,public_scan_b,key,language"
        url = (
            "https://openlibrary.org/search.json?"
            + urllib.parse.urlencode({"q": query, "fields": fields, "limit": limit})
        )
        data = json.loads(fetch_text(url))
        candidates: List[BookCandidate] = []
        for doc in data.get("docs", [])[:limit]:
            authors = doc.get("author_name") or []
            ia_ids = doc.get("ia") or []
            key = doc.get("key", "")
            candidates.append(
                BookCandidate(
                    source=self.id,
                    source_id=key,
                    title=doc.get("title", ""),
                    author=", ".join(authors[:2]),
                    year=str(doc.get("first_publish_year") or ""),
                    language=", ".join(doc.get("language") or [])[:20],
                    license="metadata / scan license varies",
                    landing_url=f"https://openlibrary.org{key}" if key else "",
                    formats={"ia": ", ".join(ia_ids[:5])},
                )
            )
        return candidates


class InternetArchiveSource(BookSource):
    id = "internet_archive"
    name = "Internet Archive"
    license_policy = "Item-level; public-domain scans are downloadable, lending items are not."
    enabled_by_default = True
    supports_download = True

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        params = [
            ("q", f"({query}) AND mediatype:texts"),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "year"),
            ("fl[]", "licenseurl"),
            ("rows", str(limit)),
            ("page", "1"),
            ("output", "json"),
        ]
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(params, doseq=True)
        data = json.loads(fetch_text(url))
        docs = (data.get("response") or {}).get("docs") or []
        candidates: List[BookCandidate] = []
        for doc in docs[:limit]:
            identifier = doc.get("identifier", "")
            creators = doc.get("creator") or []
            if isinstance(creators, str):
                creators = [creators]
            candidates.append(
                BookCandidate(
                    source=self.id,
                    source_id=identifier,
                    title=doc.get("title", ""),
                    author=", ".join(creators[:2]),
                    year=str(doc.get("year") or ""),
                    license="item-level (see licenseurl)",
                    landing_url=f"https://archive.org/details/{identifier}",
                    download_url=f"https://archive.org/download/{identifier}/{identifier}_djvu.txt",
                )
            )
        return candidates

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        url = candidate.download_url or (
            f"https://archive.org/download/{candidate.source_id}/{candidate.source_id}_djvu.txt"
        )
        try:
            raw = fetch_text(url, timeout=45)
        except SourceError as exc:
            raise SourceError(
                f"Internet Archive item {candidate.source_id} is not downloadable "
                f"(lending/restricted): {exc}"
            ) from exc
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = text.strip() + "\n"
        if len(text.split()) < 500:
            raise SourceError(f"Internet Archive text looks empty for {candidate.source_id}")
        slug = slugify(f"{candidate.title} {candidate.author}")
        path = out_dir / f"{slug}.txt"
        path.write_text(text, encoding="utf-8")
        return FetchResult(candidate=candidate, path=path, text=text, sha256=sha256_text(text))


class GoogleBooksSource(BookSource):
    id = "google_books"
    name = "Google Books"
    license_policy = "Metadata; full-text download only for public-domain full-view volumes."
    enabled_by_default = True
    supports_download = True

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        url = (
            "https://www.googleapis.com/books/v1/volumes?"
            + urllib.parse.urlencode({"q": query, "maxResults": limit})
        )
        data = json.loads(fetch_text(url))
        candidates: List[BookCandidate] = []
        for item in data.get("items", [])[:limit]:
            volume = item.get("volumeInfo", {})
            access = item.get("accessInfo", {})
            authors = volume.get("authors") or []
            viewability = access.get("viewability", "")
            pdf = access.get("pdf") or {}
            download_url = pdf.get("downloadLink", "") if pdf.get("isAvailable") else ""
            candidates.append(
                BookCandidate(
                    source=self.id,
                    source_id=item.get("id", ""),
                    title=volume.get("title", ""),
                    author=", ".join(authors[:2]),
                    year=str(volume.get("publishedDate") or "")[:4],
                    license=(
                        "public-domain full view"
                        if viewability == "FULL_PUBLIC_DOMAIN"
                        else "metadata/preview only"
                    ),
                    landing_url=volume.get("infoLink", ""),
                    download_url=download_url,
                )
            )
        return candidates

    def download(self, candidate: BookCandidate, out_dir: Path) -> FetchResult:
        if not candidate.download_url:
            raise SourceError(
                f"Google Books volume {candidate.source_id} has no public-domain download link "
                f"({candidate.license})"
            )
        text = fetch_text(candidate.download_url, timeout=60)
        slug = slugify(f"{candidate.title} {candidate.author}")
        path = out_dir / f"{slug}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return FetchResult(candidate=candidate, path=path, text=text, sha256=sha256_text(text))


class OpenAccessCatalogSource(BookSource):
    """Open-access catalog entry point. Returns a search link, not fabricated results."""

    enabled_by_default = True
    supports_download = False
    license_policy = "Open access / open textbooks; verify each item's license."

    def __init__(self, source_id: str, name: str, search_url: str):
        self.id = source_id
        self.name = name
        self._search_url = search_url

    def search(self, query: str, limit: int = 10) -> List[BookCandidate]:
        url = self._search_url.format(query=urllib.parse.quote(query))
        return [
            BookCandidate(
                source=self.id,
                source_id=query,
                title=f"{self.name} search: {query}",
                license=self.license_policy,
                landing_url=url,
                reasons=("metadata-only catalog entry; open the landing URL to download",),
            )
        ]


def default_catalogs() -> List[BookSource]:
    return [
        OpenLibrarySource(),
        InternetArchiveSource(),
        GoogleBooksSource(),
        OpenAccessCatalogSource(
            "doab", "DOAB (Directory of Open Access Books)", "https://directory.doabooks.org/discover?query={query}"
        ),
        OpenAccessCatalogSource(
            "oapen", "OAPEN", "https://library.oapen.org/discover?query={query}"
        ),
        OpenAccessCatalogSource(
            "openstax", "OpenStax", "https://openstax.org/search?q={query}"
        ),
        OpenAccessCatalogSource(
            "nap", "National Academies Press", "https://nap.nationalacademies.org/search/?term={query}"
        ),
    ]
