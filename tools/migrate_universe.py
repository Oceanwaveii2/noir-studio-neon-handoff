"""Create a scoped copy of an existing, unscoped episode timeline."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from story_graph.universe_scope import migrate_legacy_copy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True, help='New destination; existing files are never overwritten')
    parser.add_argument('--project', required=True)
    parser.add_argument('--universe', required=True)
    parser.add_argument('--afm-starters', action='store_true', help='Explicitly select the American Foxy Mom universe')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate_legacy_copy(args.source,args.out,project_id=args.project,
              universe_id=args.universe,afm=args.afm_starters),ensure_ascii=True))
        return 0
    except (OSError, ValueError, __import__('sqlite3').Error) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
