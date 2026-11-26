"""
Quality budget: fail the build when quality regresses.

Checks (all repo-relative, no provider spend):
  - canon / staging / ledger violations on the annotated scene
  - dialogue bytes changed by a mock conditioning pass
  - false accepts in the adversarial invented-entity cases
  - copy detector false accepts on the name-swapped case
  - scene tic rate against the held-out human baseline p90
  - distinct takes, when a variation report exists

    python tools/quality_budget.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.conditioner import (
    apply_proposals,
    is_dialogue,
    paragraph_spans,
    plan_conditioning,
)
from prose_engine.guards import copy_issues
from prose_engine.providers import create_prose_provider
from prose_engine.style_engine import STANDARD_DRAMATIC
from prose_engine.voice.adversarial import check as adversarial_check
from prose_engine.voice.diagnostics_suite import analyze
from prose_engine.voice.ledger import BeatPlan
from prose_engine.voice.recheck import document_issues
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "work" / "americandad" / "start_scene_annotated.md"



def dialogue_bytes_changed(text: str) -> int:
    provider = create_prose_provider("mock")
    proposals = plan_conditioning(text, provider, STANDARD_DRAMATIC)
    updated, _applied = apply_proposals(text, proposals)
    changed = 0
    for start, end in paragraph_spans(text):
        paragraph = text[start:end].strip()
        if is_dialogue(paragraph) and paragraph not in updated:
            changed += len(paragraph.encode("utf-8"))
    return changed


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-file", default=str(ROOT / "ci_budget.json"))
    parser.add_argument("--scene", default=str(SCENE))
    args = parser.parse_args()
    budget = json.loads(Path(args.budget_file).read_text(encoding="utf-8"))
    text = Path(args.scene).read_text(encoding="utf-8")
    world = WorldState.load()
    house = House.load()
    plan = BeatPlan.load()

    issues = document_issues(text, world, house, plan)
    canon = sum(1 for issue in issues if issue.startswith("canon:"))
    staging = sum(1 for issue in issues if issue.startswith("staging:"))
    ledger = sum(1 for issue in issues if issue.startswith("ledger:"))

    dialogue = dialogue_bytes_changed(text)

    fixture = json.loads((ROOT / "tests" / "fixtures" / "guards_adversarial.json").read_text(encoding="utf-8"))
    invented_false = 0
    mutant_false = 0
    clean_false = 0
    for case in fixture["cases"]:
        issues = adversarial_check(case["original"], case["candidate"], world)
        rejected = bool(issues)
        if case["expect_reject"] and not rejected:
            mutant_false += 1
            if case["id"].startswith(("invented_person", "forbidden")):
                invented_false += 1
        elif not case["expect_reject"] and rejected:
            clean_false += 1

    reference = "She picked up her purse and pulled out a five-dollar bill. She turned to Anne."
    swapped = "She picked up her purse and pulled out a five-dollar bill. She turned to Francine."
    copy_false = 0 if copy_issues(swapped, [reference]) else 1

    tic = analyze(text)["findings"]["tic"]["rate_per_1000"]

    distinct = None
    reports = sorted((ROOT / "work" / "variants").glob("*.json")) if (ROOT / "work" / "variants").is_dir() else []
    real = [path for path in reports if not any(x in json.loads(path.read_text(encoding="utf-8")).get("provider", "mock") for x in ("mock", "session", "stub"))]
    if real:
        report = json.loads(real[-1].read_text(encoding="utf-8"))
        distinct = sum(1 for take in report.get("takes", []) if take.get("chosen"))

    checks = {
        "canon_violations": (canon, budget["max_canon_violations"]),
        "staging_violations": (staging, budget["max_staging_violations"]),
        "ledger_violations": (ledger, budget["max_ledger_violations"]),
        "dialogue_bytes_changed": (dialogue, budget["max_dialogue_bytes_changed"]),
        "invented_false_accepts": (invented_false, budget["max_invented_false_accepts"]),
        "copy_false_accepts": (copy_false, budget["max_copy_false_accepts"]),
        "tic_rate_per_1000": (tic, budget["max_tic_rate_per_1000"]),
    }
    failures = [
        f"{name}: {value} > {limit}" for name, (value, limit) in checks.items() if value > limit
    ]
    if distinct is not None and distinct < budget["min_distinct_takes"]:
        failures.append(f"distinct_takes: {distinct} < {budget['min_distinct_takes']}")

    report = {
        "checks": {name: {"value": value, "limit": limit, "pass": value <= limit} for name, (value, limit) in checks.items()},
        "mutant_benchmark": {
            "cases_tested": len(fixture["cases"]),
            "fault_escapes": mutant_false,
            "clean_false_positives": clean_false,
            "recall": round(1.0 - (mutant_false / sum(1 for c in fixture["cases"] if c["expect_reject"])), 3)
        },
        "distinct_takes": distinct,
        "pass": not failures,
        "failures": failures,
    }
    target = ROOT / "telemetry" / "quality_budget.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, item in report["checks"].items():
        print(f"{'ok  ' if item['pass'] else 'OVER'} {name}: {item['value']} (limit {item['limit']})")
    if distinct is None:
        print("NOT RUN distinct_takes: no variation report")
    if failures:
        print("QUALITY BUDGET FAILED:")
        for failure in failures:
            print("  !", failure)
        return 1
    print(f"quality budget: PASS -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
