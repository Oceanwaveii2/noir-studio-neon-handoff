"""
Performance budgets.

Each metric names its fixture, hardware, baseline and budget. A budget is a guardrail, not a
benchmark claim: it catches accidental slowdowns on this machine, nothing more.

    python tools/bench.py
"""

from __future__ import annotations

import datetime as dt
import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prose_engine.conditioner import plan_conditioning  # noqa: E402
from prose_engine.diagnostics import ProseDiagnosticsAnalyzer as D  # noqa: E402
from prose_engine.style_engine import STANDARD_DRAMATIC  # noqa: E402
from prose_engine.style_guide import analyze_samples  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "bench.json"


class EchoProvider:
    """Returns the original text: measures the planner, not a model."""

    model_name = "echo"

    def generate_rewrite(self, request, prompt):  # noqa: ARG002
        return request.original_text


def timed(fn, repeat: int = 1) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(samples), 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true", help="include the local vector model benchmark")
    args = parser.parse_args()
    paragraphs = json.loads(FIXTURE.read_text(encoding="utf-8"))["paragraphs"]
    text = "\n\n".join(paragraphs)

    metrics = []

    def record(name: str, value_ms: float, budget_ms: float, detail: str = "") -> None:
        metrics.append(
            {
                "name": name,
                "value_ms": value_ms,
                "budget_ms": budget_ms,
                "pass": value_ms <= budget_ms,
                "detail": detail,
            }
        )

    record(
        "diagnostics_8_paragraphs",
        timed(lambda: [D.analyze(p) for p in paragraphs], repeat=10),
        150.0,
        f"fixture={FIXTURE.name} n={len(paragraphs)}",
    )
    record(
        "style_guide_build_8_paragraphs",
        timed(lambda: analyze_samples([text]), repeat=5),
        500.0,
        "deterministic analyzer",
    )

    def plan() -> None:
        plan_conditioning(text, EchoProvider(), STANDARD_DRAMATIC)

    record("plan_conditioning_8_paragraphs", timed(plan, repeat=3), 1000.0, "echo provider")

    index_path = ROOT / "books" / "vector_index.joblib"
    model_status = "NOT_RUN"
    if args.models and index_path.is_file():
        try:
            from prose_engine.embedding_store import load_index

            index = load_index(index_path)
            index.query(paragraphs[0], k=1)  # warm the encoder; first call loads the model
            record("vector_query_16", timed(lambda: [index.query(p, k=3) for p in paragraphs], repeat=3), 20000.0, "MiniLM 384d on CPU")
            model_status = "MEASURED"
        except (ImportError, OSError):
            model_status = "UNCONFIGURED"
    elif args.models:
        model_status = "UNCONFIGURED"

    verdict = "UNCONFIGURED" if model_status == "UNCONFIGURED" else (
        "PASS" if all(item["pass"] for item in metrics) else "FAIL"
    )
    receipt = {
        "tool": "prose_engine.bench",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "hardware": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": __import__("os").cpu_count(),
        },
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "metrics": metrics,
        "model_benchmark": model_status,
        "verdict": verdict,
    }

    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = reports / f"bench-{stamp}.json"
    with target.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)

    for item in metrics:
        mark = "ok  " if item["pass"] else "OVER"
        print(f"{mark} {item['name']:<32} {item['value_ms']:>8.2f} ms  budget {item['budget_ms']:.0f}")
    if model_status != "MEASURED":
        print(f"{model_status} vector_query_16")
    print(f"verdict: {verdict} -> {target}")
    return 0 if verdict == "PASS" else (2 if verdict == "UNCONFIGURED" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
