"""Replay the real Spring Break graph and optionally check a versioned claim file."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from story_graph.beat_claims import check_claims
from story_graph.scenarios.foxy_mo2 import run_foxy_mo2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Write a new manifest; existing files are preserved")
    parser.add_argument("--claims", type=Path, help="Read-only JSON claims against one recorded beat")
    parser.add_argument("--form-store", type=Path, help="Read saved links when projecting visible forms")
    args = parser.parse_args()
    try:
        junctions = None
        if args.form_store:
            from tools.studio_form_store import FormGraphStore
            from tools.studio_ui import form_targets
            if not args.form_store.is_file():
                raise ValueError("Character graph store not found.")
            junctions = FormGraphStore(args.form_store, form_targets()).junctions()
        packets = run_foxy_mo2(junctions)
        data = {"schema_version": 1, "scenario": "spring-break-mo2",
                "source": {"path": "work/americandad/foxy_mo2_master_stage_directions.md",
                           "sha256": hashlib.sha256(
                               (ROOT / "work/americandad/foxy_mo2_master_stage_directions.md").read_bytes()
                           ).hexdigest()},
                "beat_count": len(packets), "packets": [p.to_dict() for p in packets]}
        if args.manifest:
            with args.manifest.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        violations = []
        if args.claims:
            request = json.loads(args.claims.read_text(encoding="utf-8"))
            packet = next((p for p in packets if p.beat_id == request["beat_id"]), None)
            if packet is None:
                raise ValueError("Unknown MO2 beat.")
            violations = check_claims(packet, request["claims"], snapshot=request["world_snapshot_sha256"])
        print(json.dumps({"beats": len(packets), "final_tick": packets[-1].tick,
                          "claim_violations": violations}, indent=2))
        return int(bool(violations))
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
