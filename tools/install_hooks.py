"""
Install the repository's git hooks (currently: pre-commit -> local CI).

    python tools/install_hooks.py

The hook lives in the repo (`hooks/pre-commit`) so it survives a fresh clone; this script copies
it into `.git/hooks/` and marks it executable where the platform supports that.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
TARGET = ROOT / ".git" / "hooks"


def main() -> int:
    if not (ROOT / ".git").is_dir():
        print("not a git repository")
        return 1
    TARGET.mkdir(parents=True, exist_ok=True)
    installed = 0
    for source in sorted(HOOKS.glob("*")):
        if not source.is_file():
            continue
        destination = TARGET / source.name
        shutil.copyfile(source, destination)
        try:
            mode = destination.stat().st_mode
            destination.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError:
            pass
        installed += 1
        print(f"installed {source.name} -> {destination}")
    print(f"{installed} hook(s) installed. Bypass once with: git commit --no-verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
