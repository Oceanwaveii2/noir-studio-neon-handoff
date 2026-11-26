"""Stable character junctions and independently linkable form definitions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class FormLink:
    kind: str
    node_id: str

    def __post_init__(self):
        if self.kind not in {"digital_mind", "super_character"} or not self.node_id:
            raise ValueError("A form link needs a Digital Mind or Super Character node ID.")


@dataclass(frozen=True)
class CharacterForm:
    id: str
    label: str
    kind: str
    after: str | None = None
    link: FormLink | None = None
    unlock_episode: str | None = None
    unlock_pos: int = 0


def evaluate_form_availability(
    form: CharacterForm,
    *,
    episode_pos: int | None = None,
    time_travel_override: bool = False,
) -> dict:
    """Return programmatic availability state for one form at a given episode position."""
    if form.kind == "base" or form.unlock_pos <= 0:
        return {"unlocked": True, "gate": "base", "unlock_episode": form.unlock_episode, "unlock_pos": form.unlock_pos}
    if episode_pos is None or episode_pos >= form.unlock_pos:
        return {"unlocked": True, "gate": "unlocked", "unlock_episode": form.unlock_episode, "unlock_pos": form.unlock_pos}
    if time_travel_override:
        return {"unlocked": True, "gate": "time_travel", "unlock_episode": form.unlock_episode, "unlock_pos": form.unlock_pos}
    return {"unlocked": False, "gate": "locked_future", "unlock_episode": form.unlock_episode, "unlock_pos": form.unlock_pos}


@dataclass(frozen=True)
class CharacterJunction:
    character_id: str
    forms: tuple[CharacterForm, ...]
    node_profiles: tuple[dict, ...] = ()
    mind_behaviors: dict[str, str] = field(default_factory=dict, hash=False)
    relationship_overrides: dict[str, tuple[dict, ...]] = field(default_factory=dict, hash=False)
    relationship_edges: tuple[dict, ...] = field(default=(), hash=False)
    staging: tuple[dict, ...] = field(default=(), hash=False)

    def __post_init__(self):
        if not self.forms or self.forms[0].kind != "base":
            raise ValueError("A junction starts with its base form.")
        seen = set()
        for index, form in enumerate(self.forms):
            if (
                not form.id or form.id in seen
                or form.kind not in {"base", "persona", "transformation", "stage"}
                or (index > 0 and form.kind == "base")
                or (form.after is not None and form.after not in seen)
                or (form.kind == "stage" and form.after is None)
            ):
                raise ValueError(f"Invalid form or predecessor: {form.id}")
            seen.add(form.id)

    @property
    def id(self) -> str:
        return f"character:{self.character_id}"

    def route_at(self, episode: str, branch: str, episode_pos: int, *, time_travel_override=False):
        """Resolve staged routing and its lineage without editing the form definitions."""
        route = next((item for item in self.staging
                      if (item['episode'], item['branch']) == (episode, branch)), None)
        if route is None:
            return None, set()
        forms = {form.id: form for form in self.forms}
        form = forms.get(route['form'])
        if form is None:
            return None, set()
        selected, lineage = form.id, set()
        while form:
            gate = evaluate_form_availability(form, episode_pos=episode_pos,
                                              time_travel_override=time_travel_override)
            if not gate['unlocked']:
                return None, set()
            lineage.add(form.id)
            form = forms.get(form.after)
        return selected, lineage

    def project(self, *, approved: Iterable[str] = (), active: str | None = None,
                planning: bool = False, episode_pos: int | None = None,
                time_travel_override: bool = False) -> dict:
        """Project IDs approved by the caller for the current episode/branch/beat."""
        base = self.forms[0].id
        available = {base}
        approved = set(approved)
        for form in self.forms[1:]:
            gate = evaluate_form_availability(
                form, episode_pos=episode_pos, time_travel_override=time_travel_override
            )
            if gate["unlocked"] and form.id in approved and (form.after is None or form.after in available):
                available.add(form.id)
        active = active if active in available else base
        rows = []
        for form in self.forms:
            gate = evaluate_form_availability(
                form, episode_pos=episode_pos, time_travel_override=time_travel_override
            )
            if form.id not in available and not planning:
                continue
            if form.id == active:
                status = "active"
            elif not gate["unlocked"]:
                status = "locked_future"
            elif form.id in available:
                status = "time_travel_unlocked" if gate["gate"] == "time_travel" else "available"
            else:
                status = "planning_only"
            rows.append({
                **asdict(form),
                "port_id": f"{self.id}:form:{form.id}",
                "status": status,
                "gate": gate["gate"],
            })
        return {"junction_id": self.id, "character_id": self.character_id, "forms": rows}

    @classmethod
    def from_record(cls, data: dict) -> CharacterJunction:
        return cls(data["character_id"], tuple(
            CharacterForm(
                id=row["id"], label=row["label"], kind=row["kind"], after=row.get("after"),
                link=FormLink(**row["link"]) if row.get("link") is not None else None,
                unlock_episode=row.get("unlock_episode"),
                unlock_pos=int(row.get("unlock_pos") or 0),
            )
            for row in data["forms"]
        ), staging=tuple(data.get("staging", ())))


AFM_JUNCTIONS = {
    "roger": CharacterJunction("roger", (
        CharacterForm("roger", "Roger", "base"),
        CharacterForm("mtv_beach_host", "MTV Beach Host", "persona", unlock_episode="spring-break", unlock_pos=10),
        CharacterForm("rutgers_royal_persona", "Rutgers Royal Persona", "persona", unlock_episode="spring-break", unlock_pos=10),
    )),
    "francine": CharacterJunction("francine", (
        CharacterForm("francine", "Franny", "base"),
        CharacterForm("nurse_pamela_franny_anderson", "Nurse Frann Anderson", "transformation", unlock_episode="spring-break", unlock_pos=10),
    )),
    "rainee": CharacterJunction("rainee", (
        CharacterForm("rainee", "Rainee", "base"),
        CharacterForm("peter_griffin_celestial_variant", "Rainee Peter", "transformation", unlock_episode="spring-break", unlock_pos=10),
    )),
    "stella": CharacterJunction("stella", (
        CharacterForm("stella", "Stella", "base"),
        CharacterForm("big_tiddy_steve_stella", "Big Tiddy Steve Stella", "transformation", unlock_episode="tapped-out", unlock_pos=30),
    )),
    "haley": CharacterJunction("haley", (
        CharacterForm("haley", "Haley", "base"),
        CharacterForm("awakened_haley_fox", "Big Booty Haley — Awakened Fox", "transformation", unlock_episode="hot-scoomp", unlock_pos=20),
    )),
}
