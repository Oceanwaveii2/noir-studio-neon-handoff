"""Freeze a local, blinded author pilot and report only recorded decisions."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import re
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.conditioner import is_dialogue
from prose_engine.editorial_service import Edit, preview, revision
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState
from tools.blind_evaluation import prepare
from tools.eval_decisions import wilson

PARAGRAPH = re.compile(r"\S.*?(?=(?:\r?\n[ \t]*){2,}|\s*\Z)", re.DOTALL)
SCENE = re.compile(r"### SCENE (\d+):")
OPTION_IDS = ("a", "b")
CHOICES = frozenset((*OPTION_IDS, "tie", "reject"))


def manuscript_spans(source: str) -> list[dict]:
    scene = ""
    result = []
    for match in PARAGRAPH.finditer(source):
        paragraph = match.group()
        heading = SCENE.match(paragraph)
        if heading:
            scene = heading[1]
        protected = (not scene or paragraph[0] in "#-*_—" or is_dialogue(paragraph)
                     or any(q in paragraph for q in ('"', "“", "”")))
        result.append({"start": match.start(), "end": match.end(), "scene": scene,
                       "protected": protected, "text": paragraph})
    return result


def freeze(spec: dict, source: str, world: WorldState, house: House) -> tuple[dict, dict, dict]:
    if spec.get("schema_version") != 1 or revision(source) != spec["source_sha256"]:
        raise ValueError("The manuscript does not match the frozen pilot source.")
    spans = manuscript_spans(source)
    frozen = tuple((s["start"], s["end"]) for s in spans if s["protected"])
    scene_parts: dict[str, list[int]] = defaultdict(list)
    for i, span in enumerate(spans):
        scene_parts[span["scene"]].append(i)
    baseline_staging = {
        scene: Counter(house.check_scene([spans[i]["text"] for i in parts]))
        for scene, parts in scene_parts.items()
    }
    cases, gates, provenance = [], [], {}
    seen = set()
    for edit in spec["edits"]:
        index, scene = edit["paragraph"], edit["scene"]
        if type(index) is not int or not 0 <= index < len(spans) or index in seen:
            raise ValueError("Invalid or duplicate pilot passage.")
        seen.add(index)
        span = spans[index]
        if span["scene"] != scene or scene not in spec["scene_split"]:
            raise ValueError(f"Passage {index} no longer matches the frozen scene.")
        old, new = edit["before"], edit["after"]
        original = span["text"]
        if not old or old == new or original.count(old) != 1 or not new.strip():
            raise ValueError(f"Passage {index} needs one exact and distinct edit anchor.")
        start = span["start"] + original.index(old)
        end = start + len(old)
        case_id = f"scene-{scene}:passage-{index}"
        outcome = preview(source, spec["source_sha256"], (Edit(case_id, start, end, old, new),), frozen, world)
        candidate = original.replace(old, new, 1)
        gate = outcome.status
        if gate == "ELIGIBLE_FOR_REVIEW":
            after_scene = [candidate if i == index else spans[i]["text"] for i in scene_parts[scene]]
            if Counter(house.check_scene(after_scene)) - baseline_staging[scene]:
                gate = "BLOCKED_NEW_STAGING_ISSUE"
        gates.append({"case_id": case_id, "scene_id": scene, "split": spec["scene_split"][scene],
                      "result": gate, "baseline_issue_count": len(outcome.baseline_issues)})
        if gate == "ELIGIBLE_FOR_REVIEW":
            cases.append({"id": case_id, "scene_id": scene, "original": original, "candidate": candidate})
            provenance[case_id] = {"paragraph": index, "start": start, "end": end,
                                   "original_sha256": revision(original), "candidate_sha256": revision(candidate)}
    prepared = prepare(cases, spec["scene_split"], spec["seed"])
    held_out = [row for row in prepared["presentation"] if row["split"] == "held_out"]
    scenes = {prepared["key"][row["token"]]["scene_id"] for row in held_out}
    if not 30 <= len(held_out) <= 50 or len(scenes) < 3:
        raise ValueError(f"Need 30–50 eligible held-out passages across at least three scenes; "
                         f"got {len(held_out)} across {len(scenes)}. Gate counts: "
                         f"{dict(Counter(g['result'] for g in gates))}.")
    fingerprint = revision(json.dumps({
        "spec": spec, "pairs": prepared["fingerprint"], "gates": gates,
    }, ensure_ascii=False, sort_keys=True))
    public = {"schema_version": 1, "pilot_id": spec["pilot_id"],
              "fingerprint": fingerprint, "cases": held_out}
    private = {"schema_version": 1, "pilot_id": spec["pilot_id"], "fingerprint": fingerprint,
               "source": spec["source"], "source_sha256": spec["source_sha256"],
               "candidate_provenance": spec["candidate_provenance"],
               "case_key": {
                   row["token"]: {**prepared["key"][row["token"]], "text_a": row["option_a"],
                                  "text_b": row["option_b"],
                                  **provenance[prepared["key"][row["token"]]["case_id"]]}
                   for row in held_out
               }}
    receipt = {
        "pilot_id": spec["pilot_id"], "fingerprint": fingerprint,
        "source": spec["source"], "source_sha256": spec["source_sha256"],
        "candidate_provenance": spec["candidate_provenance"], "scene_split": spec["scene_split"],
        "held_out_count": len(held_out), "held_out_scenes": sorted(scenes),
        "development_count": sum(row["split"] == "development" for row in prepared["presentation"]),
        "automatic_gates": gates, "author_review": "PENDING", "paired_author_rows": 0,
    }
    return public, private, receipt


def edit_distance(before: str, after: str) -> int:
    """Exact character insertions, deletions or substitutions."""
    prior = list(range(len(after) + 1))
    for i, c in enumerate(before, 1):
        row = [i]
        for j, d in enumerate(after, 1):
            row.append(min(row[-1] + 1, prior[j] + 1, prior[j - 1] + (c != d)))
        prior = row
    return prior[-1]


def clustered_interval(values: list[tuple[str, float]], statistic) -> list[float] | None:
    groups = defaultdict(list)
    for scene, value in values:
        groups[scene].append(value)
    if len(groups) < 3:
        return None
    clusters = [groups[scene] for scene in sorted(groups)]
    rng = random.Random(20261108)
    draws = sorted(statistic([value for group in rng.choices(clusters, k=len(clusters)) for value in group])
                   for _ in range(2000))
    return [round(draws[49], 4), round(draws[1949], 4)]


def report(private: dict, review: dict) -> dict:
    if review.get("schema_version") != 1 or review.get("fingerprint") != private["fingerprint"]:
        raise ValueError("These decisions do not belong to this frozen pilot.")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("A named reviewer is required.")
    key = private["case_key"]
    rows = review.get("decisions")
    if not isinstance(rows, list):
        raise ValueError("Expected a list of decisions.")
    seen = set()
    choices = Counter()
    usability = Counter()
    paired_acceptance, paired_effort = [], {"edit_distance": [], "seconds_to_usable": []}
    for row in rows:
        token, choice = row["token"], row["choice"]
        if not isinstance(token, str) or token in seen or token not in key or choice not in CHOICES:
            raise ValueError("Unknown, duplicate or invalid decision.")
        seen.add(token)
        pair = key[token]
        scene = pair["scene_id"]
        preference = pair["option_" + choice] if choice in OPTION_IDS else choice
        choices[{"original": "keep_original", "candidate": "accept"}.get(preference, preference)] += 1
        assessed = {}
        effort: dict[str, dict[str, float]] = defaultdict(dict)
        options = row.get("options", {})
        if not isinstance(options, dict) or set(options) - set(OPTION_IDS):
            raise ValueError("Option assessments must be keyed by a or b.")
        for side, observation in options.items():
            arm = pair["option_" + side]
            usable = observation.get("usable")
            if type(usable) is not bool:
                raise ValueError("An assessed option needs a usable decision.")
            assessed[arm] = usable
            if usable:
                final = observation.get("final_text")
                seconds = observation.get("seconds")
                if final is not None:
                    if not isinstance(final, str) or not final.strip() or len(final) > 10000:
                        raise ValueError("Final text needs 1–10,000 characters.")
                    effort["edit_distance"][arm] = edit_distance(pair["text_" + side], final)
                if seconds is not None:
                    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
                        raise ValueError("Use a finite, nonnegative elapsed time.")
                    effort["seconds_to_usable"][arm] = seconds
        if len(assessed) == 2:
            original, candidate = assessed["original"], assessed["candidate"]
            usability["both" if original and candidate else "original_only" if original else
                      "candidate_only" if candidate else "neither"] += 1
            paired_acceptance.append((scene, int(candidate) - int(original)))
        for metric, arms in effort.items():
            if len(arms) == 2:
                paired_effort[metric].append((scene, arms["original"], arms["candidate"]))

    def mean(values):
        return sum(values) / len(values)

    count = len(rows)
    result = {
        "pilot_id": private["pilot_id"], "fingerprint": private["fingerprint"], "reviewer": reviewer.strip(),
        "status": "complete" if count == len(key) else "partial" if count else "pending",
        "author_preferences": {choice: choices[choice] for choice in ("accept", "keep_original", "tie", "reject")},
        "reviewed": count, "total": len(key), "unreviewed": len(key) - count,
        "candidate_preference_wilson_95_descriptive": wilson(choices["accept"], count),
        "paired_usability": {"denominator": len(paired_acceptance),
                             "counts": {k: usability[k] for k in ("both", "original_only", "candidate_only", "neither")},
                             "candidate_minus_original": mean([v for _, v in paired_acceptance]) if paired_acceptance else None,
                             "scene_bootstrap_95_exploratory": clustered_interval(paired_acceptance, mean)},
        "paired_effort": {},
        "limits": [
            "One named reviewer and one chapter; no promotion or automatic manuscript changes.",
            "Paired metrics use only cases where both options were assessed or measured.",
            "Scene bootstrap is exploratory and omitted with fewer than three measured scenes.",
        ],
    }
    for metric, values in paired_effort.items():
        deltas = [(scene, candidate - original) for scene, original, candidate in values]
        result["paired_effort"][metric] = {
            "denominator": len(values),
            "median_original": median([o for _, o, _ in values]) if values else None,
            "median_candidate": median([c for _, _, c in values]) if values else None,
            "median_paired_change": median([delta for _, delta in deltas]) if deltas else None,
            "scene_bootstrap_95_exploratory": clustered_interval(deltas, median),
        }
    return result


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, obj: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Freeze the pilot into a new directory")
    build.add_argument("--spec", type=Path, default=ROOT / "eval/u5_pilot_spec.json")
    build.add_argument("--out", type=Path, required=True)
    score = sub.add_parser("report", help="Summarize a named review")
    score.add_argument("--key", type=Path, required=True)
    score.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "report":
            print(json.dumps(report(read_json(args.key), read_json(args.decisions)), ensure_ascii=True, indent=2))
            return 0
        spec = read_json(args.spec)
        source = (ROOT / spec["source"]).read_bytes().decode("utf-8")
        public, private, receipt = freeze(spec, source, WorldState.load(), House.load())
        template = (ROOT / "tools/review_pilot.html").read_text(encoding="utf-8")
        embedded = json.dumps(public, ensure_ascii=True).replace("<", "\\u003c")
        (args.out / "review").mkdir(parents=True, exist_ok=False)
        with (args.out / "review/index.html").open("x", encoding="utf-8") as handle:
            handle.write(template.replace("__PILOT_DATA__", embedded))
        write_json(args.out / "pairing-key.json", private)
        receipt["spec_sha256"] = hashlib.sha256(args.spec.read_bytes()).hexdigest()
        write_json(args.out / "receipt.json", receipt)
        print(f"Frozen {receipt['held_out_count']} held-out pairs across {len(receipt['held_out_scenes'])} scenes.")
        print(f"Review file: {args.out / 'review/index.html'}")
        return 0
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
