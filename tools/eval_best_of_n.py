"""
Best-of-N evaluation over a set of paragraphs.

    python tools/eval_best_of_n.py --file work/familyguy/before.md --paragraphs 10 --n 8

Reports accept rate, mean similarity, style distance and overlap; writes reports/best_of_n.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine import reference_service
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.scoped_service import add_timeline_law_args, check_namespace_world_laws
from prose_engine.styleprint import load_model as load_style_model
from prose_engine.guards import fact_list
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.pipeline import Pipeline
from prose_engine.voice.luar import LuarDrive, LuarScorer
from prose_engine.voice.references import format_references


def load_luar_scorer(books_root: str | Path = "books") -> LuarScorer:
    """Load the local LUAR voice scorer strictly through reference_policy checks."""
    setup = reference_service.prepare_retrieval(books_root, "luar", "local", purposes=("rank_local",))
    if setup.state != "ready":
        raise ValueError(setup.message)
    return LuarScorer(setup.drive.index)


def paragraphs_from(path: Path, minimum: int, limit: int) -> list[str]:
    text = path.read_text(encoding="utf-8")
    parts = [part.strip() for part in text.split("\n\n") if len(part.strip()) >= minimum]
    return parts[:limit]


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denom
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="work/familyguy/before.md")
    parser.add_argument("--paragraphs", type=int, default=10)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--max-tokens", type=int, default=400)
    parser.add_argument("--ban-comparisons", action="store_true", default=True)
    parser.add_argument("--steer", default=None)
    parser.add_argument("--alpha", type=float, default=0.0)
    parser.add_argument("--out", default="reports/best_of_n.json")
    parser.add_argument("--references", type=int, default=0, help="LUAR references per paragraph")
    parser.add_argument("--allow-book-references", action="store_true", help="required to inject book passages")
    parser.add_argument("--style-card", action="store_true", help="numeric style targets, no passages")
    add_timeline_law_args(parser)
    args = parser.parse_args()

    print('Timeline universe world laws active.' if args.timeline else 'Standalone evaluation: no timeline or universe laws.',file=sys.stderr)
    setup=None
    if args.references and args.allow_book_references:
        setup=reference_service.prepare_retrieval('books','luar','local')
        if setup.state != 'ready':
            print('References unavailable: '+setup.message,file=sys.stderr)
            return 1

    entries = paragraphs_from(Path(args.file), 80, args.paragraphs)
    if not entries:
        raise SystemExit("no paragraphs found")

    kwargs = {"max_new_tokens": args.max_tokens}
    if args.ban_comparisons:
        kwargs["ban_comparisons"] = True
    if args.steer:
        kwargs.update({"steer_path": args.steer, "steer_alpha": args.alpha})
    provider = create_prose_provider("local", model_name=args.model, **kwargs)
    evaluator = Evaluator(books="books")
    style_model = load_style_model("books")
    voice = None
    try:
        voice = load_luar_scorer("books")
        print("voice signal: LUAR" + (" (encoder ready)" if voice else ""))
    except Exception as exc:
        print(f"voice signal: similarity fallback ({exc})")
    style_block = ""
    if args.style_card:
        from prose_engine.voice.style_card import StyleCard

        style_block = StyleCard.load("books/style_card.json").prompt_block() + "\n\n"
        print("style card: on")
    if args.references and not args.allow_book_references:
        print("references disabled (pass --allow-book-references)")
        args.references = 0
    drive = None
    if args.references:
        drive = setup.drive
        print(f"references: LUAR ({args.references} per paragraph)")
    pipeline = Pipeline(
        provider, evaluator, style_model, candidates=args.n, ledger="eval/decisions.jsonl",
        voice=voice,
    )

    rows = []
    for number, text in enumerate(entries):
        request = ProseRewriteRequest(
            request_id=f"bon-{number}", project_id="prose_engine", document_id="document",
            base_revision=1, target_span_id=f"p{number}", original_text=text,
            category=SpanCategory.GENERAL,
        )
        required = fact_list(text)
        must = (
            "MUST KEEP EXACTLY (names, numbers, quoted lines): " + ", ".join(required) + "\n\n"
            if required
            else ""
        )
        reference_texts = []
        reference_block = ""
        if drive is not None:
            hits = drive.retrieve_passages("eval", text, max_results=args.references,influence=setup.influence)
            reference_texts = [hit.text for hit in hits]
            reference_block = format_references(reference_texts) + "\n\n"
        result = pipeline.rewrite(
            text,
            must + style_block + reference_block + "REBUILD DIRECTIVE: write this beat anew from the facts. Return only the paragraph.",
            request,
            scene="eval",
            paragraph=number,
            max_overlap=0.45,
            revise_once=False,
            references=reference_texts,
        )
        if args.timeline and result.text:
            law_check = check_namespace_world_laws(result.text, args)
            if not law_check["passed"]:
                result.accepted = False
                result.reason = "breaks world law: " + "; ".join(law_check["violations"][:3])
        rows.append(
            {
                "paragraph": number,
                "accepted": result.accepted,
                "reason": result.reason,
                "score": result.score,
                "overlap": round(result.overlap, 3),
                "candidates": result.candidates,
                "similarity": round(evaluator.similarity(result.text or text), 4),
                "percentile": round(evaluator.percentile(result.text or text), 4),
            }
        )
        print(
            f"[{number + 1}/{len(entries)}] accepted={result.accepted} "
            f"score={result.score:.3f} sim={rows[-1]['similarity']:.3f} {result.reason[:60]}"
        )

    accepted = sum(1 for row in rows if row["accepted"])
    accepted_rows = [row for row in rows if row["accepted"]]
    mean_sim_acc = (
        round(sum(row["similarity"] for row in accepted_rows) / len(accepted_rows), 4)
        if accepted_rows
        else None
    )
    ci_low, ci_high = wilson_interval(accepted, len(rows))
    report = {
        "file": args.file,
        "n": args.n,
        "paragraphs": len(rows),
        "accepted": accepted,
        "accept_rate": round(accepted / len(rows), 3),
        "accept_rate_wilson_95ci": [ci_low, ci_high],
        "mean_similarity_accepted": mean_sim_acc,
        "mean_similarity": round(sum(row["similarity"] for row in rows) / len(rows), 4),
        "rows": rows,
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"accept rate: {report['accept_rate']} ({accepted}/{len(rows)}) -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
