"""
Registry and installer-checker for the book-finding tools named in the project report.

This is a setup/inventory tool, not a scraper. It records the exact repositories the
author supplied, checks whether each CLI is already on PATH, and prints install steps.

Policy: the shadow-library catalogs below are MANUAL_ONLY. Nothing here automates them.
Only public-domain / open-access sources are wired into `tools/book_finder.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
from typing import Dict, List

TOOLS: List[Dict[str, str]] = [
    {
        "id": "ravebsd",
        "name": "RaveBSD",
        "kind": "multi-library aggregator",
        "url": "https://github.com/IdleEndeavor/RaveBSD",
        "cli": "ravebsd",
        "install": "git clone https://github.com/IdleEndeavor/RaveBSD && follow its README",
        "policy": "MANUAL_ONLY: aggregates shadow libraries; review before use.",
    },
    {
        "id": "shelfmark",
        "name": "Shelfmark (calibrain)",
        "kind": "unified book search UI / library manager",
        "url": "https://github.com/calibrain/shelfmark",
        "cli": "shelfmark",
        "install": "git clone https://github.com/calibrain/shelfmark && follow its README",
        "policy": "MANUAL_ONLY: unified search UI; sources include shadow libraries.",
    },
    {
        "id": "librarr",
        "name": "Librarr",
        "kind": "download automation daemon",
        "url": "https://github.com/JeremiahM37/librarr",
        "cli": "librarr",
        "install": "git clone https://github.com/JeremiahM37/librarr && follow its README",
        "policy": "MANUAL_ONLY: concurrent multi-database downloader.",
    },
    {
        "id": "bookdl",
        "name": "bookdl",
        "kind": "CLI downloader",
        "url": "https://github.com/billmal071/bookdl",
        "cli": "bookdl",
        "install": "git clone https://github.com/billmal071/bookdl && follow its README",
        "policy": "MANUAL_ONLY: multi-source CLI downloader.",
    },
    {
        "id": "biblio-mcp",
        "name": "biblio-mcp",
        "kind": "MCP server",
        "url": "https://github.com/yashimosh/biblio-mcp",
        "cli": "biblio-mcp",
        "install": "git clone https://github.com/yashimosh/biblio-mcp && follow its README",
        "policy": "MANUAL_ONLY: MCP wrapper over shadow-library search.",
    },
]

CATALOGS: List[Dict[str, str]] = [
    {
        "id": "gutenberg",
        "name": "Project Gutenberg",
        "url": "https://www.gutenberg.org",
        "status": "SUPPORTED (search + text download)",
        "policy": "Public domain in the US.",
    },
    {
        "id": "internet_archive",
        "name": "Internet Archive",
        "url": "https://archive.org",
        "status": "SUPPORTED (search + public-domain text where available)",
        "policy": "Item-level; lending items are not downloadable.",
    },
    {
        "id": "openlibrary",
        "name": "Open Library",
        "url": "https://openlibrary.org",
        "status": "SUPPORTED (metadata + IA links)",
        "policy": "Metadata; scan licenses vary.",
    },
    {
        "id": "google_books",
        "name": "Google Books",
        "url": "https://books.google.com",
        "status": "SUPPORTED (metadata + public-domain full view)",
        "policy": "Only FULL_PUBLIC_DOMAIN volumes are downloadable.",
    },
    {
        "id": "hathitrust",
        "name": "HathiTrust",
        "url": "https://www.hathitrust.org",
        "status": "MANUAL (search link only)",
        "policy": "Access depends on institutional membership / public domain.",
    },
    {
        "id": "doab",
        "name": "DOAB",
        "url": "https://directory.doabooks.org",
        "status": "SUPPORTED (search link; per-book license)",
        "policy": "Open access.",
    },
    {
        "id": "oapen",
        "name": "OAPEN",
        "url": "https://library.oapen.org",
        "status": "SUPPORTED (search link; per-book license)",
        "policy": "Open access.",
    },
    {
        "id": "openstax",
        "name": "OpenStax",
        "url": "https://openstax.org",
        "status": "SUPPORTED (search link; open textbooks)",
        "policy": "Open textbooks.",
    },
    {
        "id": "nap",
        "name": "National Academies Press",
        "url": "https://nap.nationalacademies.org",
        "status": "SUPPORTED (search link; free PDFs)",
        "policy": "Free publications.",
    },
    {
        "id": "annas_archive",
        "name": "Anna's Archive",
        "url": "https://annas-archive.gl",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Shadow library. Not automated by this project.",
    },
    {
        "id": "libgen",
        "name": "Library Genesis (LibGen)",
        "url": "https://libgen.li",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Shadow library. Not automated by this project.",
    },
    {
        "id": "z_library",
        "name": "Z-Library",
        "url": "https://z-library.sk",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Shadow library. Not automated by this project.",
    },
    {
        "id": "sci_hub",
        "name": "Sci-Hub",
        "url": "https://sci-hub.se",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Shadow library. Not automated by this project.",
    },
    {
        "id": "oceanofpdf",
        "name": "OceanofPDF",
        "url": "https://oceanofpdf.com",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Shadow catalog. Not automated by this project.",
    },
    {
        "id": "mobilism",
        "name": "Mobilism",
        "url": "https://forum.mobilism.org",
        "status": "MANUAL_ONLY / NOT_AUTOMATED",
        "policy": "Forum catalog. Not automated by this project.",
    },
]


def installed(tool: Dict[str, str]) -> bool:
    for candidate in (tool["cli"], tool["cli"] + ".exe", tool["cli"] + ".cmd"):
        if shutil.which(candidate):
            return True
    return False


def inventory() -> Dict[str, List[Dict[str, str]]]:
    return {
        "tools": [{**tool, "installed": str(installed(tool)).lower()} for tool in TOOLS],
        "catalogs": list(CATALOGS),
    }


def print_human() -> None:
    print("BOOK-FINDING TOOLS")
    print("=" * 100)
    for tool in TOOLS:
        flag = "INSTALLED" if installed(tool) else "missing  "
        print(f"[{flag}] {tool['name']:<24} {tool['kind']:<38} {tool['url']}")
        if not installed(tool):
            print(f"           install: {tool['install']}")
        print(f"           policy : {tool['policy']}")
    print("\nCATALOGS")
    print("=" * 100)
    for catalog in CATALOGS:
        print(f"{catalog['name']:<32} {catalog['status']:<52} {catalog['url']}")
    print("\nShadow-library catalogs are MANUAL_ONLY. No automated fetchers are provided.")


def print_markdown() -> None:
    print("| Tool | Kind | Repo | Status | Policy |")
    print("|---|---|---|---|---|")
    for tool in TOOLS:
        status = "installed" if installed(tool) else "not installed"
        print(
            f"| {tool['name']} | {tool['kind']} | {tool['url']} | {status} | {tool['policy']} |"
        )
    print("\n| Catalog | Status | URL |")
    print("|---|---|---|")
    for catalog in CATALOGS:
        print(f"| {catalog['name']} | {catalog['status']} | {catalog['url']} |")


def main() -> int:
    parser = argparse.ArgumentParser(description="Book-finding tool inventory / installer checker")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    parser.add_argument("--markdown", action="store_true", help="Print a Markdown table")
    args = parser.parse_args()

    if args.json:
        print(json.dumps(inventory(), indent=2))
    elif args.markdown:
        print_markdown()
    else:
        print_human()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
