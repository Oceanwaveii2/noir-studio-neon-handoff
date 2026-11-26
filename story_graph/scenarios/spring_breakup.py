"""
Spring Breakup Canonical Scenario Builder for Story Graph.
Milestone M-SG1: World State Ledger & Fluent Tracker.
"""

from __future__ import annotations

from ..models import (
    CharacterState,
    Location,
    Portal,
    PortalState,
    Posture,
    PropState,
)
from ..world_state import StoryWorldState


def build_spring_breakup_world() -> StoryWorldState:
    """Builds the canonical world state for S04E16 'Spring Breakup' scenes 1-3."""
    world = StoryWorldState(title="Ling House - Spring Breakup")

    # 1. Locations
    kitchen = Location(id="kitchen", name="Kitchen", floor=1)
    living_room = Location(id="living_room", name="Living Room", floor=1)
    staircase = Location(id="staircase", name="Central Staircase", floor=1)
    upstairs_hallway = Location(id="upstairs_hallway", name="Second Floor Hallway", floor=2)
    master_bedroom = Location(id="master_bedroom", name="Master Bedroom", floor=2)
    master_bathroom = Location(id="master_bathroom", name="Master Bathroom", floor=2)

    for loc in (kitchen, living_room, staircase, upstairs_hallway, master_bedroom, master_bathroom):
        world.add_location(loc)

    # 2. Portals
    world.add_portal(Portal(
        id="archway_kitchen_living",
        name="Kitchen-Living Room Archway",
        from_location="kitchen",
        to_location="living_room",
        state=PortalState.OPEN,
        allows_sound=True,
        sound_attenuation=0.9,
        allows_scent=True,
        scent_permeability=0.8,
        allows_sight=True
    ))

    world.add_portal(Portal(
        id="living_to_stairs",
        name="Living Room to Stairs",
        from_location="living_room",
        to_location="staircase",
        state=PortalState.OPEN,
        allows_sound=True,
        sound_attenuation=0.85,
        allows_scent=True,
        scent_permeability=0.8,
        allows_sight=True
    ))

    world.add_portal(Portal(
        id="stairs_to_landing",
        name="Stairs to Second Floor Landing",
        from_location="staircase",
        to_location="upstairs_hallway",
        state=PortalState.OPEN,
        allows_sound=True,
        sound_attenuation=0.8,
        allows_scent=True,
        scent_permeability=0.75,
        allows_sight=True
    ))

    world.add_portal(Portal(
        id="hallway_to_master_bedroom",
        name="Master Bedroom Door",
        from_location="upstairs_hallway",
        to_location="master_bedroom",
        state=PortalState.OPEN,
        allows_sound=True,
        sound_attenuation=0.7,
        allows_scent=True,
        scent_permeability=0.7,
        allows_sight=True
    ))

    # The crucial en-suite bathroom door
    world.add_portal(Portal(
        id="master_bathroom_door",
        name="Master Bathroom Door",
        from_location="master_bedroom",
        to_location="master_bathroom",
        state=PortalState.OPEN,  # initially open before Rainee rushes in and locks it
        lock_type="deadbolt",
        locked_from="master_bathroom",
        allows_sound=True,
        sound_attenuation=0.5,
        allows_scent=True,
        scent_permeability=0.65,  # gap under door rolls draft out
        allows_sight=False
    ))

    # Heating duct connecting kitchen and master bathroom acoustically
    world.add_portal(Portal(
        id="hvac_duct_kitchen_bathroom",
        name="HVAC Vent Shaft",
        from_location="kitchen",
        to_location="master_bathroom",
        state=PortalState.OPEN,
        allows_sound=True,
        sound_attenuation=0.45,  # voices carry up/down the vent
        allows_scent=False,
        allows_sight=False
    ))

    # 3. Characters
    francine = CharacterState(
        id="francine",
        name="Francine Ling",
        location="kitchen",
        posture=Posture.STANDING,
        clothing="crisp linen blazer and white jeans",
        inventory=["cherry_overnight_bag"],
        somatic={"mood": "rushed_authority", "schedule": "on_time"},
        physique={"hair": "platinum_bouffant", "heels": "four_inch_stilettos"}
    )

    haley = CharacterState(
        id="haley",
        name="Haley Ling",
        location="living_room",
        posture=Posture.SEATED,
        clothing="oversized charcoal Nirvana T-shirt",
        inventory=["smartphone"],
        somatic={"mood": "cynical_slacker", "energy": "horizontal"},
        physique={"age": 23}
    )

    rainee = CharacterState(
        id="rainee",
        name="Rainee",
        location="master_bedroom",
        posture=Posture.SEATED,
        clothing="peach silk kimono robe",
        inventory=["lipstick"],
        somatic={
            "gut_state": "normal",
            "gas_volume_ml": 120,
            "colic_pain": 0,
            "perfume_scent": "french_gardenia_and_moroccan_rosewater"
        },
        physique={
            "species": "anthropomorphic_vixen",
            "curves": "brazilian_acoustic_guitar",
            "hips": "voluptuous_bubble_butt",
            "ears": "pointed_auburn_fox_ears",
            "tail": "plush_amber_and_cream_brush"
        }
    )

    world.add_character(francine)
    world.add_character(haley)
    world.add_character(rainee)

    # 4. Props
    world.add_prop(PropState(
        id="cherry_overnight_bag",
        name="Cherry Cough Syrup Duffel Bag",
        location="held:francine",
        properties={"telescoping_handle": "retracted"}
    ))

    world.add_prop(PropState(
        id="smartphone",
        name="Haley's iPhone",
        location="held:haley",
        properties={"screen": "tiktok_feed", "glow": "cyan"}
    ))

    world.add_prop(PropState(
        id="lipstick",
        name="Gold Tube Crimson Lipstick",
        location="held:rainee",
        properties={"capped": False}
    ))

    world.add_prop(PropState(
        id="guest_towel",
        name="Fluffy Egyptian Cotton Guest Towel",
        location="master_bathroom",
        properties={"muffle_efficiency": 0.05}
    ))

    return world
