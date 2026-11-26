"""Asset paths resolved from PROSE_ROOT, never from the current working directory."""

from __future__ import annotations

import os
from pathlib import Path


def root() -> Path:
    """Repo root: PROSE_ROOT, else the nearest parent with pyproject.toml."""
    env = os.getenv("PROSE_ROOT")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path(__file__).resolve().parents[1]


def books(*parts: str) -> Path:
    return root().joinpath("books", *parts)


def asset(*parts: str) -> Path:
    return root().joinpath(*parts)
