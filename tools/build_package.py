"""
One-shot build: copies the prose modules out of narrative_composer and rewrites imports
so the package stands alone. Re-runnable; it overwrites the copied modules only.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / "deepseek_narrative_composer" / "narrative_composer" / "prose"
DEST = HERE.parent / "prose_engine"

CORE = [
    "models.py",
    "diagnostics.py",
    "style_engine.py",
    "prompt_assembler.py",
    "invariant_gate.py",
    "protected_spans.py",
    "approved_edits.py",
    "ledger.py",
    "ports.py",
    "semantic_drive.py",
]
PROVIDERS = ["base.py", "mock_provider.py", "venice.py", "gemini_flash.py"]


def rewrite(code: str, depth: int) -> str:
    """Rewrites narrative_composer.prose.* imports to relative ones."""
    prefix = "." * depth
    code = code.replace("from narrative_composer.prose.providers.", f"from {prefix}providers.")
    code = code.replace("from narrative_composer.prose.", f"from {prefix}")
    code = code.replace("import narrative_composer.prose.", f"import {prefix}")
    return code


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "providers").mkdir(exist_ok=True)

    for name in CORE:
        source = SOURCE / name
        text = rewrite(source.read_text(encoding="utf-8"), depth=1)
        (DEST / name).write_text(text, encoding="utf-8")

    for name in PROVIDERS:
        source = SOURCE / "providers" / name
        text = rewrite(source.read_text(encoding="utf-8"), depth=2)
        (DEST / "providers" / name).write_text(text, encoding="utf-8")

    # The Venice adapter locates local_secrets.json by walking to the project root; in the
    # original it used parents[3], which does not hold here.
    venice = DEST / "providers" / "venice.py"
    text = venice.read_text(encoding="utf-8")
    text = text.replace(
        '''def _repo_root() -> Path:
    """Locates the project root from this file (narrative_composer/prose/providers/venice.py)."""
    return Path(__file__).resolve().parents[3]''',
        '''def _repo_root() -> Path:
    """Locates the project root (the directory holding pyproject.toml)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path(__file__).resolve().parents[2]''',
    )
    venice.write_text(text, encoding="utf-8")

    leftovers = []
    for path in DEST.rglob("*.py"):
        if "narrative_composer" in path.read_text(encoding="utf-8"):
            leftovers.append(path.relative_to(DEST))
    print("copied", len(CORE), "core +", len(PROVIDERS), "providers")
    print("leftover narrative_composer references:", leftovers or "none")


if __name__ == "__main__":
    main()
