"""
Spring Breakup Causal DAG: Canonical beat dependency graph for S04E16 Scenes 1–3.
Milestone M-SG2: Causal Dependency DAG & Beat Sequencer.
"""

from __future__ import annotations

from ..dag import (
    BeatNode,
    CausalDAG,
    LocationPrecondition,
    PortalPrecondition,
    SensoryPrecondition,
    SomaticPrecondition,
)
from ..models import PortalState, Posture, Transaction


def build_spring_breakup_dag() -> CausalDAG:
    dag = CausalDAG()

    # Beat 1: Francine Kitchen Departure Briefing
    dag.add_beat(BeatNode(
        id="beat_01_francine_kitchen_briefing",
        name="Francine Kitchen Briefing",
        scene_id="scene_01_kitchen_living",
        description="Francine closes fridge, packs duffel bag, and delivers the 3-night lasagna briefing.",
        primary_character="francine",
        dependencies=[],
        preconditions=[
            LocationPrecondition("francine", "kitchen"),
            LocationPrecondition("haley", "living_room"),
        ],
        transactions=[],
        raw_dialogue=[
            {
                "speaker": "FRANCINE",
                "parenthetical": "shouting up the stairwell",
                "text": "Rainee, let's go! Okay, Rainee, let's get going! The girls' dinners are in the fridge. What is taking that foxy woman so long!",
                "frozen": True
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "commanding, projection crisp",
                "text": "Okay, troops—preparedness briefing: three nights of lasagna, two nights of orange chicken, and one “mystery casserole” that should only be opened under adult supervision.",
                "frozen": True
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "softer tone",
                "text": "We’ll be at my parents' all week while Baba recovers from his hernia operation. Mostly, I'll be pressing down on his abdomen to release gas, or \"fart\" him.",
                "frozen": True
            }
        ],
        aesthetic_tags=["suburban_authority", "casserole_briefing", "lasagna", "cherry_overnight_bag", "white_jeans"]
    ))

    # Beat 2: Haley Toot-Massage Quip & Standing Transit
    dag.add_beat(BeatNode(
        id="beat_02_haley_toot_quip",
        name="Haley Toot Quip & Staircase Transit",
        scene_id="scene_01_kitchen_living",
        description="Haley delivers dry deadpan response from papasan chair, pushes up, and walks toward stairs.",
        primary_character="haley",
        dependencies=["beat_01_francine_kitchen_briefing"],
        preconditions=[
            LocationPrecondition("haley", "living_room")
        ],
        transactions=[
            Transaction(action="posture_change", actor="haley", target="haley", params={"posture": Posture.STANDING}),
            Transaction(action="move", actor="haley", target="staircase")
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "dry, without looking up",
                "text": "Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom Two is up to.",
                "frozen": True
            }
        ],
        aesthetic_tags=["slacker_cynicism", "papasan_chair", "tiktok_feed", "barefoot_hardwood"]
    ))

    # Beat 3: Rainee Brazilian Vanity Routine
    dag.add_beat(BeatNode(
        id="beat_03_rainee_vanity_glamour",
        name="Rainee Brazilian Vanity Routine",
        scene_id="scene_02_master_bedroom",
        description="Rainee brushes her tail at the vanity in peach silk, curves dominating the stool.",
        primary_character="rainee",
        dependencies=[],
        preconditions=[
            LocationPrecondition("rainee", "master_bedroom")
        ],
        transactions=[],
        raw_dialogue=[],
        aesthetic_tags=["brazilian_sensual", "voluptuous_bubble_butt", "guitar_hips", "cloves_and_cinnamon", "peach_silk_taut"]
    ))

    # Beat 4: Rainee Sudden Gut Coup
    dag.add_beat(BeatNode(
        id="beat_04_rainee_gut_coup",
        name="Rainee Sudden Gut Rebellion",
        scene_id="scene_02_master_bedroom",
        description="Sudden acute colic cramp hits Rainee. She freezes, drops lipstick, and declares denial.",
        primary_character="rainee",
        dependencies=["beat_03_rainee_vanity_glamour"],
        preconditions=[
            LocationPrecondition("rainee", "master_bedroom")
        ],
        transactions=[
            Transaction(action="drop", actor="rainee", target="lipstick"),
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "acute_colic_spasm", "gas_pressure_psi": 18.5, "colic_pain": 9}
            })
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "reasonable, strictly to herself",
                "text": "Absolutely not.",
                "frozen": True
            }
        ],
        aesthetic_tags=["acute_colic_onset", "meat_machine_revolt", "primal_gut_drop", "lipstick_clatter"]
    ))

    # Beat 5: Rainee Bathroom Sprint & Deadbolt Lock
    dag.add_beat(BeatNode(
        id="beat_05_rainee_bathroom_sprint",
        name="Rainee Bathroom Sprint & Lock",
        scene_id="scene_02_master_bedroom",
        description="Rainee bolts across carpet, rips bathroom door open, enters, and throws the deadbolt.",
        primary_character="rainee",
        dependencies=["beat_04_rainee_gut_coup"],
        preconditions=[
            SomaticPrecondition("rainee", "gut_state", "acute_colic_spasm")
        ],
        transactions=[
            Transaction(action="move", actor="rainee", target="master_bathroom"),
            Transaction(action="lock", actor="rainee", target="master_bathroom_door"),
            Transaction(action="posture_change", actor="rainee", target="rainee", params={"posture": Posture.SEATED})
        ],
        raw_dialogue=[],
        aesthetic_tags=["emergency_sprint", "porcelain_throne", "deadbolt_snap", "robe_bunched"]
    ))

    # Beat 6: Strained Shouting Exchange Across HVAC Duct
    dag.add_beat(BeatNode(
        id="beat_06_strained_shouting",
        name="Strained Shouting Across HVAC",
        scene_id="scene_03_master_bathroom",
        description="Francine yells up vent about turnpike toll. Rainee yells back with strained voice.",
        primary_character="rainee",
        dependencies=["beat_05_rainee_bathroom_sprint", "beat_01_francine_kitchen_briefing"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom"),
            SensoryPrecondition("rainee", "kitchen", "hearing", 0.3)
        ],
        transactions=[],
        raw_dialogue=[
            {
                "speaker": "FRANCINE",
                "parenthetical": "O.S.",
                "text": "Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!",
                "frozen": True
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "straining through the wood; voice pitched high",
                "text": "In a minute, Francine!",
                "frozen": True
            }
        ],
        aesthetic_tags=["strained_vocal_denial", "hvac_acoustic_link", "turnpike_toll"]
    ))

    # Beat 7: First Blast & Jeff's Burrito Blame
    dag.add_beat(BeatNode(
        id="beat_07_first_detonation",
        name="First Blast & Burrito Blame",
        scene_id="scene_03_master_bathroom",
        description="The vocal effort detonates the gas against the porcelain. Rainee blames Jeff's food truck order.",
        primary_character="rainee",
        dependencies=["beat_06_strained_shouting"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom"),
            PortalPrecondition("master_bathroom_door", PortalState.LOCKED)
        ],
        transactions=[
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "evacuating", "gas_pressure_psi": 12.0}
            })
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "groaning into her palms, agonized whisper",
                "text": "Oh God... oh sweet merciful heaven. It was that food truck burrito last night. Why do I ever let Jeff buy dinner? Who puts refried black beans, roasted garlic, and spicy street carnitas into one tortilla?",
                "frozen": True
            }
        ],
        aesthetic_tags=["whizzpopping_acoustics", "air_horn_squash_court", "bowl_water_rippling", "jeff_burrito_blame"]
    ))

    # Beat 8: Haley Arrival Outside Door & Dead Flower Shop Discovery
    dag.add_beat(BeatNode(
        id="beat_08_haley_scent_discovery",
        name="Haley Scent Discovery & Confrontation",
        scene_id="scene_03_master_bathroom",
        description="Haley pads to the master bedroom door, encounters the dead flower shop cloud, and calls through the wood.",
        primary_character="haley",
        dependencies=["beat_02_haley_toot_quip", "beat_07_first_detonation"],
        preconditions=[
            LocationPrecondition("haley", "staircase"),
            PortalPrecondition("master_bathroom_door", PortalState.LOCKED)
        ],
        transactions=[
            Transaction(action="move", actor="haley", target="upstairs_hallway"),
            Transaction(action="move", actor="haley", target="master_bedroom")
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "muffled through the wooden door",
                "text": "Mom? Are you farting up there? It smells like a flower shop died!",
                "frozen": True
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "mortified; teeth clenched",
                "text": "Quiet, Haley! It’s... it’s an aromatherapy bath bomb! And your boyfriend is a dead man!",
                "frozen": True
            },
            {
                "speaker": "HALEY",
                "parenthetical": "outside, completely unimpressed",
                "text": "Aromatherapy bath bombs don't rattle the picture frames, Mom. That was an octave jump.",
                "frozen": True
            }
        ],
        aesthetic_tags=["dead_flower_shop_clash", "perfumed_methane", "hardwood_footsteps", "hallway_standoff"]
    ))

    # Beat 9: Monster Farce Blast & Haley Exit
    dag.add_beat(BeatNode(
        id="beat_09_monster_blast_and_exit",
        name="Monster Blast & Haley Retreat",
        scene_id="scene_03_master_bathroom",
        description="A jagged thunderous blast shatters all dignity. Haley delivers final quip and flees downstairs.",
        primary_character="haley",
        dependencies=["beat_08_haley_scent_discovery"],
        preconditions=[
            LocationPrecondition("haley", "master_bedroom"),
            LocationPrecondition("rainee", "master_bathroom")
        ],
        transactions=[
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "spasm_subsiding", "gas_pressure_psi": 2.0}
            }),
            Transaction(action="move", actor="haley", target="upstairs_hallway"),
            Transaction(action="move", actor="haley", target="staircase")
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "text": "Whoa. Okay. Yeah, that’s definitely Jeff’s burrito. Did he get the habanero verde? Never mind, don't speak, the hallway paint is blistering.",
                "frozen": True
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "face buried in the bath towel, voice muffled",
                "text": "Go downstairs, Haley! Go eat your cold lasagna!",
                "frozen": True
            },
            {
                "speaker": "HALEY",
                "text": "Can't. Lasagna is dinner one. Francine has an itinerary. I’m heading back down before this weaponized orchid cloud hits the intake vents.",
                "frozen": True
            }
        ],
        aesthetic_tags=["monster_blast", "towel_muffle_failure", "doppler_effect", "retreat_downstairs"]
    ))

    # Beat 10: Rainee Recovery & Interrupted Exit
    dag.add_beat(BeatNode(
        id="beat_10_interrupted_exit",
        name="Rainee Recovery & Final Interrupted Squeal",
        scene_id="scene_03_master_bathroom",
        description="Rainee wipes, ties robe, delivers mirror mantra, steps toward door, and is cut off by final squeal.",
        primary_character="rainee",
        dependencies=["beat_09_monster_blast_and_exit"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom")
        ],
        transactions=[
            Transaction(action="posture_change", actor="rainee", target="rainee", params={"posture": Posture.STANDING}),
            Transaction(action="posture_change", actor="rainee", target="rainee", params={"posture": Posture.KNEELING})
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "whispering to herself, eyes squeezed shut",
                "text": "Okay... breathe, Rainee. We're fine. The crisis is over. We are completely fine.",
                "frozen": True
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "fierce whisper, eyes locked on her reflection",
                "text": "We are going to walk downstairs. We are going to slip into the red bandage dress. And we are going to be gorgeous—",
                "frozen": True
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "strangled gasp, forehead against the cabinet",
                "text": "—OH!",
                "frozen": True
            }
        ],
        aesthetic_tags=["mirror_mantra", "involuntary_pelvic_compression", "final_squeal", "comic_defeat"]
    ))

    return dag
