"""
Session checkpoint: record the interrupted state before changing anything.

    python tools/checkpoint.py save --task "..." --status IN_PROGRESS --next-step "..." --known-failures "none"
    python tools/checkpoint.py show
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".session" / "checkpoint.json"


def git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20
        )
        return result.stdout.strip()
    except Exception:
        return ""


def save(args: argparse.Namespace) -> int:
    STATE.parent.mkdir(exist_ok=True)
    checkpoint = {
        "saved_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "task": args.task,
        "status": args.status,
        "next_step": args.next_step,
        "known_failures": args.known_failures,
        "changed_files": [line for line in git("status", "--porcelain").splitlines() if line.strip()],
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
    }
    STATE.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    log = ROOT / "docs" / "SESSION_LOG.md"
    log.parent.mkdir(exist_ok=True)
    line = (
        f"- {checkpoint['saved_utc']} · {args.status} · {args.task} · "
        f"next: {args.next_step}\n"
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(f"saved: {STATE}")
    return 0


def show(_: argparse.Namespace) -> int:
    if not STATE.is_file():
        print("no checkpoint")
        return 1
    print(STATE.read_text(encoding="utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="checkpoint")
    sub = parser.add_subparsers(dest="command", required=True)

    save_parser = sub.add_parser("save")
    save_parser.add_argument("--task", required=True)
    save_parser.add_argument("--status", default="IN_PROGRESS")
    save_parser.add_argument("--next-step", required=True)
    save_parser.add_argument("--known-failures", default="none")
    save_parser.set_defaults(func=save)

    show_parser = sub.add_parser("show")
    show_parser.set_defaults(func=show)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
