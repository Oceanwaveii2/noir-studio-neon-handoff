"""Source-anchored, offline execution of the 20-beat Spring Break graph."""
from __future__ import annotations

from ..character_forms import CharacterJunction
from ..compiler import BeatPacket, BeatPacketCompiler
from ..dag import BeatSequencer
from ..epistemic import EpistemicLedger, Fact
from ..models import CharacterState, Location, Portal, PortalState, Posture, PropState
from ..world_state import StoryWorldState
from .foxy_mo2_dag import build_foxy_mo2_dag


def build_foxy_mo2_world() -> StoryWorldState:
    """Initial state from MO2 stage directions, with abstract movement zones."""
    world = StoryWorldState("Spring Break — MO2")
    for key, name, floor, offstage in (
        ("kitchen", "Ling House — Kitchen", 1, False),
        ("living_room", "Ling House — Living Room", 1, False),
        ("behind_sofa", "Behind the Living Room Sofa", 1, False),
        ("staircase", "Ling House — Staircase", 1, False),
        ("upstairs_hallway", "Ling House — Upstairs Hall", 2, False),
        ("master_bedroom", "Ling House — Master Bedroom", 2, False),
        ("master_bathroom", "Ling House — Master Bathroom", 2, False),
        ("exterior_driveway", "Ling House — Driveway", 1, False),
        ("pinned_at_garage", "Ling House — Garage Door", 1, False),
        ("in_transit", "Red Sedan in Transit", 1, False),
        ("driveway_offstage", "Roger Offstage", 1, True),
        ("bus_offstage", "Charter Bus Offstage", 1, True),
        ("rutgers_bus", "Charter Bus at Curb", 1, False),
    ):
        world.add_location(Location(key, name, floor=floor, ambient={"offstage": offstage}))
    for key, a, b in (
        ("kitchen_threshold", "kitchen", "living_room"),
        ("living_to_stairs", "living_room", "staircase"),
        ("stairs_to_landing", "staircase", "upstairs_hallway"),
        ("hallway_to_master_bedroom", "upstairs_hallway", "master_bedroom"),
        ("sofa_zone", "living_room", "behind_sofa"),
        ("front_entry", "living_room", "exterior_driveway"),
        ("garage_zone", "exterior_driveway", "pinned_at_garage"),
        ("sedan_departure", "exterior_driveway", "in_transit"),
        ("roger_entrance", "driveway_offstage", "exterior_driveway"),
        ("charter_arrival", "bus_offstage", "rutgers_bus"),
        ("bus_at_curb", "rutgers_bus", "exterior_driveway"),
    ):
        world.add_portal(Portal(key, key.replace("_", " "), a, b, state=PortalState.OPEN))
    world.add_portal(Portal("master_bathroom_door", "Master bathroom door", "master_bedroom",
                            "master_bathroom", state=PortalState.CLOSED, locked_from="master_bathroom"))
    # The production archive describes the hallway hearing/smelling through the
    # closed door. This sensory seam is not a second traversable door.
    world.add_portal(Portal("hall_bath_seam", "Hallway sound and scent seam", "upstairs_hallway",
                            "master_bathroom", allows_traversal=False))
    world.add_portal(Portal("hvac_duct_kitchen_bathroom", "HVAC vent", "kitchen", "master_bathroom",
                            sound_attenuation=0.45, allows_scent=False, allows_traversal=False))
    for key, name, loc, posture, clothing in (
        ("francine", "Francine Ling", "kitchen", Posture.STANDING, "pink pencil dress"),
        ("haley", "Haley Ling", "living_room", Posture.SEATED, "black Nirvana tee and jeans"),
        ("stella", "Stella Ling", "living_room", Posture.SEATED, "cat-eye sunglasses"),
        ("rainee", "Rainee Ling", "master_bedroom", Posture.SEATED, "emerald silk robe"),
        ("roger", "Roger", "driveway_offstage", Posture.STANDING, ""),
        ("college_mob", "Rutgers students", "bus_offstage", Posture.SEATED, ""),
    ):
        world.add_character(CharacterState(key, name, loc, posture, clothing))
    world.characters["rainee"].somatic["gut_state"] = "normal"
    for key, name, loc, props in (
        ("cherry_suitcase", "Cherry overnight suitcase", "kitchen", {}),
        ("silver_brush", "Silver brush", "master_bedroom", {}),
        ("red_bandage_dress", "crimson bandage dress", "master_bedroom", {"wearable": True}),
        ("toilet", "Master bathroom commode", "master_bathroom", {
            "form": "standard_porcelain", "seat_units": 1,
            "morph_forms": {"double_wide_black_lacquer_lotus": {"seat_units": 2}},
        }),
        ("peppermint_candy_canes", "Peppermint candy canes", "living_room", {
            "first_take_beat": "beat_13_peter_griffin_metamorphosis",
        }),
        ("backpacks", "Neon backpacks", "driveway_offstage", {
            "first_take_beat": "beat_17_roger_mtv_motel_bribe",
        }),
        ("purple_cape", "Purple velvet cape", "exterior_driveway", {
            "first_take_beat": "beat_19_rutgers_bus_royal_transformation", "wearable": True,
        }),
        ("ruby_scepter", "Ruby scepter", "exterior_driveway", {
            "first_take_beat": "beat_19_rutgers_bus_royal_transformation",
        }),
        ("megaphone", "Megaphone", "exterior_driveway", {
            "first_take_beat": "beat_19_rutgers_bus_royal_transformation",
        }),
        ("blue_shopping_cart", "Blue shopping cart", "exterior_driveway", {
            "first_take_beat": "beat_20_butt_plug_distribution_mob_overrun",
        }),
    ):
        world.add_prop(PropState(key, name, loc, props))
    world.form_reveal_beats = {
        "rainee": {"peter_griffin_celestial_variant": "beat_13_peter_griffin_metamorphosis"},
        "francine": {"nurse_pamela_franny_anderson": "beat_14_nurse_pamela_nanite_transfer"},
        "roger": {"mtv_beach_host": "beat_17_roger_mtv_motel_bribe",
                  "rutgers_royal_persona": "beat_19_rutgers_bus_royal_transformation"},
    }
    return world


def run_foxy_mo2(junctions: dict[str, CharacterJunction] | None = None) -> list[BeatPacket]:
    """Run the real graph and apply source-backed disclosures at their beat boundaries."""
    world = build_foxy_mo2_world()
    dag = build_foxy_mo2_dag()
    seq = BeatSequencer(dag, world)
    ledger = EpistemicLedger()
    ledger.register_fact(Fact("baba_recovering", "Baba is recovering from hernia surgery.", ["hernia"]))
    ledger.register_fact(Fact("lasagna_itinerary", "Francine left lasagna dinners.", ["lasagna"]))
    ledger.register_character("francine", ["baba_recovering", "lasagna_itinerary"])
    compiler = BeatPacketCompiler(world, ledger, junctions=junctions)
    packets = []
    for beat_id in dag.validate():
        record = seq.execute_beat(beat_id)
        tick = record["tick"]
        if beat_id == "beat_01_francine_kitchen_briefing":
            for fact in ("baba_recovering", "lasagna_itinerary"):
                ledger.broadcast_speech("francine", fact, world, tick)
        elif beat_id == "beat_04_rainee_gut_coup":
            ledger.register_fact(Fact("burrito_suspected_cause", "Rainee suspects the food truck burrito.",
                                      ["burrito", "carnitas"], origin_tick=tick, is_private=True))
            ledger.grant_knowledge("rainee", "burrito_suspected_cause", "private_deduction", tick)
        elif beat_id == "beat_08_haley_hallway_scent_discovery":
            # Haley smells the distress, then explicitly hears the suspected cause.
            ledger.register_fact(Fact("bathroom_distress", "Rainee is in distress in the bathroom.",
                                      origin_tick=tick, is_private=True))
            if not ledger.infer_from_sensory("haley", "bathroom_distress", "master_bathroom", world, tick):
                raise RuntimeError("The hallway encounter requires a scent path.")
            listeners = ledger.broadcast_speech("rainee", "burrito_suspected_cause", world, tick)
            if "haley" not in listeners:
                raise RuntimeError("Haley must hear the burrito disclosure.")
        elif beat_id == "beat_19_rutgers_bus_royal_transformation":
            ledger.register_fact(Fact("rutgers_takeover", "Roger welcomes the Rutgers students.",
                                      ["Rutgers"], origin_tick=tick))
            ledger.grant_knowledge("roger", "rutgers_takeover", "observation", tick)
            ledger.broadcast_speech("roger", "rutgers_takeover", world, tick)
        packets.append(compiler.compile(record))
    return packets
