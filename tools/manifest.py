"""Fingerprint only release application code into a new local manifest."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from u8_package import ROOT, source_files


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new manifest file")
    args = parser.parse_args()
    try:
        files = list(source_files())
        lines = [f"{sha(path)}  {path.relative_to(ROOT).as_posix()}" for path in files]
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Manifest unavailable: {exc}\n")
    print(f"{len(lines)} application code files -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
