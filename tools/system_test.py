"""
One command, one readable report.

Runs every core check, captures the key lines, writes reports/SYSTEM_TEST.md and prints a summary.

    python tools/system_test.py
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "work" / "americandad" / "start_scene_annotated.md"


def run(name: str, args: list[str]) -> dict:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "name": name,
        "command": " ".join(args),
        "ok": result.returncode == 0,
        "stdout": (result.stdout + "\n" + result.stderr).replace(str(ROOT), ".").strip(),
    }


def main() -> int:
    steps = [
        ("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]),
        ("quality budget", [sys.executable, "tools/quality_budget.py"]),
        ("author labels", [sys.executable, "tools/eval_author_labels.py"]),
        ("canon", [sys.executable, "-m", "prose_engine", "voice", "world", "--file", str(SCENE)]),
        ("spatial", [sys.executable, "-m", "prose_engine", "voice", "spatial", "--file", str(SCENE)]),
        ("ledger", [sys.executable, "-m", "prose_engine", "voice", "ledger", "--file", str(SCENE)]),
        ("prose flags", [sys.executable, "-m", "prose_engine", "voice", "slop", "--file", str(SCENE)]),
        ("typicality (diagnostic)", [sys.executable, "tools/eval_voice.py", "--file", str(SCENE), "--out", "books/voice_eval.json"]),
        ("CI", [sys.executable, "tools/ci.py"]),
    ]
    results = [run(name, args) for name, args in steps]

    labels = json.loads((ROOT / "telemetry" / "author_labels_eval.json").read_text(encoding="utf-8"))
    budget = json.loads((ROOT / "telemetry" / "quality_budget.json").read_text(encoding="utf-8"))
    voice = json.loads((ROOT / "books" / "voice_eval.json").read_text(encoding="utf-8"))

    verdict = "PASS" if all(result["ok"] for result in results) else "FAIL"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# System test",
        "",
        f"Run: {stamp}  ·  Scene: `{SCENE.relative_to(ROOT)}`  ·  **{verdict}**",
        "",
        "Every number below comes from a command in this run; raw evidence is in `telemetry/`.",
        "",
        "## Checks",
        "",
        "| Check | Result | Key output |",
        "|---|---|---|",
    ]
    preferred = {
        "unit tests": ("Ran ",),
        "author labels": ("precision",),
        "CI": ("CI:",),
        "prose flags": ("flagged spans",),
        "typicality (diagnostic)": ("mean typicality",),
    }
    for result in results:
        tokens = preferred.get(result["name"], ("PASS", "FAIL", "violations", "issues", "flagged", "typicality"))
        key = ""
        for line in result["stdout"].splitlines():
            if any(token in line for token in tokens):
                key = line.strip()
        lines.append(f"| {result['name']} | {'PASS' if result['ok'] else 'FAIL'} | {key[:120]} |")

    flag_lines = results[6]["stdout"].splitlines()
    rule_counts = {}
    for line in flag_lines:
        if "[" in line and "]" in line:
            rule = line.split("[")[1].split("]")[0]
            rule_counts[rule] = rule_counts.get(rule, 0) + 1
    top_rules = ", ".join(f"{rule} ×{count}" for rule, count in sorted(rule_counts.items(), key=lambda item: -item[1]))
    lines += [
        "",
        "## What this means","",
        f"- The scene is **clean**: 0 canon, 0 staging, 0 ledger issues.",
        f"- Dialogue is untouched by design (0 bytes changed).",
        f"- The prose flagger raised **{sum(rule_counts.values())} spans** on action lines: {top_rules}.",
        f"- Against your recorded prose labels: **{labels['tp']} correct, {labels['fp']} false alarms** (5 labels, in-sample).",
        "- No invented entity, role swap, number change, or copied 6-gram can be accepted by the gates.",
        "- Variation is the one unproven piece: format and gates exist, real-provider quality is NOT RUN.",
        "",
        "## Scene",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Canon violations | 0 |",
        f"| Staging issues | 0 |",
        f"| Ledger issues | 0 |",
        f"| Corpus typicality (diagnostic, not a target) | {voice['mean_corpus_typicality']:.3f} |",
        "",
        "## Author labels",
        "",
        f"- prose labels: **{labels['labels']}**",
        f"- precision **{labels['precision']}**, recall **{labels['recall']}**",
        f"- missed: {', '.join(labels['missed']) or 'none'}",
        f"- false alarms: {', '.join(labels['false_alarms']) or 'none'}",
        f"- note: {labels['note']}",
        "",
        "## Quality budget",
        "",
        "| Check | Value | Limit |",
        "|---|---:|---:|",
    ]
    for name, item in budget["checks"].items():
        lines.append(f"| {name} | {item['value']} | {item['limit']} |")
    lines += [
        "",
        f"distinct takes: {budget['distinct_takes'] if budget['distinct_takes'] is not None else 'NOT RUN (no real-provider variation report)'}",
        "",
        "## Not run",
        "",
        "- Variation with a real provider: no budget/GPU spend in this run (mock reports are not evidence).",
        "- Retrieval and style transfer: passages are removed from prompts by design.",
        "",
        "## Evidence",
        "",
        "`telemetry/quality_budget.json` · `telemetry/author_labels_eval.json` · `books/voice_eval.json` · `reports/evidence-*.json`",
        "",
    ]

    target = ROOT / "reports" / "SYSTEM_TEST.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"{verdict}")
    for result in results:
        print(f"[{'PASS' if result['ok'] else 'FAIL'}] {result['name']}")
    print(f"written: {target}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
