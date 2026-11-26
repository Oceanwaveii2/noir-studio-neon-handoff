"""
Finish the starting scene using the author's notes as direction.

Each beat is rewritten with:
  - the author's direction for that beat
  - the lines the author rejected (negative exemplars)
  - the world rules and house map
  - four LUAR references from the books
  - the fact / canon / copy guards

    python tools/finish_scene.py --file work/americandad/start_scene_corrected.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.guards import fact_list, preserves_facts, reference_copies
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.scoped_service import add_timeline_law_args, check_namespace_world_laws
from prose_engine.voice.editorial import EditorialNotes
from prose_engine.voice.ledger import BeatPlan, sections as scene_sections
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.luar import LuarDrive, LuarIndex
from prose_engine.voice.references import format_references
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState

HEADING = re.compile(r"^(?:Scene \d+:.*|INT\..*|EXT\..*)$", re.MULTILINE)


def sections(text: str):
    matches = list(HEADING.finditer(text))
    if not matches:
        return [(text.strip(), "")]
    parts = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        parts.append((text[match.start():end].strip(), match.group(0)))
    return parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="work/americandad/start_scene_corrected.md")
    parser.add_argument("--out", default="work/americandad/start_scene_engine.md")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--references", type=int, default=4)
    parser.add_argument("--allow-book-references", action="store_true")
    parser.add_argument("--lens", default="irby", choices=["irby", "tarantino", "glamour", "pop", "lockwood", "none"])
    add_timeline_law_args(parser)
    args = parser.parse_args()

    print('Timeline universe world laws active.' if args.timeline else 'Standalone finish: no timeline or universe laws. Use scoped episode operations for protected work.', file=sys.stderr)
    drive = None; influence = None
    if args.references and not args.allow_book_references:
        print('Book references disabled; pass --allow-book-references to use eligible sources.',file=sys.stderr)
    if args.references and args.allow_book_references:
        from prose_engine.reference_service import prepare_retrieval
        setup=prepare_retrieval('books','luar','local')
        if setup.state != 'ready':
            print('References unavailable: '+setup.message,file=sys.stderr)
            return 1
        drive,influence=setup.drive,setup.influence

    notes = EditorialNotes.load()
    plan = BeatPlan.load()
    world = WorldState.load()
    house = House.load()
    evaluator = Evaluator(books="books")
    provider = create_prose_provider("local", model_name=args.model, max_new_tokens=350)

    text = Path(args.file).read_text(encoding="utf-8")
    out_sections = []
    for section, heading in sections(text):
        beat = notes.for_text(section)
        direction = notes.prompt_block(section)
        facts = fact_list(section)
        references = []
        if drive is not None:
            hits = drive.retrieve_passages("finish", section, max_results=args.references,influence=influence)
            references = [hit.text for hit in hits]
        request = ProseRewriteRequest(
            request_id=f"finish-{len(out_sections)}", project_id="finish", document_id="scene",
            base_revision=1, target_span_id=f"s{len(out_sections)}", original_text=section,
            category=SpanCategory.GENERAL,
        )
        from prose_engine.voice.injection import format_injection_prompt
        injection = format_injection_prompt(args.lens) if args.lens and args.lens != "none" else ""
        prompt = (
            "MUST KEEP EXACTLY (names, numbers, quoted lines): " + ", ".join(facts) + "\n\n"
            + world.prompt_block() + "\n\n"
            + house.prompt_block(section, cad=False) + "\n\n"
            + direction + "\n\n"
            + ((plan.requires_block(beat.id) + "\n\n") if beat is not None else "")
            + (format_references(references) + "\n\n" if references else "")
            + (injection + "\n\n" if injection else "")
            + "Rewrite this beat. Keep every fact. Follow the direction. Stage it; do not summarise. "
            + "Return only the beat."
        )
        candidate = ""
        try:
            candidate = provider.generate_rewrite(request, prompt).strip()
        except Exception as exc:
            print(f"[{beat.id if beat else '?'}] provider error: {exc}")
        reason = "ok"
        if not candidate:
            reason = "empty"
        elif not preserves_facts(section, candidate)[0]:
            reason = "drops facts: " + ", ".join(preserves_facts(section, candidate)[1][:3])
        elif world.violations(candidate) or world.plausibility(candidate):
            reason = "breaks canon"
        elif args.timeline and not check_namespace_world_laws(candidate, args)["passed"]:
            reason = "breaks world law"
        elif house.check_scene([candidate]) and house.check_scene([section]):
            reason = "staging"
        if reason != "ok":
            candidate = section
        else:
            out_sections.append(candidate)
            print(
                f"[{beat.id if beat else '?'}] rewritten | sim {evaluator.similarity(candidate):.3f} "
                f"pct {evaluator.percentile(candidate):.3f}"
            )
            continue
        out_sections.append(section)
        print(f"[{beat.id if beat else '?'}] kept original ({reason})")

    Path(args.out).write_text("\n\n".join(out_sections) + "\n", encoding="utf-8")
    rendered = Path(args.out).read_text(encoding="utf-8")
    check = plan.validate(scene_sections(rendered))
    from prose_engine.scoped_service import record_standalone_draft
    record_standalone_draft(
        rendered,
        original_text=text,
        source_path=args.file,
        route="finish_scene",
        provider_name="local",
        timeline_path=getattr(args, "timeline", None),
        project_id=getattr(args, "project", None),
        universe_id=getattr(args, "universe", None),
        episode=getattr(args, "episode", None),
        branch=getattr(args, "branch", "main") or "main",
        beat=getattr(args, "beat", 0) or 0,
        out_dir=Path(args.out).parent,
        issues=check["issues"],
    )
    print(f"ledger issues: {len(check['issues'])}")
    for issue in check["issues"]:
        print("  !", issue)
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
