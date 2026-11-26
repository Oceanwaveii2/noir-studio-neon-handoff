"""Build the numeric style card from the corpus."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.voice.style_card import compute


def main() -> int:
    card = compute("books")
    target = card.save("books/style_card.json")
    print(card.prompt_block())
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
