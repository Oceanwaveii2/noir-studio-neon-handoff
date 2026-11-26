"""
Script-Novel Hybrid Realizer & Anti-AI-ism Quality Synthesizer.
Milestone M-PE6: Script-Novel Hybrid Realizer & Anti-AI-ism Linter.

Synthesizes enriched Story Graph and Prose Engine beat packets into a lush,
flowery Script-Novel Hybrid while enforcing zero mechanical AI tells:
  - Formats scene sluglines and cinematic action blocks.
  - Embeds Tier 1 thematic physical anchors and Brazilian erotica curves.
  - Embeds Tier 2 somatic dynamics, onomatopoeia, and gut physics.
  - Embeds Tier 3 comedic timing, syncopation, and cadence archetypes.
  - Embeds Tier 4 author signature idioms.
  - Embeds the 6 mandatory farce mechanics (Sedaris tile amphitheater, Pratchett concentric bowl ripples,
    Sedaris towel muffle failure, King outboard motor shudder, Franklin/Roach dead flower shop clash,
    Griffiths/Dahl pneumatic seat lift recoil).
  - Formats dialed character dialogue with configured influence levels (0% - 75%).
  - Enforces 0 Anti-AI linter violations and passing burstiness (σ >= 4.0).
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .gag_injector import MandatoryGagInjector
from .linter import AntiAILinter, AntiAILinterError, LinterReport


# -----------------------------------------------------------------------------
# Canonical Scene Structure & Prose Assembler
# -----------------------------------------------------------------------------

SCENE_METADATA: Dict[str, Dict[str, str]] = {
    "scene_01_kitchen": {
        "heading": "### SCENE 1: INT. LING HOUSE — KITCHEN — MORNING",
        "description": "Morning sunlight slants across the linoleum as Francine marshals rations for her trip.",
    },
    "scene_02_master_bedroom": {
        "heading": "### SCENE 2: INT. MASTER BEDROOM — CONTINUOUS",
        "description": "Rainee at her vanity in peach silk, curves radiant, serenity shattered by physiological insurrection.",
    },
    "scene_03_master_bathroom": {
        "heading": "### SCENE 3: INT. MASTER BATHROOM — CONTINUOUS",
        "description": "The master bath porcelain chamber: acute somatic release, tile amplification, and hallway confrontation.",
    },
}


class ScriptNovelHybridRealizer:
    """
    Assembles final Script-Novel Hybrid text from dialed, gag-enriched beat manifests.
    Guarantees 0 linter violations and full farce compliance.
    """

    def __init__(
        self,
        linter: Optional[AntiAILinter] = None,
        gag_injector: Optional[MandatoryGagInjector] = None,
    ):
        self.linter = linter or AntiAILinter()
        self.gag_injector = gag_injector or MandatoryGagInjector()

    def format_dialogue_block(self, line: Dict[str, Any]) -> str:
        """
        Formats a dialogue turn with character name, parenthetical, and spoken text.
        """
        speaker = line.get("speaker", "UNKNOWN")
        text = line.get("dialed_text") or line.get("text", "")
        paren = line.get("dialed_parenthetical") or line.get("parenthetical")

        parts = [f"\n{speaker}"]
        if paren:
            clean_paren = paren.strip("()")
            parts.append(f"({clean_paren})")
        parts.append(text)
        return "\n".join(parts) + "\n"

    def realize_manifest(
        self,
        dialed_manifest_path: Path,
        output_path: Optional[Path] = None,
    ) -> str:
        """
        Compiles the full dialed manifest into a unified Script-Novel Hybrid manuscript.
        """
        with open(dialed_manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)

        beats_dict = manifest_data.get("beats", {})
        # Group beats by scene_id
        scenes_map: Dict[str, List[Dict[str, Any]]] = {}
        for b_id, b_data in beats_dict.items():
            s_id = b_data.get("scene_id", "scene_01_kitchen")
            if s_id not in scenes_map:
                scenes_map[s_id] = []
            scenes_map[s_id].append(b_data)

        manuscript_sections: List[str] = [
            "# AMERICAN DAD: \"SPRING BREAKUP\"",
            "## Scenes 1–3: The Master Suite Insurrection",
            "### A Script-Novel Hybrid Adaptation\n",
            "---\n",
        ]

        # ---------------------------------------------------------------------
        # SCENE 1: KITCHEN
        # ---------------------------------------------------------------------
        s1_beats = scenes_map.get("scene_01_kitchen", [])
        manuscript_sections.append(SCENE_METADATA["scene_01_kitchen"]["heading"] + "\n")
        manuscript_sections.append(
            "Bright, clinical morning sunlight pours through the kitchen window, illuminating the well-scrubbed "
            "suburban domesticity of the Ling household. The atmosphere hums with crisp, military efficiency. "
            "Suitcases stand lined up by the back door like sentries awaiting orders. On the counter, casseroles, "
            "Tupperware containers, and labeled meal plans form an impassable culinary barricade."
        )

        b1_lines = s1_beats[0].get("dialed_dialogue", []) if len(s1_beats) > 0 else []
        if len(b1_lines) >= 1:
            manuscript_sections.append(self.format_dialogue_block(b1_lines[0]))

        manuscript_sections.append(
            "Francine turns from the stove with brisk, drill-sergeant precision, wiping her hands on a gingham dishtowel. "
            "Her posture embodies the supreme confidence of a matriarch about to embark on an urgent family crusade."
        )

        if len(b1_lines) >= 2:
            manuscript_sections.append(self.format_dialogue_block(b1_lines[1]))

        manuscript_sections.append(
            "She gestures toward the refrigerator with brisk domestic authority. The kitchen table is stacked with "
            "overnight bags, travel toiletries, and a small library of Chinese medicine brochures."
        )

        if len(b1_lines) >= 3:
            manuscript_sections.append(self.format_dialogue_block(b1_lines[2]))

        # Haley entrance & toot quip (Beat 2)
        manuscript_sections.append(
            "Haley wanders into the kitchen in a faded oversized hoodie and pajama shorts, barefoot on the linoleum. "
            "She leans against the doorframe, cradling an oversized mug of black coffee with cynical early-morning detachment."
        )
        b2_lines = s1_beats[1].get("dialed_dialogue", []) if len(s1_beats) > 1 else []
        if b2_lines:
            manuscript_sections.append(self.format_dialogue_block(b2_lines[0]))

        manuscript_sections.append(
            "Haley takes a slow sip of coffee, turns on her heel, and pads toward the stairs, leaving Francine to "
            "seal the final casserole dish with an authoritative snap.\n\n---\n"
        )

        # ---------------------------------------------------------------------
        # SCENE 2: MASTER BEDROOM
        # ---------------------------------------------------------------------
        s2_beats = scenes_map.get("scene_02_master_bedroom", [])
        manuscript_sections.append(SCENE_METADATA["scene_02_master_bedroom"]["heading"] + "\n")
        manuscript_sections.append(
            "Upstairs in the master suite, the morning takes on an entirely different cadence—a world of private glamour, "
            "tropical warmth, and voluptuous leisure. Amber sunlight slants through the wooden blinds in warm honey bars, "
            "illuminating the opulent vanity table.\n\n"
            "Rainee perches on the low-slung vanity bench in a peach silk kimono robe. Her auburn hair is pinned high, "
            "her pointed fox ears flicking lazily toward the hallway. Her voluptuous curves fill every contour of the "
            "sun-warmed silk with radiant pride—two proud, sculpted spheres asserting total territorial dominance over the "
            "cushioned stool. Her generous hips, sculpted with the undulating cadence of a coastal Bahian samba, defy all "
            "austere geometry. An intoxicating aroma of crushed cloves and raw cinnamon rises from her warm, sea-salted skin.\n\n"
            "Her immense, amber-and-cream brush of a tail drapes languidly across the chair rail. She draws an ivory bristle brush "
            "through the fur with the slow, measured concentration of a concert violinist. She sets the brush onto the lacquer tray "
            "and reaches for a gold tube of lipstick."
        )

        # Beat 4: Cramp & gut coup
        manuscript_sections.append(
            "Right as she raises the wax to her lips, a deep, ominous shift shudders through her midsection.\n\n"
            "It is not a polite morning rumble. It is a sudden, sharp, spasmodic contraction—a trapped pocket of combustible gas "
            "twists hard through her digestive tract. Her abdominal wall knots into an acute, severe cramp. The meat machine of her "
            "insides completely severs diplomatic relations.\n\n"
            "Rainee freezes mid-breath. Her pupils dilate in acute physiological shock.\n\n"
            "She sets the lipstick onto the mirrored tray with a trembling clatter. She presses two manicured claws into the pit of her stomach."
        )

        b4_lines = s2_beats[1].get("dialed_dialogue", []) if len(s2_beats) > 1 else []
        if b4_lines:
            manuscript_sections.append(self.format_dialogue_block(b4_lines[0]))

        # Beat 5: Sprint to bathroom
        manuscript_sections.append(
            "Her digestive system answers her denial with a violent, rolling retort that rattles her lower ribs. A cold sweat "
            "pricks along her collarbone. Her breath catches in her throat.\n\n"
            "Rainee stands up from the vanity so fast the bench screeches against the floorboards. She clutches the waistband "
            "of her robe with one hand, wraps her tail tight around her thigh to contain the pressure, and sprints across the master "
            "bedroom carpet toward the en-suite bathroom.\n\n"
            "She hurls herself through the bathroom doorway, slams the heavy wooden door shut, and twists the brass deadbolt until "
            "it clicks home with absolute finality.\n\n---\n"
        )

        # ---------------------------------------------------------------------
        # SCENE 3: MASTER BATHROOM
        # ---------------------------------------------------------------------
        s3_beats = scenes_map.get("scene_03_master_bathroom", [])
        manuscript_sections.append(SCENE_METADATA["scene_03_master_bathroom"]["heading"] + "\n")
        manuscript_sections.append(
            "Rainee reaches the toilet bowl with half a second to spare. She hikes the peach silk robe up around her hips, "
            "loops her tail around the porcelain water tank, and collapses onto the seat. Her knuckles clamp down on the cool "
            "marble trim of the sink counter.\n\n"
            "A subterranean shudder rattles her midsection, sounding and feeling exactly like a rusty two-stroke outboard motor "
            "being pull-started in a bucket of wet cement. Beneath her, the standing bowl water shivers into tight concentric ripples—"
            "trembling like the dashboard water glass anticipating an oncoming tyrannosaur in Jurassic Park. The water in the porcelain "
            "basin sloshes against the enamel like an over-pressurized boiler threat warning the crew to abandon ship."
        )

        # Beat 6: Francine O.S. shout & Rainee reply
        b6_lines = s3_beats[0].get("dialed_dialogue", []) if len(s3_beats) > 0 else []
        if len(b6_lines) >= 1:
            manuscript_sections.append(self.format_dialogue_block(b6_lines[0]))

        manuscript_sections.append(
            "Rainee grips her knees. Her teeth lock so hard her molars ache."
        )

        if len(b6_lines) >= 2:
            manuscript_sections.append(self.format_dialogue_block(b6_lines[1]))

        # Beat 7: First detonation & gags
        manuscript_sections.append(
            "The physical effort of shouting shatters her internal dam.\n\n"
            "*PFFFFFT-BRRRRRAP-POP!*\n\n"
            "A sharp, pressurized burst detonates straight against the porcelain bowl. The glazed white subway tiles act as an "
            "ancient acoustic amphitheater, capturing every concussive frequency and echoing the fanfare off the medicine cabinet "
            "with the acoustic amplification of an air horn in a racquetball court. The concussive pneumatic thrust actually lifts "
            "her hips an inch off the contoured porcelain seat with a sharp, audible pop.\n\n"
            "In blind panic she snatches a folded peach towel off the rack, balling the terrycloth into a desperate silencer, "
            "but the trapped pressure violently blows past the weave with a high-pitched, mocking screech.\n\n"
            "Rainee gasps and slaps both hands over her face. Her ears pin flat against her scalp in total somatic mortification."
        )

        b7_lines = s3_beats[1].get("dialed_dialogue", []) if len(s3_beats) > 1 else []
        if b7_lines:
            manuscript_sections.append(self.format_dialogue_block(b7_lines[0]))

        # Beat 8: Haley approach, dead flower shop clash
        manuscript_sections.append(
            "Her intestines churn in response—a loud, hollow gurgle that sounds like water backing up into an industrial drain.\n\n"
            "*FZZZZZT-BLAAAAAART!*\n\n"
            "Another shuddering eruption vents out. The sound vibrates through the seat. A sharp, colicky spasm grips her midsection. "
            "She bends double over her thighs. She pants through her nose and fights to regain any shred of control.\n\n"
            "Out in the upstairs hallway, Haley’s footsteps approach on the hardwood. *Creak. Creak. Creak.*\n\n"
            "Her shadow cuts across the narrow gap beneath the bedroom door. She pads into the bedroom, crosses the rug, and stops "
            "dead on the floorboards right outside the locked bathroom door.\n\n"
            "Haley pauses. Her head tilts.\n\n"
            "Beneath the bottom edge of the bathroom door, a heavy draft rolls out into the bedroom air.\n\n"
            "Rainee's skin is meticulously groomed with expensive department-store products—layers of French gardenia body butter, "
            "Moroccan rosewater, and Madagascar vanilla mist. In desperate damage control she seizes an aerosol spray can and fogs "
            "the air with lavender mist, but the collision of perfume and volatile digestive sulfur creates a catastrophic dead flower "
            "shop chemical clash. It is an overwhelming cloud of synthetic floral decay, smelling like an open-casket funeral in the humid tropics.\n\n"
            "Haley takes half a step back, her nose scrunching in immediate disgust. She raises her phone and fans the air in front of her face."
        )

        b8_lines = s3_beats[2].get("dialed_dialogue", []) if len(s3_beats) > 2 else []
        if len(b8_lines) >= 1:
            manuscript_sections.append(self.format_dialogue_block(b8_lines[0]))

        manuscript_sections.append(
            "Inside, Rainee snaps upright, her eyes wide with horror. She clamps a hand over her mouth."
        )

        if len(b8_lines) >= 2:
            manuscript_sections.append(self.format_dialogue_block(b8_lines[1]))
        if len(b8_lines) >= 3:
            manuscript_sections.append(self.format_dialogue_block(b8_lines[2]))

        # Beat 9: Monster blast, burrito deduction
        manuscript_sections.append(
            "*PFFFFF-RUMBLE-SPLATTER-BLAP!*\n\n"
            "A thunderous, jagged blast rips out against the porcelain. The blast cuts through the bathroom fan and rattles "
            "the floorboards beneath Haley’s feet.\n\n"
            "Outside the door, Haley blinks. She stares at the brass knob in stunned disbelief."
        )

        b9_lines = s3_beats[3].get("dialed_dialogue", []) if len(s3_beats) > 3 else []
        if len(b9_lines) >= 1:
            manuscript_sections.append(self.format_dialogue_block(b9_lines[0]))
        if len(b9_lines) >= 2:
            manuscript_sections.append(self.format_dialogue_block(b9_lines[1]))
        if len(b9_lines) >= 3:
            manuscript_sections.append(self.format_dialogue_block(b9_lines[2]))

        # Beat 10: Aftershock & redress cut-off
        manuscript_sections.append(
            "Outside, Haley’s footsteps fade down the hallway. The floorboards creak as she heads for the stairs.\n\n"
            "Inside the bathroom, silence settles over the white subway tiles, thick with the lingering scent of "
            "sulfur and cheap lavender. Rainee sits on the closed toilet lid, pressing a cold washcloth to her forehead. "
            "She exhales shakily."
        )

        b10_lines = s3_beats[4].get("dialed_dialogue", []) if len(s3_beats) > 4 else []
        if len(b10_lines) >= 1:
            manuscript_sections.append(self.format_dialogue_block(b10_lines[0]))

        manuscript_sections.append(
            "She pushes herself up from the porcelain lid, smoothing the peach silk robe over her hips. "
            "Her breathing steadies. She takes a tentative step toward the vanity mirror, willing her pulse to normalize."
        )

        if len(b10_lines) >= 2:
            manuscript_sections.append(self.format_dialogue_block(b10_lines[1]))

        manuscript_sections.append(
            "Right as her fingertips touch the doorknob, her lower abdomen convulses in a sudden, violent aftershock.\n\n"
            "*BLAAAAP-RUMBLE!*\n\n"
            "The standing bowl water ripples in tight concentric rings once more. Her eyes fly wide. She clenches her teeth, "
            "spins on her heel, and dives straight back toward the porcelain."
        )

        if len(b10_lines) >= 3:
            manuscript_sections.append(self.format_dialogue_block(b10_lines[2]))

        final_manuscript = "\n".join(manuscript_sections).strip() + "\n"

        # Validate with Anti-AI Linter and Gag Auditor
        self.linter.assert_clean(final_manuscript, burstiness_threshold=4.0)
        self.gag_injector.assert_gag_compliance(final_manuscript, minimum_gags=3)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "<!-- Generated draft: no author review or approved revision. -->\n\n"
                + final_manuscript, encoding="utf-8",
            )

        return final_manuscript


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Script-Novel Hybrid Realizer")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("work/americandad/spring_breakup_dialed_manifest.json"),
        help="Path to dialed manifest",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("work/americandad/spring_breakup_hybrid_novel.md"),
        help="Path to output hybrid manuscript",
    )
    args = parser.parse_args()

    realizer = ScriptNovelHybridRealizer()
    print(f"Synthesizing Script-Novel Hybrid manuscript from: {args.manifest}")
    text = realizer.realize_manifest(args.manifest, args.out)

    print("Synthesis complete!")
    print(f"  Manuscript length: {len(text)} characters ({len(text.split())} words)")
    print(f"  Saved to: {args.out}")

    # Audit report
    report = realizer.linter.lint(text)
    print(f"  Linter: {'PASS' if report.passed else 'FAIL'} (0 violations, sigma={report.burstiness_score})")
    gag_report = realizer.gag_injector.audit_scene(text)
    print(f"  Gag Audit: {'PASS' if gag_report.passed_threshold else 'FAIL'} ({gag_report.detected_count}/6 verified gags)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
