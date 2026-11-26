"""Run full discovery while explicitly isolating tests requiring local models."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL_MODULES = ("tests.test_coprocessor_reranker", "tests.test_voice_steer")
MODEL_CASES = (
    "tests.test_coprocessor_harness.TestDualEngineHarness.test_hybrid_mode_cuda_coprocessor_activation",
    "tests.test_coprocessor_micro_generator.TestLocalMicroGenerator.test_local_model_dialogue_when_requested",
)
# Tests that read or write shared workspace artifacts under work/ or telemetry/ run together in one serial shard.
SHARED_WORKSPACE_PREFIX = "tests.test_prose_engine_"
SHARED_WORKSPACE_MODULES = frozenset({
    "tests.test_coprocessor_harness",
    "tests.test_s3_dialogue",
    "tests.test_s7_budget",
})


def is_model_case(test_id: str) -> bool:
    """Return True when a test id belongs to a model-dependent module or case."""
    return any(test_id == name or test_id.startswith(name + ".")
               or test_id == "unittest.loader._FailedTest." + name
               for name in MODEL_MODULES) or test_id in MODEL_CASES


def flatten(suite):
    """Yield individual TestCase instances from nested TestSuite objects."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def discover_modules(include_models: bool) -> tuple[list[str], list[str]]:
    """Discover all packaged test modules under tests/, separating omitted model modules."""
    modules, omitted_modules = [], []
    tests_root = ROOT / "tests"
    for path in sorted(tests_root.rglob("test*.py")):
        parent = path.parent
        packaged = True
        while parent != tests_root:
            if not (parent / "__init__.py").is_file():
                packaged = False
                break
            parent = parent.parent
        if not packaged:
            continue
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if not include_models and module in MODEL_MODULES:
            omitted_modules.append(module)
        else:
            modules.append(module)
    return modules, omitted_modules


def _is_shared_workspace_module(module: str) -> bool:
    return module.startswith(SHARED_WORKSPACE_PREFIX) or module in SHARED_WORKSPACE_MODULES


def partition_modules(modules: list[str], workers: int) -> list[list[str]]:
    """Group shared-workspace modules into one serial shard and balance the rest round-robin."""
    serial = [m for m in modules if _is_shared_workspace_module(m)]
    independent = [m for m in modules if not _is_shared_workspace_module(m)]
    if workers <= 1 or not independent:
        return [modules] if modules else []
    shards: list[list[str]] = []
    if serial:
        shards.append(serial)
    ind_workers = max(1, workers - (1 if serial else 0))
    for i in range(min(ind_workers, len(independent))):
        shard = independent[i::min(ind_workers, len(independent))]
        if shard:
            shards.append(shard)
    return shards


def _load_selected(modules: list[str], *, include_models: bool) -> tuple[list[unittest.TestCase], int]:
    """Load tests from module names and exclude declared model cases when offline."""
    discovered = unittest.defaultTestLoader.loadTestsFromNames(modules)
    tests = list(flatten(discovered))
    selected = tests if include_models else [test for test in tests if not is_model_case(test.id())]
    return selected, len(tests) - len(selected)


def _print_model_banner(include_models: bool, omitted_modules: list[str], omitted_cases: int) -> None:
    if include_models:
        print("INCLUDED declared model-dependent modules and case", flush=True)
    else:
        print(f"NOT RUN model-dependent modules/case: {', '.join((*omitted_modules, *MODEL_CASES))}; "
              f"loaded cases omitted: {omitted_cases}", flush=True)


def _run_module_list(modules: list[str], *, include_models: bool, stream=None) -> tuple[unittest.TestResult, int]:
    """Load, filter, and execute tests for a list of module names."""
    selected, omitted = _load_selected(modules, include_models=include_models)
    runner = unittest.TextTestRunner(stream=stream, verbosity=1)
    return runner.run(unittest.TestSuite(selected)), omitted


def _run_worker_subprocess(shard: list[str], *, include_models: bool) -> dict:
    """Execute one shard of test modules in an isolated Python subprocess."""
    cmd = [sys.executable, "-B", __file__, "--worker"]
    if include_models:
        cmd.append("--models")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        input=json.dumps(shard),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {
            "ok": False,
            "ran": 0,
            "omitted": 0,
            "failures": 0,
            "errors": 1,
            "skipped": 0,
            "expected_failures": 0,
            "unexpected_successes": 0,
            "output": f"Worker subprocess failed (rc={proc.returncode}):\n{proc.stdout}\n{proc.stderr}",
        }
    return payload


def _format_failure_details(output: str) -> str:
    """Extract failing tracebacks cleanly without repeating the worker summary footer."""
    start = output.find("\n=======")
    body = output[start + 1:] if start != -1 else output
    footer = body.rfind("\n----------------------------------------------------------------------\nRan ")
    if footer != -1:
        body = body[:footer]
    return body.rstrip()


def _format_failure_summary(failures: int, errors: int, skipped: int, expected: int, unexpected: int) -> str:
    parts = []
    if failures:
        parts.append(f"failures={failures}")
    if errors:
        parts.append(f"errors={errors}")
    if skipped:
        parts.append(f"skipped={skipped}")
    if expected:
        parts.append(f"expected failures={expected}")
    if unexpected:
        parts.append(f"unexpected successes={unexpected}")
    return f"FAILED ({', '.join(parts)})"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true", help="include tests requiring local models")
    parser.add_argument("--workers", type=int, default=None,
                        help="parallel worker count (1 for sequential; defaults to min(6, cpu_count))")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker:
        shard = json.loads(sys.stdin.read())
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            result, omitted = _run_module_list(shard, include_models=args.models, stream=buf)
        print(json.dumps({
            "ok": result.wasSuccessful(),
            "ran": result.testsRun,
            "omitted": omitted,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "expected_failures": len(result.expectedFailures),
            "unexpected_successes": len(result.unexpectedSuccesses),
            "output": buf.getvalue(),
        }))
        return 0 if result.wasSuccessful() else 1

    modules, omitted_modules = discover_modules(args.models)
    workers = args.workers if args.workers is not None else min(6, os.cpu_count() or 2)
    if workers <= 1:
        selected, omitted = _load_selected(modules, include_models=args.models)
        _print_model_banner(args.models, omitted_modules, omitted)
        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(selected))
        return 0 if result.wasSuccessful() else 1

    started = time.perf_counter()
    shards = partition_modules(modules, workers)
    with ThreadPoolExecutor(max_workers=len(shards)) as pool:
        results = list(pool.map(lambda s: _run_worker_subprocess(s, include_models=args.models), shards))
    elapsed = time.perf_counter() - started

    total_omitted = sum(r["omitted"] for r in results)
    total_ran = sum(r["ran"] for r in results)
    total_failures = sum(r["failures"] for r in results)
    total_errors = sum(r["errors"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_expected = sum(r["expected_failures"] for r in results)
    total_unexpected = sum(r["unexpected_successes"] for r in results)
    all_ok = total_ran > 0 and all(r["ok"] for r in results)

    _print_model_banner(args.models, omitted_modules, total_omitted)
    for r in results:
        if not r["ok"]:
            detail = _format_failure_details(r["output"])
            if detail:
                print(detail, file=sys.stderr, flush=True)
    print("-" * 70, file=sys.stderr, flush=True)
    print(f"Ran {total_ran} tests in {elapsed:.3f}s\n", file=sys.stderr, flush=True)
    if all_ok:
        ok_note = ""
        extras = []
        if total_skipped:
            extras.append(f"skipped={total_skipped}")
        if total_expected:
            extras.append(f"expected failures={total_expected}")
        if extras:
            ok_note = f" ({', '.join(extras)})"
        print(f"OK{ok_note}", file=sys.stderr, flush=True)
        return 0
    print(_format_failure_summary(total_failures, total_errors, total_skipped, total_expected, total_unexpected),
          file=sys.stderr, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
