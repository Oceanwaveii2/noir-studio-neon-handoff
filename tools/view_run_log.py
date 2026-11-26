#!/usr/bin/env python3
"""
CLI Tool to inspect the latest Prose Engine run log.

Usage:
    python tools/view_run_log.py
    python tools/view_run_log.py --json
"""

import argparse
import sys
from pathlib import Path

RUNS_DIR = Path("telemetry/engine_runs")
LATEST_MD = RUNS_DIR / "LATEST_RUN_LOG.md"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="View latest Prose Engine run log.")
    parser.add_argument("--json", action="store_true", help="Print latest run JSON instead of markdown")
    args = parser.parse_args()

    if not LATEST_MD.exists():
        print("No engine run logs found in telemetry/engine_runs.")
        return 0

    if args.json:
        manifest = RUNS_DIR / "runs_manifest.jsonl"
        if manifest.exists():
            last_line = manifest.read_text(encoding="utf-8").strip().splitlines()[-1]
            import json
            data = json.loads(last_line)
            json_file = RUNS_DIR / f"{data['run_id']}.json"
            if json_file.exists():
                print(json_file.read_text(encoding="utf-8"))
                return 0
        print("No JSON run record found.")
        return 1

    print(LATEST_MD.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
