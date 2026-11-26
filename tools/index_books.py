"""
Incremental or full rebuild of books/vector_index.joblib.

Incremental mode embeds only books that are in the manifest but not yet in the index,
then appends them to the existing texts/meta/vectors. Full mode re-encodes the whole
corpus. Both modes back up the old index and add new books to books/influence.json.

    python tools/index_books.py --mode incremental
    python tools/index_books.py --mode full
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.corpus import Book, load_corpus
from prose_engine.embedding_store import DEFAULT_MODEL, EmbeddingIndex, load_index
from prose_engine.influence import DEFAULT_LEVEL, load_influence, save_influence
from prose_engine.vector_store import chunk_books


def _backup(index_path: Path, books_dir: Path) -> Path:
    backup_dir = books_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"vector_index-{stamp}.joblib"
    shutil.copy2(index_path, target)
    return target


def _encode(chunks: List[dict], model_name: str) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    return model.encode(
        [chunk["text"] for chunk in chunks],
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).astype("float32")


def _update_influence(books_dir: Path, books: List[Book]) -> int:
    influence = load_influence(books_dir)
    added = 0
    for book in books:
        if book.slug not in influence.levels:
            influence.levels[book.slug] = DEFAULT_LEVEL
            added += 1
    if added:
        save_influence(influence)
    return added


def run_index(
    books_dir: Path,
    index_path: Path,
    mode: str = "incremental",
    model_name: str = DEFAULT_MODEL,
    dry_run: bool = False,
    backup: bool = True,
) -> int:
    books = load_corpus(books_dir)
    if not books:
        print(f"no books found under {books_dir}")
        return 1

    if mode == "full":
        chunks = chunk_books(books)
        print(f"full rebuild: {len(books)} books, {len(chunks):,} chunks")
        if dry_run:
            return 0
        if backup and index_path.is_file():
            print(f"backup -> {_backup(index_path, books_dir)}")
        index = EmbeddingIndex.build(chunks, model_name=model_name)
        index.save(index_path)
        added = _update_influence(books_dir, books)
        print(
            f"rebuilt {len(index.texts):,} passages | {index.vectors.shape[1]} dims | "
            f"{index_path.stat().st_size / 1_000_000:.1f} MB -> {index_path}"
        )
        print(f"influence: {added} new book(s) at level {DEFAULT_LEVEL}")
        return 0

    if not index_path.is_file():
        print(f"no index at {index_path}; run --mode full")
        return 1

    index = load_index(index_path)
    if not isinstance(index, EmbeddingIndex):
        print("the existing index is not a transformer index; run --mode full")
        return 1

    known = {meta.get("book") for meta in index.meta}
    new_books = [book for book in books if book.slug not in known]
    print(
        f"incremental: {len(books)} books on disk, {len(known)} already indexed, "
        f"{len(new_books)} new"
    )
    for book in new_books:
        print(f"  + {book.slug} ({len(book.text.split()):,} words)")

    chunks = chunk_books(new_books)
    print(f"{len(chunks):,} new passages to embed")
    if dry_run or not chunks:
        if not chunks and new_books:
            print("new books produced no chunks")
        return 0

    if backup:
        print(f"backup -> {_backup(index_path, books_dir)}")

    vectors = _encode(chunks, model_name=index.model_name or model_name)
    if vectors.shape[1] != index.vectors.shape[1]:
        print(
            f"embedding dimension changed ({index.vectors.shape[1]} -> {vectors.shape[1]}); "
            "run --mode full"
        )
        return 1

    combined = EmbeddingIndex(
        texts=list(index.texts) + [chunk["text"] for chunk in chunks],
        meta=list(index.meta) + chunks,
        vectors=np.vstack([index.vectors, vectors]).astype("float32"),
        model_name=index.model_name,
    )
    combined.save(index_path)
    added = _update_influence(books_dir, new_books)
    print(
        f"appended {len(chunks):,} passages | total {len(combined.texts):,} | "
        f"{combined.vectors.shape[1]} dims | {index_path.stat().st_size / 1_000_000:.1f} MB"
    )
    print(f"influence: {added} new book(s) at level {DEFAULT_LEVEL}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Incremental/full vector index rebuild")
    parser.add_argument("--books", default=str(ROOT / "books"))
    parser.add_argument("--index", default=str(ROOT / "books" / "vector_index.joblib"))
    parser.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    return run_index(
        books_dir=Path(args.books),
        index_path=Path(args.index),
        mode=args.mode,
        model_name=args.model,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )


if __name__ == "__main__":
    raise SystemExit(main())
