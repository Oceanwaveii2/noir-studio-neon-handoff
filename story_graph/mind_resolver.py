"""Unified MindProjectionResolver consolidating multi-body manifestations, layered provenance, and InteractionRules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class InteractionRule:
    """Conditional interaction directive evaluated against scene pressure & active state."""

    rule_id: str
    speaker_id: str
    when_pressure: str
    required_acts: Tuple[str, ...] = ()
    avoid: Tuple[str, ...] = ()
    priority: int = 1


@dataclass(frozen=True)
class MindProjection:
    """Compiled active mind packet for one character/manifestation at beat t."""

    character_id: str
    form_id: str
    node_id: str
    location: str
    speaker_label: str
    provenance_layers: Tuple[str, ...]
    active_rules: Tuple[InteractionRule, ...] = ()
    traits: Dict[str, Any] = field(default_factory=dict)
    relationships: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class MindProjectionResolver:
    """Single resolver projecting >= 1 active bodies(t), layered overrides, and conditional InteractionRules."""

    LAYER_ORDER = ("base", "form", "group", "manifestation", "beat_override")

    def active_bodies(
        self,
        junctions: Sequence[dict],
        *,
        replay_frame: Optional[dict] = None,
        beat_overrides: Optional[Dict[str, dict]] = None,
        active_relationships: Optional[Dict[Tuple[str, str], dict]] = None,
        interaction_rules: Sequence[InteractionRule] = (),
        active_pressures: Sequence[str] = (),
    ) -> List[MindProjection]:
        """Resolve >= 1 simultaneous active bodies with layered provenance and matching conditional rules."""
        overrides = beat_overrides or {}
        rels = active_relationships or {}
        pressures = {p.casefold() for p in active_pressures if p}
        projections: List[MindProjection] = []

        # Build fast lookup of form port_id -> metadata across junctions
        junction_map: Dict[str, dict] = {j["character_id"]: j for j in junctions}

        if replay_frame and replay_frame.get("state", {}).get("manifestations"):
            state = replay_frame["state"]
            root_id = str(state.get("root") or "")
            root_j = junction_map.get(root_id, {})
            forms_by_port = {f.get("port_id"): f for f in root_j.get("forms", ())}
            for m in state["manifestations"]:
                port_id = m.get("id") or ""
                form_info = forms_by_port.get(port_id, {})
                cid = root_id or port_id
                fid = form_info.get("id") or port_id
                layers = self._collect_layers(cid, fid, overrides.get(port_id) or overrides.get(cid))
                matched_rules = tuple(
                    r for r in interaction_rules
                    if r.speaker_id.casefold() in (cid.casefold(), fid.casefold(), port_id.casefold())
                    and (not r.when_pressure or r.when_pressure.casefold() in pressures)
                )
                char_rels = {
                    b: info for (a, b), info in rels.items() if a.casefold() == cid.casefold()
                }
                projections.append(
                    MindProjection(
                        character_id=cid,
                        form_id=fid,
                        node_id=str(m.get("mind") or form_info.get("link") or port_id),
                        location=str(m.get("location") or "scene"),
                        speaker_label=str(form_info.get("display_label") or form_info.get("label") or fid),
                        provenance_layers=layers,
                        active_rules=matched_rules,
                        traits=dict(overrides.get(port_id, {})),
                        relationships=char_rels,
                    )
                )
            return projections

        for j in junctions:
            cid = str(j.get("character_id") or "")
            active_forms = [f for f in j.get("forms", ()) if f.get("status") == "active"]
            if not active_forms and j.get("forms"):
                active_forms = [j["forms"][0]]
            for f in active_forms:
                fid = str(f.get("id") or "base")
                port_id = str(f.get("port_id") or cid)
                layers = self._collect_layers(cid, fid, overrides.get(port_id) or overrides.get(cid))
                matched_rules = tuple(
                    r for r in interaction_rules
                    if r.speaker_id.casefold() in (cid.casefold(), fid.casefold(), port_id.casefold())
                    and (not r.when_pressure or r.when_pressure.casefold() in pressures)
                )
                char_rels = {
                    b: info for (a, b), info in rels.items() if a.casefold() == cid.casefold()
                }
                projections.append(
                    MindProjection(
                        character_id=cid,
                        form_id=fid,
                        node_id=str(f.get("link") or port_id),
                        location=str((overrides.get(cid) or {}).get("location") or "scene"),
                        speaker_label=str(f.get("display_label") or f.get("label") or cid),
                        provenance_layers=layers,
                        active_rules=matched_rules,
                        traits=dict(overrides.get(port_id) or overrides.get(cid) or {}),
                        relationships=char_rels,
                    )
                )
        return projections

    def _collect_layers(self, cid: str, fid: str, override: Optional[dict]) -> Tuple[str, ...]:
        layers = [f"base:{cid}", f"form:{fid}", f"group:{cid}"]
        if override:
            layers.append("beat_override")
        return tuple(layers)


def check_interaction_rules(text: str, projections: Iterable[MindProjection]) -> List[str]:
    """Verify candidate prose against active conditional InteractionRule directives."""
    lowered = text.casefold()
    issues: List[str] = []
    for proj in projections:
        for rule in proj.active_rules:
            for forbidden in rule.avoid:
                tok = forbidden.strip().casefold()
                if tok and tok in lowered:
                    issues.append(f"InteractionRule '{rule.rule_id}' violation ({proj.speaker_label}): avoided phrase '{forbidden}'.")
            if rule.required_acts:
                if not any(act.strip().casefold() in lowered for act in rule.required_acts if act.strip()):
                    issues.append(
                        f"InteractionRule '{rule.rule_id}' missed ({proj.speaker_label}): expected one of {list(rule.required_acts)}."
                    )
    return issues
