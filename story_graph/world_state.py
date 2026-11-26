"""
Story Graph World State: Deterministic state ledger, fluent tracker, and transaction gate.
Milestone M-SG1: World State Ledger & Fluent Tracker.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .character_forms import AFM_JUNCTIONS
from .models import (
    CharacterState,
    Location,
    Portal,
    PortalState,
    Posture,
    PropState,
    Transaction,
    TransactionResult,
)


class StoryWorldState:
    """
    Deterministic Narrative State Engine.
    Tracks entities, physical affordances, somatic fluents, and validates state transactions.
    """

    def __init__(self, title: str = "StoryWorld"):
        self.title = title
        self.tick: int = 0
        self.locations: Dict[str, Location] = {}
        self.portals: Dict[str, Portal] = {}
        self.characters: Dict[str, CharacterState] = {}
        self.props: Dict[str, PropState] = {}
        self.transaction_history: List[TransactionResult] = []
        # None preserves unscoped legacy fixtures. A scoped scenario explicitly
        # names its permitted forms and the beats that can introduce them.
        self.form_reveal_beats: Dict[str, Dict[str, str]] | None = None
        self.revealed_forms: Dict[str, List[str]] = {}

    # -------------------------------------------------------------------------
    # Entity Registration
    # -------------------------------------------------------------------------

    def add_location(self, location: Location) -> None:
        self.locations[location.id] = location

    def add_portal(self, portal: Portal) -> None:
        self.portals[portal.id] = portal
        # Link portal to locations if not already present
        if portal.from_location in self.locations:
            if portal.id not in self.locations[portal.from_location].connected_portals:
                self.locations[portal.from_location].connected_portals.append(portal.id)
        if portal.to_location in self.locations:
            if portal.id not in self.locations[portal.to_location].connected_portals:
                self.locations[portal.to_location].connected_portals.append(portal.id)

    def add_character(self, character: CharacterState) -> None:
        if character.location not in self.locations:
            raise ValueError(f"Cannot spawn character '{character.name}' in non-existent location '{character.location}'")
        self.characters[character.id] = character

    def add_prop(self, prop: PropState) -> None:
        self.props[prop.id] = prop
        if not prop.is_held and prop.location in self.locations:
            if prop.id not in self.locations[prop.location].props:
                self.locations[prop.location].props.append(prop.id)

    # -------------------------------------------------------------------------
    # Spatial Topology & Queries
    # -------------------------------------------------------------------------

    def get_portal_between(self, loc_a: str, loc_b: str) -> Optional[Portal]:
        for portal in self.portals.values():
            if (portal.from_location == loc_a and portal.to_location == loc_b) or \
               (portal.from_location == loc_b and portal.to_location == loc_a):
                return portal
        return None

    def get_characters_in_location(self, loc_id: str) -> List[CharacterState]:
        return [c for c in self.characters.values() if c.location == loc_id]

    def get_props_in_location(self, loc_id: str) -> List[PropState]:
        return [p for p in self.props.values() if p.location == loc_id]

    # -------------------------------------------------------------------------
    # Sensory Propagation (Acoustic & Olfactory)
    # -------------------------------------------------------------------------

    def can_hear(self, listener_id: str, sound_source_loc: str) -> Tuple[bool, float]:
        """
        Calculates if listener can hear a sound originating in sound_source_loc.
        Returns (can_hear: bool, acoustic_clarity: float [0.0 - 1.0]).
        """
        listener = self.characters.get(listener_id)
        if not listener:
            return False, 0.0

        if listener.location == sound_source_loc:
            return True, 1.0

        # Check direct portal
        portal = self.get_portal_between(listener.location, sound_source_loc)
        if portal and portal.allows_sound:
            clarity = portal.sound_attenuation if portal.state in (PortalState.CLOSED, PortalState.LOCKED) else 0.95
            return True, clarity

        # Check multi-hop acoustic path (max 2 hops)
        for p1_id in self.locations[listener.location].connected_portals:
            p1 = self.portals[p1_id]
            adj_loc = p1.to_location if p1.from_location == listener.location else p1.from_location
            p2 = self.get_portal_between(adj_loc, sound_source_loc)
            if p2 and p1.allows_sound and p2.allows_sound:
                c1 = p1.sound_attenuation if p1.state != PortalState.OPEN else 0.9
                c2 = p2.sound_attenuation if p2.state != PortalState.OPEN else 0.9
                return True, round(c1 * c2 * 0.7, 2)

        return False, 0.0

    def can_smell(self, sniffer_id: str, scent_source_loc: str) -> Tuple[bool, float]:
        """
        Calculates if sniffer can detect scent from scent_source_loc.
        Returns (can_smell: bool, intensity: float [0.0 - 1.0]).
        """
        sniffer = self.characters.get(sniffer_id)
        if not sniffer:
            return False, 0.0

        if sniffer.location == scent_source_loc:
            return True, 1.0

        portal = self.get_portal_between(sniffer.location, scent_source_loc)
        if portal and portal.allows_scent:
            intensity = portal.scent_permeability if portal.state in (PortalState.CLOSED, PortalState.LOCKED) else 0.9
            return True, intensity

        return False, 0.0

    # -------------------------------------------------------------------------
    # Transaction Execution & Invariant Verification
    # -------------------------------------------------------------------------

    def execute(self, txn: Transaction, *, beat_id: str | None = None) -> TransactionResult:
        """Executes a transaction, updating working memory if invariants pass."""
        self.tick += 1
        txn.tick = self.tick
        txn.beat_id = beat_id

        handler_name = f"_handle_{txn.action}"
        handler = getattr(self, handler_name, None)
        if not handler:
            res = TransactionResult(
                success=False,
                action=txn.action,
                actor=txn.actor,
                target=txn.target,
                reason=f"Unknown transaction action '{txn.action}'"
            )
            self.transaction_history.append(res)
            return res

        res = handler(txn)
        self.transaction_history.append(res)
        return res

    def _handle_move(self, txn: Transaction) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        dest_id = txn.target
        if dest_id not in self.locations:
            return TransactionResult(False, txn.action, txn.actor, dest_id, f"Destination location '{dest_id}' does not exist.")

        if character.location == dest_id:
            return TransactionResult(False, txn.action, txn.actor, dest_id, f"Character '{txn.actor}' is already in '{dest_id}'.")

        # Verify portal connection
        portal = self.get_portal_between(character.location, dest_id)
        if not portal:
            return TransactionResult(False, txn.action, txn.actor, dest_id, f"No portal connects '{character.location}' to '{dest_id}'.")

        if not portal.is_passable():
            return TransactionResult(
                False, txn.action, txn.actor, dest_id,
                f"Cannot pass through portal '{portal.name}': portal is {portal.state.value}."
            )

        # Execute move
        old_loc = character.location
        character.location = dest_id
        return TransactionResult(
            True, txn.action, txn.actor, dest_id,
            state_deltas={"location": {"from": old_loc, "to": dest_id}}
        )

    def _handle_portal_state(self, txn: Transaction, desired_state: PortalState) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        portal = self.portals.get(txn.target)
        if not portal:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Portal '{txn.target}' not found.")

        # Character must be adjacent to portal
        if character.location not in (portal.from_location, portal.to_location):
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Character '{txn.actor}' is at '{character.location}' and cannot reach portal '{portal.name}'."
            )

        if desired_state == PortalState.LOCKED:
            if portal.locked_from and character.location != portal.locked_from:
                return TransactionResult(
                    False, txn.action, txn.actor, txn.target,
                    f"Portal '{portal.name}' can only be locked from '{portal.locked_from}', actor is in '{character.location}'."
                )
        if desired_state == PortalState.CLOSED and portal.state == PortalState.LOCKED:
            if txn.action != "unlock" or (portal.locked_from and character.location != portal.locked_from):
                return TransactionResult(False, txn.action, txn.actor, txn.target,
                                         f"Cannot release the deadbolt from '{character.location}'.")

        old_state = portal.state
        portal.state = desired_state
        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"portal_state": {"from": old_state.value, "to": desired_state.value}}
        )

    def _handle_lock(self, txn: Transaction) -> TransactionResult:
        return self._handle_portal_state(txn, PortalState.LOCKED)

    def _handle_unlock(self, txn: Transaction) -> TransactionResult:
        return self._handle_portal_state(txn, PortalState.CLOSED)

    def _handle_open(self, txn: Transaction) -> TransactionResult:
        portal = self.portals.get(txn.target)
        if portal and portal.state == PortalState.LOCKED:
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Cannot open portal '{portal.name}': portal is locked."
            )
        return self._handle_portal_state(txn, PortalState.OPEN)

    def _handle_close(self, txn: Transaction) -> TransactionResult:
        return self._handle_portal_state(txn, PortalState.CLOSED)

    def _handle_posture_change(self, txn: Transaction) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        new_posture = Posture(txn.params.get("posture", Posture.STANDING))
        old_posture = character.posture
        character.posture = new_posture
        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"posture": {"from": old_posture.value, "to": new_posture.value}}
        )

    def _handle_somatic_update(self, txn: Transaction) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        updates = txn.params.get("somatic")
        if not isinstance(updates, dict) or not updates:
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Expected non-empty somatic values.")
        if "form" in updates and self.form_reveal_beats is not None:
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Use a scoped form transition.")
        old_somatic = copy.deepcopy(character.somatic)
        character.somatic.update(updates)
        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"somatic": {"old": old_somatic, "new": copy.deepcopy(character.somatic)}}
        )

    def _handle_take(self, txn: Transaction) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        prop = self.props.get(txn.target)
        if not prop:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Prop '{txn.target}' not found.")

        if prop.is_held:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Prop '{txn.target}' is already held by '{prop.holder_id}'.")

        if prop.location != character.location:
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Prop '{txn.target}' is in '{prop.location}', but character is in '{character.location}'."
            )

        first_beat = prop.properties.get("first_take_beat")
        if first_beat and txn.beat_id != first_beat:
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Prop has not entered the scene yet.")

        # Pick up
        if prop.location in self.locations and prop.id in self.locations[prop.location].props:
            self.locations[prop.location].props.remove(prop.id)
        prop.location = f"held:{character.id}"
        prop.properties.pop("first_take_beat", None)
        character.inventory.append(prop.id)

        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"inventory": {"added": prop.id}}
        )

    def _handle_wear(self, txn: Transaction) -> TransactionResult:
        actor = self.characters.get(txn.actor)
        prop = self.props.get(txn.target)
        if not actor or not prop or prop.holder_id != actor.id or not prop.properties.get("wearable"):
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Wear requires a held garment.")
        old = actor.clothing
        actor.clothing = prop.name
        return TransactionResult(True, txn.action, txn.actor, txn.target,
                                 state_deltas={"clothing": {"from": old, "to": actor.clothing}})

    def _handle_morph_prop(self, txn: Transaction) -> TransactionResult:
        actor = self.characters.get(txn.actor)
        prop = self.props.get(txn.target)
        form_id = txn.params.get("form")
        forms = prop.properties.get("morph_forms", {}) if prop else {}
        if (not actor or not actor.can_target_morph or not prop
                or prop.location != actor.location or not isinstance(form_id, str) or form_id not in forms):
            return TransactionResult(False, txn.action, txn.actor, txn.target,
                                     "Prop morph requires a reachable fixture and an authorized actor and form.")
        old = {key: prop.properties.get(key) for key in ("form", *forms[form_id])}
        new = {"form": form_id, **forms[form_id]}
        prop.properties.update(new)
        return TransactionResult(True, txn.action, txn.actor, txn.target,
                                 state_deltas={"prop_form": {"from": old, "to": new}})

    def _handle_drop(self, txn: Transaction) -> TransactionResult:
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        prop = self.props.get(txn.target)
        if not prop or not character.holds(prop.id):
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' is not holding prop '{txn.target}'.")

        character.inventory.remove(prop.id)
        prop.location = character.location
        if prop.id not in self.locations[character.location].props:
            self.locations[character.location].props.append(prop.id)

        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"inventory": {"removed": prop.id}, "prop_location": character.location}
        )

    def _handle_seat_claim(self, txn: Transaction) -> TransactionResult:
        """
        Enforces physical seating affordances.
        Rainee requires 2 chairs of space (or a custom enlarged fixture).
        """
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        # Check required seating units
        seat_units = character.seat_units_required
        chairs_claimed = txn.params.get("chairs_claimed", 1)
        is_custom_enlarged = txn.params.get("is_custom_enlarged", False)
        prop = self.props.get(txn.target)
        if prop and "seat_units" in prop.properties:
            if prop.location != character.location:
                return TransactionResult(False, txn.action, txn.actor, txn.target, "Seat is not in the actor's location.")
            chairs_claimed = prop.properties["seat_units"]
            is_custom_enlarged = chairs_claimed >= seat_units

        if seat_units > 1 and chairs_claimed < seat_units and not is_custom_enlarged:
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Affordance Violation: Character '{character.name}' requires {seat_units} chairs of space "
                f"(or custom enlarged fixture). Claiming only {chairs_claimed} chair violates physical invariants."
            )

        old_posture = character.posture
        character.posture = Posture.SEATED
        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={
                "posture": {"from": old_posture.value, "to": Posture.SEATED.value},
                "seating": {"prop": txn.target, "chairs_claimed": chairs_claimed, "custom_enlarged": is_custom_enlarged}
            }
        )

    def _handle_claim_seat(self, txn: Transaction) -> TransactionResult:
        return self._handle_seat_claim(txn)

    def _check_form(self, txn: Transaction, character: CharacterState, form_id: str, kind: str) -> str | None:
        if self.form_reveal_beats is None:
            return None
        junction = AFM_JUNCTIONS.get(character.id)
        form = next((f for f in junction.forms if f.id == form_id), None) if junction else None
        if form is None or form.kind not in ("base", kind):
            return "Form does not belong to this character or transition type."
        if form.kind == "base":
            return None
        revealed = self.revealed_forms.get(character.id, ())
        reveal_beat = self.form_reveal_beats.get(character.id, {}).get(form_id)
        if reveal_beat is None or (form_id not in revealed and txn.beat_id != reveal_beat):
            return "Form is unavailable at this point in this story."
        if form.after and form.after != character.active_avatar and form_id not in revealed:
            return "The form's predecessor is not active."
        return None

    def _record_form(self, character: CharacterState, form_id: str) -> None:
        if self.form_reveal_beats is not None:
            known = self.revealed_forms.setdefault(character.id, [])
            if form_id not in known:
                known.append(form_id)
        character.physique["active_avatar"] = form_id

    def _handle_adopt_persona(self, txn: Transaction) -> TransactionResult:
        actor = self.characters.get(txn.actor)
        form_id = txn.params.get("avatar_id")
        if not actor or actor.id != txn.target or not isinstance(form_id, str) or self.form_reveal_beats is None:
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Persona needs a scoped actor and form.")
        error = self._check_form(txn, actor, form_id, "persona")
        if error:
            return TransactionResult(False, txn.action, txn.actor, txn.target, error)
        old = actor.active_avatar
        self._record_form(actor, form_id)
        return TransactionResult(True, txn.action, txn.actor, txn.target,
                                 state_deltas={"active_avatar": {"from": old, "to": form_id}})

    def _handle_morph_self(self, txn: Transaction) -> TransactionResult:
        """
        Enforces self-morph permissions and avatar state transitions.
        Haley has dormant genes and CANNOT shapeshift.
        """
        character = self.characters.get(txn.actor)
        if not character:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Character '{txn.actor}' not found.")

        # Check permission
        can_morph = character.can_self_morph
        if not can_morph or character.id.lower() == "haley":
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Morph Permission Violation: Character '{character.name}' has dormant fox genes and CANNOT shapeshift."
            )

        avatar_id = txn.params.get("avatar_id", "avatar_custom")
        error = self._check_form(txn, character, avatar_id, "transformation")
        if error:
            return TransactionResult(False, txn.action, txn.actor, txn.target, error)
        old_avatar = character.active_avatar
        self._record_form(character, avatar_id)
        if "clothing" in txn.params:
            character.clothing = txn.params["clothing"]
        if "visual_description" in txn.params:
            character.physique["avatar_visual"] = txn.params["visual_description"]
        if "somatic_deltas" in txn.params:
            character.somatic.update(txn.params["somatic_deltas"])

        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={"active_avatar": {"from": old_avatar, "to": avatar_id}}
        )

    def _handle_morph_target(self, txn: Transaction) -> TransactionResult:
        """
        Enforces target-morph permissions (nanite transformation of others).
        Rainee is the only character authorized to transform others.
        """
        actor = self.characters.get(txn.actor)
        if not actor:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Actor '{txn.actor}' not found.")

        target = self.characters.get(txn.target)
        if not target:
            return TransactionResult(False, txn.action, txn.actor, txn.target, f"Target '{txn.target}' not found.")

        can_target_morph = actor.can_target_morph
        if not can_target_morph:
            return TransactionResult(
                False, txn.action, txn.actor, txn.target,
                f"Morph Permission Violation: Actor '{actor.name}' cannot transform other characters. "
                f"Only Rainee has nanite target-transformation capabilities."
            )

        avatar_id = txn.params.get("avatar_id", "transformed_avatar")
        error = self._check_form(txn, target, avatar_id, "transformation")
        if error:
            return TransactionResult(False, txn.action, txn.actor, txn.target, error)
        if self.form_reveal_beats is not None and actor.location != target.location:
            return TransactionResult(False, txn.action, txn.actor, txn.target, "Actor and target must share the scene.")
        old_appearance = target.physique.get("active_avatar", "default")
        self._record_form(target, avatar_id)
        if "clothing" in txn.params:
            target.clothing = txn.params["clothing"]
        if "visual_description" in txn.params:
            target.physique["avatar_visual"] = txn.params["visual_description"]

        return TransactionResult(
            True, txn.action, txn.actor, txn.target,
            state_deltas={
                "target_avatar": {"character": target.id, "from": old_appearance, "to": avatar_id}
            }
        )

    # -------------------------------------------------------------------------
    # Snapshot & Beat Context Compilation
    # -------------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "tick": self.tick,
            "locations": {k: copy.deepcopy(v.__dict__) for k, v in self.locations.items()},
            "portals": {k: copy.deepcopy(v.__dict__) for k, v in self.portals.items()},
            "characters": {k: copy.deepcopy(v.__dict__) for k, v in self.characters.items()},
            "props": {k: copy.deepcopy(v.__dict__) for k, v in self.props.items()},
            "form_reveal_beats": copy.deepcopy(self.form_reveal_beats),
            "revealed_forms": copy.deepcopy(self.revealed_forms),
        }

    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any]) -> StoryWorldState:
        data = copy.deepcopy(snapshot)
        world = cls(data["title"])
        world.tick = data["tick"]
        world.locations = {key: Location(**row) for key, row in data["locations"].items()}
        world.portals = {
            key: Portal(**{**row, "state": PortalState(row["state"])})
            for key, row in data["portals"].items()
        }
        world.characters = {
            key: CharacterState(**{**row, "posture": Posture(row["posture"])})
            for key, row in data["characters"].items()
        }
        world.props = {key: PropState(**row) for key, row in data["props"].items()}
        world.form_reveal_beats = data.get("form_reveal_beats")
        world.revealed_forms = data.get("revealed_forms", {})
        return world

    def compile_beat_context(self, active_characters: List[str]) -> Dict[str, Any]:
        """
        Exports the ground truth for an active beat to be consumed by the Beat Packet compiler.
        """
        active_locs = {self.characters[c_id].location for c_id in active_characters if c_id in self.characters}
        
        adjacent_characters = []
        for c in self.characters.values():
            if c.id not in active_characters and c.location in active_locs:
                adjacent_characters.append(c.id)

        # Detect audible and olfactory links
        sensory_links = []
        for listener in self.characters.values():
            if listener.id not in active_characters:
                for a_id in active_characters:
                    a_loc = self.characters[a_id].location
                    audible, clarity = self.can_hear(listener.id, a_loc)
                    smellable, intensity = self.can_smell(listener.id, a_loc)
                    if audible or smellable:
                        sensory_links.append({
                            "listener": listener.id,
                            "listener_location": listener.location,
                            "source_character": a_id,
                            "source_location": a_loc,
                            "audible": audible,
                            "clarity": clarity,
                            "smellable": smellable,
                            "intensity": intensity
                        })

        return {
            "tick": self.tick,
            "active_characters": {
                c_id: {
                    "location": self.characters[c_id].location,
                    "posture": self.characters[c_id].posture.value,
                    "somatic": self.characters[c_id].somatic,
                    "physique": self.characters[c_id].physique,
                    "clothing": self.characters[c_id].clothing,
                    "inventory": self.characters[c_id].inventory
                } for c_id in active_characters if c_id in self.characters
            },
            "locations": {
                loc_id: {
                    "name": self.locations[loc_id].name,
                    "portals": {p_id: self.portals[p_id].state.value for p_id in self.locations[loc_id].connected_portals}
                } for loc_id in active_locs if loc_id in self.locations
            },
            "sensory_links": sensory_links
        }
