"""Show what the reference-conditioned drafts actually look like, including copied phrases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.guards import fact_list, reference_copies
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.luar import LuarDrive, LuarIndex
from prose_engine.voice.references import format_references


def paragraphs(path: Path, minimum: int = 80):
    return [part.strip() for part in path.read_text(encoding="utf-8").split("\n\n") if len(part.strip()) >= minimum]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="work/americandad/start_scene_corrected.md")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--references", type=int, default=4)
    parser.add_argument("--out", default="reports/copies_sample.md")
    args = parser.parse_args()

    text = paragraphs(Path(args.file))[args.index]
    drive = LuarDrive(LuarIndex.load("books/luar_index.joblib"))
    hits = drive.retrieve_passages("inspect", text, max_results=args.references)
    references = [hit.text for hit in hits]
    evaluator = Evaluator(books="books")
    provider = create_prose_provider("local", model_name="Qwen/Qwen3.5-9B", max_new_tokens=350)

    request = ProseRewriteRequest(
        request_id="inspect", project_id="inspect", document_id="scene",
        base_revision=1, target_span_id="p0", original_text=text, category=SpanCategory.GENERAL,
    )
    prompt = (
        "MUST KEEP EXACTLY (names, numbers, quoted lines): " + ", ".join(fact_list(text)) + "\n\n"
        + format_references(references) + "\n\n"
        + "REBUILD DIRECTIVE: write this beat anew from the facts. Return only the paragraph."
    )

    lines = [f"# Reference-conditioned drafts — paragraph {args.index}", "", "## Original", text, "", "## References"]
    lines += [f"- {reference}" for reference in references]
    lines += ["", "## Drafts"]

    for number in range(1, args.n + 1):
        draft = provider.generate_rewrite(request, prompt).strip()
        copies = reference_copies(draft, references, 6)
        lines += [
            f"### Draft {number}",
            f"similarity {evaluator.similarity(draft):.3f} · percentile {evaluator.percentile(draft):.3f} · "
            f"copied 6-grams {len(copies)}",
            "",
            draft,
            "",
        ]
        if copies:
            lines += ["Copied spans: " + "; ".join(copies[:6]), ""]
        print(f"[{number}/{args.n}] sim {evaluator.similarity(draft):.3f} copied {len(copies)}")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
