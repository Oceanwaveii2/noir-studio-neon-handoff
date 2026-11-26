"""Book-source adapters for the public-domain / open-access corpus expansion."""

from .base import BookCandidate, BookSource, FetchResult, SourceError
from .catalogs import default_catalogs
from .curated import SPRING_BATCH, CuratedBook
from .epub import extract_epub_text
from .gutenberg import GutenbergSource, strip_gutenberg_boilerplate
from .local import ExternalUrlSource, LocalSource
from .registry import default_sources, get_source

__all__ = [
    "BookCandidate",
    "BookSource",
    "FetchResult",
    "SourceError",
    "GutenbergSource",
    "LocalSource",
    "ExternalUrlSource",
    "SPRING_BATCH",
    "CuratedBook",
    "default_catalogs",
    "default_sources",
    "get_source",
    "strip_gutenberg_boilerplate",
    "extract_epub_text",
]
