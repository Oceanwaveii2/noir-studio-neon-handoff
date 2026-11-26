"""
Verification harness.

Runs the test suite, hashes the implementation and the index, and writes an evidence receipt.
A green test run is reported separately from review/acceptance; this tool only produces the
evidence a reviewer needs.

    python tools/verify.py
"""

from __future__ import annotations

import datetime as dt
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_FILES = [
    "prose_engine/diagnostics.py",
    "prose_engine/style_guide.py",
    "prose_engine/guards.py",
    "prose_engine/rhythm.py",
    "prose_engine/vector_store.py",
    "prose_engine/embedding_store.py",
    "prose_engine/conditioner.py",
    "prose_engine/cli.py",
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20
        )
        return result.stdout.strip()
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true", help="include tests requiring local models")
    args = parser.parse_args()
    started = dt.datetime.now(dt.timezone.utc)
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%S%fZ")
    details = reports / f"evidence-{stamp}.tests.log"
    try:
        command = [sys.executable, "-B", "tools/release_tests.py"]
        if args.models:
            command.append("--models")
        run = subprocess.run(
            command,
            cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", timeout=240,
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired as exc:
        def as_text(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
        with details.open("x", encoding="utf-8") as handle:
            handle.write(as_text(exc.stdout) + "\n" + as_text(exc.stderr))
        print("BLOCKED: full test discovery exceeded 240 seconds.")
        return 2
    with details.open("x", encoding="utf-8") as handle:
        handle.write((run.stdout or "") + "\n" + (run.stderr or ""))
    ok = run.returncode == 0
    tail = (run.stderr or run.stdout).strip().splitlines()[-6:]

    index = ROOT / "books" / "vector_index.joblib"
    guide = ROOT / "out" / "style_guide.json"
    receipt = {
        "tool": "prose_engine.verify",
        "version": "1.0",
        "started_utc": started.isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")),
        "tests": {
            "command": "python -B tools/release_tests.py" + (" --models" if args.models else ""),
            "returncode": run.returncode,
            "summary": tail,
            "details_file": str(details.relative_to(ROOT)),
        },
        "evidence": {
            "index_present": index.is_file(),
            "index_mb": round(index.stat().st_size / 1e6, 1) if index.is_file() else 0,
            "style_guide_present": guide.is_file(),
        },
        "files": {
            name: sha(ROOT / name) for name in KEY_FILES if (ROOT / name).is_file()
        },
        "fixtures": "tests/fixtures/guards.json",
        "verdict": "PASS" if ok else "FAIL",
    }

    target = reports / f"evidence-{stamp}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)

    print(f"verdict: {receipt['verdict']}")
    print(f"tests:   returncode {run.returncode} | {tail[-1] if tail else ''}")
    if not args.models:
        print("NOT RUN declared model-dependent test modules and case; see details log.")
    print(f"evidence: {target}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
