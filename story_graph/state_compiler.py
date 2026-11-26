"""Event-sourced, interval-scoped compiler for Universe Laws, Character Minds, and Timeline Deltas."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from .canon_models import (
    ASSERTION_CLASSES,
    CharacterMemory,
    CharacterMind,
    CharacterTrait,
    CompiledWorldState,
    DELTA_OPS,
    EXCEPTION_POLICIES,
    LAW_MODALITIES,
    StateDelta,
    StoryCoord,
    UniverseLawV2,
)


def upstream_dependency_fingerprint(
    *,
    law_revision: Any = None,
    form_hash: Any = None,
    media_revision: Any = None,
    episode_pos: Any = None,
) -> str:
    """Deterministic digest of upstream story, law, form, and media versions."""
    payload = json.dumps(
        {
            "law_revision": law_revision,
            "form_hash": form_hash,
            "media_revision": media_revision,
            "episode_pos": episode_pos,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_stale_decisions(
    decisions: Sequence[Dict[str, Any]],
    current_versions: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Flag downstream beats, facts, or decisions as needs_review when upstream sources change."""
    checks = (
        ("law_revision", "world_laws_changed"),
        ("form_hash", "form_gate_changed"),
        ("media_revision", "media_override_changed"),
        ("episode_pos", "timeline_position_changed"),
    )
    annotated: List[Dict[str, Any]] = []
    for item in decisions:
        saved = item.get("upstream_versions") or {}
        reasons = [
            reason
            for key, reason in checks
            if key in saved and key in current_versions and saved.get(key) != current_versions.get(key)
        ]
        annotated.append(
            {
                **item,
                "needs_review": bool(reasons),
                "stale_reasons": reasons,
            }
        )
    return annotated

CANON_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS universe_laws_v2 (
    law_id            TEXT PRIMARY KEY,
    universe_id       TEXT NOT NULL,
    name              TEXT NOT NULL,
    statement         TEXT NOT NULL,
    modality          TEXT NOT NULL,
    exception_policy  TEXT NOT NULL,
    assertion_scope   TEXT NOT NULL,
    rule_kind         TEXT NOT NULL,
    pattern           TEXT,
    negation_cues     TEXT NOT NULL,
    allow_context     TEXT NOT NULL,
    branch            TEXT NOT NULL,
    valid_from_json   TEXT,
    valid_until_json  TEXT,
    enabled           INTEGER NOT NULL DEFAULT 1,
    source_id         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_minds (
    character_id      TEXT NOT NULL,
    universe_id       TEXT NOT NULL,
    canonical_name    TEXT NOT NULL,
    family_id         TEXT,
    default_surname   TEXT NOT NULL DEFAULT '',
    species_baseline  TEXT NOT NULL DEFAULT 'human',
    home_location     TEXT NOT NULL DEFAULT '',
    aliases_json      TEXT NOT NULL DEFAULT '[]',
    inheritance_json  TEXT NOT NULL DEFAULT '{}',
    baseline_notes    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (universe_id, character_id)
);

CREATE TABLE IF NOT EXISTS character_traits (
    trait_id                 TEXT PRIMARY KEY,
    universe_id              TEXT NOT NULL,
    owner_id                 TEXT NOT NULL,
    trait_kind               TEXT NOT NULL,
    predicate                TEXT NOT NULL,
    value_json               TEXT NOT NULL,
    grants_law_exception_id  TEXT,
    evidence_summary         TEXT NOT NULL DEFAULT '',
    active_from_branch       TEXT NOT NULL DEFAULT '*',
    active_from_pos          REAL,
    active_from_beat         INTEGER
);

CREATE TABLE IF NOT EXISTS character_memories (
    memory_id        TEXT PRIMARY KEY,
    universe_id      TEXT NOT NULL,
    owner_scope      TEXT NOT NULL,
    owner_id         TEXT NOT NULL,
    subject_id       TEXT NOT NULL,
    predicate        TEXT NOT NULL,
    object_value     TEXT NOT NULL,
    truth_status     TEXT NOT NULL,
    branch           TEXT NOT NULL,
    episode_pos      REAL NOT NULL,
    beat             INTEGER NOT NULL,
    source_event_id  TEXT NOT NULL,
    revision         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS state_deltas (
    delta_id         TEXT PRIMARY KEY,
    universe_id      TEXT NOT NULL,
    branch           TEXT NOT NULL,
    episode_id       TEXT NOT NULL,
    episode_pos      REAL NOT NULL,
    beat             INTEGER NOT NULL,
    seq              INTEGER NOT NULL,
    op               TEXT NOT NULL,
    subject_id       TEXT NOT NULL,
    target_id        TEXT,
    payload_json     TEXT NOT NULL,
    source_event_id  TEXT,
    authority        TEXT NOT NULL,
    revision         INTEGER NOT NULL DEFAULT 1,
    retired          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_state_deltas_coord
    ON state_deltas(universe_id, branch, episode_pos, beat, seq);

CREATE TABLE IF NOT EXISTS compiled_state_checkpoints (
    checkpoint_key   TEXT PRIMARY KEY,
    universe_id      TEXT NOT NULL,
    branch           TEXT NOT NULL,
    episode_pos      REAL NOT NULL,
    beat             INTEGER NOT NULL,
    state_digest     TEXT NOT NULL,
    payload_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canon_proposals (
    proposal_id      TEXT PRIMARY KEY,
    universe_id      TEXT NOT NULL,
    branch           TEXT NOT NULL,
    episode_id       TEXT NOT NULL,
    episode_pos      REAL NOT NULL,
    beat             INTEGER NOT NULL,
    kind             TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    rationale        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    reviewer         TEXT,
    created_utc      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_utc     TEXT
);
"""


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def ensure_canon_schema(conn: sqlite3.Connection) -> None:
    """Create accumulative canon & memory tables idempotently inside the caller's connection."""
    conn.executescript(CANON_SCHEMA_SQL)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def branch_intervals(
    conn: sqlite3.Connection,
    branch: str,
    episode_position: float,
    beat: int,
) -> Dict[str, Tuple[int, Tuple[float, int]]]:
    """Return ordered ancestor branch upper bounds {branch_id: (depth_from_root, (max_pos, max_beat))}."""
    if not _table_exists(conn, "branches") or not _table_exists(conn, "episodes"):
        return {branch: (0, (float(episode_position), int(beat)))}
    row = conn.execute("SELECT 1 FROM branches WHERE id=?", (branch,)).fetchone()
    if row is None:
        return {branch: (0, (float(episode_position), int(beat)))}

    chain: List[Tuple[str, Tuple[float, int]]] = [(branch, (float(episode_position), int(beat)))]
    seen = {branch}
    curr = branch
    while True:
        brow = conn.execute("SELECT parent, fork_episode, fork_beat FROM branches WHERE id=?", (curr,)).fetchone()
        if brow is None or brow["parent"] is None:
            break
        parent = brow["parent"]
        if parent in seen:
            raise ValueError("Cyclic branch ancestry")
        seen.add(parent)
        ep = conn.execute("SELECT branch, position FROM episodes WHERE id=?", (brow["fork_episode"],)).fetchone()
        if ep is None or ep["branch"] != parent:
            raise ValueError("Invalid branch fork")
        chain.append((parent, (float(ep["position"]), int(brow["fork_beat"]))))
        curr = parent

    chain.reverse()
    return {name: (depth, bound) for depth, (name, bound) in enumerate(chain)}


def _coord_in_bounds(
    item_branch: str,
    pos: float,
    beat: int,
    intervals: Dict[str, Tuple[int, Tuple[float, int]]],
) -> Optional[int]:
    """Return branch depth when (item_branch, pos, beat) lies within inherited bounds, else None."""
    if item_branch not in intervals:
        return None
    depth, max_point = intervals[item_branch]
    if (float(pos), int(beat)) <= max_point:
        return depth
    return None


def _law_applies(
    law: UniverseLawV2,
    intervals: Dict[str, Tuple[int, Tuple[float, int]]],
    current_branch: str,
) -> bool:
    if not law.enabled:
        return False
    target_branch = current_branch if law.branch == "*" else law.branch
    if target_branch not in intervals:
        return False
    _, point = intervals[target_branch]
    if law.valid_from is not None and point < law.valid_from:
        return False
    if law.valid_until is not None and point > law.valid_until:
        return False
    return True


def _trait_applies(
    trait: CharacterTrait,
    intervals: Dict[str, Tuple[int, Tuple[float, int]]],
    current_branch: str,
) -> bool:
    target_branch = current_branch if trait.active_from_branch == "*" else trait.active_from_branch
    if target_branch not in intervals:
        return False
    if trait.active_from_pos is None:
        return True
    _, point = intervals[target_branch]
    start_beat = 0 if trait.active_from_beat is None else int(trait.active_from_beat)
    return point >= (float(trait.active_from_pos), start_beat)


def upsert_law(conn: sqlite3.Connection, law: UniverseLawV2) -> None:
    if law.modality not in LAW_MODALITIES:
        raise ValueError(f"Unsupported law modality: {law.modality}")
    if law.exception_policy not in EXCEPTION_POLICIES:
        raise ValueError(f"Unsupported exception policy: {law.exception_policy}")
    if any(a not in ASSERTION_CLASSES for a in law.assertion_scope):
        raise ValueError("Invalid assertion class in law scope")
    ensure_canon_schema(conn)
    conn.execute(
        """INSERT OR REPLACE INTO universe_laws_v2 (
               law_id, universe_id, name, statement, modality, exception_policy,
               assertion_scope, rule_kind, pattern, negation_cues, allow_context,
               branch, valid_from_json, valid_until_json, enabled, source_id
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            law.law_id,
            law.universe_id,
            law.name,
            law.statement,
            law.modality,
            law.exception_policy,
            _json_dumps(list(law.assertion_scope)),
            law.rule_kind,
            law.pattern,
            _json_dumps(list(law.negation_cues)),
            _json_dumps(list(law.allow_context)),
            law.branch,
            _json_dumps(list(law.valid_from)) if law.valid_from is not None else None,
            _json_dumps(list(law.valid_until)) if law.valid_until is not None else None,
            1 if law.enabled else 0,
            law.source_id,
        ),
    )


def upsert_character_mind(conn: sqlite3.Connection, mind: CharacterMind) -> None:
    ensure_canon_schema(conn)
    conn.execute(
        """INSERT OR REPLACE INTO character_minds (
               character_id, universe_id, canonical_name, family_id, default_surname,
               species_baseline, home_location, aliases_json, inheritance_json, baseline_notes
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mind.character_id,
            mind.universe_id,
            mind.canonical_name,
            mind.family_id,
            mind.default_surname,
            mind.species_baseline,
            mind.home_location,
            _json_dumps(list(mind.aliases)),
            _json_dumps(mind.inheritance_model),
            mind.baseline_notes,
        ),
    )


def grant_trait(conn: sqlite3.Connection, trait: CharacterTrait) -> None:
    ensure_canon_schema(conn)
    conn.execute(
        """INSERT OR REPLACE INTO character_traits (
               trait_id, universe_id, owner_id, trait_kind, predicate, value_json,
               grants_law_exception_id, evidence_summary, active_from_branch,
               active_from_pos, active_from_beat
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trait.trait_id,
            trait.universe_id,
            trait.owner_id,
            trait.trait_kind,
            trait.predicate,
            _json_dumps(trait.value),
            trait.grants_law_exception_id,
            trait.evidence_summary,
            trait.active_from_branch,
            trait.active_from_pos,
            trait.active_from_beat,
        ),
    )


def record_memory(conn: sqlite3.Connection, memory: CharacterMemory) -> None:
    if memory.owner_scope not in ("personal", "family", "shared"):
        raise ValueError("Invalid memory owner_scope")
    if memory.truth_status not in ("established_fact", "false_belief", "tease_joke", "retconned_assumption"):
        raise ValueError("Invalid memory truth_status")
    ensure_canon_schema(conn)
    conn.execute(
        """INSERT OR REPLACE INTO character_memories (
               memory_id, universe_id, owner_scope, owner_id, subject_id, predicate,
               object_value, truth_status, branch, episode_pos, beat, source_event_id, revision
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            memory.memory_id,
            memory.universe_id,
            memory.owner_scope,
            memory.owner_id,
            memory.subject_id,
            memory.predicate,
            memory.object_value,
            memory.truth_status,
            memory.branch,
            float(memory.episode_pos),
            int(memory.beat),
            memory.source_event_id,
            int(memory.revision),
        ),
    )


def append_delta(conn: sqlite3.Connection, delta: StateDelta) -> None:
    if delta.op not in DELTA_OPS:
        raise ValueError(f"Unsupported delta op: {delta.op}")
    ensure_canon_schema(conn)
    conn.execute(
        """INSERT OR REPLACE INTO state_deltas (
               delta_id, universe_id, branch, episode_id, episode_pos, beat, seq,
               op, subject_id, target_id, payload_json, source_event_id, authority, revision, retired
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            delta.delta_id,
            delta.universe_id,
            delta.branch,
            delta.episode_id,
            float(delta.episode_pos),
            int(delta.beat),
            int(delta.seq),
            delta.op,
            delta.subject_id,
            delta.target_id,
            _json_dumps(delta.payload),
            delta.source_event_id,
            delta.authority,
            int(delta.revision),
            1 if delta.retired else 0,
        ),
    )


def retire_delta(conn: sqlite3.Connection, delta_id: str, retired: bool = True) -> int:
    ensure_canon_schema(conn)
    return conn.execute(
        "UPDATE state_deltas SET retired=? WHERE delta_id=?",
        (1 if retired else 0, delta_id),
    ).rowcount


def _row_to_law(row: sqlite3.Row) -> UniverseLawV2:
    vf = json.loads(row["valid_from_json"]) if row["valid_from_json"] else None
    vu = json.loads(row["valid_until_json"]) if row["valid_until_json"] else None
    return UniverseLawV2(
        law_id=row["law_id"],
        universe_id=row["universe_id"],
        name=row["name"],
        statement=row["statement"],
        modality=row["modality"],
        exception_policy=row["exception_policy"],
        assertion_scope=tuple(json.loads(row["assertion_scope"])),
        rule_kind=row["rule_kind"],
        pattern=row["pattern"],
        negation_cues=tuple(json.loads(row["negation_cues"])),
        allow_context=tuple(json.loads(row["allow_context"])),
        branch=row["branch"],
        valid_from=(float(vf[0]), int(vf[1])) if vf is not None else None,
        valid_until=(float(vu[0]), int(vu[1])) if vu is not None else None,
        enabled=bool(row["enabled"]),
        source_id=row["source_id"],
    )


def _apply_delta(
    delta: StateDelta,
    characters: Dict[str, Dict[str, Any]],
    relationships: Dict[Tuple[str, str], Dict[str, Any]],
) -> None:
    subj = delta.subject_id.casefold()
    char = characters.setdefault(
        subj,
        {
            "character_id": subj,
            "canonical_name": subj.title(),
            "traits": [],
            "exceptions": {},
            "biology_stage": "baseline",
            "can_self_morph": False,
            "can_target_morph": False,
            "traits_manifested": [],
            "attraction": {"attracted_to": [], "repulsed_by": [], "exception_granted": False},
            "devices": {},
            "alters": [],
            "active_form": subj,
            "known_facts": [],
        },
    )
    payload = delta.payload
    op = delta.op

    if op == "SET_RELATIONSHIP":
        if not delta.target_id:
            raise ValueError("SET_RELATIONSHIP requires target_id")
        key = (subj, delta.target_id.casefold())
        existing = relationships.get(key, {})
        relationships[key] = {
            "subject_id": key[0],
            "target_id": key[1],
            "status": payload.get("status", existing.get("status", "associated")),
            "allowed_terms": list(payload.get("allowed_terms", existing.get("allowed_terms", []))),
            "anachronistic_terms": list(payload.get("anachronistic_terms", existing.get("anachronistic_terms", []))),
            "facets": dict(existing.get("facets", {}), **payload.get("facets", {})),
            "concurrent_with_marriage": payload.get(
                "concurrent_with_marriage", existing.get("concurrent_with_marriage", False)
            ),
            "authority": delta.authority,
            "last_delta_id": delta.delta_id,
        }
    elif op == "SET_RELATIONSHIP_FACET":
        if not delta.target_id:
            raise ValueError("SET_RELATIONSHIP_FACET requires target_id")
        key = (subj, delta.target_id.casefold())
        edge = relationships.setdefault(
            key,
            {
                "subject_id": key[0],
                "target_id": key[1],
                "status": payload.get("status", "associated"),
                "allowed_terms": [],
                "anachronistic_terms": [],
                "facets": {},
            },
        )
        if "status" in payload:
            edge["status"] = payload["status"]
        if "allowed_terms" in payload:
            edge["allowed_terms"] = list(payload["allowed_terms"])
        if "anachronistic_terms" in payload:
            edge["anachronistic_terms"] = list(payload["anachronistic_terms"])
        facets = {k: v for k, v in payload.items() if k not in ("status", "allowed_terms", "anachronistic_terms")}
        edge["facets"].update(facets)
        edge["last_delta_id"] = delta.delta_id
    elif op == "RETRACT_RELATIONSHIP":
        if delta.target_id:
            relationships.pop((subj, delta.target_id.casefold()), None)
    elif op == "SET_BIOLOGY_STAGE":
        char["biology_stage"] = payload.get("stage", char["biology_stage"])
        if "can_self_morph" in payload:
            char["can_self_morph"] = bool(payload["can_self_morph"])
        if "can_target_morph" in payload:
            char["can_target_morph"] = bool(payload["can_target_morph"])
        if "traits_manifested" in payload:
            char["traits_manifested"] = list(payload["traits_manifested"])
        if "trigger" in payload:
            char["awakening_trigger"] = payload["trigger"]
    elif op == "SET_ATTRACTION_PROFILE":
        att = char["attraction"]
        for field_name in ("attracted_to", "repulsed_by"):
            if field_name in payload:
                att[field_name] = list(payload[field_name])
        for field_name in ("reason", "exception_granted", "notes"):
            if field_name in payload:
                att[field_name] = payload[field_name]
    elif op == "GRANT_DEVICE":
        device_id = payload.get("device_id")
        if device_id:
            char["devices"][device_id] = copy.deepcopy(payload)
            alter = payload.get("transforms_to")
            if alter and alter not in char["alters"]:
                char["alters"].append(alter)
    elif op == "BIND_ALTER_IDENTITY":
        alter_id = payload.get("alter_id") or delta.target_id
        if alter_id and alter_id not in char["alters"]:
            char["alters"].append(alter_id)
    elif op == "REVEAL_FORM":
        if "active_form" in payload:
            char["active_form"] = payload["active_form"]
    elif op == "GRANT_KNOWLEDGE":
        fact = payload.get("fact")
        if fact and fact not in char["known_facts"]:
            char["known_facts"].append(fact)


class StateCompiler:
    """Compiles cumulative World Laws, Character Minds, and State Deltas at any StoryCoord."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        ensure_canon_schema(self.conn)

    def compile_state(
        self,
        coord: StoryCoord,
        *,
        viewpoint: Optional[str] = None,
        use_checkpoint: bool = False,
    ) -> CompiledWorldState:
        self.conn.row_factory = sqlite3.Row
        intervals = branch_intervals(self.conn, coord.branch, coord.episode_position, coord.beat)

        laws_raw = self.conn.execute(
            "SELECT * FROM universe_laws_v2 WHERE universe_id=? ORDER BY law_id",
            (coord.universe_id,),
        ).fetchall()
        active_laws = [
            law for law in (_row_to_law(r) for r in laws_raw)
            if _law_applies(law, intervals, coord.branch)
        ]

        hard = tuple(l for l in active_laws if l.modality == "hard_invariant")
        soft = tuple(l for l in active_laws if l.modality == "soft_tendency")
        guards = tuple(l for l in active_laws if l.modality == "import_bleed_guard")

        characters: Dict[str, Dict[str, Any]] = {}
        for r in self.conn.execute(
            "SELECT * FROM character_minds WHERE universe_id=? ORDER BY character_id",
            (coord.universe_id,),
        ):
            cid = r["character_id"].casefold()
            characters[cid] = {
                "character_id": cid,
                "canonical_name": r["canonical_name"],
                "family_id": r["family_id"],
                "default_surname": r["default_surname"],
                "species_baseline": r["species_baseline"],
                "home_location": r["home_location"],
                "aliases": json.loads(r["aliases_json"]),
                "inheritance_model": json.loads(r["inheritance_json"]),
                "baseline_notes": r["baseline_notes"],
                "traits": [],
                "exceptions": {},
                "biology_stage": "baseline",
                "can_self_morph": False,
                "can_target_morph": False,
                "traits_manifested": [],
                "attraction": {"attracted_to": [], "repulsed_by": [], "exception_granted": False},
                "devices": {},
                "alters": [],
                "active_form": cid,
                "known_facts": [],
            }

        for tr in self.conn.execute(
            "SELECT * FROM character_traits WHERE universe_id=? ORDER BY trait_id",
            (coord.universe_id,),
        ):
            trait = CharacterTrait(
                trait_id=tr["trait_id"],
                universe_id=tr["universe_id"],
                owner_id=tr["owner_id"].casefold(),
                trait_kind=tr["trait_kind"],
                predicate=tr["predicate"],
                value=json.loads(tr["value_json"]),
                grants_law_exception_id=tr["grants_law_exception_id"],
                evidence_summary=tr["evidence_summary"],
                active_from_branch=tr["active_from_branch"],
                active_from_pos=tr["active_from_pos"],
                active_from_beat=tr["active_from_beat"],
            )
            if not _trait_applies(trait, intervals, coord.branch):
                continue
            char = characters.setdefault(
                trait.owner_id,
                {
                    "character_id": trait.owner_id,
                    "canonical_name": trait.owner_id.title(),
                    "traits": [],
                    "exceptions": {},
                    "biology_stage": "baseline",
                    "can_self_morph": False,
                    "can_target_morph": False,
                    "traits_manifested": [],
                    "attraction": {"attracted_to": [], "repulsed_by": [], "exception_granted": False},
                    "devices": {},
                    "alters": [],
                    "active_form": trait.owner_id,
                    "known_facts": [],
                },
            )
            char["traits"].append(trait.to_dict())
            if trait.grants_law_exception_id:
                char["exceptions"][trait.grants_law_exception_id] = trait.to_dict()
                if trait.grants_law_exception_id == "fox_sapphic_tendency":
                    char["attraction"]["exception_granted"] = True

        ordered_deltas: List[Tuple[int, float, int, int, StateDelta]] = []
        for dr in self.conn.execute(
            "SELECT * FROM state_deltas WHERE universe_id=? AND retired=0",
            (coord.universe_id,),
        ):
            depth = _coord_in_bounds(dr["branch"], dr["episode_pos"], dr["beat"], intervals)
            if depth is None:
                continue
            delta = StateDelta(
                delta_id=dr["delta_id"],
                universe_id=dr["universe_id"],
                branch=dr["branch"],
                episode_id=dr["episode_id"],
                episode_pos=float(dr["episode_pos"]),
                beat=int(dr["beat"]),
                seq=int(dr["seq"]),
                op=dr["op"],
                subject_id=dr["subject_id"],
                target_id=dr["target_id"],
                payload=json.loads(dr["payload_json"]),
                source_event_id=dr["source_event_id"],
                authority=dr["authority"],
                revision=int(dr["revision"]),
                retired=bool(dr["retired"]),
            )
            ordered_deltas.append((depth, delta.episode_pos, delta.beat, delta.seq, delta))

        ordered_deltas.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4].delta_id))
        relationships: Dict[Tuple[str, str], Dict[str, Any]] = {}
        applied_ids: List[str] = []
        for _, _, _, _, delta in ordered_deltas:
            _apply_delta(delta, characters, relationships)
            applied_ids.append(delta.delta_id)

        visible_memories: List[CharacterMemory] = []
        hidden_facts: List[Dict[str, Any]] = []
        mem_rows: List[Tuple[int, float, int, CharacterMemory]] = []
        for mr in self.conn.execute(
            "SELECT * FROM character_memories WHERE universe_id=? ORDER BY episode_pos, beat, memory_id",
            (coord.universe_id,),
        ):
            mem = CharacterMemory(
                memory_id=mr["memory_id"],
                universe_id=mr["universe_id"],
                owner_scope=mr["owner_scope"],
                owner_id=mr["owner_id"].casefold(),
                subject_id=mr["subject_id"].casefold(),
                predicate=mr["predicate"],
                object_value=mr["object_value"],
                truth_status=mr["truth_status"],
                branch=mr["branch"],
                episode_pos=float(mr["episode_pos"]),
                beat=int(mr["beat"]),
                source_event_id=mr["source_event_id"],
                revision=int(mr["revision"]),
            )
            depth = _coord_in_bounds(mem.branch, mem.episode_pos, mem.beat, intervals)
            if depth is None:
                # Sibling/future branch or post-coord memories remain hidden from current beat prompts
                hidden_facts.append(
                    {
                        "memory_id": mem.memory_id,
                        "subject_id": mem.subject_id,
                        "predicate": mem.predicate,
                        "object_value": mem.object_value,
                        "reason": "future_or_sibling_branch",
                    }
                )
                continue
            if mem.owner_scope == "personal" and viewpoint is not None and mem.owner_id != viewpoint.casefold():
                hidden_facts.append(
                    {
                        "memory_id": mem.memory_id,
                        "subject_id": mem.subject_id,
                        "predicate": mem.predicate,
                        "object_value": mem.object_value,
                        "reason": f"private_to:{mem.owner_id}",
                    }
                )
                continue
            mem_rows.append((depth, mem.episode_pos, mem.beat, mem))

        mem_rows.sort(key=lambda item: (item[0], item[1], item[2], item[3].memory_id))
        visible_memories = [item[3] for item in mem_rows]

        digest_basis = {
            "coord": coord.to_dict(),
            "viewpoint": viewpoint,
            "laws": [l.law_id for l in active_laws],
            "deltas": applied_ids,
            "memories": [(m.memory_id, m.revision, m.object_value) for m in visible_memories],
            "characters": sorted((k, v["biology_stage"], v.get("active_form")) for k, v in characters.items()),
        }
        state_digest = hashlib.sha256(_json_dumps(digest_basis).encode("utf-8")).hexdigest()

        compiled = CompiledWorldState(
            coord=coord,
            viewpoint=viewpoint,
            hard_invariants=hard,
            soft_tendencies=soft,
            import_bleed_guards=guards,
            characters=characters,
            relationships=relationships,
            memories=tuple(visible_memories),
            hidden_facts=tuple(hidden_facts),
            applied_deltas=tuple(applied_ids),
            state_digest=state_digest,
        )
        if use_checkpoint:
            ckey = f"{coord.universe_id}:{coord.branch}:{coord.episode_position}:{coord.beat}:{viewpoint or '*'}"
            self.conn.execute(
                """INSERT OR REPLACE INTO compiled_state_checkpoints (
                       checkpoint_key, universe_id, branch, episode_pos, beat, state_digest, payload_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ckey,
                    coord.universe_id,
                    coord.branch,
                    float(coord.episode_position),
                    int(coord.beat),
                    state_digest,
                    _json_dumps(compiled.to_dict()),
                ),
            )
        return compiled


def propose_canon_change(
    conn: sqlite3.Connection,
    coord: StoryCoord,
    *,
    kind: str,
    payload: Dict[str, Any],
    rationale: str,
    proposal_id: Optional[str] = None,
) -> str:
    """Queue an author-reviewable canon proposal (delta, trait exception, or memory) without auto-committing."""
    if kind not in ("state_delta", "character_trait", "character_memory"):
        raise ValueError("Unsupported proposal kind")
    ensure_canon_schema(conn)
    pid = proposal_id or f"prop-{uuid4().hex[:12]}"
    conn.execute(
        """INSERT INTO canon_proposals (
               proposal_id, universe_id, branch, episode_id, episode_pos, beat,
               kind, payload_json, rationale, status
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (
            pid,
            coord.universe_id,
            coord.branch,
            coord.episode_id,
            float(coord.episode_position),
            int(coord.beat),
            kind,
            _json_dumps(payload),
            rationale,
        ),
    )
    return pid


def list_proposals(
    conn: sqlite3.Connection,
    universe_id: str,
    *,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ensure_canon_schema(conn)
    conn.row_factory = sqlite3.Row
    if status:
        rows = conn.execute(
            "SELECT * FROM canon_proposals WHERE universe_id=? AND status=? ORDER BY created_utc, proposal_id",
            (universe_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM canon_proposals WHERE universe_id=? ORDER BY created_utc, proposal_id",
            (universe_id,),
        ).fetchall()
    return [
        {
            "proposal_id": r["proposal_id"],
            "universe_id": r["universe_id"],
            "branch": r["branch"],
            "episode_id": r["episode_id"],
            "episode_pos": float(r["episode_pos"]),
            "beat": int(r["beat"]),
            "kind": r["kind"],
            "payload": json.loads(r["payload_json"]),
            "rationale": r["rationale"],
            "status": r["status"],
            "reviewer": r["reviewer"],
        }
        for r in rows
    ]


def resolve_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    decision: str,
    reviewer: str,
) -> Dict[str, Any]:
    """Accept or dismiss one pending canon proposal transactionally."""
    if decision not in ("accepted", "dismissed"):
        raise ValueError("Proposal decision must be 'accepted' or 'dismissed'")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer is required")
    ensure_canon_schema(conn)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM canon_proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown canon proposal: {proposal_id}")
    if row["status"] != "pending":
        raise ValueError(f"Canon proposal {proposal_id} is already {row['status']}")

    payload = json.loads(row["payload_json"])
    applied_id: Optional[str] = None
    if decision == "accepted":
        kind = row["kind"]
        if kind == "state_delta":
            delta = StateDelta(
                delta_id=payload.get("delta_id") or f"delta-{uuid4().hex[:12]}",
                universe_id=row["universe_id"],
                branch=payload.get("branch", row["branch"]),
                episode_id=payload.get("episode_id", row["episode_id"]),
                episode_pos=float(payload.get("episode_pos", row["episode_pos"])),
                beat=int(payload.get("beat", row["beat"])),
                seq=int(payload.get("seq", 10)),
                op=payload["op"],
                subject_id=payload["subject_id"],
                target_id=payload.get("target_id"),
                payload=payload.get("payload", {}),
                source_event_id=f"proposal:{proposal_id}",
                authority="author_approved_extraction",
                revision=1,
            )
            append_delta(conn, delta)
            applied_id = delta.delta_id
        elif kind == "character_trait":
            trait = CharacterTrait(
                trait_id=payload.get("trait_id") or f"trait-{uuid4().hex[:12]}",
                universe_id=row["universe_id"],
                owner_id=payload["owner_id"],
                trait_kind=payload["trait_kind"],
                predicate=payload["predicate"],
                value=payload["value"],
                grants_law_exception_id=payload.get("grants_law_exception_id"),
                evidence_summary=payload.get("evidence_summary", row["rationale"]),
                active_from_branch=payload.get("active_from_branch", row["branch"]),
                active_from_pos=payload.get("active_from_pos", float(row["episode_pos"])),
                active_from_beat=payload.get("active_from_beat", int(row["beat"])),
            )
            grant_trait(conn, trait)
            applied_id = trait.trait_id
        elif kind == "character_memory":
            mem = CharacterMemory(
                memory_id=payload.get("memory_id") or f"mem-{uuid4().hex[:12]}",
                universe_id=row["universe_id"],
                owner_scope=payload.get("owner_scope", "personal"),
                owner_id=payload["owner_id"],
                subject_id=payload["subject_id"],
                predicate=payload["predicate"],
                object_value=payload["object_value"],
                truth_status=payload.get("truth_status", "established_fact"),
                branch=payload.get("branch", row["branch"]),
                episode_pos=float(payload.get("episode_pos", row["episode_pos"])),
                beat=int(payload.get("beat", row["beat"])),
                source_event_id=f"proposal:{proposal_id}",
                revision=1,
            )
            record_memory(conn, mem)
            applied_id = mem.memory_id

    conn.execute(
        "UPDATE canon_proposals SET status=?, reviewer=?, resolved_utc=CURRENT_TIMESTAMP WHERE proposal_id=?",
        (decision, reviewer.strip(), proposal_id),
    )
    return {
        "proposal_id": proposal_id,
        "status": decision,
        "reviewer": reviewer.strip(),
        "applied_id": applied_id,
    }
