"""
Annotated documents: each chunk of text, then a NOTE beneath it. The note is the rewrite
direction for that chunk.

    python tools/annotate.py init --file docs/00_combined.md --out docs/00_combined.annotated.md
    python tools/annotate.py compile --file docs/00_combined.annotated.md
    python tools/annotate.py run --file docs/00_combined.annotated.md --provider edits --edits edits.json

Format:

    ## CHUNK 1 — INT. SMITH HOUSE — MASTER BEDROOM — 7:31 A.M.
    <verbatim text>

    **NOTE:**
    <direction: what the rewrite should do; empty means keep untouched>

Chunks default to scenes (split at INT./EXT. headings). `init --level paragraph` chunks by
blank-line paragraph instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.guards import fact_list, preserves_facts
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider

HEADING = re.compile(r"^(INT|EXT)\.", re.IGNORECASE)
CHUNK = re.compile(r"^## CHUNK (\d+) — (.*)$", re.MULTILINE)
NOTE = "**NOTE:**"


def split_scenes(text: str):
    lines = text.splitlines()
    preamble, chunks, current = [], [], None
    for line in lines:
        if HEADING.match(line.strip()):
            if current is not None:
                chunks.append(current)
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        chunks.append(current)
    return "\n".join(preamble).strip(), ["\n".join(part).strip() for part in chunks]


def split_paragraphs(text: str):
    parts = [part.strip() for part in text.split("\n\n") if part.strip()]
    return "", parts


def init_document(text: str, level: str = "scene") -> str:
    title = next((line for line in text.splitlines() if line.startswith("# ")), "# Document")
    preamble, chunks = split_scenes(text) if level == "scene" else split_paragraphs(text)
    if preamble.startswith("# "):
        preamble = "\n".join(preamble.splitlines()[1:]).strip()
    lines = [title + " — annotated", ""]
    if preamble:
        lines += [preamble, ""]
    for number, chunk in enumerate(chunks, 1):
        label = chunk.splitlines()[0][:80]
        lines += [f"## CHUNK {number} — {label}", "", chunk, "", NOTE, "", "---", ""]
    return "\n".join(lines)


def parse_document(text: str):
    """Returns (title, preamble, [{'index','label','text','note'}])."""
    title = next((line for line in text.splitlines() if line.startswith("# ")), "# Document")
    matches = list(CHUNK.finditer(text))
    preamble = text[: matches[0].start()].strip() if matches else text.strip()
    preamble = "\n".join(line for line in preamble.splitlines()[2:] if line).strip()
    chunks = []
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        if NOTE in body:
            passage, note = body.split(NOTE, 1)
        else:
            passage, note = body, ""
        passage = passage.strip().strip("-\n").strip()
        note = note.strip().strip("-\n").strip()
        chunks.append(
            {"index": int(match.group(1)), "label": match.group(2).strip(), "text": passage, "note": note}
        )
    return title, preamble, chunks


def rewrite_chunk(provider, chunk: dict) -> dict:
    text = chunk["text"]
    if not chunk["note"]:
        return {"index": chunk["index"], "text": text, "changed": False, "issues": []}
    prompt = (
        f"DIRECTION: {chunk['note']}\n\n"
        "MUST KEEP EXACTLY: " + ", ".join(fact_list(text)) + "\n\n"
        "PASSAGE:\n" + text + "\n\n"
        "Rewrite the passage following the direction. Keep every name, number and quoted line. "
        "Stage it; do not summarise. Return only the rewritten passage."
    )
    request = ProseRewriteRequest(
        request_id=f"ann-{chunk['index']}", project_id="annotate", document_id="doc",
        base_revision=1, target_span_id=f"c{chunk['index']}", original_text=text,
        category=SpanCategory.GENERAL,
    )
    try:
        candidate = provider.generate_rewrite(request, prompt).strip()
    except Exception as exc:
        return {"index": chunk["index"], "text": text, "changed": False, "issues": [f"provider error: {exc}"]}
    ok, missing = preserves_facts(text, candidate)
    return {
        "index": chunk["index"],
        "text": candidate or text,
        "changed": bool(candidate),
        "issues": [] if ok else ["drops facts: " + ", ".join(missing[:5])],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--file", required=True)
    init.add_argument("--out", required=True)
    init.add_argument("--level", choices=("scene", "paragraph"), default="scene")
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--file", required=True)
    compile_parser.add_argument("--out", default=None)
    run = sub.add_parser("run")
    run.add_argument("--file", required=True)
    run.add_argument("--out", default="out/annotated")
    run.add_argument("--provider", default="edits")
    run.add_argument("--edits", default=None)
    run.add_argument("--model", default=None)
    args = parser.parse_args()

    if args.command == "init":
        text = Path(args.file).read_text(encoding="utf-8")
        target = Path(args.out)
        target.write_text(init_document(text, args.level), encoding="utf-8")
        print(f"written: {target}")
        return 0

    if args.command == "compile":
        title, preamble, chunks = parse_document(Path(args.file).read_text(encoding="utf-8"))
        print(json.dumps({"title": title, "preamble": preamble, "chunks": chunks}, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps({"title": title, "chunks": chunks}, indent=2), encoding="utf-8")
        return 0

    title, preamble, chunks = parse_document(Path(args.file).read_text(encoding="utf-8"))
    provider = create_prose_provider(args.provider, model_name=args.model, edits_path=args.edits)
    results = [rewrite_chunk(provider, chunk) for chunk in chunks]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(result["text"] for result in results)
    (out / "rewritten.md").write_text(body + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    changed = sum(1 for result in results if result["changed"])
    print(f"chunks: {len(chunks)} | rewritten: {changed} | written: {out/'rewritten.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
