"""Local CI: verification, performance budgets, release manifest. Nonzero exit on failure."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ("architecture", [sys.executable, "-B", "tools/check_architecture.py"])
CORE_STEPS = [ARCHITECTURE, ("core_fixtures", [sys.executable, "-B", "tools/verify_core.py"])]
STEPS = [
    ARCHITECTURE,
    ("verify", [sys.executable, "tools/verify.py"]),
    ("bench", [sys.executable, "tools/bench.py"]),
    ("quality", [sys.executable, "tools/quality_budget.py"]),
    ("hybrid_ci", [sys.executable, "tools/ci_hybrid.py"]),
    ("manifest", [sys.executable, "tools/manifest.py"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", action="store_true", help="run the read-only architecture and fixture baseline")
    parser.add_argument("--models", action="store_true", help="opt in to the local model benchmark")
    studio = parser.add_mutually_exclusive_group()
    studio.add_argument("--studio-e2e", action="store_true", help="run the Studio v2 Edge CDP suite")
    studio.add_argument("--library-stress", action="store_true", help="scan the 190-book catalog and rank stored index vectors")
    studio.add_argument("--provider-smoke", metavar="WRITER", help="run one isolated Cook writer attempt")
    parser.add_argument("--smoke-out", type=Path, help="new local evidence directory for the provider smoke")
    args = parser.parse_args()
    if args.core and args.models:
        parser.error("--models is a release-only opt-in")
    if (args.core or args.models) and (args.studio_e2e or args.library_stress or args.provider_smoke):
        parser.error("run Studio qualification separately from core and release")
    if args.provider_smoke and args.smoke_out is None:
        parser.error("--provider-smoke requires --smoke-out")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if not args.models:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    command = None
    if args.studio_e2e:
        env["NOIR_REQUIRE_STUDIO_E2E"] = "1"
        command = [sys.executable, "-B", "-m", "unittest", "tests.test_e2e_cdp_v2"]
    elif args.library_stress:
        command = [sys.executable, "-B", "tools/studio_cook_smoke.py", "--library-stress"]
    elif args.provider_smoke:
        command = [sys.executable, "-B", "tools/studio_cook_smoke.py", "--writer", args.provider_smoke,
                   "--out", str(args.smoke_out.resolve())]
    if command:
        limit = 600 if args.library_stress else 300
        try:
            return subprocess.run(command, cwd=ROOT, env=env, timeout=limit).returncode
        except subprocess.TimeoutExpired:
            print(f"[BLOCKED] Studio qualification exceeded {limit} s")
            return 2
    results = []
    for name, command in CORE_STEPS if args.core else STEPS:
        if name == "manifest" and not all(results):
            print("[NOT RUN] manifest: an earlier release check did not pass")
            continue
        command = list(command)
        if name == "manifest":
            reports = ROOT / "reports"
            reports.mkdir(exist_ok=True)
            command.extend(["--out", str(reports / f"release-manifest-{uuid4().hex}.sha256")])
        if name in ("bench", "verify") and args.models:
            command.append("--models")
        # Keep the fixture set fixed. The expanded 555+ test sequential core
        # selection now runs ~620 s on Windows, so give it a bounded
        # 900 s machine margin without changing any fixture or floor.
        limit = {"architecture": 120, "core_fixtures": 900}.get(name, 300)
        try:
            run = subprocess.run(
                command, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                timeout=limit, env=env,
            )
        except subprocess.TimeoutExpired:
            print(f"[BLOCKED] {name}: exceeded {limit} s")
            results.append(False)
            continue
        ok = run.returncode == 0
        results.append(ok)
        label = "PASS" if ok else ("BLOCKED" if run.returncode == 2 else "FAIL")
        print(f"[{label}] {name}")
        if args.core or (name == "verify" and ok):
            print((run.stdout or "").strip())
        if not ok:
            if not args.core:
                print((run.stdout or "")[-1500:])
            print((run.stderr or "") if args.core else (run.stderr or "")[-1500:])
    verdict = "PASS" if all(results) else "FAIL"
    if not args.core and not args.models:
        print("[NOT RUN] model benchmark: opt in with --models")
    print(f"{'Core CI' if args.core else 'CI'}: {verdict}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    raise SystemExit(main())
