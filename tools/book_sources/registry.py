"""Source registry: which catalogs are wired in, and how to resolve one by id."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .base import BookSource
from .catalogs import default_catalogs
from .gutenberg import GutenbergSource
from .local import ExternalUrlSource, LocalSource


def default_sources(
    incoming_dir: str | Path = "books/incoming",
    allow_external: bool = False,
) -> List[BookSource]:
    sources: List[BookSource] = [GutenbergSource()]
    sources.extend(default_catalogs())
    sources.append(LocalSource(incoming_dir))
    sources.append(ExternalUrlSource(allow_downloads=allow_external))
    return sources


def get_source(
    source_id: str,
    incoming_dir: str | Path = "books/incoming",
    allow_external: bool = False,
) -> Optional[BookSource]:
    for source in default_sources(incoming_dir, allow_external):
        if source.id == source_id:
            return source
    return None


def source_map(**kwargs) -> Dict[str, BookSource]:
    return {source.id: source for source in default_sources(**kwargs)}
