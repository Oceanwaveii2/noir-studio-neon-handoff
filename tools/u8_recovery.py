"""Create and restore a SQLite-aware editorial checkpoint without overwriting."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import time


def describe(path: Path) -> dict:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("Revision database integrity check failed.")
        head = db.execute("SELECT head FROM state WHERE id=1").fetchone()
        rows = db.execute("SELECT * FROM revisions ORDER BY number").fetchall()
        if not head or not rows or not any(row[0] == head[0] for row in rows):
            raise ValueError("Revision database is incomplete.")
        encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return {"head": head[0], "revision_count": len(rows), "history_sha256": hashlib.sha256(encoded).hexdigest()}


def copy_database(source: Path, destination: Path) -> None:
    # Exclusive creation; sqlite's online backup includes any committed WAL data.
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as src:
        with closing(sqlite3.connect(str(destination), timeout=10)) as dst:
            deadline = time.monotonic() + 30
            def progress(_status, _remaining, _total):
                if time.monotonic() > deadline:
                    raise TimeoutError("SQLite backup exceeded 30 seconds.")
            src.backup(dst, pages=256, progress=progress, sleep=0.1)


def recover(source: Path, out: Path) -> dict:
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise ValueError("Source revision store must not be a link.")
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError("Source revision store is not a file.")
    out.mkdir(parents=True, exist_ok=False)
    before = describe(source)
    checkpoint = out / "checkpoint.sqlite"
    restored = out / "restored.sqlite"
    copy_database(source, checkpoint)
    copy_database(checkpoint, restored)
    saved, recovered, after = describe(checkpoint), describe(restored), describe(source)
    if before != after:
        raise ValueError("Source changed during backup; retain this copy and repeat at a stable point.")
    if saved != recovered or before != saved:
        raise ValueError("Restored revision history does not match the source.")
    result = {"status": "PASS", "source": str(source), "checkpoint": str(checkpoint),
              "restored": str(restored), "revision_history": recovered}
    (out / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="new local directory")
    args = parser.parse_args()
    try:
        result = recover(args.source, args.out)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"Recovery check unavailable: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
