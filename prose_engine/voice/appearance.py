"""
Appearance canon: an image becomes checkable constraints.

The image is the source of truth; a vision model (Qwen3.5 is image-text-to-text) extracts a strict
schema, a human confirms it, and the schema is hash-pinned to the image. The story then has to
respect it: immutable traits may be altered by a transformation but never erased, and forbidden
claims are blocked.

    python -m prose_engine voice appearance show --file appearances/rainee.json
    python -m prose_engine voice appearance check --text-file draft.md --appearance appearances/rainee.json
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

PROMPT = """You are reading a character reference image. Return ONLY a JSON object, no prose, with these keys:
{
  "entity": "name",
  "immutable_base_traits": ["traits that never change"],
  "state_deltas": {"state_name": ["traits for that state"]},
  "forbidden_claims": ["claims the story must never make, e.g. 'hair vanished'"],
  "palette": ["dominant colours"],
  "silhouette": "one phrase describing the body shape",
  "notes": "anything else visible"
}
Describe only what you can see. Do not invent backstory."""


def image_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Appearance:
    entity: str
    image: str = ""
    image_sha256: str = ""
    immutable_base_traits: List[str] = field(default_factory=list)
    state_deltas: Dict[str, List[str]] = field(default_factory=dict)
    forbidden_claims: List[str] = field(default_factory=list)
    palette: List[str] = field(default_factory=list)
    silhouette: str = ""
    notes: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "Appearance":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**{key: data[key] for key in data if key in cls.__dataclass_fields__})

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    def check(self, text: str) -> List[str]:
        lowered = text.lower()
        violations = [
            f"forbidden claim: {claim}"
            for claim in self.forbidden_claims
            if claim.lower() in lowered
        ]
        for trait in self.immutable_base_traits:
            words = [word for word in re.findall(r"[a-z]+", trait.lower()) if len(word) > 3]
            if not words:
                continue
            pattern = re.compile(
                r"(?:no longer|without|lost|gone|vanished)[^.!?]{0,40}\b"
                + re.escape(words[-1])
                + r"\b|\b"
                + re.escape(words[-1])
                + r"\b[^.!?]{0,30}(?:was gone|had vanished|disappeared)",
                re.IGNORECASE,
            )
            if pattern.search(text):
                violations.append(f"immutable trait erased: {trait}")
        return violations

    def prompt_block(self) -> str:
        lines = [f"APPEARANCE CANON — {self.entity}"]
        if self.immutable_base_traits:
            lines.append("always: " + ", ".join(self.immutable_base_traits))
        for state, traits in self.state_deltas.items():
            lines.append(f"{state}: " + ", ".join(traits))
        if self.forbidden_claims:
            lines.append("never claim: " + "; ".join(self.forbidden_claims))
        if self.palette:
            lines.append("palette: " + ", ".join(self.palette))
        if self.silhouette:
            lines.append("silhouette: " + self.silhouette)
        return "\n".join(lines)


class AppearanceBible:
    def __init__(self, entries: Optional[Dict[str, Appearance]] = None):
        self.entries = entries or {}

    @classmethod
    def load_dir(cls, directory: str | Path) -> "AppearanceBible":
        entries = {}
        for path in sorted(Path(directory).glob("*.json")):
            appearance = Appearance.load(path)
            entries[appearance.entity] = appearance
        return cls(entries)

    def check(self, text: str) -> List[str]:
        found: List[str] = []
        for appearance in self.entries.values():
            found.extend(f"{appearance.entity}: {violation}" for violation in appearance.check(text))
        return found

    def prompt_block(self) -> str:
        return "\n\n".join(appearance.prompt_block() for appearance in self.entries.values())


def parse_schema(text: str, entity: str = "", image: str = "") -> Appearance:
    """Extracts the first JSON object from a model reply and validates the keys."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the model reply")
    data = json.loads(match.group(0))
    return Appearance(
        entity=data.get("entity") or entity,
        image=image,
        image_sha256=image_hash(image) if image and Path(image).is_file() else "",
        immutable_base_traits=list(data.get("immutable_base_traits") or []),
        state_deltas={key: list(value) for key, value in (data.get("state_deltas") or {}).items()},
        forbidden_claims=list(data.get("forbidden_claims") or []),
        palette=list(data.get("palette") or []),
        silhouette=data.get("silhouette") or "",
        notes=data.get("notes") or "",
    )
