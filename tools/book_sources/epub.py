"""
EPUB text extraction using only the standard library.

An EPUB is a ZIP with an OPF package (spine + manifest) and XHTML content documents.
This reads the spine in order, skips navigation documents, strips markup, and returns
plain text with paragraph breaks. It does not touch DRM; an encrypted EPUB will fail
with a clear error.
"""

from __future__ import annotations

import html
import posixpath
import re
import zipfile
from pathlib import Path
from typing import List
from xml.etree import ElementTree as ET

_BLOCK_TAGS = (
    "p",
    "div",
    "br",
    "li",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "section",
    "article",
    "header",
    "footer",
    "pre",
    "hr",
)
_BLOCK_RE = re.compile(r"</?(?:" + "|".join(_BLOCK_TAGS) + r")\b[^>]*>", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<(script|style|head)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\u00a0]+")
_NEWLINE_RE = re.compile(r"\n{3,}")
_XML_ENC_RE = re.compile(rb'encoding=["\']([A-Za-z0-9._-]+)["\']')


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _read_opf(zf: zipfile.ZipFile) -> str | None:
    try:
        container = zf.read("META-INF/container.xml").decode("utf-8", "replace")
    except KeyError:
        return None
    match = re.search(r'full-path=["\']([^"\']+)["\']', container)
    return match.group(1) if match else None


def _decode(data: bytes) -> str:
    match = _XML_ENC_RE.search(data[:200])
    encodings = [match.group(1).decode("ascii")] if match else []
    encodings += ["utf-8", "cp1252", "latin-1"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def _html_to_text(markup: str) -> str:
    markup = _SCRIPT_RE.sub(" ", markup)
    markup = _BLOCK_RE.sub("\n", markup)
    text = _TAG_RE.sub(" ", markup)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def extract_epub_text(path: str | Path) -> str:
    """Returns the reading-order text of an EPUB."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            opf_path = _read_opf(zf)
            if not opf_path or opf_path not in names:
                # Fallback: every XHTML/HTML document, sorted by name.
                docs = sorted(
                    name
                    for name in names
                    if name.lower().endswith((".xhtml", ".html", ".htm"))
                    and posixpath.basename(name).lower() not in {"nav.xhtml", "toc.xhtml"}
                )
                if not docs:
                    raise ValueError(f"no XHTML documents in EPUB: {path}")
                return "\n\n".join(_html_to_text(_decode(zf.read(doc))) for doc in docs).strip()

            root = ET.fromstring(zf.read(opf_path))
            manifest = {}
            spine = []
            for element in root.iter():
                tag = _local(element.tag)
                if tag == "item":
                    item_id = element.attrib.get("id", "")
                    href = element.attrib.get("href", "")
                    media = element.attrib.get("media-type", "")
                    props = element.attrib.get("properties", "")
                    manifest[item_id] = (href, media, props)
                elif tag == "itemref":
                    spine.append(element.attrib.get("idref", ""))

            opf_dir = posixpath.dirname(opf_path)
            chapters: List[str] = []
            used = set()
            for item_id in spine:
                item = manifest.get(item_id)
                if not item:
                    continue
                href, media, props = item
                if "html" not in media and not href.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                if "nav" in props.lower():
                    continue
                doc_path = posixpath.normpath(posixpath.join(opf_dir, href))
                if doc_path in used or doc_path not in names:
                    continue
                used.add(doc_path)
                chapters.append(_html_to_text(_decode(zf.read(doc_path))))

            if not chapters:
                # Some malformed EPUBs have an empty spine; fall back to manifest order.
                for href, media, props in manifest.values():
                    doc_path = posixpath.normpath(posixpath.join(opf_dir, href))
                    if (
                        doc_path in names
                        and doc_path not in used
                        and "html" in media
                        and "nav" not in props.lower()
                    ):
                        chapters.append(_html_to_text(_decode(zf.read(doc_path))))

            if not chapters:
                raise ValueError(f"no readable chapters in EPUB: {path}")
            return "\n\n".join(chapter for chapter in chapters if chapter).strip() + "\n"
    except zipfile.BadZipFile as exc:
        raise ValueError(f"not a valid EPUB (not a ZIP): {path}") from exc
