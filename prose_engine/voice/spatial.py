"""
House geometry as a writing constraint.

The floor plans (physics_engine / Ling House SVG-derived JSON) give rooms, areas, doors and
fixtures. This module puts them in front of the model and checks staging against them:

    - location heading -> room facts in the prompt (size, floor, fixtures)
    - character in a new room without a transition -> teleport flag
    - toilet mentioned outside a bathroom -> fixture flag
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

HEADING = re.compile(r"^(?:INT|EXT)\.\s*(.+?)(?:\s+[—-]\s+|$)", re.IGNORECASE)
TRANSITION = re.compile(
    r"\b(?:walks?|walked|walking|goes|went|going|runs?|ran|running|enters?|entered|entering|comes?|came|coming|heads?|headed|"
    r"climbs?|descends?|crosses?|steps?|moves?|hurries|upstairs|downstairs|through the door|"
    r"lunges?|lunged|lunging|waddles?|waddled|waddling|slides?|slid|sliding|crawls?|crawled|crawling|"
    r"rushes?|rushed|rushing|leaps?|leapt|leaped|leaping|strides?|strode|striding|dodges?|dodged|dodging|"
    r"retreats?|retreated|retreating|wanders?|wandered|wandering|drifts?|drifted|drifting|drapes?|draped|"
    r"slumps?|slumped|slumping|stands?|stood|standing|leaves?|left|leaving|turns?|turned|turning)\b",
    re.IGNORECASE,
)
HINTS = {
    "kitchen": "Kitchen / dining",
    "dining": "Kitchen / dining",
    "living": "Living room + TV",
    "entrance": "Entrance hall",
    "stair": "Stair hall",
    "landing": "Upper landing",
    "hallway": "Wide upstairs hallway",
    "bathroom": "Full bathroom",
    "toilet": "Wide toilet room",
    "primary": "Primary bedroom",
    "bedroom": "Primary bedroom",
    "laundry": "Laundry / utilities",
    "storage": "Storage room",
    "hobby": "Hobby / studio room",
    "studio": "Hobby / studio room",
}
DEFAULT_NAMES = ("Rainee", "Francine", "Haley", "Stan", "Roger", "Steve")


def _centroid(polygon):
    x = sum(point[0] for point in polygon) / len(polygon)
    y = sum(point[1] for point in polygon) / len(polygon)
    return (x, y)


def _inside(point, polygon):
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if (y1 > y) != (y2 > y):
            intersect = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersect:
                inside = not inside
    return inside


@dataclass
class Room:
    id: str
    label: str
    floor: str
    area: float
    bbox: tuple
    fixtures: List[str] = field(default_factory=list)

    @property
    def size(self) -> str:
        width = max(point[0] for point in self.bbox) - min(point[0] for point in self.bbox)
        depth = max(point[1] for point in self.bbox) - min(point[1] for point in self.bbox)
        return f"{width:.1f} x {depth:.1f} m"

    def describe(self, cad: bool = True) -> str:
        fixtures = ", ".join(self.fixtures[:5]) if self.fixtures else "none listed"
        if not cad:
            return f"{self.label} ({self.floor} floor); fixtures: {fixtures}"
        return (
            f"{self.label} ({self.floor} floor), about {self.area:.1f} m2, {self.size}; "
            f"fixtures: {fixtures}"
        )


class House:
    def __init__(self, rooms: Sequence[Room], doors=()):
        self.rooms = list(rooms)
        self.doors = list(doors)

    @classmethod
    def load(cls, directory: str | Path | None = None) -> "House":
        from ..paths import books

        rooms: List[Room] = []
        doors: List = []
        for path in sorted(Path(directory or books("ling_house")).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            floor = data.get("floor", path.stem)
            for door in data.get("doors", []):
                if isinstance(door, list) and len(door) == 2:
                    doors.append((floor, door))
            fixture_polygons = [
                item for item in data.get("fixtures", []) if item.get("id") and item.get("polygon")
            ]
            for entry in data.get("rooms", []):
                polygon = entry.get("polygon") or [[0, 0], [0, 0]]
                fixtures = [
                    item["id"]
                    for item in fixture_polygons
                    if _inside(_centroid(item["polygon"]), polygon)
                ]
                rooms.append(
                    Room(
                        id=entry.get("id", ""),
                        label=entry.get("label", ""),
                        floor=floor,
                        area=float(entry.get("area_m2") or 0.0),
                        bbox=(
                            (min(p[0] for p in polygon), min(p[1] for p in polygon)),
                            (max(p[0] for p in polygon), max(p[1] for p in polygon)),
                        ),
                        fixtures=fixtures,
                    )
                )
        return cls(rooms, doors)

    def adjacency(self):
        """Room graph from door segments: each door connects its two nearest rooms."""
        if hasattr(self, "_adjacency") and self._adjacency:
            return self._adjacency
        edges = set()
        for floor, segment in self.doors:
            midpoint = (
                (segment[0][0] + segment[1][0]) / 2,
                (segment[0][1] + segment[1][1]) / 2,
            )
            scored = []
            for room in self.rooms:
                if room.floor != floor:
                    continue
                distance = self._distance(midpoint, room.bbox)
                scored.append((distance, room))
            scored.sort(key=lambda item: item[0])
            near = [room for distance, room in scored[:2] if distance < 3.0]
            if len(near) == 2:
                edges.add(frozenset((near[0].label, near[1].label)))
        edges.add(frozenset(("Stair hall", "Upper landing")))
        edges.add(frozenset(("Stair hall", "Entrance hall")))
        edges.add(frozenset(("Upper landing", "Wide upstairs hallway")))
        edges.add(frozenset(("Stair hall", "Basement stair hall")))
        edges.add(frozenset(("Basement stair hall", "Basement lounge")))
        self._adjacency = edges
        return edges

    @staticmethod
    def _distance(point, bbox):
        (min_x, min_y), (max_x, max_y) = bbox
        dx = max(min_x - point[0], 0, point[0] - max_x)
        dy = max(min_y - point[1], 0, point[1] - max_y)
        return (dx * dx + dy * dy) ** 0.5

    def reachable(self, start: str, end: str) -> bool:
        graph = {}
        for edge in self.adjacency():
            a, b = tuple(edge)
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
        seen, queue = {start}, [start]
        while queue:
            room = queue.pop(0)
            if room == end:
                return True
            for neighbour in graph.get(room, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return False

    def find(self, text: str) -> Optional[Room]:
        lowered = text.lower()
        for keyword, label in sorted(HINTS.items(), key=lambda item: -len(item[0])):
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                for room in self.rooms:
                    if room.label == label:
                        return room
        for room in self.rooms:
            if room.label.lower() in lowered:
                return room
        return None

    def map_block(self, cad: bool = False) -> str:
        lines = ["HOUSE MAP (established rooms and floors):"]
        for floor in ("ground", "upper", "basement"):
            rooms = [room for room in self.rooms if room.floor == floor]
            if not rooms:
                continue
            if cad:
                described = "; ".join(f"{room.label} ({room.size})" for room in rooms)
            else:
                described = "; ".join(room.label for room in rooms)
            lines.append(f"- {floor}: {described}")
        lines.append("- stairs: stair hall (ground) <-> upper landing (upper)")
        lines.append("- the upstairs hallway runs past the bathroom door")
        return "\n".join(lines)

    def prompt_block(self, location: str, cad: bool = True) -> str:
        room = self.find(location)
        if room is None:
            return ""
        if cad:
            return f"SETTING (from the floor plans): {room.describe(cad=True)}."
        return f"SETTING: {room.describe(cad=False)}."

    def narrative_prompt_block(self, location: str) -> str:
        """Evocative narrative setting without CAD measurements."""
        return self.prompt_block(location, cad=False)

    def check_scene(self, chunks: Sequence[str], names: Iterable[str] = DEFAULT_NAMES) -> List[str]:
        issues: List[str] = []
        current: Optional[Room] = None
        location: Optional[str] = None
        last_room: Dict[str, Room] = {}
        moved_last = False
        for chunk in chunks:
            if chunk.lstrip().startswith(("[", "]", "#")):
                continue
            match = HEADING.search(chunk.strip())
            if match:
                location = match.group(1)
                current = self.find(location)
            where = current if current is not None else self.find(chunk)
            moved_now = bool(TRANSITION.search(chunk))
            spoken = re.sub(r'"[^"]*"', ' ', chunk)
            spoken = re.sub(r"[^.]*\b(?:voice came through|O\.S\.|through the door)\b[^.]*\.", " ", spoken)
            mentions = [name for name in names if re.search(rf"\b{re.escape(name)}\b", spoken)]
            for name in mentions:
                previous = last_room.get(name)
                if previous is not None and where is not None and previous.id != where.id:
                    if not (moved_now or moved_last):
                        issues.append(
                            f"{name}: {previous.label} -> {where.label} without a transition"
                        )
                if where is not None:
                    last_room[name] = where
            moved_last = moved_now
            if where is not None:
                lowered = chunk.lower()
                if "toilet" in lowered and "bath" not in where.label.lower() and "toilet" not in where.label.lower():
                    issues.append(f"toilet mentioned in {where.label}")
                if "stove" in lowered and "kitchen" not in where.label.lower():
                    issues.append(f"stove mentioned in {where.label}")
        return issues
