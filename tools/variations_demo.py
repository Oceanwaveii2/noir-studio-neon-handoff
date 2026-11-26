"""Generate distinct treatments of the same beat and print them."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.guards import fact_list
from prose_engine.imagery import vehicles
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.scoped_service import add_timeline_law_args, check_namespace_world_laws
from prose_engine.voice.tellgate import load_profile
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.retrieve import StyleIndex
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState
from prose_engine.voice.variations import VariationSet

TREATMENTS = ["nanite_malfunction", "wish_gone_wrong", "curse", "staged"]

TONE = ("deadpan camp comedy: dry, bitchy, specific; the narrator is unimpressed; the joke "
        "comes from precise physical detail, never from exclamation or summary")

EXEMPLARS = [
    "Still hot. Objectively.",
    "That's a Botticelli with extra bounce.",
    "A mouse in a dress.",
]

EVENTS = [
    "a long trombone-like noise comes out of Rainee",
    "nanites race from her arms to her hips",
    "the dress seams burst",
    "her backside swells until it takes the couch",
    "her face flattens into Peter Griffin's oval",
    "her lipstick stays perfect",
    "her tail thickens",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-book-references", action="store_true", help="Run without eligible style excerpts")
    add_timeline_law_args(parser)
    args, _ = parser.parse_known_args()
    print('Timeline universe world laws active.' if args.timeline else 'Standalone demo: no timeline or universe laws. Use scoped episode operations for protected work.',file=sys.stderr)
    from prose_engine.reference_service import prepare_retrieval
    references = []
    purposes: tuple[str, ...] = ()
    if not args.no_book_references:
        setup = prepare_retrieval('books', 'style', 'local')
        if setup.state != 'ready':
            print('References unavailable: ' + setup.message, file=sys.stderr)
            return 1
        original = Path("work/familyguy/paragraph.md").read_text(encoding="utf-8").strip()
        hits = setup.drive.retrieve_passages('variations', original, max_results=4, influence=setup.influence)
        references = [hit.text for hit in hits]
        purposes = tuple(getattr(setup.drive, 'reference_purposes', ('rank_local', 'prompt')))
        print("voice references from:", sorted({hit.provenance.get('source_id', 'unknown') for hit in hits}))
    else:
        original = Path("work/familyguy/paragraph.md").read_text(encoding="utf-8").strip()
    facts = fact_list(original)
    forbidden = sorted(vehicles(original))
    card = Path("books/voice_card.md").read_text(encoding="utf-8") if Path("books/voice_card.md").is_file() else ""
    profile = load_profile("books/antislop.json")
    evaluator = Evaluator(books="books")
    world = WorldState.load("books/world_state.json")
    house = House.load("books/ling_house")
    context = world.prompt_block() + "\n\n" + house.map_block(cad=False) + "\n\n" + house.prompt_block(original, cad=False)

    provider = create_prose_provider("local", model_name="Qwen/Qwen3.5-9B", max_new_tokens=320)
    request = ProseRewriteRequest(
        request_id="variations", project_id="prose_engine", document_id="document",
        base_revision=1, target_span_id="paragraph", original_text=original,
        category=SpanCategory.GENERAL,
    )

    variants = VariationSet().run(
        provider, request, original, facts, TREATMENTS,
        voice_card=card, forbidden=forbidden, tell_profile=profile, events=EVENTS,
        tone=TONE, exemplars=EXEMPLARS, references=references, context=context,
    )

    lines = ["# Variations: the transformation beat", "", f"facts: {', '.join(facts)}", ""]
    for variant in variants:
        if args.timeline and variant.text:
            law_check = check_namespace_world_laws(variant.text, args)
            if not law_check["passed"]:
                variant.accepted = False
                variant.reason = "breaks world law: " + "; ".join(law_check["violations"][:3])
        lines.append(f"## {variant.treatment} — {'kept' if variant.accepted else 'rejected'}")
        lines.append(f"similarity={evaluator.similarity(variant.text):.3f} percentile={evaluator.percentile(variant.text):.3f}")
        lines.append(f"facts_ok={variant.facts_ok} tells={variant.tell_density} "
                     f"overlap_original={variant.overlap_original:.2f} "
                     f"overlap_other={variant.max_overlap_other:.2f} ({variant.reason})")
        lines.append("")
        lines.append(variant.text)
        lines.append("")
    out_text = "\n".join(lines)
    Path("work/familyguy/variations.md").write_text(out_text, encoding="utf-8")
    from prose_engine.scoped_service import record_standalone_draft
    record_standalone_draft(
        out_text,
        original_text=original,
        source_path="work/familyguy/paragraph.md",
        route="variations_demo",
        provider_name="local",
        timeline_path=getattr(args, "timeline", None),
        project_id=getattr(args, "project", None),
        universe_id=getattr(args, "universe", None),
        episode=getattr(args, "episode", None),
        branch=getattr(args, "branch", "main") or "main",
        beat=getattr(args, "beat", 0) or 0,
        out_dir=Path("work/familyguy"),
        extra={"variants": len(variants), "reference_purposes": list(purposes)},
    )

    for variant in variants:
        print(f"[{variant.treatment}] {'KEPT' if variant.accepted else 'REJECTED'} ({variant.reason})")
        print(variant.text)
        print()
    print("written: work/familyguy/variations.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
