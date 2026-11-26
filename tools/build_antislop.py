"""Build the Antislop-style tell profile: our outputs vs the reference corpus."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.embedding_store import load_index
from prose_engine.voice.tellgate import build_profile, save_profile


def generated_texts() -> list[str]:
    texts = []
    for pattern in ("work/**/conditioned.md", "work/**/*_out.md", "work/**/fusion.md"):
        for path in Path(".").glob(pattern):
            text = path.read_text(encoding="utf-8")
            texts.extend(part.strip() for part in text.split("\n\n") if len(part.strip()) > 120)
    return texts


def main() -> int:
    generated = generated_texts()
    if not generated:
        raise SystemExit("no generated text found under work/")
    index = load_index("books/vector_index.joblib")
    reference = index.texts
    profile = build_profile(generated, reference, min_ratio=6.0, min_count=2)
    target = save_profile(profile)
    print(f"generated paragraphs: {len(generated)} | reference passages: {len(reference)}")
    print(f"banlisted trigrams: {len(profile['banlist'])}")
    for phrase, ratio in profile["banlist"][:15]:
        print(f"  {ratio:>7.1f}x  {phrase}")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
