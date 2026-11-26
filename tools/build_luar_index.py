"""Build the LUAR style index over the corpus (GPU, a few minutes)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.voice.luar import LuarIndex


def main() -> int:
    index = LuarIndex.build("books")
    target = index.save("books/luar_index.joblib")
    print(f"vectors: {index.vectors.shape} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
