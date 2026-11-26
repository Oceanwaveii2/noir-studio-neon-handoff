"""
Check a manuscript against the world-state canon (negation-aware).

Examples:
    python tools/check_canon.py
    python tools/check_canon.py --file work/americandad/foxy_mo2_hybrid_novel.md
    python tools/check_canon.py --file scene.md --world books/world_state.json

Exit codes: 0 = clean, 1 = canon violations, 2 = missing input.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.voice.world_state import WorldState


def main() -> int:
    parser = argparse.ArgumentParser(description="Check prose against the world-state canon")
    parser.add_argument(
        "--file",
        type=Path,
        default=ROOT / "work" / "americandad" / "foxy_mo2_hybrid_novel.md",
        help="Manuscript to check",
    )
    parser.add_argument(
        "--world",
        type=Path,
        default=ROOT / "books" / "world_state.json",
        help="World-state JSON",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically apply deterministic world-rule, profile, and mind corrections",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output file when using --fix (preserves frozen source files)",
    )
    parser.add_argument("--episode", default="spring-break", help="Episode coordinate for epoch-aware rules")
    parser.add_argument("--beat", type=int, default=0, help="Beat index for epoch-aware rules")
    args = parser.parse_args()

    if not args.file.is_file():
        print(f"Missing manuscript: {args.file}", file=sys.stderr)
        return 2
    if not args.world.is_file():
        print(f"Missing world state: {args.world}", file=sys.stderr)
        return 2

    from prose_engine.canon_corrector import auto_correct_canon

    world = WorldState.load(args.world)
    text = args.file.read_bytes().decode("utf-8")
    if args.fix:
        outcome = auto_correct_canon(
            text,
            apply=True,
            world_state=world,
            episode_id=args.episode,
            beat=args.beat,
        )
        dest = args.out or args.file
        if outcome.applied_count or args.out is not None:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(outcome.corrected_text.encode("utf-8"))
            print(f"CANON AUTO-CORRECTED: {dest} ({outcome.applied_count} fixes applied)")
            for fix in outcome.corrections:
                print(f"  * [{fix.code} | {fix.source}] {fix.original!r} -> {fix.replacement!r} ({fix.reason})")
        text = outcome.corrected_text
        checked_target = dest
    else:
        checked_target = args.file

    violations = world.violations(text)

    if not violations:
        print(f"CANON OK: {checked_target} (0 violations)")
        return 0

    preview = auto_correct_canon(
        text,
        apply=False,
        world_state=world,
        episode_id=args.episode,
        beat=args.beat,
    )
    print(f"CANON VIOLATIONS: {args.file} ({len(violations)})")
    for matched, why in violations:
        print(f"  - {matched!r}: {why}")
    if preview.corrections:
        print(f"SUGGESTED AUTO-FIXES ({len(preview.corrections)}; pass --fix to apply):")
        for fix in preview.corrections:
            print(f"  * [{fix.code} | {fix.source}] {fix.original!r} -> {fix.replacement!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
