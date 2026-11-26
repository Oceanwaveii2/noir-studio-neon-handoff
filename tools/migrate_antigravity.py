"""Offline copy-first Antigravity data migration, selection and rollback."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from prose_engine.source_migration import publish_bundle,publish_workspace,activate,rollback


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='action',required=True)
    m=subs.add_parser('import');m.add_argument('--source',required=True);m.add_argument('--out',required=True)
    m.add_argument('--bundle-root',default=str(ROOT/'imports'));m.add_argument('--base')
    a=subs.add_parser('activate');a.add_argument('--workspace',required=True);a.add_argument('--expected',default='missing')
    r=subs.add_parser('rollback');r.add_argument('--expected',required=True)
    for item in (a,r):item.add_argument('--pointer',default=str(ROOT/'.app-steward/local/studio/active_workspace.json'))
    args=p.parse_args(argv)
    if args.action=='import':
        bundle=publish_bundle(args.source,args.bundle_root);result=publish_workspace(bundle,args.out,base=args.base)
    elif args.action=='activate':result=activate(args.workspace,args.pointer,args.expected)
    else:result=rollback(args.pointer,args.expected)
    print(json.dumps(result,ensure_ascii=True,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
