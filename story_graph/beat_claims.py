"""Validate structured continuity claims against a recorded beat boundary."""
from __future__ import annotations

from .compiler import BeatPacket


def check_claims(packet: BeatPacket, claims: list[dict], *, snapshot: str) -> list[dict]:
    if not packet.world_snapshot_sha256 or snapshot != packet.world_snapshot_sha256:
        raise ValueError("Claims must name the recorded world snapshot for this beat.")
    if not isinstance(claims, list) or not claims:
        raise ValueError("Provide at least one structured claim.")
    actors = packet.continuity_context["actors"]
    props = packet.continuity_context["props"]
    violations = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or set(claim) != {"kind", "subject", "value"}:
            raise ValueError(f"Claim {index + 1} needs kind, subject and value.")
        kind, subject, value = claim["kind"], claim["subject"], claim["value"]
        if not isinstance(kind, str) or not isinstance(subject, str) or not subject:
            raise ValueError(f"Claim {index + 1} needs a valid kind and subject.")
        if kind == "tick":
            valid = type(value) is int and subject == packet.beat_id and value == packet.tick
        elif not isinstance(value, str) or not value:
            raise ValueError(f"Claim {index + 1} needs a nonempty ID or location.")
        elif kind == "location":
            valid = actors.get(subject) == value
        elif kind == "prop_location":
            valid = props.get(subject, {}).get("location") == value
        elif kind == "prop_form":
            valid = props.get(subject, {}).get("form") == value
        elif kind == "knows":
            valid = value in packet.epistemic_context.get(subject, ())
        elif kind in ("active_form", "available_form"):
            group = packet.form_context.get(subject, {})
            valid = any(
                f["id"] == value and (kind == "available_form" or f["status"] == "active")
                for f in group.get("forms", ())
            )
        else:
            raise ValueError(f"Unknown claim kind: {kind}")
        if not valid:
            violations.append({"claim": index + 1, "kind": kind, "subject": subject,
                               "reason": "Unsupported at this beat boundary."})
    return violations
