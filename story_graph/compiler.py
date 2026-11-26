"""
Story Graph Beat Packet Compiler: The bridge interface between Story Graph and Prose Engine.
Milestone M-SG4: Beat Packet Compiler.
Compiles lean, un-hallucinated structural beat data from World State, Causal DAG,
and Epistemic Ledger into machine-readable JSON and lean Screenplay Markdown.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .character_forms import AFM_JUNCTIONS, CharacterJunction
from .epistemic import EpistemicLedger
from .world_state import StoryWorldState


@dataclass
class BeatPacket:
    """
    Standardized, self-contained data packet representing one atomic story beat.
    The Prose Engine consumes this to execute targeted aesthetic retrieval and styling.
    """
    beat_id: str
    name: str
    scene_id: str
    slugline: str
    tick: int
    description: str
    characters_present: List[str] = field(default_factory=list)
    characters_adjacent: List[str] = field(default_factory=list)
    spatial_context: Dict[str, Any] = field(default_factory=dict)
    somatic_context: Dict[str, Any] = field(default_factory=dict)
    epistemic_context: Dict[str, Any] = field(default_factory=dict)
    sensory_links: List[Dict[str, Any]] = field(default_factory=list)
    state_deltas: List[Dict[str, Any]] = field(default_factory=list)
    raw_dialogue: List[Dict[str, Any]] = field(default_factory=list)
    aesthetic_tags: List[str] = field(default_factory=list)
    ontological_context: Dict[str, Any] = field(default_factory=dict)
    world_snapshot_sha256: str | None = None
    negative_constraints: List[Dict[str, str]] = field(default_factory=list)
    form_context: Dict[str, Any] = field(default_factory=dict)
    continuity_context: Dict[str, Any] = field(default_factory=dict)
    epistemic_unknown: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    reader_reveals: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.__dict__)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_screenplay_markdown(self) -> str:
        """Renders lean screenplay markdown with aesthetic annotations."""
        lines = []
        lines.append(f"### {self.slugline}")
        lines.append(f"<!-- BEAT_ID: {self.beat_id} | SCENE: {self.scene_id} | TICK: {self.tick} -->")
        if self.aesthetic_tags:
            tags_str = ", ".join(self.aesthetic_tags)
            lines.append(f"<!-- AESTHETIC_TAGS: [{tags_str}] -->")
        lines.append("")
        lines.append(self.description)
        lines.append("")

        for d in self.raw_dialogue:
            speaker = d.get("speaker", "UNKNOWN")
            parenthetical = d.get("parenthetical")
            text = d.get("text", "")
            lines.append(speaker)
            if parenthetical:
                lines.append(f"({parenthetical})")
            lines.append(text)
            lines.append("")

        return "\n".join(lines).rstrip()


class BeatPacketCompiler:
    """
    Compiles live StoryWorldState and EpistemicLedger states into BeatPackets.
    """

    def __init__(
        self,
        world: StoryWorldState,
        ledger: Optional[EpistemicLedger] = None,
        ontology_compiler: Optional[Any] = None,
        junctions: Optional[Dict[str, CharacterJunction]] = None,
    ):
        self.world = world
        self.ledger = ledger
        self.ontology_compiler = ontology_compiler
        self.junctions = AFM_JUNCTIONS if junctions is None else junctions

    def compile(self, beat_record: Dict[str, Any]) -> BeatPacket:
        """
        Compiles an execution record from BeatSequencer into a formal BeatPacket.
        """
        beat_id = beat_record["beat_id"]
        scene_id = beat_record.get("scene_id", "scene_unknown")
        name = beat_record.get("beat_name", beat_id)
        description = beat_record.get("description", "")
        tick = beat_record.get("tick", self.world.tick)
        aesthetic_tags = beat_record.get("aesthetic_tags", [])
        raw_dialogue = beat_record.get("raw_dialogue", [])
        transaction_results = beat_record.get("transaction_results", [])

        snapshot = beat_record.get("world_after")
        if snapshot is not None and snapshot["tick"] != tick:
            raise ValueError("The world snapshot does not match the beat tick.")
        if snapshot is None and tick != self.world.tick:
            raise ValueError("Historical beat compilation requires its recorded world snapshot.")
        world = StoryWorldState.from_snapshot(snapshot) if snapshot is not None else self.world
        snapshot_digest = (
            hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()
            if snapshot is not None else None
        )

        # 1. Determine active and adjacent characters
        primary_char = beat_record.get("primary_character")
        speakers = {d["speaker"].lower() for d in raw_dialogue if "speaker" in d}
        actors = {tx["actor"].lower() for tx in transaction_results if "actor" in tx}
        if primary_char:
            active_char_ids = sorted(list(speakers | actors | {primary_char.lower()}))
        else:
            active_char_ids = sorted(list(speakers | actors))

        if not active_char_ids and world.characters:
            active_char_ids = [list(world.characters.keys())[0]]

        # Determine primary location and slugline
        primary_loc_id = "unknown"
        if primary_char and primary_char.lower() in world.characters:
            primary_loc_id = world.characters[primary_char.lower()].location
        elif active_char_ids and active_char_ids[0] in world.characters:
            primary_loc_id = world.characters[active_char_ids[0]].location

        scene_location = beat_record.get("scene_location") or primary_loc_id
        loc_obj = world.locations.get(scene_location)
        loc_name = loc_obj.name.upper() if loc_obj else primary_loc_id.upper()
        interior = "EXT." if scene_location.startswith("exterior_") else "INT."
        slugline = f"{interior} {loc_name} - CONTINUOUS"

        # 2. Characters Present vs. Adjacent
        visible = {
            cid: char for cid, char in world.characters.items()
            if not world.locations[char.location].ambient.get("offstage")
        }
        characters_present = [
            c_id for c_id, c in visible.items()
            if c.location == scene_location
        ]
        characters_adjacent = [
            c_id for c_id, c in visible.items()
            if c.location != scene_location
        ]

        # 3. Spatial Context
        spatial_context = {
            "locations": {
                scene_location: {
                    "name": loc_name,
                    "connected_portals": {
                        p_id: world.portals[p_id].state.value
                        for p_id in (loc_obj.connected_portals if loc_obj else [])
                    }
                }
            },
            "characters": {
                c_id: {
                    "location": world.characters[c_id].location,
                    "posture": world.characters[c_id].posture.value,
                    "clothing": world.characters[c_id].clothing,
                    "inventory": list(world.characters[c_id].inventory)
                } for c_id in characters_present
            }
        }
        scene_props = {prop_id: prop for prop_id, prop in world.props.items()
                       if prop.location == scene_location or prop.holder_id in characters_present}
        spatial_context["prop_locations"] = {prop_id: prop.location for prop_id, prop in scene_props.items()}
        spatial_context["props"] = {
            prop_id: prop.properties["state"] for prop_id, prop in scene_props.items()
            if isinstance(prop.properties.get("state"), str)
        }

        # 4. Somatic Context
        somatic_context = {
            c_id: {
                "somatic": copy.deepcopy(world.characters[c_id].somatic),
                "physique": copy.deepcopy(world.characters[c_id].physique)
            } for c_id in characters_present
        }

        # 5. Epistemic Context (known facts + complement unlearned facts)
        epistemic_context = {}
        epistemic_unknown = {}
        if self.ledger:
            actors_in_scope = characters_present + characters_adjacent
            epistemic_context = {
                c_id: [f.id for f in self.ledger.get_known_facts(c_id, tick=tick)]
                for c_id in actors_in_scope
            }
            epistemic_unknown = {
                c_id: [
                    {
                        "id": f.id,
                        "keywords": list(f.keywords),
                        "is_private": f.is_private,
                        "description": f.description,
                    }
                    for f in self.ledger.get_unknown_facts(c_id, tick=tick)
                ]
                for c_id in actors_in_scope
            }
        reader_reveals = beat_record.get("reader_reveals")
        if reader_reveals is not None:
            if not isinstance(reader_reveals, list) or any(not isinstance(item, str) or not item.strip() for item in reader_reveals):
                raise ValueError("Reader reveals require explicit text entries for this beat.")
            reader_reveals = list(reader_reveals)

        # 6. Sensory Links
        sensory_links = []
        for adj_id in characters_adjacent:
            adj_loc = world.characters[adj_id].location
            can_hear, clarity = world.can_hear(adj_id, scene_location)
            can_smell, intensity = world.can_smell(adj_id, scene_location)
            if can_hear or can_smell:
                sensory_links.append({
                    "listener": adj_id,
                    "listener_location": adj_loc,
                    "target_location": scene_location,
                    "can_hear": can_hear,
                    "acoustic_clarity": clarity,
                    "can_smell": can_smell,
                    "olfactory_intensity": intensity
                })

        # 7. State Deltas
        state_deltas = [
            copy.deepcopy(tx["state_deltas"]) for tx in transaction_results
            if tx.get("state_deltas")
        ]
        form_context = {}
        if world.form_reveal_beats is not None:
            for cid, junction in self.junctions.items():
                if cid in visible:
                    form_context[cid] = junction.project(
                        approved=world.revealed_forms.get(cid, ()), active=visible[cid].active_avatar,
                    )
        continuity_context = {
            "actors": {cid: char.location for cid, char in visible.items()},
            "props": {
                pid: {"location": prop.location, "form": prop.properties.get("form"),
                      "seat_units": prop.properties.get("seat_units")}
                for pid, prop in world.props.items()
                if not prop.properties.get("first_take_beat") and (
                    prop.holder_id in visible if prop.is_held
                    else prop.location in world.locations and not world.locations[prop.location].ambient.get("offstage")
                )
            },
        }

        packet = BeatPacket(
            beat_id=beat_id,
            name=name,
            scene_id=scene_id,
            slugline=slugline,
            tick=tick,
            description=description,
            characters_present=characters_present,
            characters_adjacent=characters_adjacent,
            spatial_context=spatial_context,
            somatic_context=somatic_context,
            epistemic_context=epistemic_context,
            reader_reveals=reader_reveals,
            sensory_links=sensory_links,
            state_deltas=state_deltas,
            raw_dialogue=copy.deepcopy(raw_dialogue),
            world_snapshot_sha256=snapshot_digest,
            aesthetic_tags=list(aesthetic_tags),
            form_context=form_context,
            continuity_context=continuity_context,
            epistemic_unknown=epistemic_unknown,
        )

        if self.ontology_compiler:
            packet = self.ontology_compiler.enrich_beat_packet(packet)

        return packet

    def compile_all(self, execution_log: List[Dict[str, Any]]) -> List[BeatPacket]:
        return [self.compile(rec) for rec in execution_log]

    def export_manifest(self, packets: List[BeatPacket], path: str | Path) -> None:
        data = {
            "version": "1.0",
            "beat_count": len(packets),
            "packets": [p.to_dict() for p in packets]
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def export_raw_script(self, packets: List[BeatPacket], path: Optional[str | Path] = None) -> str:
        text = "\n\n---\n\n".join([p.to_screenplay_markdown() for p in packets])
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text
