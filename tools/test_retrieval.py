"""Inspect eligible local LUAR reference matches via policy-gated retrieval."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_QUERIES = (
    "morning living room coffee couch",
    "blonde woman tight dress heels entrance supermodel",
    "stomach ache bathroom indigestion fart",
    "body expanding hips swelling transformation cartoon",
    "glamour nurse outfit blonde hair heels",
)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Inspect policy-eligible LUAR reference passages")
    parser.add_argument("--books", default="books")
    parser.add_argument("-k", type=int, default=2)
    parser.add_argument("queries", nargs="*", help="Optional custom search queries")
    args = parser.parse_args(argv)

    from prose_engine.reference_service import prepare_retrieval

    setup = prepare_retrieval(args.books, "luar", "local", purposes=("rank_local", "inspect_local"))
    if setup.state != "ready":
        print(f"References unavailable: {setup.message}", file=sys.stderr)
        return 1

    drive = setup.drive
    influence = setup.influence
    for query in (args.queries or DEFAULT_QUERIES):
        print(f"=== Query: {query} ===")
        hits = drive.retrieve_passages("query", query, max_results=args.k, influence=influence)
        for hit in hits:
            print(f"[{hit.id}] {hit.text[:140]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
