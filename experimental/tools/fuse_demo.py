"""Fusion demo: three drafts, one synthesis, tell-gate report."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.guards import fact_list
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.strength import get as get_strength
from prose_engine.styleprint import load_model as load_style_model
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.fusion import Fusion
from prose_engine.imagery import mask, vehicles
from prose_engine.voice.tellgate import load_profile, score

FILE = Path("work/familyguy/paragraph.md")
OUT = Path("work/familyguy/fusion.md")


def main() -> int:
    original = FILE.read_text(encoding="utf-8").strip()
    required = fact_list(original)
    images = sorted(vehicles(original))
    directive = get_strength("rebuild").directive
    card = Path("books/voice_card.md").read_text(encoding="utf-8") if Path("books/voice_card.md").is_file() else ""
    prompt = (
        "MUST KEEP EXACTLY (names, numbers, quoted lines): " + ", ".join(required) + "\n\n"
        + directive + "\n\n"
        + card + "\n\n"
        + "FORBIDDEN IMAGES (do not reuse or reword): " + ", ".join(images) + "\n\n"
        + "ORIGINAL WITH COMPARISONS REMOVED:\n" + mask(original)
    )

    provider = create_prose_provider("local", model_name="Qwen/Qwen3.5-9B", max_new_tokens=400)
    request = ProseRewriteRequest(
        request_id="fusion", project_id="prose_engine", document_id="document",
        base_revision=1, target_span_id="paragraph", original_text=original,
        category=SpanCategory.GENERAL,
    )
    evaluator = Evaluator(books="books")
    style_model = load_style_model("books")
    profile = load_profile("books/antislop.json")

    start = time.time()
    result = Fusion(provider, evaluator, style_model, drafts=3).run(original, prompt, request)
    elapsed = round(time.time() - start, 1)

    lines = ["# Fusion: Family Guy paragraph", "", f"elapsed: {elapsed}s", f"accepted: {result.accepted} ({result.reason})", "", "## Drafts"]
    for index, draft in enumerate(result.drafts, 1):
        report = score(draft, profile)
        lines.append(f"### Draft {index} (tell density {report.density})")
        lines.append(draft)
        lines.append("")
    fused_report = score(result.text, profile)
    lines += ["## Fused", f"tell density {fused_report.density} | tics {fused_report.tics} | hits {fused_report.hits}", "", result.text, ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print(f"elapsed: {elapsed}s")
    print(f"accepted: {result.accepted} | {result.reason}")
    print(f"drafts: {len(result.drafts)}")
    print(f"fused tell density: {fused_report.density} | hits: {fused_report.hits[:5]}")
    print(f"written: {OUT}")
    print()
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
