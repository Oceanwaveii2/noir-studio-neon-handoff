"""
Book finder CLI: search public-domain catalogs, rank spring-story matches, download a
batch, then hand it to the ingest and index tools.

Examples:
    python tools/book_finder.py sources
    python tools/book_finder.py search --source gutenberg --query "custom of the country"
    python tools/book_finder.py recommend --limit 11
    python tools/book_finder.py expand --limit 11
    python tools/book_finder.py wishlist
    python tools/book_finder.py ingest
    python tools/book_finder.py index --mode incremental

Shadow-library catalogs are not automated. See `tools/book_tools.py` for the manual list.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from book_sources import SPRING_BATCH, BookCandidate, CuratedBook, default_sources, get_source
from book_sources.gutenberg import GutenbergSource

SPRING_WEIGHTS = {
    "farce": 3.0,
    "comedy": 3.0,
    "glamour": 2.5,
    "satire": 2.0,
    "social climbing": 2.0,
    "divorce": 2.0,
    "hollywood": 2.0,
    "movies": 2.0,
    "parties": 2.0,
    "domestic satire": 2.0,
    "romance": 1.5,
    "family": 1.5,
    "wealth": 1.5,
    "ambition": 1.5,
    "marriage": 1.5,
    "desire": 1.5,
    "appetite": 1.5,
    "body": 1.5,
    "episodic": 1.5,
    "ensemble": 1.5,
    "celebrity": 1.5,
}

# In-copyright spring matches. This list is for LEGAL acquisition only: Open Library /
# Internet Archive lending, Google Books preview, library, or purchase. It is not a
# download list.
WISHLIST = (
    ("The Best of Everything", "Rona Jaffe", "career girls, glamour, 1950s New York"),
    ("The Dud Avocado", "Elaine Dundy", "comic glamour, Paris, appetite"),
    ("Hollywood Wives", "Jackie Collins", "Hollywood glamour, scandal, ensemble"),
    ("The Devil Wears Prada", "Lauren Weisberger", "fashion, status, workplace comedy"),
    ("Crazy Rich Asians", "Kevin Kwan", "wealth, social climbing, ensemble farce"),
    ("The Seven Husbands of Evelyn Hugo", "Taylor Jenkins Reid", "Hollywood, fame, marriages"),
    ("City of Girls", "Elizabeth Gilbert", "showgirls, glamour, appetite"),
    ("Sweetbitter", "Stephanie Danler", "appetite, city, service-industry ensemble"),
    ("Bergdorf Blondes", "Plum Sykes", "glamour satire, social climbing"),
    ("Bridget Jones's Diary", "Helen Fielding", "domestic/romance comedy"),
)


def score_book(book: CuratedBook) -> float:
    themes = " ".join(book.themes).lower()
    score = sum(weight for theme, weight in SPRING_WEIGHTS.items() if theme in themes)
    try:
        year = int(book.year)
    except ValueError:
        year = 0
    if 1900 <= year <= 1930:
        score += 1.0
    return round(score, 2)


def matched_themes(book: CuratedBook) -> list[str]:
    themes = " ".join(book.themes).lower()
    return [theme for theme in SPRING_WEIGHTS if theme in themes]


def cmd_sources(args: argparse.Namespace) -> int:
    for source in default_sources(args.incoming, allow_external=args.i_have_rights):
        info = source.describe()
        print(
            f"{info['id']:<18} {info['name']:<30} "
            f"download={'yes' if info['supports_download'] else 'metadata'}  {info['license_policy']}"
        )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    source = get_source(args.source, args.incoming, allow_external=args.i_have_rights)
    if source is None:
        raise SystemExit(f"unknown source: {args.source}")
    results = source.search(args.query, limit=args.limit)
    for candidate in results:
        print(
            f"{candidate.source_id:<18} {candidate.year:<6} {candidate.title[:70]:<70} "
            f"{candidate.author[:30]}"
        )
    if not results:
        print("(no results)")
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    ranked = sorted(SPRING_BATCH, key=score_book, reverse=True)[: args.limit]
    print(f"{'score':>6}  {'year':<5} {'title':<46} {'author':<28} matched")
    print("-" * 120)
    for book in ranked:
        print(
            f"{score_book(book):>6.1f}  {book.year:<5} {book.title[:46]:<46} "
            f"{book.author[:28]:<28} {', '.join(matched_themes(book))[:40]}"
        )
    print("\nReasoning:")
    for book in ranked:
        print(f"- {book.title}: {book.reason}")
    return 0


def cmd_expand(args: argparse.Namespace) -> int:
    out_dir = Path(args.incoming)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = GutenbergSource()
    ranked = sorted(SPRING_BATCH, key=score_book, reverse=True)[: args.limit]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch": "spring",
        "books": [],
    }
    for book in ranked:
        candidate = BookCandidate(
            source="gutenberg",
            source_id=book.gutenberg_id,
            title=book.title,
            author=book.author,
            year=book.year,
            license="Public domain in the US (Project Gutenberg)",
            landing_url=f"https://www.gutenberg.org/ebooks/{book.gutenberg_id}",
        )
        try:
            result = source.download(candidate, out_dir)
            payload["books"].append(
                {
                    "slug": result.path.stem,
                    "title": book.title,
                    "author": book.author,
                    "year": book.year,
                    "gutenberg_id": book.gutenberg_id,
                    "themes": list(book.themes),
                    "reason": book.reason,
                    "source": f"https://www.gutenberg.org/ebooks/{book.gutenberg_id}",
                    "path": str(result.path),
                    "chars": result.chars,
                }
            )
            print(f"downloaded {book.gutenberg_id:>6} {book.title[:55]:<55} {result.chars:>9,} chars")
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            print(f"FAILED     {book.gutenberg_id:>6} {book.title[:55]:<55} {exc}")
        time.sleep(0.4)

    sidecar = out_dir / "_candidates.json"
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(payload['books'])}/{len(ranked)} downloaded -> {out_dir}")
    print(f"metadata -> {sidecar}")
    return 0 if payload["books"] else 1


def cmd_download(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    if args.source == "gutenberg":
        if not args.id:
            raise SystemExit("--id is required for gutenberg")
        result = GutenbergSource().download_by_id(args.id, out_dir, title=args.title or "")
    elif args.source == "external_url":
        if not args.i_have_rights:
            raise SystemExit("external URL download requires --i-have-rights")
        if not args.url:
            raise SystemExit("--url is required for external_url")
        source = get_source("external_url", args.incoming, allow_external=True)
        candidate = BookCandidate(
            source="external_url",
            source_id=args.url,
            title=args.title or "external_book",
            download_url=args.url,
            license="user-provided; rights acknowledged",
        )
        result = source.download(candidate, out_dir)
    else:
        source = get_source(args.source, args.incoming, allow_external=args.i_have_rights)
        if source is None:
            raise SystemExit(f"unknown source: {args.source}")
        if not args.id:
            raise SystemExit("--id is required")
        candidate = BookCandidate(
            source=source.id,
            source_id=args.id,
            title=args.title or args.id,
            download_url=args.url or "",
        )
        result = source.download(candidate, out_dir)
    print(f"{result.path} ({result.chars:,} chars)")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from book_ingest import ingest_incoming

    entries = ingest_incoming(
        Path(args.incoming), Path(args.books), force=args.force, dry_run=args.dry_run
    )
    for entry in entries:
        print(f"{entry['slug']:<60} {entry['words']:>9,} words  {entry['title'][:40]}")
    print(f"\n{len(entries)} book(s) ingested")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from index_books import run_index

    return run_index(
        books_dir=Path(args.books),
        index_path=Path(args.index),
        mode=args.mode,
        model_name=args.model,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )


def _get_json(url: str) -> dict:
    import urllib.request

    from book_sources.base import DEFAULT_UA

    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def cmd_wishlist(args: argparse.Namespace) -> int:
    """Find in-copyright spring matches through legal access channels.

    This is metadata only: Open Library / Internet Archive lending links, Google Books
    preview/buy links, and the library. It does not download in-copyright text.
    """
    rows = []
    for title, author, why in WISHLIST[: args.limit]:
        row = {
            "title": title,
            "author": author,
            "why": why,
            "year": "",
            "access": "unknown",
            "openlibrary": "",
            "internet_archive": "",
            "google_books": "",
            "gb_viewability": "",
        }
        try:
            url = "https://openlibrary.org/search.json?" + urllib.parse.urlencode(
                {
                    "title": title,
                    "author": author,
                    "fields": "title,author_name,first_publish_year,key,ia,ebook_access,public_scan_b",
                    "limit": 1,
                }
            )
            docs = _get_json(url).get("docs") or []
            if docs:
                doc = docs[0]
                row["year"] = str(doc.get("first_publish_year") or "")
                row["access"] = doc.get("ebook_access", "unknown")
                key = doc.get("key", "")
                if key:
                    row["openlibrary"] = f"https://openlibrary.org{key}"
                ia_ids = doc.get("ia") or []
                if ia_ids:
                    row["internet_archive"] = f"https://archive.org/details/{ia_ids[0]}"
        except Exception as exc:  # noqa: BLE001 - one bad lookup must not kill the report
            row["openlibrary_error"] = str(exc)

        try:
            url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(
                {"q": f'intitle:"{title}" inauthor:"{author}"', "maxResults": 1}
            )
            items = _get_json(url).get("items") or []
            if items:
                volume = items[0].get("volumeInfo", {})
                access = items[0].get("accessInfo", {})
                row["google_books"] = volume.get("infoLink") or volume.get("canonicalVolumeLink", "")
                row["gb_viewability"] = access.get("viewability", "")
        except Exception as exc:  # noqa: BLE001
            row["google_books_error"] = str(exc)

        rows.append(row)
        print(
            f"{title[:42]:<42} {row['year']:<5} {row['access']:<14} "
            f"{row['openlibrary'] or row['google_books']}"
        )
        time.sleep(0.25)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "books": rows}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Legal Book Wishlist — Spring / Hot Scoomp Matches",
        "",
        "In-copyright titles. This is a legal-access list, not a download list.",
        "",
        "| Title | Author | Year | Legal access | Open Library | Internet Archive | Google Books |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        def link(url: str, label: str) -> str:
            return f"[{label}]({url})" if url else "—"

        lines.append(
            f"| {row['title']} | {row['author']} | {row['year']} | `{row['access']}` | "
            f"{link(row['openlibrary'], 'catalog')} | "
            f"{link(row['internet_archive'], 'borrow/scan')} | "
            f"{link(row['google_books'], 'preview/buy')} |"
        )
    lines += [
        "",
        "Access values: `public` = readable/downloadable; `borrowable` = controlled digital",
        "lending; `printdisabled` = accessible copy only; `no_ebook` = physical/library.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwishlist -> {out} (+ .json)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Public-domain book finder and corpus expander")
    parser.add_argument("--incoming", default=str(ROOT / "books" / "incoming"))
    parser.add_argument("--books", default=str(ROOT / "books"))
    parser.add_argument("--i-have-rights", action="store_true", help="Enable the explicit URL source")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("sources", help="List wired sources")
    p.set_defaults(func=cmd_sources)

    p = sub.add_parser("search", help="Search a catalog")
    p.add_argument("--source", required=True)
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("recommend", help="Rank the curated spring batch")
    p.add_argument("--limit", type=int, default=11)
    p.set_defaults(func=cmd_recommend)

    p = sub.add_parser("expand", help="Download the curated spring batch")
    p.add_argument("--limit", type=int, default=11)
    p.set_defaults(func=cmd_expand)

    p = sub.add_parser("download", help="Download one candidate")
    p.add_argument("--source", required=True)
    p.add_argument("--id", default="")
    p.add_argument("--url", default="")
    p.add_argument("--title", default="")
    p.add_argument("--out", default=str(ROOT / "books" / "incoming"))
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("ingest", help="Ingest books/incoming into books/text + manifest")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("index", help="Incrementally update or fully rebuild the vector index")
    p.add_argument("--index", default=str(ROOT / "books" / "vector_index.joblib"))
    p.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    p.add_argument("--model", default="all-MiniLM-L6-v2")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser(
        "wishlist", help="Find in-copyright spring matches through legal access channels"
    )
    p.add_argument("--out", default=str(ROOT / "reports" / "book_wishlist.md"))
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_wishlist)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
