"""
Full Narrative Causal DAG for AMERICAN FOXY MO2: 'SPRING BREAKUP' (S04E16).
Milestone M-SG2 / MO2 Architecture.
Encompasses all 4 Acts (Kitchen Briefing, Upstairs Farce, Living Room Detonation, Driveway Takeover).
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


def build_foxy_mo2_dag() -> CausalDAG:
    dag = CausalDAG()

    # =========================================================================
    # ACT I: THE KITCHEN BRIEFING & LIVING ROOM LOUNGE (7:31 A.M.)
    # =========================================================================

    # Beat 1: Francine Departure Briefing (Ref: Image 1, 2)
    dag.add_beat(BeatNode(
        id="beat_01_francine_kitchen_briefing",
        name="Francine Kitchen Briefing & Lasagna Itinerary",
        scene_id="act_01_kitchen_living",
        description="Francine in pink pencil dress packs cherry suitcase, briefs Haley and Stella on 3 nights of lasagna and Baba's post-op gas release.",
        primary_character="francine",
        dependencies=[],
        preconditions=[
            LocationPrecondition("francine", "kitchen"),
            LocationPrecondition("haley", "living_room"),
            LocationPrecondition("stella", "living_room"),
        ],
        transactions=[
            Transaction(action="take", actor="francine", target="cherry_suitcase"),
            Transaction(action="posture_change", actor="francine", target="francine", params={"posture": Posture.STANDING}),
        ],
        raw_dialogue=[
            {
                "speaker": "FRANCINE",
                "parenthetical": "shouting upstairs",
                "text": "Rainee, let's go! Okay, Rainee, let's get going! The girls' dinners are in the fridge. What is taking that foxy woman so long?!",
                "frozen": True,
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "commanding, to Haley and Stella",
                "text": "Okay, troops—preparedness briefing: three nights of lasagna, two nights of orange chicken, and one 'mystery casserole' that should only be opened under adult supervision.",
                "frozen": True,
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "straightening her sweetheart neckline",
                "text": "Haley, Stella—we are going to be out of town at my parents' house all week while Baba recovers from his inguinal hernia surgery. The doctors repaired the wall, but his intestines are practically paralyzed with post-op air. Mostly, I’ll be sitting at his bedside, pressing both hands into his abdominal cavity to manually express the trapped gas. 'Farting him.' Or as the surgeon technically billed it: 'ancestral farting.'",
                "frozen": True,
            },
        ],
        aesthetic_tags=["suburban_authority", "pink_pencil_dress", "lasagna_itinerary", "cherry_overnight_bag", "image1", "image2"],
    ))

    # Beat 2: Haley Toot Quip & Stella Sarcasm (Ref: Image 3, 4, 9)
    dag.add_beat(BeatNode(
        id="beat_02_haley_toot_quip_stella_banter",
        name="Haley Toot Quip & Stella Sarcasm",
        scene_id="act_01_kitchen_living",
        description="Haley deadpans from papasan chair; Stella quips over iced coffee behind cat-eye sunglasses; Francine justifies love as releasing gastrointestinal rebellion.",
        primary_character="haley",
        dependencies=["beat_01_francine_kitchen_briefing"],
        preconditions=[
            LocationPrecondition("haley", "living_room"),
            LocationPrecondition("stella", "living_room"),
        ],
        transactions=[
            Transaction(action="posture_change", actor="haley", target="haley", params={"posture": Posture.STANDING}),
            Transaction(action="move", actor="haley", target="staircase"),
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "without looking up from phone",
                "text": "Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom 2 is up to.",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "lowering sunglasses",
                "text": "That's… sweet. Gross, but sweet. Like a caramel-covered cricket.",
                "frozen": True,
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "rolling eyes",
                "text": "When you love someone, you help them let it out—be it feelings or gastrointestinal rebellion.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["papasan_slouch", "nirvana_tee", "iced_coffee", "cat_eye_sunglasses", "image3", "image9"],
    ))

    # =========================================================================
    # ACT II: THE UPSTAIRS MASTER SUITE & DOUBLE-WIDE FARCE (7:31–7:40 A.M.)
    # =========================================================================

    # Beat 3: Rainee Vanity Tail-Brushing (Ref: Image 6, 7)
    dag.add_beat(BeatNode(
        id="beat_03_rainee_vanity_glamour",
        name="Rainee Vanity Tail-Brushing Glamour",
        scene_id="act_02_master_bedroom",
        description="Rainee brushes her four-foot fox tail at the three-way vanity in an emerald silk robe with violin precision.",
        primary_character="rainee",
        dependencies=["beat_02_haley_toot_quip_stella_banter"],
        preconditions=[
            LocationPrecondition("rainee", "master_bedroom"),
        ],
        transactions=[
            Transaction(action="take", actor="rainee", target="silver_brush"),
            Transaction(action="posture_change", actor="rainee", target="rainee", params={"posture": Posture.SEATED}),
        ],
        raw_dialogue=[],
        aesthetic_tags=["hollywood_vanity", "tail_brushing", "emerald_silk", "image6", "image7"],
    ))

    # Beat 4: Rainee Colic Attack & Carnitas Epiphany
    dag.add_beat(BeatNode(
        id="beat_04_rainee_gut_coup",
        name="Rainee Acute Colic Attack",
        scene_id="act_02_master_bedroom",
        description="Subterranean gut rumble strikes Rainee. She drops the silver brush, curses Jeff's food-truck burrito run.",
        primary_character="rainee",
        dependencies=["beat_03_rainee_vanity_glamour"],
        preconditions=[
            LocationPrecondition("rainee", "master_bedroom"),
        ],
        transactions=[
            Transaction(action="drop", actor="rainee", target="silver_brush"),
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "acute_colic_spasm", "gas_pressure_psi": 22.0, "pain": 9}
            }),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "clutching stomach in sharp panic",
                "text": "Uggh, what the hell, man? I was just fine... Ugh, must have been that street burrito Jeff bought last night! Never let a stoner buy dinner!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["acute_colic_spasm", "silver_brush_clatter", "perfume_puff", "jeff_burrito_blame"],
    ))

    # Beat 5: Bathroom Bolt & Double-Wide Commode Morph (Ref: Image 8)
    dag.add_beat(BeatNode(
        id="beat_05_bathroom_sprint_commode_morph",
        name="Rainee Bathroom Sprint & Double-Wide Commode Morph",
        scene_id="act_02_master_bathroom",
        description="Rainee waddles into master bath, locks deadbolt, slams hand on standard toilet to trigger nanite expansion into 4-foot black lacquer gold-lotus throne.",
        primary_character="rainee",
        dependencies=["beat_04_rainee_gut_coup"],
        preconditions=[
            SomaticPrecondition("rainee", "gut_state", "acute_colic_spasm"),
        ],
        transactions=[
            Transaction(action="open", actor="rainee", target="master_bathroom_door"),
            Transaction(action="move", actor="rainee", target="master_bathroom"),
            Transaction(action="lock", actor="rainee", target="master_bathroom_door"),
            Transaction(action="morph_prop", actor="rainee", target="toilet", params={"form": "double_wide_black_lacquer_lotus"}),
            Transaction(action="seat_claim", actor="rainee", target="toilet"),
        ],
        raw_dialogue=[],
        aesthetic_tags=["nanite_morph", "double_wide_throne", "black_lacquer", "gold_lotus_filigree", "image8"],
    ))

    # Beat 6: HVAC Shouting Exchange
    dag.add_beat(BeatNode(
        id="beat_06_strained_shouting_hvac",
        name="Strained Shouting Across HVAC",
        scene_id="act_02_master_bathroom",
        description="Francine yells up from foot of stairs about leaving in thirty minutes; Rainee screams back from throne through door.",
        primary_character="rainee",
        dependencies=["beat_05_bathroom_sprint_commode_morph", "beat_01_francine_kitchen_briefing"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom"),
            LocationPrecondition("francine", "kitchen"),
            SensoryPrecondition("rainee", "kitchen", "hearing", 0.3),
        ],
        transactions=[Transaction(action="move", actor="francine", target="living_room")],
        raw_dialogue=[
            {
                "speaker": "FRANCINE",
                "parenthetical": "O.S., yelling from downstairs",
                "text": "We're leaving in thirty minutes, Rainee!",
                "frozen": True,
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "yelling from the bathroom, voice trembling",
                "text": "In a minute, Francine!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["strained_vocal_denial", "hvac_acoustic_link"],
    ))

    # Beat 7: Acoustic Porcelain Detonation & Water Ripples
    dag.add_beat(BeatNode(
        id="beat_07_acoustic_porcelain_detonation",
        name="Acoustic Porcelain Detonation & Shockwave Ripples",
        scene_id="act_02_master_bathroom",
        description="Rainee releases; concussive acoustic resonance shakes tiles, concentric shockwave ripples in bowl water, towel muffle blown clear across room.",
        primary_character="rainee",
        dependencies=["beat_06_strained_shouting_hvac"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom"),
            PortalPrecondition("master_bathroom_door", PortalState.LOCKED),
        ],
        transactions=[
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "evacuating", "gas_pressure_psi": 14.0}
            }),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "whisper, clutching brass rails",
                "text": "Oh God... breathe, Rainee... Jeff, I am personally launching you into the sun!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["acoustic_porcelain_resonance", "water_ripple_shockwaves", "towel_muffle_blowout", "lilac_methane_fog"],
    ))

    # Beat 8: Haley Hallway Scent Discovery & Standoff
    dag.add_beat(BeatNode(
        id="beat_08_haley_hallway_scent_discovery",
        name="Haley Hallway Scent Discovery & Verbal Standoff",
        scene_id="act_02_master_bathroom",
        description="Haley pads to master bathroom door, encounters dense lilac perfume fog billowing under oak door, calls out dead flower shop line.",
        primary_character="haley",
        dependencies=["beat_02_haley_toot_quip_stella_banter", "beat_07_acoustic_porcelain_detonation"],
        preconditions=[
            LocationPrecondition("haley", "staircase"),
            PortalPrecondition("master_bathroom_door", PortalState.LOCKED),
        ],
        transactions=[
            Transaction(action="move", actor="haley", target="upstairs_hallway"),
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "muffled through closed door, waving smog away",
                "text": "Mom! Are you farting up there? It smells like a flower shop died!",
                "frozen": True,
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "mortified through wood",
                "text": "Quiet, Haley!!!! Oh god, it must have been that burrito last night... Never trust Jeff to buy us dinner!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "unimpressed, laughing",
                "text": "I knew it! That food truck behind the head shop has a C-minus health rating!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["dead_flower_shop_smog", "oak_door_vibrations", "burrito_confession"],
    ))

    # Beat 9: Monster Farce Blast & Haley Downstairs Retreat
    dag.add_beat(BeatNode(
        id="beat_09_monster_blast_haley_retreat",
        name="Monster Farce Blast & Haley Downstairs Retreat",
        scene_id="act_02_master_bathroom",
        description="Massive monster fart echoes against porcelain. Rainee wipes, flushes. Haley retreats downstairs before vents spread odor.",
        primary_character="haley",
        dependencies=["beat_08_haley_hallway_scent_discovery"],
        preconditions=[
            LocationPrecondition("haley", "upstairs_hallway"),
            LocationPrecondition("rainee", "master_bathroom"),
        ],
        transactions=[
            Transaction(action="move", actor="haley", target="staircase"),
            Transaction(action="move", actor="haley", target="living_room"),
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={
                "somatic": {"gut_state": "spasm_subsiding", "gas_pressure_psi": 4.0}
            }),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "whispering to mirror",
                "text": "Okay… breathe, Rainee. We're fine. The crisis is over.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["monster_blast", "power_flush", "retreat_downstairs"],
    ))

    # Beat 10: Bandage Dress Struggle, Mid-Line Interruption & 'Nailed It' (Ref: Image 6)
    dag.add_beat(BeatNode(
        id="beat_10_bandage_dress_struggle_nailed_it",
        name="Bandage Dress Zipper Struggle & 'Nailed It'",
        scene_id="act_02_master_bedroom",
        description="Rainee wrangles the tight crimson bandage dress over massive hips; zipper screeches under load; cut off mid-mantra by sharp toot; rallies with 'Nailed it.'",
        primary_character="rainee",
        dependencies=["beat_09_monster_blast_haley_retreat"],
        preconditions=[
            LocationPrecondition("rainee", "master_bathroom"),
        ],
        transactions=[
            Transaction(action="unlock", actor="rainee", target="master_bathroom_door"),
            Transaction(action="open", actor="rainee", target="master_bathroom_door"),
            Transaction(action="move", actor="rainee", target="master_bedroom"),
            Transaction(action="take", actor="rainee", target="red_bandage_dress"),
            Transaction(action="wear", actor="rainee", target="red_bandage_dress"),
            Transaction(action="posture_change", actor="rainee", target="rainee", params={"posture": Posture.STANDING}),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "whispering in mirror",
                "text": "Okay. Wooh boy, that seems to have quieted down. We're fine. We are going to walk downstairs, and we are going to be a gorgeous— OH!",
                "frozen": True,
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "recovering, small and satisfied",
                "text": "Nailed it.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["bandage_dress_zipper", "mid_line_fart_cutoff", "nailed_it", "image6"],
    ))

    # =========================================================================
    # ACT III: LIVING ROOM DETONATION & DUAL METAMORPHOSIS (7:42 A.M.)
    # =========================================================================

    # Beat 11: Staircase Descent & Jeff Ass Quip (Ref: Image 9)
    dag.add_beat(BeatNode(
        id="beat_11_staircase_descent_jeff_ass_quip",
        name="Staircase Descent & Jeff Ass Banter",
        scene_id="act_03_living_room",
        description="Rainee descends staircase gripping bannister; Stella & Haley quip about Richter scale; Rainee burns Haley about inheriting Jeff's flat white-boy ass.",
        primary_character="rainee",
        dependencies=["beat_10_bandage_dress_struggle_nailed_it"],
        preconditions=[
            LocationPrecondition("rainee", "master_bedroom"),
            LocationPrecondition("haley", "living_room"),
            LocationPrecondition("stella", "living_room"),
            LocationPrecondition("francine", "living_room"),
        ],
        transactions=[
            Transaction(action="move", actor="rainee", target="upstairs_hallway"),
            Transaction(action="move", actor="rainee", target="staircase"),
            Transaction(action="move", actor="rainee", target="living_room"),
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "smirk from papasan",
                "text": "One wrong torque on those platform heels and that thing you're smuggling back there is gonna register on the Richter scale in Delaware.",
                "frozen": True,
            },
            {
                "speaker": "RAINEE",
                "parenthetical": "voice strained, lips twitching",
                "text": "Haley... sweetie... just because you inherited your boyfriend Jeff's tragic flat-white-boy rear is no excuse to be catty... Hhhk!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "freezing mid-eyeroll, processing the biological absurdity for two seconds, then outraged",
                "text": "Wait. What?! Are you saying I have a flat white-boy butt?! HEY!",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "cackling over iced coffee",
                "text": "Don't body-shame the masterpiece! That's a high-renaissance Botticelli with eighty pounds of celestial bounce!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["staircase_descent", "richter_scale_quip", "jeff_flat_ass_burn", "image9"],
    ))

    # Beat 12: Concussive Living Room Detonation & Haley Launch
    dag.add_beat(BeatNode(
        id="beat_12_concussive_detonation_haley_launch",
        name="Concussive Living Room Detonation & Haley Launch",
        scene_id="act_03_living_room",
        description="Rainee's dam bursts; massive concussive flatulent shockwave launches Haley 6 feet across room into coffee table crash.",
        primary_character="rainee",
        dependencies=["beat_11_staircase_descent_jeff_ass_quip"],
        preconditions=[
            LocationPrecondition("rainee", "living_room"),
            LocationPrecondition("haley", "living_room"),
        ],
        transactions=[
            Transaction(action="somatic_update", actor="rainee", target="rainee", params={"somatic": {"gut_state": "detonated", "gas_pressure_psi": 0.0}}),
            Transaction(action="move", actor="haley", target="behind_sofa"),
            Transaction(action="posture_change", actor="haley", target="haley", params={"posture": Posture.PRONE}),
        ],
        raw_dialogue=[
            {
                "speaker": "HALEY",
                "parenthetical": "flying through the air",
                "text": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH!-crash-",
                "frozen": True,
            },
        ],
        aesthetic_tags=["kinetic_shockwave", "haley_launched", "coffee_table_impact", "lavender_blast_zone"],
    ))

    # Beat 13: Peter Griffin Variant Metamorphosis (Ref: Image 10, 11)
    dag.add_beat(BeatNode(
        id="beat_13_peter_griffin_metamorphosis",
        name="Rainee Peter Griffin Variant Metamorphosis",
        scene_id="act_03_living_room",
        description="Rainee shifts into Peter Griffin variant: cleft butt-chin, bulbous nose, tight white crewneck, painted-on jeans over massive bubble rear, spider tattoo, candy canes.",
        primary_character="rainee",
        dependencies=["beat_12_concussive_detonation_haley_launch"],
        preconditions=[
            LocationPrecondition("rainee", "living_room"),
        ],
        transactions=[
            Transaction(action="morph_self", actor="rainee", target="rainee", params={
                "avatar_id": "peter_griffin_celestial_variant", "clothing": "white crewneck and blue jeans",
            }),
            Transaction(action="take", actor="rainee", target="peppermint_candy_canes"),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "Peter Griffin / Cleveland baritone, massive relief",
                "text": "Aaaaaaaahhh... that is so much better! Felt a huge pressure let off! Oh, sorry Haley, you got caught in the blast zone there!",
                "frozen": True,
            },
            {
                "speaker": "FRANCINE",
                "parenthetical": "snorting with laughter against bannister",
                "text": "Oh my God, that is just hilarious! Snrk! You're coming with me! Clearly you need farting just as much as Baba!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "rubbing skull from floor",
                "text": "My head... ugh. Yes. Totally normal day in this family. Nothing to see here, just Mom cosplaying as a cartoon dad with a Kardashian rear. Move along.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["peter_griffin_variant", "cleft_butt_chin", "painted_on_jeans", "candy_canes", "spider_tattoo", "image11"],
    ))

    # Beat 14: Nurse Pamela Franny Anderson Nanite Transformation (Ref: Image 13, 14, 15)
    dag.add_beat(BeatNode(
        id="beat_14_nurse_pamela_nanite_transfer",
        name="Nurse Pamela Franny Anderson Nanite Transformation",
        scene_id="act_03_living_room",
        description="Francine demands sexy nurse cosplay; Rainee fires finger-gun nanites; Francine morphs into Nurse Pamela Franny Anderson with inflating bust, veil, and thigh-highs.",
        primary_character="francine",
        dependencies=["beat_13_peter_griffin_metamorphosis"],
        preconditions=[
            LocationPrecondition("francine", "living_room"),
            LocationPrecondition("rainee", "living_room"),
        ],
        transactions=[
            Transaction(action="morph_target", actor="rainee", target="francine", params={
                "avatar_id": "nurse_pamela_franny_anderson", "clothing": "Nurse Frann Anderson costume",
            }),
        ],
        raw_dialogue=[
            {
                "speaker": "FRANCINE",
                "parenthetical": "finger-guns at Rainee",
                "text": "You're sick, missus! And I am going to nurse you. Make me into a sexy nurse—stat!",
                "frozen": True,
            },
            {
                "speaker": "NURSE PAMELA FRANNY ANDERSON",
                "parenthetical": "breathy Marilyn-meets-valley-girl purr",
                "text": "Mmm… I’ve got the touch for healing. And squeezing. And maybe a little light spanking if insurance covers it.",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "laughing hysterically, spilling iced coffee",
                "text": "You two are gross. Power-couple gross. Like if Cher and Shrek had a love child.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["nurse_pamela_anderson", "inflating_bust", "white_veil", "thigh_high_garters", "image15"],
    ))

    # Beat 15: Chinese Cultural Heritage Resolution & Departure Warnings
    dag.add_beat(BeatNode(
        id="beat_15_chinese_heritage_resolution",
        name="Chinese Cultural Folklore Resolution & Departure",
        scene_id="act_03_living_room",
        description="Rainee asks about parents' reaction; Francine resolves cultural lore: Rainee looks like Húxiān Niángniáng and Fat God of Fortune Cáishen farting red envelopes; scolds Haley to learn her Chinese heritage.",
        scene_location="living_room",
        primary_character="francine",
        dependencies=["beat_14_nurse_pamela_nanite_transfer"],
        preconditions=[
            LocationPrecondition("francine", "living_room"),
            LocationPrecondition("rainee", "living_room"),
            LocationPrecondition("haley", "behind_sofa"),
        ],
        transactions=[
            Transaction(action="move", actor="francine", target="exterior_driveway"),
            Transaction(action="move", actor="rainee", target="exterior_driveway"),
        ],
        raw_dialogue=[
            {
                "speaker": "RAINEE",
                "parenthetical": "Peter-voiced, scratching cleft chin",
                "text": "Won't your parents mind if you're strutting around their house dressed like the night-shift fantasy of a 90's music video?",
                "frozen": True,
            },
            {
                "speaker": "NURSE PAMELA FRANNY ANDERSON",
                "parenthetical": "waving gold bracelet dismissively",
                "text": "Please—they'll be relieved I didn't marry Stan, and look at you! You look like Húxiān Niángniáng (狐仙娘娘) or the Fat God of Fortune (Cáishen 财神) himself! Extra lucky! They'll probably think you fart red envelopes!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "sotto voce from floor",
                "text": "Never heard of a Fat Fortune Fox Goddess. Sounds like a rejected Pokémon.",
                "frozen": True,
            },
            {
                "speaker": "NURSE PAMELA FRANNY ANDERSON",
                "parenthetical": "pointing nail sternly at Haley",
                "text": "Learn your heritage, Haley, you're also Chinese! Húxiān worship dates back three thousand years! Wikipedia it! Oh, and like—no wild parties, okay? Hold down the fort!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["huxian_niangniang", "caishen_god_of_fortune", "red_envelopes_hongbao", "chinese_heritage_correction"],
    ))

    # =========================================================================
    # ACT IV: THE DRIVEWAY AMBUSH & RUTGERS '08 MOB INVASION (8:15 A.M.)
    # =========================================================================

    # Beat 16: Driveway Peel-Out & Lilac Exhaust Trail (Ref: Image 16)
    dag.add_beat(BeatNode(
        id="beat_16_driveway_peelout",
        name="Sedan Driveway Peel-Out & Lilac Exhaust",
        scene_id="act_04_driveway",
        description="Red sedan peels out down street leaving trail of exhaust and floral lilac perfume hovering over asphalt.",
        scene_location="exterior_driveway",
        primary_character="francine",
        dependencies=["beat_15_chinese_heritage_resolution"],
        preconditions=[
            LocationPrecondition("francine", "exterior_driveway"),
            LocationPrecondition("rainee", "exterior_driveway"),
        ],
        transactions=[
            Transaction(action="move", actor="francine", target="in_transit"),
            Transaction(action="move", actor="rainee", target="in_transit"),
            Transaction(action="move", actor="haley", target="living_room"),
            Transaction(action="posture_change", actor="haley", target="haley", params={"posture": Posture.STANDING}),
            Transaction(action="move", actor="haley", target="exterior_driveway"),
            Transaction(action="move", actor="stella", target="exterior_driveway"),
        ],
        raw_dialogue=[],
        aesthetic_tags=["red_sedan_peelout", "lilac_exhaust_haze", "tire_screech", "image16"],
    ))

    # Beat 17: Roger MTV Regalia & Highway Motel Bribe (Ref: Image 17)
    dag.add_beat(BeatNode(
        id="beat_17_roger_mtv_motel_bribe",
        name="Roger MTV Regalia & Highway Motel Bribe Attempt",
        scene_id="act_04_driveway",
        description="Roger in 1998 MTV beach host wig and cutoff shorts yells after departing car, then aggressively shoves heavy backpacks into Haley & Stella to bribe them to highway motel.",
        primary_character="roger",
        dependencies=["beat_16_driveway_peelout"],
        preconditions=[
            LocationPrecondition("roger", "driveway_offstage"),
            LocationPrecondition("haley", "exterior_driveway"),
            LocationPrecondition("stella", "exterior_driveway"),
        ],
        transactions=[
            Transaction(action="take", actor="roger", target="backpacks"),
            Transaction(action="move", actor="roger", target="exterior_driveway"),
            Transaction(action="adopt_persona", actor="roger", target="roger", params={"avatar_id": "mtv_beach_host"}),
        ],
        raw_dialogue=[
            {
                "speaker": "ROGER",
                "parenthetical": "yelling after car, then hissing to girls",
                "text": "—that you're taking the girls! (to Haley and Stella) Did you two do something? Say you'll buy them jewelry! (yelling again) They'll buy you jewelry! (snapping) Jewelry? What are you, crazy? On your allowance?",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "crossing arms",
                "text": "Cut the crap, Roger. Francine and Rainee left us three trays of lasagna and the house keys. We're not going anywhere.",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "squinting at wig",
                "text": "Yeah, and why are you dressed like a 1998 MTV beach house host?",
                "frozen": True,
            },
            {
                "speaker": "ROGER",
                "parenthetical": "shoving backpacks into their chests",
                "text": "Mmm, say, wouldn't you two rather have this conversation with each other in a motel? The place off the freeway is nice.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["mtv_host_wig", "backpack_shove", "highway_motel_con", "image17"],
    ))

    # Beat 18: Roger Cold Eviction Threat
    dag.add_beat(BeatNode(
        id="beat_18_roger_cold_eviction_threat",
        name="Roger Deadpan Eviction Threat",
        scene_id="act_04_driveway",
        description="Stella pushes backpack back; Roger deadpans chillingly that their moms hate them and they should go kill themselves in the freeway motel.",
        primary_character="roger",
        dependencies=["beat_17_roger_mtv_motel_bribe"],
        preconditions=[
            LocationPrecondition("roger", "exterior_driveway"),
            LocationPrecondition("haley", "exterior_driveway"),
            LocationPrecondition("stella", "exterior_driveway"),
        ],
        transactions=[],
        raw_dialogue=[
            {
                "speaker": "STELLA",
                "parenthetical": "pushing bag back",
                "text": "We live here! Why would we go sit in a roach motel when our moms finally gave us the house for a full week?",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "text": "Wait a second... you're up to something. Did you rent out the backyard again?",
                "frozen": True,
            },
            {
                "speaker": "ROGER",
                "parenthetical": "pointing finger deadpan in their faces",
                "text": "Francine and Rainee hate you. You should both go kill yourselves in the motel off the freeway.",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "text": "Are you trying to get rid of us?!",
                "frozen": True,
            },
            {
                "speaker": "ROGER",
                "parenthetical": "switching to innocent smile",
                "text": "That's ridiculous! Why would I want to get rid of you? I love you guys. Go wait for me in the motel off the freeway.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["deadpan_threat", "psychopathic_pivot", "motel_obsession"],
    ))

    # Beat 19: Rutgers '08 Charter Bus Arrival & Royal Metamorphosis (Ref: Image 17)
    dag.add_beat(BeatNode(
        id="beat_19_rutgers_bus_royal_transformation",
        name="Rutgers Charter Bus Arrival & Roger Royal Metamorphosis",
        scene_id="act_04_driveway",
        description="Heavy diesel rumble cuts Stella off. Roger dons royal purple velvet cape, ruby scepter, and megaphone as massive Rutgers '08 bus screeches to curb.",
        primary_character="roger",
        dependencies=["beat_18_roger_cold_eviction_threat"],
        preconditions=[
            LocationPrecondition("roger", "exterior_driveway"),
        ],
        transactions=[
            Transaction(action="take", actor="roger", target="purple_cape"),
            Transaction(action="wear", actor="roger", target="purple_cape"),
            Transaction(action="take", actor="roger", target="ruby_scepter"),
            Transaction(action="take", actor="roger", target="megaphone"),
            Transaction(action="adopt_persona", actor="roger", target="roger", params={"avatar_id": "rutgers_royal_persona"}),
            Transaction(action="move", actor="college_mob", target="rutgers_bus"),
        ],
        raw_dialogue=[
            {
                "speaker": "ROGER",
                "parenthetical": "checking invisible wrist",
                "text": "Op, too late, here we go!",
                "frozen": True,
            },
            {
                "speaker": "ROGER",
                "parenthetical": "into megaphone, booming",
                "text": "Welcome, Rutgers, to Spring Break '08!",
                "frozen": True,
            },
            {
                "speaker": "COLLEGE STUDENTS",
                "parenthetical": "cheering from windows",
                "text": "Woooo! Yeah!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "waving arms at bus driver",
                "text": "Whoa, whoa, no! Hey, bus driver! Turn around! This is a residential street, there is no Spring Break here!",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "grabbing Roger's cape",
                "text": "Roger, call them off right now! Rainee is gonna vaporize us if they touch her vanity room!",
                "frozen": True,
            },
        ],
        aesthetic_tags=["rutgers_charter_bus", "purple_royal_cape", "ruby_scepter", "megaphone_blast", "image17"],
    ))

    # Beat 20: Blue Shopping Cart, Butt Plug Distribution & House Overrun (Ref: Image 17)
    dag.add_beat(BeatNode(
        id="beat_20_butt_plug_distribution_mob_overrun",
        name="Blue Cart Goody Bags, Butt Plug Reveal & Mob Overrun",
        scene_id="act_04_driveway",
        description="Roger rolls blue wire shopping cart of goody bags, hip-checks girls aside, explains wristband colors, confirms silicone butt plug to frat guy, and college mob overruns the house.",
        primary_character="roger",
        dependencies=["beat_19_rutgers_bus_royal_transformation"],
        preconditions=[
            LocationPrecondition("roger", "exterior_driveway"),
            LocationPrecondition("haley", "exterior_driveway"),
            LocationPrecondition("stella", "exterior_driveway"),
        ],
        transactions=[
            Transaction(action="take", actor="roger", target="blue_shopping_cart"),
            Transaction(action="move", actor="college_mob", target="exterior_driveway"),
            Transaction(action="move", actor="college_mob", target="living_room"),
            Transaction(action="move", actor="haley", target="pinned_at_garage"),
            Transaction(action="move", actor="stella", target="pinned_at_garage"),
        ],
        raw_dialogue=[
            {
                "speaker": "ROGER",
                "parenthetical": "megaphone to mob",
                "text": "Get your goody bags! Inside are wristbands—red for cabanas, blue for the beer line.",
                "frozen": True,
            },
            {
                "speaker": "FRAT GUY",
                "parenthetical": "holding up small plastic baggie",
                "text": "What's this?",
                "frozen": True,
            },
            {
                "speaker": "ROGER",
                "parenthetical": "delighted, grandmotherly warmth",
                "text": "Why, it's a butt plug, young man.",
                "frozen": True,
            },
            {
                "speaker": "FRAT GUY",
                "parenthetical": "pumping fist in triumphant ecstasy",
                "text": "YEAH!",
                "frozen": True,
            },
            {
                "speaker": "HALEY",
                "parenthetical": "pinned against garage door",
                "text": "...I am going to murder that alien with my bare hands.",
                "frozen": True,
            },
            {
                "speaker": "STELLA",
                "parenthetical": "snatching a red cup from the mob",
                "text": "Not until we finish the keg, Haley. If we're getting executed by Rainee on Sunday, I'm dying intoxicated.",
                "frozen": True,
            },
        ],
        aesthetic_tags=["blue_shopping_cart", "silicone_butt_plug", "frat_guy_triumph", "mob_overrun", "image17"],
    ))

    return dag
