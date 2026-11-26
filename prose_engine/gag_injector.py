"""
Mandatory Joke & Somatic Gag Injector.
Milestone M-PE4: Mandatory Joke & Somatic Gag Injector.

Enforces the inclusion of verified, signature comedic and somatic gag mechanics
derived directly from the 15 ingested modern and classical farce volumes:
  1. Acoustic Tile Amplification (David Sedaris, Me Talk Pretty One Day)
  2. Bowl Water Vibration / Boiler Threat (Terry Pratchett, Guards! Guards! / Jurassic Park)
  3. Towel Muffle Failure (David Sedaris, Me Talk Pretty One Day)
  4. Outboard Motor / Subterranean Shudder (Stephen King, Dreamcatcher)
  5. Dead Flower Shop Chemical Clash (Benjamin Franklin / Mary Roach, Fart Proudly / Gulp)
  6. Seat Lift Recoil & Pop (Andy Griffiths / Roald Dahl, The Day My Bum Went Psycho / The BFG)

Exit Criterion:
  Farce scenes fail build if fewer than 3 verified book mechanics are present.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class GagDefinition:
    gag_id: str
    name: str
    author: str
    source_book: str
    mechanic_description: str
    sensory_signatures: List[str]
    verification_patterns: List[str]
    prose_templates: List[str]
    required_keywords: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InjectedGag:
    gag_id: str
    name: str
    author: str
    source_book: str
    somatic_mechanism: str
    prose_payload: str
    verification_patterns: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BeatGagPackage:
    beat_id: str
    scene_id: str
    is_farce_beat: bool
    assigned_gags: List[InjectedGag]
    total_gags: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "scene_id": self.scene_id,
            "is_farce_beat": self.is_farce_beat,
            "total_gags": self.total_gags,
            "assigned_gags": [g.to_dict() for g in self.assigned_gags],
        }


@dataclass
class GagAuditReport:
    text_length: int
    detected_gags: List[str]
    detected_count: int
    missing_gags: List[str]
    passed_threshold: bool
    minimum_required: int
    diagnostics: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GagComplianceError(Exception):
    """Raised when a farce scene fails to satisfy the minimum gag threshold."""
    pass


# -----------------------------------------------------------------------------
# Canonical Gag Matrix (The 6 Ingested Farce Mechanics)
# -----------------------------------------------------------------------------

CANONICAL_GAGS: Dict[str, GagDefinition] = {
    # 1. Acoustic Tile Amplification (Sedaris)
    "acoustic_tile_amplification": GagDefinition(
        gag_id="acoustic_tile_amplification",
        name="Acoustic Tile Amplification",
        author="David Sedaris",
        source_book="Me Talk Pretty One Day",
        mechanic_description=(
            "Enclosed bathroom architecture and glazed porcelain tiles acting as a concert-hall "
            "amplifier/megaphone, reflecting and magnifying sound waves so that a suppressed internal "
            "release turns into an inescapable brass fanfare."
        ),
        sensory_signatures=[
            "glazed porcelain tiles",
            "acoustic amphitheater",
            "megaphone reverb",
            "hallway echo",
        ],
        verification_patterns=[
            r"\b(porcelain|glazed\s*tile|acoustic\s*amphitheater|reverberating\s*chamber|enclosed\s*bathroom)\b",
            r"\b(echo\w*|reverberat\w*|amplif\w*|acoustic\s*fanfare|bounc\w*)\b",
        ],
        prose_templates=[
            (
                "The glazed porcelain tiles of the master bath acted like an ancient Roman amphitheater, "
                "capturing every acoustic frequency and broadcasting it straight under the doorframe into the hallway."
            ),
            (
                "The hard surfaces offered zero mercy, bouncing the concussive report between the vanity mirror "
                "and the tile floor until the entire room hummed with acoustic reverberation."
            ),
        ],
        required_keywords=["tile", "porcelain", "acoustic", "reverberation"],
    ),

    # 2. Bowl Water Vibration / Boiler Threat (Pratchett / Jurassic Park)
    "bowl_water_vibration": GagDefinition(
        gag_id="bowl_water_vibration",
        name="Bowl Water Vibration / Boiler Threat",
        author="Terry Pratchett / Michael Crichton",
        source_book="Guards! Guards! / Jurassic Park",
        mechanic_description=(
            "The standing water in the toilet bowl trembling with rhythmic, concentric shockwave ripples, "
            "akin to a glass of water heralding an oncoming tyrannosaur or an overloaded steam boiler "
            "reaching structural breaking point."
        ),
        sensory_signatures=[
            "standing bowl water",
            "concentric ripples",
            "boiler threat",
            "trembling surface",
        ],
        verification_patterns=[
            r"\b(bowl\s*water|surface\s*of\s*the\s*water|standing\s*water|water\s*in\s*the\s*bowl)\b",
            r"\b(concentric\s*ring|rippl\w*|vibrat\w*|boiler\s*threat|shiver\w*|tremor)\b",
        ],
        prose_templates=[
            (
                "Beneath her, the standing bowl water shivered into tight, concentric ripples, trembling "
                "like the dashboard water glass anticipating an oncoming tyrannosaur in Jurassic Park."
            ),
            (
                "The water in the porcelain basin gave a sickening tremor, concentric rings sloshing "
                "against the enamel like an over-pressurized boiler warning the crew to abandon ship."
            ),
        ],
        required_keywords=["bowl", "water", "concentric", "ripples"],
    ),

    # 3. Towel Muffle Failure (Sedaris)
    "towel_muffle_failure": GagDefinition(
        gag_id="towel_muffle_failure",
        name="Towel Muffle Failure",
        author="David Sedaris",
        source_book="Me Talk Pretty One Day",
        mechanic_description=(
            "Desperately balling up a plush cotton bath towel or guest sheet to press against the epicenter "
            "as an acoustic silencer, only for the escaping pressure to violently bypass the weave with a "
            "high-pitched screech or kazoo-like buzz."
        ),
        sensory_signatures=[
            "folded bath towel",
            "cotton silencer",
            "blow past weave",
            "kazoo screech",
        ],
        verification_patterns=[
            r"\b(towel|terrycloth|bath\s*sheet|washcloth)\b",
            r"\b(muffle|suppress|silenc\w*|smother)\b",
            r"\b(fail\w*|blew\s*past|blow\s*past|screech|kazoo|bypass)\b",
        ],
        prose_templates=[
            (
                "In blind panic she snatched a folded peach towel off the rack, balling the terrycloth into a "
                "desperate silencer, but the trapped pressure violently blew past the fibers with a high-pitched, "
                "mocking screech."
            ),
            (
                "The thick Egyptian cotton towel did nothing to smother the report; if anything, the compressed weave "
                "transformed the concussive burst into the furious, indignant buzz of an amplified kazoo."
            ),
        ],
        required_keywords=["towel", "muffle", "silencer", "screech"],
    ),

    # 4. Outboard Motor / Subterranean Shudder (Stephen King)
    "outboard_motor_shudder": GagDefinition(
        gag_id="outboard_motor_shudder",
        name="Outboard Motor / Subterranean Shudder",
        author="Stephen King",
        source_book="Dreamcatcher",
        mechanic_description=(
            "A violent, deep-gut visceral shudder vibrating through the lower abdomen, sounding like a "
            "two-stroke outboard motor or an old chainsaw being violently pull-started in wet cement."
        ),
        sensory_signatures=[
            "two-stroke outboard motor",
            "wet cement",
            "subterranean shudder",
            "rhythmic gut chug",
        ],
        verification_patterns=[
            r"\b(outboard\s*motor|two[- ]stroke|wet\s*cement|diesel\s*engine|chainsaw)\b",
            r"\b(pull[- ]start\w*|shudder\w*|chug\w*|rumble|subterranean)\b",
        ],
        prose_templates=[
            (
                "Her midsection gave a deep, subterranean shudder that sounded and felt exactly like a rusty "
                "two-stroke outboard motor being pull-started in a bucket of wet cement."
            ),
            (
                "A violent internal chugging rattled her lower ribs, the sensation of an ungreased two-stroke "
                "engine violently coughing to life in her transverse colon."
            ),
        ],
        required_keywords=["outboard motor", "two-stroke", "cement", "shudder"],
    ),

    # 5. Dead Flower Shop Chemical Clash (Franklin / Roach)
    "dead_flower_shop_clash": GagDefinition(
        gag_id="dead_flower_shop_clash",
        name="Dead Flower Shop Chemical Clash",
        author="Benjamin Franklin / Mary Roach",
        source_book="Fart Proudly / Gulp",
        mechanic_description=(
            "A frantic burst of vanilla, lavender, or potpourri aerosol spray colliding in mid-air with volatile "
            "sulfur compounds (hydrogen sulfide and methanethiol), producing an eye-watering synthetic abomination "
            "that smells like a funeral home or a dead flower shop rotting in high summer."
        ),
        sensory_signatures=[
            "dead flower shop",
            "aerosol lavender spray",
            "volatile sulfur clash",
            "funeral home odor",
        ],
        verification_patterns=[
            r"\b(dead\s*flower\s*shop|funeral\s*home|flower\s*shop\s*died|decaying\s*florist)\b",
            r"\b(lavender|vanilla|potpourri|aerosol|perfume|air\s*freshener|spray)\b",
        ],
        prose_templates=[
            (
                "In desperate damage control she seized the aerosol can and fogged the stall with lavender mist, "
                "but the chemical clash was an instant catastrophe—the room now smelled like a dead flower shop left "
                "to bake in an August dumpster."
            ),
            (
                "Spraying the perfumed aerosol only created a monstrous third entity: an eye-watering synthetic clash "
                "resembling the floral arrangement of a humid, cut-rate funeral parlor."
            ),
        ],
        required_keywords=["dead flower shop", "spray", "lavender", "sulfur"],
    ),

    # 6. Seat Lift Recoil & Pop (Andy Griffiths / Roald Dahl)
    "seat_lift_recoil": GagDefinition(
        gag_id="seat_lift_recoil",
        name="Seat Lift Recoil & Pop",
        author="Andy Griffiths / Roald Dahl",
        source_book="The Day My Bum Went Psycho / The BFG",
        mechanic_description=(
            "The concussive pneumatic thrust lifting the hips slightly off the contoured porcelain seat, "
            "accompanied by a sharp pressure pop as the seal breaks."
        ),
        sensory_signatures=[
            "concussive seat lift",
            "pneumatic pop",
            "airborne recoil",
            "breaking seal",
        ],
        verification_patterns=[
            r"\b(seat|porcelain\s*ring|toilet\s*rim)\b",
            r"\b(lift\w*|recoil|launch\w*|kick\w*|airborne)\b",
            r"\b(pop|pneumatic|thrust|rebound)\b",
        ],
        prose_templates=[
            (
                "The concussive pneumatic thrust of the blast actually lifted her hips two inches off the "
                "porcelain rim with a sharp, audible pop."
            ),
            (
                "The sheer mechanical recoil kicked her upward against gravity, the sudden burst of pressurized "
                "gas breaking the biological seal on the seat."
            ),
        ],
        required_keywords=["seat", "lift", "recoil", "pop"],
    ),
}


# -----------------------------------------------------------------------------
# Beat-to-Gag Assignment Routing for Spring Breakup
# -----------------------------------------------------------------------------

SPRING_BREAKUP_GAG_ROUTING: Dict[str, List[str]] = {
    # Beat 4: Rainee's vanity serenity shattered by the first gut convulsion
    "beat_04_rainee_gut_coup": [
        "outboard_motor_shudder",
    ],
    # Beat 5: Rushing to master bath and locking deadbolt
    "beat_05_rainee_bathroom_sprint": [
        "outboard_motor_shudder",
    ],
    # Beat 7: First massive detonation on porcelain
    "beat_07_first_detonation": [
        "acoustic_tile_amplification",
        "bowl_water_vibration",
        "towel_muffle_failure",
        "seat_lift_recoil",
    ],
    # Beat 8: Haley investigating the smell from hallway
    "beat_08_haley_scent_discovery": [
        "dead_flower_shop_clash",
    ],
    # Beat 9: Monster blast, burrito deduction, and doorframe vibration
    "beat_09_monster_blast_and_exit": [
        "outboard_motor_shudder",
        "acoustic_tile_amplification",
        "seat_lift_recoil",
    ],
    # Beat 10: Attempted redress cut off by aftershock
    "beat_10_interrupted_exit": [
        "bowl_water_vibration",
    ],
}


# -----------------------------------------------------------------------------
# Mandatory Gag Injector Engine
# -----------------------------------------------------------------------------

class MandatoryGagInjector:
    """
    Enforces the presence of verified book gag mechanics in farce beats.
    Provides auditing, build gates, and manifest enrichment.
    """

    def __init__(self, custom_gags: Optional[Dict[str, GagDefinition]] = None):
        self.gags = custom_gags or CANONICAL_GAGS

    def get_gag(self, gag_id: str) -> GagDefinition:
        if gag_id not in self.gags:
            raise KeyError(f"Unknown gag ID: '{gag_id}'. Available: {list(self.gags.keys())}")
        return self.gags[gag_id]

    def get_all_gags(self) -> List[GagDefinition]:
        return list(self.gags.values())

    def get_gags_for_beat(self, beat_id: str, policy_name: str) -> List[InjectedGag]:
        """
        Retrieves the assigned gag packages for a specific beat.
        """
        assigned_ids = SPRING_BREAKUP_GAG_ROUTING.get(beat_id, [])
        if not assigned_ids and policy_name == "farce_fart":
            # Default farce assignment
            assigned_ids = [
                "acoustic_tile_amplification",
                "bowl_water_vibration",
                "outboard_motor_shudder",
            ]

        injected: List[InjectedGag] = []
        for gid in assigned_ids:
            if gid in self.gags:
                g = self.gags[gid]
                injected.append(
                    InjectedGag(
                        gag_id=g.gag_id,
                        name=g.name,
                        author=g.author,
                        source_book=g.source_book,
                        somatic_mechanism=g.mechanic_description,
                        prose_payload=g.prose_templates[0],
                        verification_patterns=g.verification_patterns,
                    )
                )
        return injected

    def audit_scene(
        self,
        text: str,
        minimum_gags: int = 3,
        raise_on_failure: bool = False,
    ) -> GagAuditReport:
        """
        Audits a scene or text block against all canonical gags.
        Fails if fewer than minimum_gags distinct mechanics are detected.
        """
        detected: List[str] = []
        diagnostics: List[str] = []

        for gag_id, gag in self.gags.items():
            # A gag is detected if ALL its verification pattern groups have at least one regex match
            matched_all_groups = True
            for pattern_str in gag.verification_patterns:
                if not re.search(pattern_str, text, re.IGNORECASE):
                    matched_all_groups = False
                    break

            if matched_all_groups:
                detected.append(gag_id)
                diagnostics.append(f"[PASS] Gag '{gag.name}' verified ({gag.author} - {gag.source_book})")
            else:
                diagnostics.append(f"[MISSING] Gag '{gag.name}' missing verification patterns")

        missing = [gid for gid in self.gags.keys() if gid not in detected]
        passed = len(detected) >= minimum_gags

        report = GagAuditReport(
            text_length=len(text),
            detected_gags=detected,
            detected_count=len(detected),
            missing_gags=missing,
            passed_threshold=passed,
            minimum_required=minimum_gags,
            diagnostics=diagnostics,
        )

        if raise_on_failure and not passed:
            raise GagComplianceError(
                f"Farce scene failed gag compliance! Found {len(detected)} verified mechanics "
                f"(minimum required: {minimum_gags}). Detected: {detected}. Missing: {missing}"
            )

        return report

    def assert_gag_compliance(self, text: str, minimum_gags: int = 3) -> None:
        """Asserts that text contains >= minimum_gags; raises GagComplianceError otherwise."""
        self.audit_scene(text, minimum_gags=minimum_gags, raise_on_failure=True)

    def enrich_manifest(
        self,
        deep_scan_manifest_path: Path,
        output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Takes the deep scan manifest and enriches each beat packet with
        mandatory gag packages and audit invariants.
        """
        with open(deep_scan_manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        deep_scans = manifest_data.get("deep_scans", {})
        enriched_beats: Dict[str, Any] = {}

        total_farce_beats = 0
        total_gags_injected = 0

        for beat_id, scan_data in deep_scans.items():
            policy_name = scan_data.get("policy_name", "")
            is_farce = (policy_name == "farce_fart") or (beat_id in SPRING_BREAKUP_GAG_ROUTING)

            gags_for_beat = self.get_gags_for_beat(beat_id, policy_name)
            if is_farce:
                total_farce_beats += 1
                total_gags_injected += len(gags_for_beat)

            beat_pkg = BeatGagPackage(
                beat_id=beat_id,
                scene_id=scan_data.get("scene_id", ""),
                is_farce_beat=is_farce,
                assigned_gags=gags_for_beat,
                total_gags=len(gags_for_beat),
            )

            # Clone and enrich scan data
            enriched_item = dict(scan_data)
            enriched_item["gag_package"] = beat_pkg.to_dict()
            enriched_beats[beat_id] = enriched_item

        output_manifest = {
            "version": "1.0.0",
            "beat_count": len(enriched_beats),
            "total_farce_beats": total_farce_beats,
            "total_gags_injected": total_gags_injected,
            "canonical_gags_available": len(self.gags),
            "beats": enriched_beats,
        }

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_manifest, f, indent=2)

        return output_manifest


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Prose Engine Mandatory Joke & Somatic Gag Injector")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("work/americandad/spring_breakup_deep_scan_manifest.json"),
        help="Path to deep scan manifest",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("work/americandad/spring_breakup_gag_enriched_manifest.json"),
        help="Path to output gag-enriched manifest",
    )
    parser.add_argument(
        "--audit-file",
        type=Path,
        default=None,
        help="Path to a text or markdown scene file to audit for gag compliance",
    )
    parser.add_argument(
        "--min-gags",
        type=int,
        default=3,
        help="Minimum number of verified gags required to pass build gate",
    )
    args = parser.parse_args()

    injector = MandatoryGagInjector()

    if args.audit_file:
        print(f"Auditing scene file for gag compliance: {args.audit_file}")
        if not args.audit_file.exists():
            print(f"Error: Audit file not found: {args.audit_file}")
            return 1
        text = args.audit_file.read_text(encoding="utf-8")
        report = injector.audit_scene(text, minimum_gags=args.min_gags)
        print(f"Gag Audit: {'PASS' if report.passed_threshold else 'FAIL'}")
        print(f"  Detected ({report.detected_count}/{report.minimum_required}): {', '.join(report.detected_gags)}")
        print(f"  Missing: {', '.join(report.missing_gags)}")
        for d in report.diagnostics:
            print(f"    {d}")
        return 0 if report.passed_threshold else 1

    print(f"Enriching deep scan manifest with mandatory gags: {args.manifest}")
    res = injector.enrich_manifest(args.manifest, args.out)
    print(f"Enrichment complete!")
    print(f"  Total beats: {res['beat_count']}")
    print(f"  Total farce beats: {res['total_farce_beats']}")
    print(f"  Total gags injected: {res['total_gags_injected']}")
    print(f"Saved to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
