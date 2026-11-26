"""Evaluate scored LUAR examples offline; never activates a threshold."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.voice.luar_calibration import evaluate_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="JSON scored examples and pipeline identity")
    parser.add_argument("--out", help="New report path; existing files are never overwritten")
    parser.add_argument("--max-false-rejection", type=float, default=0.10)
    parser.add_argument("--min-detection", type=float, default=0.50)
    args = parser.parse_args(argv)
    try:
        report = evaluate_file(args.file, max_false_rejection=args.max_false_rejection,
                               min_detection=args.min_detection)
        rendered = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.out:
            destination = Path(args.out)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8", newline="\n") as out:
                out.write(rendered)
        print(rendered, end="")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"Calibration unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
