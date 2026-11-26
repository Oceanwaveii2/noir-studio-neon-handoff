"""
Story Graph Models: Core data structures for narrative state, fluents, and transactions.
Milestone M-SG1: World State Ledger & Fluent Tracker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PortalState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"
    AJAR = "ajar"


class Posture(str, Enum):
    STANDING = "standing"
    SEATED = "seated"
    PRONE = "prone"
    SPRINTING = "sprinting"
    KNEELING = "kneeling"
    CROUCHING = "crouching"


@dataclass
class Portal:
    id: str
    name: str
    from_location: str
    to_location: str
    state: PortalState = PortalState.CLOSED
    lock_type: Optional[str] = "deadbolt"
    locked_from: Optional[str] = None  # None means accessible from both sides, or specify location
    allows_sound: bool = True
    sound_attenuation: float = 0.5  # 0.0 (silent) to 1.0 (no attenuation)
    allows_scent: bool = True
    scent_permeability: float = 0.7  # e.g., drafts under the door
    allows_sight: bool = False
    allows_traversal: bool = True

    def is_passable(self) -> bool:
        return self.allows_traversal and self.state in (PortalState.OPEN, PortalState.AJAR)


@dataclass
class Location:
    id: str
    name: str
    floor: int = 1
    connected_portals: List[str] = field(default_factory=list)
    props: List[str] = field(default_factory=list)
    ambient: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CharacterState:
    id: str
    name: str
    location: str
    posture: Posture = Posture.STANDING
    clothing: str = "casual"
    inventory: List[str] = field(default_factory=list)
    somatic: Dict[str, Any] = field(default_factory=dict)
    physique: Dict[str, Any] = field(default_factory=dict)

    @property
    def seat_units_required(self) -> int:
        return self.physique.get("seat_units_required", 2 if self.id.lower() == "rainee" else 1)

    @property
    def active_avatar(self) -> str:
        return self.physique.get("active_avatar", "default")

    @property
    def can_self_morph(self) -> bool:
        return self.physique.get("can_self_morph", self.id.lower() in ("rainee", "stella"))

    @property
    def can_target_morph(self) -> bool:
        return self.physique.get("can_target_morph", self.id.lower() == "rainee")

    def holds(self, prop_id: str) -> bool:
        return prop_id in self.inventory


@dataclass
class PropState:
    id: str
    name: str
    location: str  # location_id or "held:<character_id>"
    properties: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_held(self) -> bool:
        return self.location.startswith("held:")

    @property
    def holder_id(self) -> Optional[str]:
        if self.is_held:
            return self.location.split("held:", 1)[1]
        return None


@dataclass
class Transaction:
    action: str
    actor: str
    target: str
    params: Dict[str, Any] = field(default_factory=dict)
    tick: int = 0
    beat_id: str | None = None


@dataclass
class TransactionResult:
    success: bool
    action: str
    actor: str
    target: str
    reason: str = ""
    state_deltas: Dict[str, Any] = field(default_factory=dict)
