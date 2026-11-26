"""
Story Graph Causal Dependency DAG & Beat Sequencer.
Milestone M-SG2: Causal Dependency DAG & Beat Sequencer.
Ensures narrative beats execute strictly according to causality, state preconditions,
and dependency ordering.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .models import PortalState, Posture, Transaction, TransactionResult
from .world_state import StoryWorldState


# -----------------------------------------------------------------------------
# Preconditions
# -----------------------------------------------------------------------------

class Precondition(ABC):
    """Abstract condition that must evaluate to True in WorldState before a beat can fire."""
    @abstractmethod
    def evaluate(self, world: StoryWorldState) -> Tuple[bool, str]:
        """Returns (is_satisfied: bool, failure_reason: str)."""
        pass


@dataclass
class LocationPrecondition(Precondition):
    character_id: str
    expected_location: str

    def evaluate(self, world: StoryWorldState) -> Tuple[bool, str]:
        char = world.characters.get(self.character_id)
        if not char:
            return False, f"Character '{self.character_id}' does not exist in world."
        if char.location != self.expected_location:
            return False, f"Character '{self.character_id}' is at '{char.location}', expected '{self.expected_location}'."
        return True, ""


@dataclass
class PortalPrecondition(Precondition):
    portal_id: str
    expected_state: PortalState

    def evaluate(self, world: StoryWorldState) -> Tuple[bool, str]:
        portal = world.portals.get(self.portal_id)
        if not portal:
            return False, f"Portal '{self.portal_id}' does not exist in world."
        if portal.state != self.expected_state:
            return False, f"Portal '{self.portal_id}' is '{portal.state.value}', expected '{self.expected_state.value}'."
        return True, ""


@dataclass
class SomaticPrecondition(Precondition):
    character_id: str
    somatic_key: str
    expected_value: Any

    def evaluate(self, world: StoryWorldState) -> Tuple[bool, str]:
        char = world.characters.get(self.character_id)
        if not char:
            return False, f"Character '{self.character_id}' does not exist in world."
        val = char.somatic.get(self.somatic_key)
        if val != self.expected_value:
            return False, f"Character '{self.character_id}' somatic '{self.somatic_key}' is '{val}', expected '{self.expected_value}'."
        return True, ""


@dataclass
class SensoryPrecondition(Precondition):
    listener_or_sniffer_id: str
    source_location: str
    sense_type: str  # "hearing" or "smell"
    min_threshold: float = 0.1

    def evaluate(self, world: StoryWorldState) -> Tuple[bool, str]:
        if self.sense_type == "hearing":
            can_hear, clarity = world.can_hear(self.listener_or_sniffer_id, self.source_location)
            if not can_hear or clarity < self.min_threshold:
                return False, f"Character '{self.listener_or_sniffer_id}' cannot hear sounds from '{self.source_location}' (clarity {clarity} < {self.min_threshold})."
            return True, ""
        elif self.sense_type == "smell":
            can_smell, intensity = world.can_smell(self.listener_or_sniffer_id, self.source_location)
            if not can_smell or intensity < self.min_threshold:
                return False, f"Character '{self.listener_or_sniffer_id}' cannot smell scents from '{self.source_location}' (intensity {intensity} < {self.min_threshold})."
            return True, ""
        return False, f"Unknown sense type '{self.sense_type}'."


# -----------------------------------------------------------------------------
# Beat Node
# -----------------------------------------------------------------------------

@dataclass
class BeatNode:
    id: str
    name: str
    scene_id: str
    description: str
    primary_character: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    preconditions: List[Precondition] = field(default_factory=list)
    transactions: List[Transaction] = field(default_factory=list)
    raw_dialogue: List[Dict[str, Any]] = field(default_factory=list)
    aesthetic_tags: List[str] = field(default_factory=list)
    scene_location: Optional[str] = None

    def is_eligible(self, world: StoryWorldState, completed_beats: Set[str]) -> Tuple[bool, List[str]]:
        """
        Checks if this beat can legally fire right now.
        Returns (is_eligible, list_of_blocking_reasons).
        """
        reasons = []
        # 1. Dependency checks
        for dep in self.dependencies:
            if dep not in completed_beats:
                reasons.append(f"Prerequisite beat '{dep}' is not completed.")

        # 2. Precondition checks
        for pre in self.preconditions:
            ok, reason = pre.evaluate(world)
            if not ok:
                reasons.append(reason)

        return len(reasons) == 0, reasons


# -----------------------------------------------------------------------------
# Causal DAG
# -----------------------------------------------------------------------------

class CycleError(Exception):
    pass


class CausalDAG:
    """Directed Acyclic Graph of story beats."""

    def __init__(self):
        self.nodes: Dict[str, BeatNode] = {}

    def add_beat(self, beat: BeatNode) -> None:
        self.nodes[beat.id] = beat

    def validate(self) -> List[str]:
        """
        Validates that the graph is acyclic using Kahn's algorithm.
        Returns topological ordering of beat IDs if valid.
        Raises CycleError if a cycle is detected.
        """
        in_degree: Dict[str, int] = {node_id: 0 for node_id in self.nodes}
        adj: Dict[str, List[str]] = {node_id: [] for node_id in self.nodes}

        for node_id, node in self.nodes.items():
            for dep in node.dependencies:
                if dep not in self.nodes:
                    raise ValueError(f"Beat '{node_id}' depends on non-existent beat '{dep}'.")
                adj[dep].append(node_id)
                in_degree[node_id] += 1

        queue = [n for n, deg in in_degree.items() if deg == 0]
        topological_order = []

        while queue:
            curr = queue.pop(0)
            topological_order.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(topological_order) != len(self.nodes):
            missing = set(self.nodes) - set(topological_order)
            raise CycleError(f"Causal cycle detected among beats: {missing}")

        return topological_order


# -----------------------------------------------------------------------------
# Beat Sequencer
# -----------------------------------------------------------------------------

class BeatSequencer:
    """
    Executes narrative beats through the CausalDAG against the StoryWorldState.
    Advances narrative time and executes atomic state updates.
    """

    def __init__(self, dag: CausalDAG, world: StoryWorldState):
        self.dag = dag
        self.dag.validate()  # Ensure no cycles before execution starts
        self.world = world
        self.completed_beats: Set[str] = set()
        self.execution_log: List[Dict[str, Any]] = []

    def get_eligible_beats(self) -> List[BeatNode]:
        """Returns all beats whose dependencies and preconditions are satisfied right now."""
        eligible = []
        for beat in self.dag.nodes.values():
            if beat.id in self.completed_beats:
                continue
            ok, _ = beat.is_eligible(self.world, self.completed_beats)
            if ok:
                eligible.append(beat)
        return eligible

    def can_execute(self, beat_id: str) -> Tuple[bool, List[str]]:
        beat = self.dag.nodes.get(beat_id)
        if not beat:
            return False, [f"Beat '{beat_id}' not found in DAG."]
        if beat_id in self.completed_beats:
            return False, [f"Beat '{beat_id}' already executed."]
        return beat.is_eligible(self.world, self.completed_beats)

    def execute_beat(self, beat_id: str) -> Dict[str, Any]:
        """
        Executes a beat:
        1. Verifies eligibility.
        2. Applies transactions to the StoryWorldState.
        3. Records deltas and marks beat as completed.
        """
        can_exec, reasons = self.can_execute(beat_id)
        if not can_exec:
            raise ValueError(f"Cannot execute beat '{beat_id}': {'; '.join(reasons)}")

        beat = self.dag.nodes[beat_id]
        results: List[TransactionResult] = []

        # Stage the whole beat so a failed later transaction cannot leave
        # earlier moves or inventory changes in the live world.
        staged_world = copy.deepcopy(self.world)
        for txn in beat.transactions:
            res = staged_world.execute(copy.deepcopy(txn), beat_id=beat_id)
            results.append(res)
            if not res.success:
                raise RuntimeError(
                    f"Transaction failed during beat '{beat_id}': action='{txn.action}', reason='{res.reason}'"
                )

        # Dialogue-only beats still advance narrative time.
        if not results:
            staged_world.tick += 1
        self.world.__dict__.clear()
        self.world.__dict__.update(staged_world.__dict__)
        self.completed_beats.add(beat_id)

        record = {
            "tick": self.world.tick,
            "world_after": self.world.snapshot(),
            "beat_id": beat.id,
            "beat_name": beat.name,
            "scene_id": beat.scene_id,
            "scene_location": beat.scene_location,
            "description": beat.description,
            "primary_character": beat.primary_character,
            "aesthetic_tags": beat.aesthetic_tags,
            "transaction_results": [r.__dict__ for r in results],
            "raw_dialogue": copy.deepcopy(beat.raw_dialogue),
        }
        self.execution_log.append(record)
        return record

    def is_finished(self) -> bool:
        return len(self.completed_beats) == len(self.dag.nodes)
