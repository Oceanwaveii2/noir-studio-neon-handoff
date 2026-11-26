"""Command line interface for the standalone prose engine.

    python -m prose_engine books
    python -m prose_engine corpus index --out out/corpus_index.json
    python -m prose_engine corpus profile --out out/corpus_profile.json
    python -m prose_engine corpus passages --out books/passages.json
    python -m prose_engine diagnose --file chapter.md
    python -m prose_engine condition --file chapter.md --out out/run --provider venice
    python -m prose_engine providers
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .conditioner import paragraph_spans, run_conditioning
from .guards import preserves_facts, token_overlap
from .rhythm import rhythm_match, rhythm_target
from .scoped_service import add_timeline_law_args, check_namespace_world_laws
from .style_guide import analyze_samples, load_guide, save_guide, style_fit
from .invariant_gate import InvariantGate
from .models import ProseRewriteRequest
from .corpus import (
    Book,
    corpus_index,
    derive_style_profile,
    load_corpus,
    load_passages,
    reference_passages,
    save_passages,
)
from .influence import LEVEL_NAMES, describe, load_influence, parse_level, save_influence
from .preferences import load_proposals, suggest, summarize
from .voice import Evaluator
from .voice.appearance import Appearance, AppearanceBible
from .voice.evaluate import report as voice_report
from .voice.tics import counts as tic_counts, scan as tic_scan
from .voice.strength_map import StrengthMap, dialogue_lines, policy as strength_policy
from .voice.slop import SlopModel
from .voice.world_state import WorldState
from .voice.ledger import BeatPlan, sections as scene_sections
from .voice.spatial import House
from .voice.scene_brief import SceneBrief
from .voice.best_of_n import BestOfN
from .voice.bible import Bible
from .voice.epistemic import Ledger
from .voice.pipeline import Pipeline
from .voice.scene import Contract
from .diagnostics import ProseDiagnosticsAnalyzer
from .providers import create_prose_provider

ProviderConfigurationError = (ValueError, RuntimeError)
from .screenplay import analyze_document, summarize as summarize_tells
from .semantic_drive import SemanticDrive
from .style_engine import STANDARD_DRAMATIC, StyleProfile, StyleProfileRepository
from .embedding_store import DEFAULT_MODEL, EmbeddingIndex, load_index
from .vector_store import VectorSemanticDrive, chunk_books


def _load_books(path: str) -> List[Book]:
    books = load_corpus(path)
    if not books:
        raise SystemExit(
            f"No books found under '{path}'. Run tools/extract_books.py or drop .txt files "
            f"in {path}/text/."
        )
    return books


def _profile(args: argparse.Namespace) -> StyleProfile:
    if getattr(args, "profile_file", None):
        return StyleProfile.model_validate_json(Path(args.profile_file).read_text(encoding="utf-8"))
    style = getattr(args, "style", "auto")
    if style in (None, "auto"):
        # Books are the default voice: use the corpus profile if one was derived.
        candidate = Path(getattr(args, "books", "books")) / "profile.json"
        if candidate.is_file():
            return StyleProfile.model_validate_json(candidate.read_text(encoding="utf-8"))
        return STANDARD_DRAMATIC
    repository = StyleProfileRepository()
    return repository.get_style_profile(style) or STANDARD_DRAMATIC


def cmd_books(args: argparse.Namespace) -> int:
    books = _load_books(args.books)
    print(f"{'slug':<52}{'words':>9} {'pages':>6}  title")
    print("-" * 100)
    for book in books:
        print(f"{book.slug:<52}{len(book.text.split()):>9,} {book.pages:>6}  {book.title}")
    print(f"\n{len(books)} books, {sum(len(book.text.split()) for book in books):,} words")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    books = _load_books(args.books)
    index = corpus_index(books)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(index, indent=2), encoding="utf-8")
    aggregate = index["aggregate"]
    print(
        f"{aggregate['books']} books | {aggregate['words']:,} words | "
        f"burstiness {aggregate['burstiness']:.2f} | "
        f"sensory/1k {aggregate['sensory_per_1k_words']:.2f} | "
        f"dialogue {aggregate['dialogue_ratio']:.1%}"
    )
    for entry in index["books"]:
        print(
            f"  {entry['slug']:<46} cadence {entry['paragraph_burstiness']:>4.2f}  "
            f"sensory/1k {entry['sensory_per_1k_words']:>5.2f}  "
            f"filters {entry['filter_words']:>3}  labels {entry['emotion_labels']:>2}"
        )
    if args.out:
        print(f"written: {args.out}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    books = _load_books(args.books)
    base = StyleProfileRepository().get_style_profile(args.base) or STANDARD_DRAMATIC
    profile = derive_style_profile(books, profile_id=args.id, name=args.name, base=base)
    payload = profile.model_dump_json(indent=2)
    target = args.out or str(Path(args.books) / "profile.json")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(payload, encoding="utf-8")
    print(f"written: {target}")
    print(payload)
    return 0


def cmd_passages(args: argparse.Namespace) -> int:
    books = _load_books(args.books)
    from .reference_policy import ReferencePolicy
    source_policy = ReferencePolicy.load(args.books)
    influence = load_influence(args.books)
    books = [book for book in books if source_policy.allows(
        {"book": book.slug}, ("rank_local", "export"), influence)]
    if not books:
        raise SystemExit("No sources eligible for passage export; configure reference_policy.json.")
    passages = reference_passages(books, profile_id=args.id, count=args.count)
    target = args.out or str(Path(args.books) / "passages.json")
    save_passages(passages, target)
    for passage in passages:
        print(f"[{passage.passage_id}] {passage.text[:150]}...")
    print(f"\n{len(passages)} passages -> {target}")
    return 0


def cmd_vectors(args: argparse.Namespace) -> int:
    books = _load_books(args.books)
    chunks = chunk_books(books)
    if args.backend == "transformer":
        index = EmbeddingIndex.build(chunks, model_name=args.model)
        dims = index.vectors.shape[1]
    else:
        from .vector_store import VectorIndex

        index = VectorIndex.build(chunks, dim=args.dim)
        dims = index.dim
    target = args.out or str(Path(args.books) / "vector_index.joblib")
    index.save(target)
    size = Path(target).stat().st_size / 1_000_000
    print(f"{len(chunks):,} passages | {args.backend} | {dims} dims | {size:.1f} MB -> {target}")
    return 0


STRATEGIES = {
    "image": (
        "Two sentences. Sentence 1 is a fragment of at most 6 words. Sentence 2 is one long "
        "image (15-30 words) with concrete physical detail. No similes, no interpretation."
    ),
    "action": (
        "Three sentences. Each starts with a different subject. No sentence longer than 14 "
        "words. Only what someone does; no interiority, no similes."
    ),
    "understatement": (
        "One or two sentences. A flat declarative plus one absurd concrete detail, stated "
        "without comment or explanation. No exclamation marks."
    ),
    "rhythm": (
        "Imitate the reference cadence: at least one sentence under 6 words and one over 20 "
        "words, alternating short and long."
    ),
}


STRATEGIES = {
    "image": (
        "Rewrite as images: one or two concrete physical details that carry the beat. "
        "No interpretation, no pile of similes."
    ),
    "action": (
        "Rewrite as action: subjects doing things, in order. Minimal description, no similes."
    ),
    "understatement": (
        "Rewrite with comic understatement: state the beat plainly and let the absurdity sit "
        "uncommented."
    ),
    "rhythm": (
        "Rewrite to match the cadence of the reference passages: imitate their sentence-length "
        "variation and their short/long alternation."
    ),
}


def cmd_generate_variants(args: argparse.Namespace) -> int:
    """Generate strategy-conditioned candidates for each flagged paragraph."""
    print('Timeline universe world laws active.' if getattr(args, 'timeline', None) else 'Standalone variants: no timeline or universe laws. Use the scoped command for an episode.', file=sys.stderr)
    from .library_indexes import index_path as library_index_path, validate_index
    index_path = library_index_path(args.books, "topic") if getattr(args, "allow_book_references", False) else None
    index = load_index(index_path) if index_path is not None and index_path.is_file() else None
    influence = load_influence(args.books)
    from .reference_policy import ReferencePolicy, eligible_index, legacy_identities, prompt_purposes
    if not getattr(args, "allow_book_references", False):
        print("retrieval: disabled (use --allow-book-references and configure reference_policy.json)")
    if index is not None:
        validate_index(args.books, "topic", index)
        policy = ReferencePolicy.load(args.books)
        index = eligible_index(legacy_identities(index), policy,
                               prompt_purposes(args.provider), influence)
        if index is None:
            raise SystemExit("retrieval: no eligible sources; check reference_policy.json and influence settings")
    elif getattr(args, "allow_book_references", False):
        raise SystemExit("retrieval: requested vector index unavailable")
    provider = create_prose_provider(args.provider, model_name=args.model)
    guide = load_guide(args.style_guide) if getattr(args, "style_guide", None) else None
    style_block = ("HOUSE STYLE:\n" + guide.to_markdown()[:1400] + "\n\n") if guide else ""

    text = Path(args.file).read_text(encoding="utf-8")
    paragraphs = [
        text[start:end].strip()
        for start, end in paragraph_spans(text)
        if text[start:end].strip()
    ]
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    if not strategies:
        strategies = list(STRATEGIES)

    entries = []
    attempted = 0
    for number, paragraph in enumerate(paragraphs):
        if len(paragraph) < 80 or len(paragraph) > 6000:
            continue
        if paragraph.startswith("("):
            continue
        report = ProseDiagnosticsAnalyzer.analyze(paragraph)
        if not report.warnings:
            continue
        if args.limit is not None and attempted >= args.limit:
            break
        attempted += 1

        hits = index.query(paragraph, k=args.references, influence=influence) if index is not None else []
        references = "\n".join(f"- {passage[:280]}" for _score, passage, _meta in hits)
        target = rhythm_target([passage for _score, passage, _meta in hits]) if hits else None
        cadence_hint = (
            f"Reference cadence: mean {target[0]:.1f} words per sentence, "
            f"variation {target[1]:.1f}."
            if target
            else ""
        )

        variants = []
        issues = "; ".join(report.warnings)
        budget = max(20, int(len(paragraph.split()) * 1.4))
        for strategy in strategies:
            instruction = STRATEGIES.get(strategy, strategy)
            pattern = ""
            if index is not None:
                pattern_hits = index.query(instruction, k=1, influence=influence)
                if pattern_hits:
                    pattern = pattern_hits[0][1][:240]
            for _ in range(args.count):
                prompt = (
                    f"ISSUES: {issues}\n\n"
                    f"STRATEGY: {instruction}\n"
                    f"PATTERN EXAMPLE (imitate the shape, not the words): {pattern}\n"
                    f"{cadence_hint}\n\n"
                    f"{style_block}"
                    f"REFERENCE PASSAGES (voice):\n{references}\n\n"
                    f"PARAGRAPH:\n{paragraph}\n\n"
                    "Rules: 1 to 3 sentences; at most "
                    f"{budget} words (the original is {len(paragraph.split())}); keep every fact, "
                    "name, number and quoted line; match the house style; do not add new actions, "
                    "characters, or explanation. Return only the rewritten beat."
                )
                request = ProseRewriteRequest(
                    request_id=f"gen_{number}_{strategy}",
                    project_id="prose_engine",
                    document_id="document",
                    base_revision=1,
                    target_span_id=f"para-{number}",
                    original_text=paragraph,
                    style_profile_id="corpus",
                )
                try:
                    raw = provider.generate_rewrite(request, prompt)
                except Exception as exc:
                    print(f"  paragraph {number}/{strategy}: provider error: {exc}")
                    break
                cleaned = " ".join(InvariantGate.clean_candidate_text(raw).split())
                if cleaned:
                    if check_namespace_world_laws(cleaned, args)["passed"]:
                        variants.append({"text": cleaned, "strategy": strategy})
        if variants:
            entries.append({"original": paragraph, "variants": variants})
        print(f"  paragraph {number}: {len(variants)} variants ({', '.join(strategies)})")

    target_path = Path(args.out)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    from .scoped_service import record_standalone_draft
    summary_text = "\n\n".join(row["variants"][0]["text"] for row in entries if row.get("variants"))
    record_standalone_draft(
        summary_text or text[:400],
        original_text=text,
        source_path=args.file,
        route="generate-variants",
        provider_name=args.provider,
        timeline_path=getattr(args, "timeline", None),
        project_id=getattr(args, "project", None),
        universe_id=getattr(args, "universe", None),
        episode=getattr(args, "episode", None),
        branch=getattr(args, "branch", "main") or "main",
        beat=getattr(args, "beat", 0) or 0,
        out_dir=target_path.parent,
        extra={"paragraph_entries": len(entries), "allow_book_references": bool(getattr(args, "allow_book_references", False))},
    )
    print(f"{len(entries)} paragraphs -> {target_path}")
    return 0


def cmd_style(args: argparse.Namespace) -> int:
    samples = []
    for item in args.samples.split(","):
        path = Path(item.strip())
        if path.is_file():
            samples.append(path.read_text(encoding="utf-8"))
    if not samples:
        raise SystemExit("no sample files found")
    guide = analyze_samples(samples)
    out = Path(args.out or "out/style_guide.json")
    save_guide(guide, out)
    md = Path(args.md or out.with_suffix(".md"))
    md.write_text(guide.to_markdown(), encoding="utf-8")
    print(f"{guide.samples} samples | {guide.words:,} words | {guide.sentences:,} sentences")
    print(
        f"mean sentence {guide.mean_sentence_length} | SD {guide.sentence_sd} | "
        f"short {guide.short_sentence_pct}% | questions {guide.question_pct}% | "
        f"similes {guide.simile_per_1k}/1k"
    )
    print(f"written: {out} and {md}")
    return 0


def cmd_variants(args: argparse.Namespace) -> int:
    from .library_indexes import index_path as library_index_path, validate_index
    index_path = library_index_path(args.books, "topic")
    if not index_path.is_file():
        raise SystemExit("no vector index; run: prose_engine corpus vectors --books books")
    index = load_index(index_path)
    validate_index(args.books, "topic", index)
    influence = load_influence(args.books)
    from .reference_policy import ReferencePolicy, eligible_index, legacy_identities
    index = eligible_index(legacy_identities(index), ReferencePolicy.load(args.books), ("rank_local",), influence)
    if index is None:
        raise SystemExit("No eligible reference sources; configure reference_policy.json.")
    guide = load_guide(args.style_guide) if getattr(args, "style_guide", None) else None
    entries = json.loads(Path(args.file).read_text(encoding="utf-8"))

    selected = []
    for entry in entries:
        original = entry["original"].strip()
        base = ProseDiagnosticsAnalyzer.analyze(original)
        hits = index.query(original, k=args.references, influence=influence)
        target = rhythm_target([passage for _s, passage, _m in hits])

        rows = []
        for number, variant in enumerate(entry.get("variants", [])):
            if isinstance(variant, dict):
                raw_text = variant.get("text", "")
                strategy = variant.get("strategy", "")
            else:
                raw_text = variant
                strategy = ""
            text = " ".join(raw_text.split())
            if not text:
                continue
            report = ProseDiagnosticsAnalyzer.analyze(text)
            ratio = len(text) / max(1, len(original))
            quotes = text.count('"') + text.count(chr(8220)) + text.count(chr(8221))
            facts_ok, missing = preserves_facts(original, text)
            base_rules = {warning.split(':')[0] for warning in base.warnings}
            new_rules = {warning.split(':')[0] for warning in report.warnings} - base_rules
            overlap = token_overlap(original, text)
            valid = (
                facts_ok
                and overlap <= 0.82
                and 0.4 <= ratio <= 2.2
                and report.filter_word_count <= base.filter_word_count
                and len(report.label_examples) <= len(base.label_examples)
                and quotes % 2 == 0
                and not new_rules
            )
            voice = index.score(text)["mean_top"]
            gain = (len(base.warnings) - len(report.warnings)) / max(1, len(base.warnings))
            rhythm = rhythm_match(text, target)
            style = style_fit(text, guide) if guide else 0.0
            penalty = 0.08 * max(0.0, ratio - 1.25)
            novelty = 1.0 - overlap
            if guide:
                score = (
                    0.28 * voice + 0.22 * gain + 0.15 * rhythm + 0.20 * style
                    + 0.15 * novelty - penalty
                )
            else:
                score = 0.40 * voice + 0.25 * gain + 0.15 * rhythm + 0.20 * novelty - penalty
            rows.append(
                {
                    "variant": number,
                    "strategy": strategy,
                    "text": text,
                    "voice": round(voice, 3),
                    "gain": round(gain, 2),
                    "rhythm": round(rhythm, 2),
                    "style": round(style, 2),
                    "score": round(score, 3),
                    "ratio": round(ratio, 2),
                    "valid": valid,
                    "missing": missing,
                    "overlap": round(overlap, 2),
                }
            )
        rows.sort(key=lambda row: (-row["score"], not row["valid"]))
        best = next((row for row in rows if row["valid"]), None)
        print(f"=== {original[:80]}")
        for row in rows:
            mark = "*" if best and row is best else " "
            note = f" missing={row['missing']}" if row["missing"] else ""
            print(
                f" {mark} {row['strategy']:<14} v{row['variant']}  voice {row['voice']:.3f}"
                f"  gain {row['gain']:.2f}  rhythm {row['rhythm']:.2f}  style {row['style']:.2f}"
                f"  score {row['score']:.3f}  ratio {row['ratio']:.2f}  overlap {row['overlap']:.2f}"
                f"  valid={row['valid']}{note}"
            )
        if best:
            selected.append(
                {
                    "original": original,
                    "text": best["text"],
                    "strategy": best["strategy"],
                    "score": best["score"],
                }
            )
        print()

    target_path = Path(args.out)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(selected)}/{len(entries)} paragraphs have a valid selection -> {target_path}")
    return 0


def cmd_influence(args: argparse.Namespace) -> int:
    books_dir = Path(args.books)
    influence = load_influence(books_dir)
    manifest_path = books_dir / "manifest.json"
    titles = {}
    text_books = set()
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest.get("books", []):
            titles[entry.get("slug")] = entry.get("title", "")
            if int(entry.get("words") or 0) > 0:
                text_books.add(entry.get("slug"))
    titles = {slug: title for slug, title in titles.items() if slug in text_books}

    if not influence.levels:
        influence.levels = {slug: 2 for slug in text_books}
        save_influence(influence)
    else:
        influence.levels = {
            slug: level for slug, level in influence.levels.items() if slug in text_books
        }

    if args.influence_command == "show":
        print(describe(influence, titles))
        return 0

    if args.influence_command == "set":
        if args.book not in influence.levels:
            raise SystemExit(f"unknown book: {args.book}")
        level = parse_level(args.level)
        influence.levels[args.book] = level
        save_influence(influence)
        print(f"{args.book}: {LEVEL_NAMES[level]} ({level})")
        return 0

    if args.influence_command == "mode":
        influence.mode = args.mode
        save_influence(influence)
        print(f"mode: {influence.mode}")
        return 0

    return 1


def cmd_reference(args: argparse.Namespace) -> int:
    from .library_indexes import index_path as library_index_path, validate_index
    index_path = library_index_path(args.books, "topic")
    if not index_path.is_file():
        raise SystemExit("no vector index; run: prose_engine corpus vectors --books books")
    index = load_index(index_path)
    validate_index(args.books, "topic", index)
    influence = load_influence(args.books)
    from .reference_policy import ReferencePolicy, eligible_index, legacy_identities
    index = eligible_index(legacy_identities(index), ReferencePolicy.load(args.books),
                           ("rank_local", "inspect_local"), influence)
    if index is None:
        raise SystemExit("No locally inspectable references; configure reference_policy.json.")
    text = Path(args.file).read_text(encoding="utf-8")
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]

    indices = []
    if args.paragraph is not None:
        indices = [args.paragraph]
    elif args.flagged:
        for number, paragraph in enumerate(paragraphs):
            if len(paragraph) < 80:
                continue
            if ProseDiagnosticsAnalyzer.analyze(paragraph).warnings:
                indices.append(number)
    else:
        indices = list(range(len(paragraphs)))

    for number in indices:
        if number >= len(paragraphs):
            continue
        paragraph = paragraphs[number]
        print(f"=== paragraph {number}: {paragraph[:90]}")
        for score, passage, meta in index.query(paragraph, k=args.k, influence=influence):
            print(f"  {score:.3f} [{meta['book']}] {passage[:180]}")
        print()
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    spans = paragraph_spans(text)
    rows = []
    for index, (start, end) in enumerate(spans):
        core = text[start:end].strip()
        if len(core) < 40:
            continue
        report = ProseDiagnosticsAnalyzer.analyze(core)
        if report.warnings:
            rows.append(
                {
                    "paragraph": index,
                    "chars": len(core),
                    "burstiness": round(report.burstiness_score, 2),
                    "sensory": report.sensory_details_count,
                    "filters": report.filter_word_count,
                    "labels": len(report.label_examples),
                    "warnings": report.warnings,
                    "preview": core[:110],
                }
            )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print(f"{len(rows)} flagged paragraphs of {len(spans)} in {args.file}")
    for row in rows:
        print(f"  ¶{row['paragraph']:<4} burstiness {row['burstiness']:>4.2f}  sensory {row['sensory']:>2}  "
              f"filters {row['filters']:>2}  labels {row['labels']:>2}  {row['warnings'][0][:70]}")
        print(f"        {row['preview']}")
    return 0


def cmd_condition(args: argparse.Namespace) -> int:
    print('Timeline universe world laws active.' if getattr(args, 'timeline', None) else 'Standalone conditioning: no timeline or universe laws. Use the scoped command for an episode.', file=sys.stderr)
    if args.apply:
        if not args.review_store or not args.review_request:
            print("condition --apply requires --review-store and --review-request; preview and review the edit first.",
                  file=sys.stderr)
            return 2
        return cmd_editorial(argparse.Namespace(
            store=args.review_store, request=args.review_request, apply_source=args.file,
        ))
    if not args.out:
        print("condition requires --out for proposal artifacts", file=sys.stderr)
        return 2
    try:
        provider_kwargs = {}
        if args.provider == "edits":
            provider_kwargs["edits_path"] = args.edits
        if getattr(args, "max_tokens", None):
            provider_kwargs["max_new_tokens"] = args.max_tokens
        if args.provider == "local":
            if getattr(args, "steer", None):
                provider_kwargs["steer_path"] = args.steer
            if getattr(args, "alpha", None):
                provider_kwargs["steer_alpha"] = args.alpha
            if getattr(args, "ban_comparisons", False):
                provider_kwargs["ban_comparisons"] = True
        provider = create_prose_provider(
            args.provider,
            model_name=args.model,
            **provider_kwargs,
        )
    except ProviderConfigurationError as exc:
        print(f"provider configuration error: {exc}", file=sys.stderr)
        return 2

    profile = _profile(args)
    drive = None
    if args.references and getattr(args, "retrieval", "none") != "none" and not getattr(args, "allow_book_references", False):
        print("references: disabled (pass --allow-book-references to inject book passages)")
        args.retrieval = "none"
    if args.references and getattr(args, "retrieval", "none") != "none":
        from .reference_service import prepare_retrieval
        setup = prepare_retrieval(args.books, args.retrieval, args.provider, profile_id=profile.profile_id)
        print(f"retrieval: {setup.state}: {setup.message}")
        if setup.state != "ready":
            return 2
        drive = setup.drive

    frozen = list(getattr(args, "freeze", []) or [])
    freeze_file = getattr(args, "freeze_file", None)
    if freeze_file:
        frozen += [line.strip() for line in Path(freeze_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    if getattr(args, "freeze_dialogue", False):
        source = Path(args.file).read_text(encoding="utf-8")
        frozen += dialogue_lines(source.split("\n\n"))
    strength_map = (
        StrengthMap.load(args.strength_map) if getattr(args, "strength_map", None) else None
    )
    extra_context = ""
    brief = SceneBrief.load(args.brief) if getattr(args, "brief", None) else None
    if brief is not None:
        frozen += brief.frozen()
        extra_context = brief.prompt_block()
        if args.strength == "standard":
            args.strength = strength_policy(brief.strength).preset
    world = None
    house = None
    try:
        world = WorldState.load(args.world_file)
        extra_context = (extra_context + "\n\n" + world.prompt_block()).strip()
    except Exception:
        world = None
    try:
        house = House.load(args.house)
        extra_context = (extra_context + "\n\n" + house.map_block(cad=False)).strip()
    except Exception:
        house = None
    result = run_conditioning(
        args.file,
        args.out,
        provider=provider,
        profile=profile,
        drive=drive,
        apply=args.apply,
        limit=args.limit,
        title=args.title,
        strength=getattr(args, "strength", "standard"),
        influence=load_influence(args.books),
        strength_map=strength_map,
        frozen=tuple(frozen),
        extra_context=extra_context,
        world=world,
        house=house,
        allow_dialogue=getattr(args, "allow_dialogue", False),
        books_dir=args.books,
        contrastive=getattr(args, "contrastive", False)
        or getattr(args, "strength", "standard") == "rebuild",
    )
    print(f"provider:  {args.provider} ({provider.model_name})")
    print(f"profile:   {result.get(chr(112)+chr(114)+chr(111)+chr(102)+chr(105)+chr(108)+chr(101), profile.profile_id)}")
    print(f"strength:  {result.get('strength', 'standard')}")
    print(f"flagged:   {result['flagged']}   accepted: {result['accepted']}   applied: {result['applied']}")
    if args.references:
        print(f"references: {result.get('references', 0)} eligible passages; up to {args.references} per paragraph")
    if result.get("voice_before"):
        print(f"voice:     {result['voice_before']:.3f} -> {result['voice_after']:.3f} (corpus similarity)")
    print(f"before:    {result['before']}")
    if result.get("after"):
        print(f"after:     {result['after']}")
    for name, path in result["artifacts"].items():
        print(f"{name + ':':<11} {path}")
    checks = result.get("document_checks") or []
    from .scoped_service import resolve_default_timeline, record_standalone_draft
    effective_tl = resolve_default_timeline(getattr(args, "timeline", None))
    if effective_tl and result.get("after"):
        law_check = check_namespace_world_laws(Path(result["after"]).read_text(encoding="utf-8"), args)
        if not law_check["passed"]:
            print("universe world-law violations:")
            for violation in law_check["violations"]:
                print("  !", violation)
            for check in checks:
                print("  !", check)
            return 1
    source_text = Path(args.file).read_text(encoding="utf-8")
    conditioned_path = result["artifacts"].get("conditioned")
    candidate_text = Path(conditioned_path).read_text(encoding="utf-8") if conditioned_path else source_text
    record_standalone_draft(
        candidate_text,
        original_text=source_text,
        source_path=args.file,
        route="condition",
        provider_name=args.provider,
        timeline_path=getattr(args, "timeline", None),
        project_id=getattr(args, "project", None),
        universe_id=getattr(args, "universe", None),
        episode=getattr(args, "episode", None),
        branch=getattr(args, "branch", "main") or "main",
        beat=getattr(args, "beat", 0) or 0,
        out_dir=args.out,
        issues=checks,
        extra={"flagged": result["flagged"], "accepted": result["accepted"], "applied": result["applied"]},
    )
    if checks:
        print("document checks:")
        for check in checks:
            print("  !", check)
    return 0


def cmd_preferences(args: argparse.Namespace) -> int:
    patterns = args.proposals or ["work/**/proposals.json"]
    rows = load_proposals(patterns)
    if not rows:
        print("no proposals found")
        return 1
    summary = summarize(rows)
    print(
        f"decisions: {summary['total']} "
        f"({summary['accepted']} accepted, {summary['rejected']} rejected)"
    )
    for key in (
        "accepted_overlap_mean",
        "accepted_overlap_max",
        "accepted_ratio_range",
        "rejected_overlap_min",
    ):
        if key in summary:
            print(f"  {key}: {summary[key]}")
    if summary.get("rejection_reasons"):
        print("  rejection reasons:")
        for reason, count in summary["rejection_reasons"].items():
            print(f"    {count:>3}  {reason}")
    suggestion = suggest(summary)
    if suggestion:
        print(f"suggested preset: {json.dumps(suggestion)}")
    return 0


def cmd_voice(args: argparse.Namespace) -> int:
    if args.voice_command == "report":
        result = voice_report(args.ledger)
        print(json.dumps(result, indent=2))
        return 0

    text = Path(args.file).read_text(encoding="utf-8")
    if args.voice_command == "tics":
        findings = tic_scan(text)
        for finding in findings:
            print(f"{finding.severity:<8} {finding.rule:<22} {finding.excerpt[:70]}")
        print(json.dumps(tic_counts(text), indent=2))
        return 0

    evaluator = Evaluator(books=args.books)
    similarity = evaluator.similarity(text)
    print(f"similarity: {similarity:.4f}")
    print(f"percentile: {evaluator.percentile(text):.3f}")
    print(json.dumps(tic_counts(text), indent=2))
    return 0


def cmd_voice_ledger(args: argparse.Namespace) -> int:
    plan = BeatPlan.load(args.notes)
    text = Path(args.file).read_text(encoding="utf-8")
    parts = scene_sections(text)
    result = plan.validate(parts)
    for row in result["states"]:
        print(f"[{row['beat']}] {', '.join(row['state'])}")
    print(f"issues: {len(result['issues'])}")
    for issue in result["issues"]:
        print("  !", issue)
    return 0


def cmd_voice_spatial(args: argparse.Namespace) -> int:
    from .conditioner import paragraph_spans

    house = House.load(args.house)
    text = Path(args.file).read_text(encoding="utf-8")
    chunks = [text[start:end].strip() for start, end in paragraph_spans(text)]
    found = []
    for chunk in chunks:
        room = house.find(chunk)
        if room is not None:
            found.append(room)
    print("rooms found:")
    for room in found:
        print(f"  - {room.describe()}")
    issues = house.check_scene(chunks)
    print(f"staging issues: {len(issues)}")
    for issue in issues:
        print("  !", issue)
    return 0


def cmd_voice_world(args: argparse.Namespace) -> int:
    from .conditioner import paragraph_spans

    state = WorldState.load(args.world_file)
    text = Path(args.file).read_text(encoding="utf-8")
    total = 0
    for index, (start, end) in enumerate(paragraph_spans(text)):
        core = text[start:end].strip()
        found = state.violations(core) + state.plausibility(core)
        if not found:
            continue
        total += len(found)
        print(f"¶{index + 1}: {core[:90]}")
        for phrase, why in found:
            print(f"   '{phrase}' — {why}")
    print(f"canon violations: {total}")
    if getattr(args, "timeline", None):
        law_check = check_namespace_world_laws(text, args)
        for violation in law_check["violations"]:
            print(f"   universe world law — {violation}")
        print(f"universe world-law violations: {len(law_check['violations'])}")
        if not law_check["passed"]:
            return 1
    return 0


def cmd_voice_slop(args: argparse.Namespace) -> int:
    from .conditioner import is_dialogue, paragraph_spans
    from .voice.slop import flag

    text = Path(args.file).read_text(encoding="utf-8")
    total = 0
    for index, (start, end) in enumerate(paragraph_spans(text)):
        core = text[start:end].strip()
        if len(core.split()) < getattr(args, "min_words", 8) or is_dialogue(core):
            continue
        if core.lstrip().startswith(("[", "]", "#")):
            continue
        spans = flag(core)
        if not spans:
            continue
        total += len(spans)
        print(f"¶{index + 1}  {core[:70]}")
        for span in spans:
            print(f"   [{span.rule}] {span.text[:50]!r} — {span.why}")
    print(f"flagged spans: {total} (rule-based; no score — see docs/RETRACTIONS.md)")
    return 0


def cmd_voice_vary(args: argparse.Namespace) -> int:
    print('Timeline universe world laws active.' if getattr(args, 'timeline', None) else 'Standalone variations: no timeline or universe laws. Use the scoped command for an episode.', file=sys.stderr)
    from .voice.vary import run

    provider = create_prose_provider(
        args.provider, edits_path=getattr(args, "edits", None), model_name=getattr(args, "model", None)
    )
    report = run(
        provider, args.file, args.para, args.direction,
        n=args.n, draws=args.draws, out=args.out,
    )
    if getattr(args, "timeline", None):
        for take in report["takes"]:
            if take["chosen"]:
                law_check = check_namespace_world_laws(take["text"], args)
                if not law_check["passed"]:
                    take["chosen"] = False
                    take["issues"].extend("breaks world law: " + v for v in law_check["violations"])
        report["survivors"] = sum(1 for take in report["takes"] if take["chosen"])
    print(f"generated {report['generated']} | survivors {report['survivors']}")
    for take in report["takes"]:
        if take["chosen"]:
            print(f"[{take['treatment']}] {take['text']}")
        elif take["issues"]:
            print(f"[{take['treatment']}] rejected: {'; '.join(take['issues'][:2])}")
    return 0


def cmd_voice_appearance(args: argparse.Namespace) -> int:
    if args.appearance_command == "show":
        appearance = Appearance.load(args.file)
        print(appearance.prompt_block())
        print()
        print(f"image: {appearance.image or 'none'} ({appearance.image_sha256[:12] or 'unhashed'})")
        return 0

    if args.appearance_command == "check":
        path = Path(args.appearance)
        bible = AppearanceBible.load_dir(path) if path.is_dir() else AppearanceBible({Appearance.load(path).entity: Appearance.load(path)})
        text = Path(args.text_file).read_text(encoding="utf-8")
        violations = bible.check(text)
        print(f"violations: {len(violations)}")
        for violation in violations:
            print(f"  - {violation}")
        return 0 if not violations else 1

    return 1


def cmd_voice_rewrite(args: argparse.Namespace) -> int:
    print('Timeline universe world laws active.' if getattr(args, 'timeline', None) else 'Standalone rewrite: no timeline or universe laws. Use the scoped command for an episode.', file=sys.stderr)
    from .models import ProseRewriteRequest, SpanCategory
    from .strength import get as get_strength
    from .styleprint import load_model as load_style_model

    provider_kwargs = {}
    if getattr(args, "steer", None):
        provider_kwargs["steer_path"] = args.steer
    if getattr(args, "alpha", None):
        provider_kwargs["steer_alpha"] = args.alpha
    if getattr(args, "ban_comparisons", False):
        provider_kwargs["ban_comparisons"] = True
    provider = create_prose_provider(
        args.provider,
        model_name=args.model,
        edits_path=getattr(args, "edits", None),
        **provider_kwargs,
    )
    evaluator = Evaluator(books=args.books)
    style_model = load_style_model(args.books)
    contract = Contract.load(args.scene) if args.scene else None
    appearance_bible = None
    if getattr(args, "appearance", None):
        appearance_path = Path(args.appearance)
        appearance_bible = (
            AppearanceBible.load_dir(appearance_path)
            if appearance_path.is_dir()
            else AppearanceBible({Appearance.load(appearance_path).entity: Appearance.load(appearance_path)})
        )
    bible = Bible.load(args.bible) if args.bible else None
    ledger = Ledger.load(args.ledger) if args.ledger else None
    text = Path(args.file).read_text(encoding="utf-8").strip()

    request = ProseRewriteRequest(
        request_id="voice", project_id="prose_engine", document_id="document",
        base_revision=1, target_span_id="paragraph", original_text=text,
        category=SpanCategory.GENERAL,
    )
    blocks = [get_strength(args.strength).directive]
    if appearance_bible is not None:
        blocks.append(appearance_bible.prompt_block())
    for block in (contract.prompt_block() if contract else "", bible.prompt_block() if bible else "",
                  ledger.prompt_block(contract.pov) if ledger and contract and contract.pov else ""):
        if block:
            blocks.append(block)
    prompt = "\n\n".join(blocks)

    pipeline = Pipeline(provider, evaluator, style_model, candidates=args.candidates)
    result = pipeline.rewrite(
        text, prompt, request, contract=contract, bible=bible, ledger=ledger,
        pov=contract.pov if contract else "", scene=Path(args.file).stem,
        max_overlap=0.45,
    )
    if appearance_bible is not None and result.text:
        violations = appearance_bible.check(result.text)
        if violations:
            result.accepted = False
            result.reason = "appearance: " + "; ".join(violations[:3])
    if getattr(args, "timeline", None) and result.text:
        law_check = check_namespace_world_laws(result.text, args)
        if not law_check["passed"]:
            result.accepted = False
            result.reason = "world law: " + "; ".join(law_check["violations"][:3])
    from .scoped_service import record_standalone_draft
    record_standalone_draft(
        result.text or text,
        original_text=text,
        source_path=args.file,
        route="voice.rewrite",
        provider_name=args.provider,
        timeline_path=getattr(args, "timeline", None),
        project_id=getattr(args, "project", None),
        universe_id=getattr(args, "universe", None),
        episode=getattr(args, "episode", None),
        branch=getattr(args, "branch", "main") or "main",
        beat=getattr(args, "beat", 0) or 0,
        out_dir=Path(args.out).parent if args.out else None,
        issues=[] if result.accepted else [result.reason],
        extra={"score": result.score, "candidates": result.candidates},
    )
    print(f"accepted: {result.accepted} | {result.reason}")
    print(f"score: {result.score} | candidates: {result.candidates} | overlap: {result.overlap:.2f}")
    if result.issues:
        print("issues: " + ", ".join(result.issues[:8]))
    print()
    print(result.text or text)
    if args.out and result.accepted:
        Path(args.out).write_text(result.text, encoding="utf-8")
        print(f"written: {args.out}")
    return 0


def cmd_tells(args: argparse.Namespace) -> int:
    text = Path(args.file).read_text(encoding="utf-8")
    paragraphs = [part for part in text.split("\n\n") if part.strip()]
    tells = analyze_document(paragraphs)
    if args.json:
        print(json.dumps([tell.to_dict() for tell in tells], indent=2))
        return 0
    summary = summarize_tells(tells)
    print(f"{summary['total']} document tells ({summary['warnings']} warnings) in {args.file}")
    for tell in tells:
        preview = paragraphs[tell.index][:70].replace("\n", " ") if tell.index < len(paragraphs) else ""
        print(f"  {tell.severity.upper():<7} {tell.rule:<18} para {tell.index:<4} {tell.message}")
        if preview:
            print(f"          {preview}")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    print("mock              offline, deliberately poor prose")
    print("edits             host-written drafts from a JSON file")
    print("local             Qwen3.5-9B 4-bit (optional local extra)")
    print("deepseek          API key + call/token budget")
    print("deepseek-session  injected session handler, no stored credentials")
    print("codex-session     host-injected Codex session handler")
    print("gemini-session    host-injected Gemini session handler")
    print("experimental providers (venice, gemini) live under experimental/providers/")
    return 0


def cmd_editorial(args: argparse.Namespace) -> int:
    import sqlite3
    from .editorial_adapter import dispatch
    from .editorial_revisions import RevisionStore

    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        apply_source = getattr(args, "apply_source", None)
        if apply_source is not None:
            if request.get("action") != "apply":
                raise ValueError("condition --apply requires an apply request")
            if RevisionStore(args.store).at(0)[0] != Path(apply_source).read_bytes().decode("utf-8"):
                raise ValueError("source file does not match the revision store's original text")
        if request.get("action") == "init":
            source = Path(request["source"]).read_bytes().decode("utf-8")
            if "frozen" not in request and "frozen_texts" not in request:
                raise ValueError("explicit protected ranges are required")
            frozen = [tuple(x) for x in request.get("frozen", [])]
            for value in request.get("frozen_texts", []):
                if not isinstance(value, str) or not value or source.count(value) != 1:
                    raise ValueError("each protected passage must occur exactly once")
                start = source.index(value)
                frozen.append((start, start + len(value)))
            if not frozen and request.get("allow_unlocked") is not True:
                raise ValueError("provide protected passages or explicitly set allow_unlocked")
            RevisionStore.create(args.store, source, tuple(frozen))
            result = {"status": "CREATED", "revision": 0}
        else:
            result = dispatch(RevisionStore(args.store), WorldState.load(), request)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_scoped(args: argparse.Namespace) -> int:
    """Use only episode-scoped stored sources; legacy corpus inputs are excluded."""
    import sqlite3
    from story_graph.episode_timeline import TimelineStore
    from .scoped_service import execute_scoped
    from .scoped_references import ReferenceUnavailable
    from .providers.deepseek import BudgetExceeded
    from .providers.session_attempts import SessionAttemptError
    try:
        path = Path(args.timeline)
        if not path.is_file(): raise ValueError("Timeline store does not exist")
        configured_forms = getattr(args, "form_store", None)
        store = TimelineStore(path, project_id=args.project, universe_id=args.universe,
                              form_graph_path=configured_forms)
        form_store_path = store.form_graph_path
        if configured_forms and not form_store_path.is_file():
            raise ValueError("Form graph store does not exist")
        junctions_supplier = None
        if form_store_path.is_file():
            from story_graph.form_graph_store import FormGraphStore
            from story_graph.source_imports import junctions as imported_junctions

            def junctions_supplier():
                if store.scope()["kind"] != "afm-starters":
                    return {}
                with store._connect() as c:
                    imp = imported_junctions(c, {})
                return FormGraphStore(form_store_path, imported=imp).junctions()
        legacy = None
        if args.spring_source:
            protected = Path(__file__).resolve().parents[1] / "work/americandad/foxy_mo2_hybrid_novel.md"
            if args.episode != "spring-break" or Path(args.spring_source).resolve() != protected.resolve():
                raise ValueError("Spring source must be the protected project manuscript")
            legacy = lambda: protected.read_text(encoding="utf-8")
        protected_ranges = json.loads(args.protected_ranges)
        req={'episode':args.episode,'beat':args.beat,'revision':args.revision,'start':args.start,'end':args.end,
             'viewpoint':args.viewpoint,'project':args.project,'universe':args.universe,'branch':args.branch,
             'law_revision':args.law_revision,'protected_ranges':protected_ranges,'query':args.query,
             'claims':json.loads(args.claims),'provider':args.provider,
             'draft':args.draft,'notebook_revision':args.notebook_revision,
             'references':args.references,'reference_delivery':getattr(args,'reference_delivery','excerpt'),
             'scene_function':args.scene_function,'request_id':args.request_id}
        result=execute_scoped(store,args.action,req,junctions=junctions_supplier,legacy_source=legacy,books_root=args.books)
        # JSON escapes keep the command portable when Windows stdout uses a
        # legacy code page but a caller decodes its output as UTF-8.
        print(json.dumps(result,ensure_ascii=True))
        return 0 if result.get("status") != "BLOCKED" else 1
    except SessionAttemptError as exc:
        print(json.dumps({"error":str(exc),"state":exc.state,"attempt_id":exc.attempt_id}),file=sys.stderr)
        return 1
    except ReferenceUnavailable as exc:
        print(json.dumps({"error":str(exc),"state":exc.state},ensure_ascii=True),file=sys.stderr)
        return 1
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,BudgetExceeded) as exc:
        print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr)
        return 1


def cmd_episode(args) -> int:
    """Run the same versioned episode commands as the timeline workspace."""
    import sqlite3
    from contextlib import nullcontext
    from story_graph.episode_timeline import TimelineStore
    from story_graph.form_graph_store import FormGraphStore
    from story_graph.source_imports import junctions as imported_junctions
    from .episode_commands import EpisodeCommands
    from story_graph.scene_fragments import SceneFragmentError
    try:
        path=Path(args.timeline)
        if not path.is_file():
            raise ValueError('Timeline store does not exist')
        from .intake import MAX_REQUEST
        limit=MAX_REQUEST if args.action in ('intake.preview','intake.create','episode.create') else (
            1_400_000 if args.action=='timeline.cover.set' else 100_000)
        with (Path(args.request).open('rb') if args.request!='-' else nullcontext(sys.stdin.buffer)) as stream:
            raw=stream.read(limit+1)
        if len(raw)>limit:
            raise ValueError('Episode request is too large')
        request=json.loads(raw)
        timeline=TimelineStore(path, form_graph_path=args.form_store)
        form_path=timeline.form_graph_path
        if args.form_store and not form_path.is_file() and args.action not in ('episode.prepare', 'episode.preparation.open'):
            raise ValueError('Form graph store does not exist')
        graph=None
        supplier=None
        if form_path.is_file() and timeline.scope()['kind']=='afm-starters':
            def open_graph():
                with timeline._connect() as c:
                    imported=imported_junctions(c,{})
                return FormGraphStore(form_path,imported=imported)
            graph=open_graph()
            supplier=lambda:open_graph().junctions()
        result=EpisodeCommands(timeline,junctions=supplier,form_graph=graph,
                               books_root=Path(args.books) if args.books else None).execute(args.action,request)
        print(json.dumps(result,ensure_ascii=True))
        return int(result.get('status') in ('UNKNOWN','PARTIAL','STALE'))
    except SceneFragmentError as exc:
        print(json.dumps({'error':str(exc),'code':exc.code},ensure_ascii=True),file=sys.stderr)
        return 1
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=True),file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    from .timeline_commands import ACTIONS as timeline_actions
    from story_graph.scene_fragments import COMMANDS as fragment_actions
    from story_graph.scene_override import COMMANDS as override_actions
    from .replay_minds import COMMANDS as mind_actions
    from .scene_clips import COMMANDS as clip_actions
    from .branch_continuations import COMMANDS as branch_actions
    from .scene_bridges import COMMANDS as bridge_actions
    from .scene_plan_inputs import COMMANDS as plan_inputs_actions
    from .story_timeline import COMMAND as story_timeline_action
    from .mind_inspection import COMMAND as mind_inspection_action
    from .processing import COMMANDS as processing_actions
    from .media_graph import COMMANDS as media_actions
    from .evidence_exchange import COMMANDS as exchange_actions

    parser = argparse.ArgumentParser(prog="prose_engine", description="Standalone prose conditioning engine")
    parser.add_argument("--version", action="version", version="prose_engine 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)
    episode=sub.add_parser('episode',help='inspect direction, run writing and edit a saved timeline')
    episode.add_argument('action',choices=['intake.preview','intake.create','intake.receipt','intake.source','episode.create','episode.prepare','episode.preparation.open','director.open','director.preview','run.start','run.selection','run.selection.preview','run.status','run.latest',
        'run.cancel','run.resume','draft.open','draft.list','draft.compare','draft.apply','notebook.undo','notebook.redo',
        'graph.history','graph.undo','graph.redo','graph.cook', *sorted(timeline_actions), *sorted(fragment_actions),
        *sorted(override_actions), *sorted(mind_actions), *sorted(clip_actions), *sorted(branch_actions),
        *sorted(exchange_actions), *sorted(bridge_actions), story_timeline_action, mind_inspection_action, 'scene.plan.open',
        *sorted(processing_actions), *sorted(media_actions), *sorted(plan_inputs_actions)])
    episode.add_argument('--timeline',required=True)
    episode.add_argument('--form-store')
    episode.add_argument('--books')
    episode.add_argument('--request',required=True,help="UTF-8 JSON file or '-' for standard input")
    episode.set_defaults(func=cmd_episode)
    scoped = sub.add_parser("scoped", help="timeline-scoped generation, retrieval, validation and export")
    scoped.add_argument("action", choices=["context","retrieve","validate","export","generate","condition","variant","apply-draft"])
    scoped.add_argument("--timeline", required=True)
    scoped.add_argument("--project", help="Expected project ID")
    scoped.add_argument("--universe", help="Expected universe ID (supply with --project)")
    scoped.add_argument("--branch", help="Expected episode branch")
    scoped.add_argument("--law-revision", type=int, help="Expected world-law revision")
    scoped.add_argument("--episode", required=True)
    scoped.add_argument("--beat", type=int, required=True)
    scoped.add_argument("--revision", type=int, required=True)
    scoped.add_argument("--start", type=int, required=True)
    scoped.add_argument("--end", type=int, required=True)
    scoped.add_argument("--viewpoint")
    scoped.add_argument("--form-store", help="Character form graph SQLite store; defaults to sibling character-forms.sqlite when present")
    scoped.add_argument("--spring-source", help="Protected Spring Break source for an empty starter card")
    scoped.add_argument("--query", default="")
    scoped.add_argument("--claims", default="[]")
    scoped.add_argument("--protected-ranges", default="[]", help="JSON list of absolute [start, end] code-point ranges")
    from .providers.session_registry import session_names
    scoped.add_argument("--provider", choices=session_names(), default="codex-session")
    scoped.add_argument("--books", help="Book library directory; defaults to this project's library")
    scoped.add_argument("--references", choices=["none","topic","luar","style"], default="none")
    scoped.add_argument("--reference-delivery", choices=["cadence","excerpt"], default="excerpt")
    scoped.add_argument("--scene-function", choices=["scene","beauty","comedy","tension","dialogue","quiet","transformation"], default="scene")
    scoped.add_argument("--draft", help="Existing scoped draft ID for apply-draft")
    scoped.add_argument("--notebook-revision", type=int, help="Expected notebook revision for apply-draft")
    scoped.add_argument("--request-id", help="Stable ID to replay a selection or edit without repeating it")
    scoped.set_defaults(func=cmd_scoped)

    from .providers.session_attempts import inspect_attempts
    from .providers.primary_session import DEFAULT_SESSION_LEDGER
    attempts = sub.add_parser("session-attempts", help="Inspect or reconcile local provider attempts")
    attempts.add_argument("--ledger", default=str(DEFAULT_SESSION_LEDGER))
    attempts.add_argument("--attempt")
    attempts.add_argument("--state", choices=["remote_unknown","cancel_requested","cancelled","completed","failed"])
    attempts.add_argument("--checked", action="store_true", help="Confirm you checked the worker and provider outcome")
    attempts.set_defaults(func=inspect_attempts)

    editorial = sub.add_parser("editorial", help="reviewed revision store operations")
    editorial.add_argument("--store", required=True)
    editorial.add_argument("--request", required=True, help="JSON file with state, preview, apply, undo or redo request")
    editorial.set_defaults(func=cmd_editorial)

    books = sub.add_parser("books", help="List the reference corpus")
    books.add_argument("--books", default="books")
    books.set_defaults(func=cmd_books)

    influence = sub.add_parser("influence", help="Per-book influence on retrieved references")
    influence_sub = influence.add_subparsers(dest="influence_command", required=True)

    influence_show = influence_sub.add_parser("show", help="Show levels and mode")
    influence_show.add_argument("--books", default="books")
    influence_show.set_defaults(func=cmd_influence)

    influence_set = influence_sub.add_parser("set", help="Set one book's level (0-4 or name)")
    influence_set.add_argument("book")
    influence_set.add_argument("level")
    influence_set.add_argument("--books", default="books")
    influence_set.set_defaults(func=cmd_influence)

    influence_mode = influence_sub.add_parser("mode", help="balanced (size-independent) or volume")
    influence_mode.add_argument("mode", choices=["balanced", "volume"])
    influence_mode.add_argument("--books", default="books")
    influence_mode.set_defaults(func=cmd_influence)

    voice = sub.add_parser("voice", help="Voice engine: evaluation, tics, style index")
    voice_sub = voice.add_subparsers(dest="voice_command", required=True)

    voice_eval = voice_sub.add_parser("eval", help="Corpus similarity and tic counts for a file")
    voice_eval.add_argument("--file", required=True)
    voice_eval.add_argument("--books", default="books")
    voice_eval.set_defaults(func=cmd_voice)

    voice_report = voice_sub.add_parser("report", help="Aggregate the decision ledger")
    voice_report.add_argument("--ledger", default="eval/decisions.jsonl")
    voice_report.set_defaults(func=cmd_voice)

    voice_ledger = voice_sub.add_parser("ledger", help="Validate beats and fluents across the scene")
    voice_ledger.add_argument("--file", required=True)
    voice_ledger.add_argument("--notes", default="books/editorial_notes.json")
    voice_ledger.set_defaults(func=cmd_voice_ledger)

    voice_spatial_parser = voice_sub.add_parser("spatial", help="Check staging against the floor plans")
    voice_spatial_parser.add_argument("--file", required=True)
    voice_spatial_parser.add_argument("--house", default="books/ling_house")
    voice_spatial_parser.set_defaults(func=cmd_voice_spatial)

    voice_world = voice_sub.add_parser("world", help="Check text against the world state")
    voice_world.add_argument("--file", required=True)
    voice_world.add_argument("--world-file", default="books/world_state.json")
    add_timeline_law_args(voice_world)
    voice_world.set_defaults(func=cmd_voice_world)

    voice_vary = voice_sub.add_parser("vary", help="Distinct gated takes for one directed paragraph")
    voice_vary.add_argument("--file", required=True)
    voice_vary.add_argument("--para", type=int, required=True)
    voice_vary.add_argument("--direction", required=True)
    voice_vary.add_argument("--n", type=int, default=3)
    voice_vary.add_argument("--draws", type=int, default=2)
    voice_vary.add_argument("--provider", default="edits")
    voice_vary.add_argument("--edits", default=None)
    voice_vary.add_argument("--model", default=None)
    voice_vary.add_argument("--out", default=None)
    add_timeline_law_args(voice_vary)
    voice_vary.set_defaults(func=cmd_voice_vary)

    voice_slop = voice_sub.add_parser("slop", help="Score paragraphs with the AI-slop detector")
    voice_slop.add_argument("--file", required=True)
    voice_slop.add_argument("--threshold", type=float, default=50.0)
    voice_slop.add_argument("--min-words", type=int, default=8)
    voice_slop.add_argument("--model-file", default="books/slop_model.json")
    voice_slop.set_defaults(func=cmd_voice_slop)

    voice_appearance = voice_sub.add_parser("appearance", help="Appearance canon: show or check a schema")
    appearance_sub = voice_appearance.add_subparsers(dest="appearance_command", required=True)
    appearance_show = appearance_sub.add_parser("show")
    appearance_show.add_argument("--file", required=True)
    appearance_show.set_defaults(func=cmd_voice_appearance)
    appearance_check = appearance_sub.add_parser("check")
    appearance_check.add_argument("--text-file", required=True)
    appearance_check.add_argument("--appearance", required=True)
    appearance_check.set_defaults(func=cmd_voice_appearance)

    voice_rewrite = voice_sub.add_parser("rewrite", help="Full pipeline: retrieve, sample, select, critique")
    voice_rewrite.add_argument("--file", required=True)
    voice_rewrite.add_argument("--scene", default=None)
    voice_rewrite.add_argument("--appearance", default=None)
    voice_rewrite.add_argument("--bible", default=None)
    voice_rewrite.add_argument("--ledger", default=None)
    voice_rewrite.add_argument("--provider", default="local")
    voice_rewrite.add_argument("--model", default=None)
    voice_rewrite.add_argument("--edits", default=None)
    voice_rewrite.add_argument("--books", default="books")
    voice_rewrite.add_argument("--strength", default="rebuild")
    voice_rewrite.add_argument("--candidates", type=int, default=4)
    voice_rewrite.add_argument("--steer", default=None)
    voice_rewrite.add_argument("--alpha", type=float, default=0.0)
    voice_rewrite.add_argument("--ban-comparisons", action="store_true")
    voice_rewrite.add_argument("--out", default=None)
    add_timeline_law_args(voice_rewrite)
    voice_rewrite.set_defaults(func=cmd_voice_rewrite)

    voice_tics = voice_sub.add_parser("tics", help="List tic findings for a file")
    voice_tics.add_argument("--file", required=True)
    voice_tics.set_defaults(func=cmd_voice)

    preferences = sub.add_parser(
        "preferences", help="Calibrate thresholds from the engine's accept/reject decisions"
    )
    preferences.add_argument(
        "--proposals", nargs="*", default=None, help="glob(s); default work/**/proposals.json"
    )
    preferences.set_defaults(func=cmd_preferences)

    corpus = sub.add_parser("corpus", help="Corpus measurements and derived profiles")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)

    index = corpus_sub.add_parser("index", help="Measure the corpus")
    index.add_argument("--books", default="books")
    index.add_argument("--out", default=None)
    index.set_defaults(func=cmd_index)

    profile = corpus_sub.add_parser("profile", help="Derive a style profile from the corpus")
    profile.add_argument("--books", default="books")
    profile.add_argument("--base", default="standard_dramatic")
    profile.add_argument("--id", default="corpus")
    profile.add_argument("--name", default="House Corpus")
    profile.add_argument("--out", default=None)
    profile.set_defaults(func=cmd_profile)

    vectors = corpus_sub.add_parser("vectors", help="Build the vector index over the books")
    vectors.add_argument("--books", default="books")
    vectors.add_argument("--out", default=None)
    vectors.add_argument("--dim", type=int, default=256)
    vectors.add_argument("--backend", choices=("transformer", "lsa"), default="transformer")
    vectors.add_argument("--model", default=DEFAULT_MODEL)
    vectors.set_defaults(func=cmd_vectors)

    passages = corpus_sub.add_parser("passages", help="Select reference passages")
    passages.add_argument("--books", default="books")
    passages.add_argument("--id", default="corpus")
    passages.add_argument("--count", type=int, default=8)
    passages.add_argument("--out", default=None)
    passages.set_defaults(func=cmd_passages)

    generate = sub.add_parser("generate-variants", help="Generate candidates with a local model")
    generate.add_argument("--file", required=True)
    generate.add_argument("--out", required=True)
    generate.add_argument("--provider", default="local")
    generate.add_argument("--model", default=None)
    generate.add_argument("--books", default="books")
    generate.add_argument("--count", type=int, default=1)
    generate.add_argument("--strategies", default="image,action,understatement,rhythm")
    generate.add_argument("--style-guide", default=None)
    generate.add_argument("--references", type=int, default=2)
    generate.add_argument("--allow-book-references", action="store_true",
                          help="enable policy-authorized book excerpts in provider prompts")
    generate.add_argument("--limit", type=int, default=None)
    add_timeline_law_args(generate)
    generate.set_defaults(func=cmd_generate_variants)

    style = sub.add_parser("style", help="Build a style guide from writing samples")
    style_sub = style.add_subparsers(dest="style_command", required=True)
    style_guide = style_sub.add_parser("guide", help="Analyze samples into a guide")
    style_guide.add_argument("--samples", required=True, help="Comma-separated sample files")
    style_guide.add_argument("--out", default=None)
    style_guide.add_argument("--md", default=None)
    style_guide.set_defaults(func=cmd_style)

    variants = sub.add_parser("variants", help="Score rewrite variants against the corpus voice")
    variants.add_argument("--file", required=True)
    variants.add_argument("--books", default="books")
    variants.add_argument("--references", type=int, default=3)
    variants.add_argument("--style-guide", default=None)
    variants.add_argument("--out", required=True)
    variants.set_defaults(func=cmd_variants)

    reference = sub.add_parser("reference", help="Vector-search corpus passages for a draft")
    reference.add_argument("--file", required=True)
    reference.add_argument("--books", default="books")
    reference.add_argument("--paragraph", type=int, default=None)
    reference.add_argument("--flagged", action="store_true")
    reference.add_argument("-k", type=int, default=3)
    reference.set_defaults(func=cmd_reference)

    diagnose = sub.add_parser("diagnose", help="Report flagged paragraphs")
    diagnose.add_argument("--file", required=True)
    diagnose.add_argument("--json", action="store_true")
    diagnose.set_defaults(func=cmd_diagnose)

    condition = sub.add_parser("condition", help="Rewrite flagged paragraphs")
    condition.add_argument("--file", required=True)
    condition.add_argument("--out", help="Output directory for proposal artifacts")
    condition.add_argument("--provider", default="mock")
    condition.add_argument("--model", default=None)
    condition.add_argument("--edits", default=None, help="JSON rewrites for --provider edits")
    condition.add_argument("--style", default="auto", help="auto (corpus profile) or a built-in id")
    condition.add_argument("--profile-file", default=None)
    condition.add_argument("--references", type=int, default=3, help="Corpus passages per paragraph (0 disables)")
    condition.add_argument(
        "--retrieval", choices=("none", "topic", "style", "luar"), default="none",
        help="topic: embedding similarity; style: stylometric similarity",
    )
    condition.add_argument("--books", default="books")
    condition.add_argument("--limit", type=int, default=None)
    condition.add_argument(
        "--max-tokens", type=int, default=None, help="max new tokens for local providers (default 512)"
    )
    condition.add_argument("--apply", action="store_true", help="Commit an explicitly reviewed request")
    condition.add_argument("--review-store", help="Existing revision store for --apply")
    condition.add_argument("--review-request", help="Reviewed apply request JSON for --apply")
    condition.add_argument("--strength-map", default=None, help="JSON per-passage strength map")
    condition.add_argument("--freeze", action="append", default=None, help="exact span that must survive")
    condition.add_argument("--freeze-file", default=None, help="file of frozen spans, one per line")
    condition.add_argument("--brief", default=None, help="scene brief JSON (events + dialogue checkboxes)")
    condition.add_argument("--allow-book-references", action="store_true", help="inject book passages into prompts (off by default)")
    condition.add_argument("--world-file", default="books/world_state.json")
    condition.add_argument("--house", default="books/ling_house")
    condition.add_argument("--allow-dialogue", action="store_true", help="allow dialogue rewrites (frozen by default)")
    condition.add_argument(
        "--strength",
        choices=("light", "standard", "rebuild"),
        default="standard",
        help="light: minimal edit; standard: rewrite in place; rebuild: new writing from the facts",
    )
    condition.add_argument(
        "--contrastive",
        action="store_true",
        help="append AI-voice negative examples that match the paragraph's warnings",
    )
    condition.add_argument("--steer", default=None, help="path to a style_vector.npz")
    condition.add_argument("--alpha", type=float, default=0.0, help="steering strength (0 = off)")
    condition.add_argument(
        "--ban-comparisons", action="store_true", help="ban like/as if/resembling at decode time"
    )
    condition.add_argument("--title", default=None)
    add_timeline_law_args(condition)
    condition.set_defaults(func=cmd_condition)

    tells = sub.add_parser("tells", help="Document-level AI rhythm tells")
    tells.add_argument("--file", required=True)
    tells.add_argument("--json", action="store_true")
    tells.set_defaults(func=cmd_tells)

    providers = sub.add_parser("providers", help="Show provider availability")
    providers.set_defaults(func=cmd_providers)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
