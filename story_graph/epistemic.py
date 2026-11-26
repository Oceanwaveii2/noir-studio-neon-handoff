"""
Story Graph Epistemic Knowledge Ledger.
Milestone M-SG3: Epistemic Scoping & Character Knowledge Ledger.
Tracks character knowledge, private vs. public information, and prevents
information leakage across character boundaries.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .world_state import StoryWorldState


@dataclass
class Fact:
    id: str
    description: str
    keywords: List[str] = field(default_factory=list)
    origin_tick: int = 0
    is_private: bool = False  # If true, requires explicit sharing or sensory inference


@dataclass
class KnowledgeEntry:
    fact_id: str
    acquired_tick: int
    source_type: str  # "innate", "observation", "speech", "sensory_inference", "private_deduction"
    source_actor: Optional[str] = None
    certainty: float = 1.0


def viewpoint_diff(events, viewpoint, *, sight=True, audio=True):
    """Compare approved events with the facts available to one viewpoint."""
    from .source_timing import visible_to

    ledger = EpistemicLedger()
    ledger.register_character(viewpoint)
    channels = {'sight': sight, 'audio': audio}
    for event in events:
        ident, content, tick = event['id'], event['content'], event['beat']
        ledger.register_fact(Fact(ident, content, origin_tick=tick))
        channel = event.get('sensory_channel')
        if visible_to(event, viewpoint) and (channel not in channels or channels[channel]):
            ledger.grant_knowledge(viewpoint, ident, 'observation', tick)

    def rows(facts):
        return [{'id': fact.id, 'text': fact.description, 'beat': fact.origin_tick} for fact in facts]

    return {'viewpoint': viewpoint, 'channels': channels,
            'known': rows(ledger.get_known_facts(viewpoint)), 'withheld': rows(ledger.get_unknown_facts(viewpoint))}


class EpistemicLedger:
    """
    Tracks and validates character knowledge states over narrative time.
    Prevents dialogue and thought generation from leaking facts a character cannot know.
    """

    def __init__(self):
        self.facts: Dict[str, Fact] = {}
        # character_id -> {fact_id -> KnowledgeEntry}
        self.knowledge: Dict[str, Dict[str, KnowledgeEntry]] = {}
        self._history: Dict[str, Dict[str, List[KnowledgeEntry]]] = {}
        self.leakage_log: List[Dict[str, Any]] = []

    def register_fact(self, fact: Fact) -> None:
        self.facts[fact.id] = fact

    def register_character(self, character_id: str, initial_fact_ids: Optional[List[str]] = None) -> None:
        if character_id not in self.knowledge:
            self.knowledge[character_id] = {}
        if initial_fact_ids:
            for fid in initial_fact_ids:
                self.grant_knowledge(character_id, fid, source_type="innate", tick=0)

    def reset_character(self, character_id: str) -> None:
        """Start a new local activation without inheriting the old actor ledger."""
        self.knowledge[character_id] = {}
        self._history.pop(character_id, None)

    def grant_knowledge(
        self,
        character_id: str,
        fact_id: str,
        source_type: str,
        tick: int,
        source_actor: Optional[str] = None,
        certainty: float = 1.0,
    ) -> None:
        if fact_id not in self.facts:
            raise ValueError(f"Cannot grant unknown fact '{fact_id}' to character '{character_id}'.")
        if character_id not in self.knowledge:
            self.knowledge[character_id] = {}

        entry = KnowledgeEntry(
            fact_id=fact_id,
            acquired_tick=tick,
            source_type=source_type,
            source_actor=source_actor,
            certainty=certainty,
        )

        self.knowledge[character_id][fact_id] = entry
        self._history.setdefault(character_id, {}).setdefault(fact_id, []).append(entry)

    def knows(
        self, character_id: str, fact_id: str, min_certainty: float = 0.5, *,
        tick: Optional[int] = None,
    ) -> bool:
        entry = self.knowledge.get(character_id, {}).get(fact_id)
        if tick is not None:
            fact = self.facts.get(fact_id)
            if fact is None or fact.origin_tick > tick:
                return False
            history = self._history.get(character_id, {}).get(fact_id, ())
            entry = max(
                (record for record in reversed(history) if record.acquired_tick <= tick),
                key=lambda record: record.acquired_tick, default=None,
            )
        return entry is not None and entry.certainty >= min_certainty

    def get_known_facts(self, character_id: str, *, tick: Optional[int] = None) -> List[Fact]:
        return [
            fact for fid, fact in self.facts.items()
            if self.knows(character_id, fid, tick=tick)
        ]

    def get_unknown_facts(self, character_id: str, *, tick: Optional[int] = None) -> List[Fact]:
        return [
            fact for fid, fact in self.facts.items()
            if not self.knows(character_id, fid, tick=tick)
        ]

    # -------------------------------------------------------------------------
    # Knowledge Propagation via World State (Acoustics & Olfactory)
    # -------------------------------------------------------------------------

    def broadcast_speech(
        self,
        speaker_id: str,
        fact_id: str,
        world: StoryWorldState,
        tick: int,
    ) -> List[str]:
        """
        Speaker speaks a fact aloud. All characters who can hear the speaker acquire the fact.
        Returns list of character IDs who overheard the fact.
        """
        if not self.knows(speaker_id, fact_id, tick=tick):
            raise ValueError(f"Speaker '{speaker_id}' cannot speak fact '{fact_id}' because they do not know it.")

        speaker_loc = world.characters[speaker_id].location
        overheard_by = []

        for listener_id, listener in world.characters.items():
            if listener_id == speaker_id:
                continue
            can_hear, clarity = world.can_hear(listener_id, speaker_loc)
            if can_hear and clarity >= 0.3:
                self.grant_knowledge(
                    listener_id,
                    fact_id,
                    source_type="speech",
                    tick=tick,
                    source_actor=speaker_id,
                    certainty=min(1.0, clarity + 0.2),
                )
                overheard_by.append(listener_id)

        return overheard_by

    def infer_from_sensory(
        self,
        sniffer_id: str,
        fact_id: str,
        source_loc: str,
        world: StoryWorldState,
        tick: int,
    ) -> bool:
        """
        Character infers a fact from olfactory or acoustic clues if sensory threshold met.
        """
        can_smell, intensity = world.can_smell(sniffer_id, source_loc)
        if can_smell and intensity >= 0.5:
            self.grant_knowledge(
                sniffer_id,
                fact_id,
                source_type="sensory_inference",
                tick=tick,
                certainty=intensity,
            )
            return True
        return False

    # -------------------------------------------------------------------------
    # Leakage Auditing (Anti-Hallucination Guard)
    # -------------------------------------------------------------------------

    def audit_text_for_leaks(self, speaker_id: str, text: str, tick: int) -> List[Tuple[str, str]]:
        """
        Audits character dialogue or interiority against their unknown facts.
        If the speaker uses keywords from a fact they do not know, returns a list of (fact_id, matched_phrase).
        """
        unknown_facts = self.get_unknown_facts(speaker_id, tick=tick)
        violations = []

        for fact in unknown_facts:
            matched_terms = []
            for kw in fact.keywords:
                pattern = rf"\b{re.escape(kw)}\b"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    matched_terms.append(match.group(0))
            if matched_terms:
                violations.append((fact.id, matched_terms[0]))
                self.leakage_log.append({
                    "tick": tick,
                    "speaker": speaker_id,
                    "fact_id": fact.id,
                    "matched_terms": matched_terms,
                    "text_snippet": text[:80],
                })

        return violations

    # -------------------------------------------------------------------------
    # Snapshot & Serialization
    # -------------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "facts": {k: copy.deepcopy(v.__dict__) for k, v in self.facts.items()},
            "knowledge_history": {
                cid: {fid: [copy.deepcopy(entry.__dict__) for entry in history]
                      for fid, history in facts.items()}
                for cid, facts in self._history.items()
            },
            "knowledge": {
                c_id: {f_id: copy.deepcopy(entry.__dict__) for f_id, entry in k_dict.items()}
                for c_id, k_dict in self.knowledge.items()
            },
        }

    def restore(self, snap: Dict[str, Any]) -> None:
        self.facts = {k: Fact(**v) for k, v in snap["facts"].items()}
        self.knowledge = {}
        for c_id, k_dict in snap["knowledge"].items():
            self.knowledge[c_id] = {f_id: KnowledgeEntry(**e) for f_id, e in k_dict.items()}

        self._history = {
            cid: {fid: [entry] for fid, entry in facts.items()}
            for cid, facts in self.knowledge.items()
        }
        for cid, facts in snap.get("knowledge_history", {}).items():
            for fid, history in facts.items():
                self._history.setdefault(cid, {})[fid] = [KnowledgeEntry(**row) for row in history]
