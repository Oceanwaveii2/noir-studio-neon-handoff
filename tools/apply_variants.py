"""Apply chosen variation takes to the main scene and produce a clean formatted version."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.conditioner import paragraph_spans

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "work" / "americandad" / "start_scene_annotated.md"
OUT = ROOT / "work" / "americandad" / "start_scene_v2.md"
PREFERENCE = ["understatement", "dignity_loss", "escalation_by_stages", "overheard_thin_walls", "deadpan_cut"]
# Explicit picks: the bedroom understatement take was deliberately fragmentary and read badly in the main text.
CHOICE = {7: "understatement", 18: "escalation_by_stages", 33: "understatement"}


def chosen_for(index: int) -> str:
    report = json.loads((ROOT / "work" / "variants" / f"beat{index}.json").read_text(encoding="utf-8"))
    chosen = [take for take in report["takes"] if take["chosen"]]
    wanted = CHOICE.get(index)
    if wanted:
        for take in chosen:
            if take["treatment"] == wanted:
                return take["text"].strip()
    for treatment in PREFERENCE:
        for take in chosen:
            if take["treatment"] == treatment:
                return take["text"].strip()
    return chosen[0]["text"].strip() if chosen else ""


def main() -> int:
    text = SCENE.read_text(encoding="utf-8")
    spans = paragraph_spans(text)
    replacements = {index: chosen_for(index) for index in (7, 18, 33)}
    replacements = {index: value for index, value in replacements.items() if value}

    parts = []
    for index, (start, end) in enumerate(spans):
        parts.append(replacements.get(index, text[start:end].strip()))

    body = "\n\n".join(parts)
    body = body.replace("# AMERICAN FOXY MOM - starting scene (annotated)", "# AMERICAN FOXY MOM - starting scene")
    body = body.replace("# AMERICAN FOXY MOM \u2014 starting scene (annotated, v2)", "# AMERICAN FOXY MOM \u2014 starting scene")
    body = body.replace("# AMERICAN FOXY MOM \u2014 starting scene (annotated)", "# AMERICAN FOXY MOM \u2014 starting scene")
    # drop world-rules preamble and tone-reference block; keep the title
    body = re.sub(r"\nWorld rules:.*?\n---\n", "\n", body, flags=re.DOTALL)
    body = re.sub(r"\nTONE REFERENCES.*?\n---\n", "\n", body, flags=re.DOTALL)
    # drop annotation blocks
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(("[", "]")))
    body = re.sub(r"\n{3,}", "\n\n", body).strip() + "\n"

    OUT.write_text(body, encoding="utf-8")
    print(f"written: {OUT}")
    for index, value in replacements.items():
        print(f"beat {index}: {value[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
