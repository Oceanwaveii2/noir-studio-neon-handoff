"""
S5: variation that is actually varied.

    python -m prose_engine voice vary --file scene.md --para 3 --direction "make it worse for her" --n 3

Five comedic treatments, 2 draws each, every take gated (facts, canon, personification, copy),
then MMR selects distinct takes. No book text enters the prompt (author-voice block only).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from ..conditioner import apply_proposals, is_dialogue, paragraph_spans
from ..guards import fact_list, preserves_facts
from ..models import ProseRewriteRequest, SpanCategory
from .adversarial import check as adversarial_check
from .author_voice import block as author_block
from .distinctness import Take, select, structural
from .editorial import EditorialNotes
from .ledger import BeatPlan
from .spatial import House
from .world_state import WorldState

TREATMENTS = {
    "understatement": "Play it smaller than the situation. The narrator refuses to escalate; the body does.",
    "escalation_by_stages": "Escalate in three clear stages. Each stage costs her a little more dignity.",
    "dignity_loss": "She tries to keep her composure and fails in pieces. Never announce the shame.",
    "overheard_thin_walls": "Someone outside hears everything and says as little as possible.",
    "deadpan_cut": "Cut on the driest possible line. No reaction shot, no explanation.",
}


@dataclass
class Variant:
    treatment: str
    text: str
    issues: List[str] = field(default_factory=list)
    structural: tuple = ()


def build_prompt(original: str, direction: str, treatment: str) -> str:
    notes = EditorialNotes.load()
    plan = BeatPlan.load()
    parts = [
        "DIRECTION: " + direction,
        "TREATMENT: " + TREATMENTS.get(treatment, treatment),
        "MUST KEEP EXACTLY: " + ", ".join(fact_list(original)),
        author_block(original),
    ]
    return "\n\n".join(part for part in parts if part)


def run(provider, file: str | Path, index: int, direction: str, n: int = 3,
        draws: int = 2, out: str | Path | None = None, *, encode=None) -> Dict:
    text = Path(file).read_text(encoding="utf-8")
    spans = paragraph_spans(text)
    if index < 0 or index >= len(spans):
        raise SystemExit(f"paragraph {index} out of range (0-{len(spans)-1})")
    start, end = spans[index]
    original = text[start:end].strip()
    if is_dialogue(original):
        raise SystemExit("that paragraph is dialogue; it is frozen by default")

    world = WorldState.load()
    house = House.load()
    chunks = [text[a:b].strip() for a, b in spans]
    baseline_staging = Counter(house.check_scene(chunks))
    request = ProseRewriteRequest(
        request_id="vary", project_id="vary", document_id=Path(file).name,
        base_revision=1, target_span_id=f"p{index}", original_text=original,
        category=SpanCategory.GENERAL,
    )

    takes: List[Variant] = []
    for treatment in TREATMENTS:
        prompt = build_prompt(original, direction, treatment)
        for _ in range(draws):
            from ..providers.deepseek import BudgetExceeded
            try:
                candidate = (provider.generate_rewrite(request, prompt) or "").strip()
            except BudgetExceeded:
                raise
            except Exception as exc:
                takes.append(Variant(treatment, "", [f"provider error: {exc}"]))
                continue
            issues = adversarial_check(original, candidate, world)
            if candidate:
                proposed = chunks.copy()
                proposed[index] = candidate
                new_staging = Counter(house.check_scene(proposed)) - baseline_staging
                issues.extend(f"staging: {issue}" for issue in new_staging.elements())
            takes.append(Variant(treatment, candidate, issues, structural(candidate)))

    survivors = [take for take in takes if take.text and not take.issues]
    vectors = [None] * len(survivors)
    if encode is not None:
        try:
            vectors = [[float(value) for value in encode(t.text)] for t in survivors]
        except Exception:
            pass  # All candidates use the same lexical fallback.
    selection = [Take(t.text, t.treatment, vector) for t, vector in zip(survivors, vectors)]
    chosen = {id(t) for t in select(selection, n, max_similarity=0.92)}
    chosen_ids = {id(v) for v, t in zip(survivors, selection) if id(t) in chosen}

    report = {
        "file": str(file),
        "provider": getattr(provider, "model_name", "?"),
        "paragraph": index,
        "direction": direction,
        "generated": len(takes),
        "survivors": len(survivors),
        "selected": len(chosen_ids),
        "distinctness": "semantic_with_lexical_guard" if any(v is not None for v in vectors) else "lexical_fallback",
        "takes": [
            {"treatment": take.treatment, "text": take.text, "issues": take.issues,
             "chosen": id(take) in chosen_ids, "structural": list(take.structural)}
            for take in takes
        ],
    }
    if out:
        target = Path(out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
