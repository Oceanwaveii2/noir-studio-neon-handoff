"""Bundle a local book library into a new export directory and archive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.paths import books

FORMATS = {".txt": "text", ".epub": "epub", ".pdf": "pdf", ".mobi": "mobi"}

# prefer canonical text/ over incoming, then anything else
PREFERENCE = {"text": 0, "incoming": 1, "source_documents": 2, "backups": 3}


def rank(path: Path, base: Path) -> tuple:
    parts = [part.lower() for part in path.relative_to(base).parts]
    canonical = next((PREFERENCE[p] for p in parts if p in PREFERENCE), 9)
    return (canonical, len(parts), str(path))


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bundle(base: Path, out: Path) -> tuple[Path, list[dict]]:
    base, out = base.resolve(strict=True), out.resolve()
    if not base.is_dir() or out.is_relative_to(base):
        raise ValueError("Use a new export directory outside the book library.")
    archive = out.with_suffix(".zip")
    if archive == out or archive.is_relative_to(base) or out.exists() or archive.exists():
        raise ValueError("The export directory and archive must both be new.")
    files = [
        path
        for path in base.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in FORMATS
        and "_backup" not in str(path).lower()
        and "backup" not in path.parent.name.lower()
    ]

    groups: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        groups[fingerprint(path)].append(path)
    if not groups:
        raise ValueError("No supported books found in the library.")
    out.mkdir(parents=True, exist_ok=False)

    rows = []
    counters = Counter()
    used_names: set[str] = set()
    for digest, paths in sorted(groups.items()):
        chosen = min(paths, key=lambda path: rank(path, base))
        fmt = FORMATS[chosen.suffix.lower()]
        target_dir = out / fmt
        target_dir.mkdir(parents=True, exist_ok=True)
        name = chosen.name
        number = 1
        while name.casefold() in used_names:
            name = f"{chosen.stem}-{digest[:8]}-{number}{chosen.suffix}"
            number += 1
        used_names.add(name.casefold())
        target = target_dir / name
        with chosen.open("rb") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination, 1024 * 1024)
        if fingerprint(target) != digest:
            raise ValueError(f"A source changed during export: {chosen.name}")
        counters[fmt] += 1
        rows.append(
            {
                "file": f"{fmt}/{name}",
                "format": fmt,
                "bytes": chosen.stat().st_size,
                "sha256": digest,
                "source": chosen.relative_to(base).as_posix(),
                "duplicates_removed": len(paths) - 1,
            }
        )

    with (out / "MANIFEST.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    total_bytes = sum(row["bytes"] for row in rows)
    duplicates = sum(row["duplicates_removed"] for row in rows)
    lines = [
        "# All books",
        "",
        "Bundled from the selected local library.",
        "",
        f"- **{len(rows)} unique books**",
        f"- {counters.get('text', 0)} text · {counters.get('pdf', 0)} PDF · "
        f"{counters.get('epub', 0)} EPUB · {counters.get('mobi', 0)} MOBI",
        f"- {duplicates} hash-identical duplicates omitted",
        f"- {total_bytes / 1024 / 1024:.1f} MB",
        "",
        "Each file appears once; `MANIFEST.csv` records its source path, hash and duplicates removed.",
        "",
        "| Format | Count |",
        "|---|---:|",
    ]
    for fmt in ("text", "pdf", "epub", "mobi"):
        lines.append(f"| {fmt} | {counters.get(fmt, 0)} |")
    lines.append("")
    with (out / "README.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as handle:
        for name in ["README.md", "MANIFEST.csv", *(row["file"] for row in rows)]:
            handle.write(out / name, (Path(out.name) / name).as_posix())
    return archive, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=books())
    parser.add_argument("--out", type=Path, required=True, help="New destination outside the library")
    args = parser.parse_args()
    try:
        archive, rows = bundle(args.library, args.out)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Book export could not finish: {exc}\n")
    print(f"folder: {args.out.resolve()}")
    print(f"zip:    {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"unique: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
