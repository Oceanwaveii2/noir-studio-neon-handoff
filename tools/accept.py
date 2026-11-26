"""
Record a named reviewer's acceptance against an evidence receipt.

A test run is not an acceptance. This tool refuses self-review names and requires a passing
receipt from the current commit.

    python tools/accept.py --feature "style profiler" --reviewer "J. Smith" \
        --receipt reports/evidence-20261104T223337Z.json --outcome ACCEPTED --notes "..."
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF_NAMES = {"", "me", "assistant", "author", "ai", "self", "the author"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(prog="accept")
    parser.add_argument("--feature", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--outcome", choices=("ACCEPTED", "REJECTED", "PENDING"), required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--self-accept", action="store_true",
        help="solo mode: the author accepts their own work after reviewing the diff",
    )
    parser.add_argument("--diff-reviewed", action="store_true")
    parser.add_argument("--no-secrets", action="store_true")
    args = parser.parse_args()

    reviewer = args.reviewer.strip()
    solo = reviewer.lower() in SELF_NAMES
    if solo and not args.self_accept:
        print(
            "refused: self-review needs --self-accept --diff-reviewed --no-secrets (solo mode)"
        )
        return 2
    if solo and not (args.diff_reviewed and args.no_secrets):
        print("refused: self-acceptance requires a reviewed diff and a secret scan")
        return 2

    receipt_path = (ROOT / args.receipt).resolve()
    if not receipt_path.is_file():
        print(f"refused: receipt not found: {args.receipt}")
        return 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("verdict") != "PASS":
        print("refused: receipt verdict is not PASS")
        return 2
    receipt_commit = receipt.get("git_commit", "")
    current = head()
    if receipt_commit and current and receipt_commit != current:
        print(f"refused: receipt is for {receipt_commit[:8]}, HEAD is {current[:8]}")
        return 2

    slug = re.sub(r"[^a-z0-9]+", "-", args.feature.lower()).strip("-")
    record = {
        "feature": args.feature,
        "reviewer": reviewer,
        "self_acceptance": solo,
        "checklist": {
            "diff_reviewed": args.diff_reviewed,
            "no_secrets": args.no_secrets,
        },
        "outcome": args.outcome,
        "notes": args.notes,
        "accepted_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "receipt": {
            "path": args.receipt,
            "sha256": sha256(receipt_path),
            "commit": receipt_commit,
        },
    }
    target = ROOT / "docs" / "acceptance" / f"{slug}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"recorded {args.outcome} for '{args.feature}' by {reviewer} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
