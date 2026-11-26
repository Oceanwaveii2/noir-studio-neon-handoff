"""Layer-2 bridge connecting prose_engine and tools cleanly to story_graph.StateCompiler."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional

from story_graph.canon_models import (
    CompiledWorldState,
    StoryCoord,
    ValidationFinding,
)
from story_graph.seeds.afm_seed import DEFAULT_AFM_UNIVERSE, seed_afm_universe
from story_graph.state_compiler import CANON_SCHEMA_SQL, StateCompiler
from story_graph.state_validator import validate_text

EPISODE_DEFAULT_POS: Dict[str, float] = {
    "origin": 0.0,
    "spring-break": 10.0,
    "spring-break-up": 10.0,
    "post-spring-marriage": 15.0,
    "hot-scoomp": 20.0,
    "tapped-out": 30.0,
}

_CACHE_LOCK = threading.RLock()
_CACHED_AFM_CONN: Optional[sqlite3.Connection] = None


def _afm_base_conn() -> sqlite3.Connection:
    global _CACHED_AFM_CONN
    with _CACHE_LOCK:
        if _CACHED_AFM_CONN is None:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            seed_afm_universe(conn, universe_id=DEFAULT_AFM_UNIVERSE)
            _CACHED_AFM_CONN = conn
        return _CACHED_AFM_CONN


def resolve_episode_position(
    episode_id: str,
    explicit_position: Optional[float] = None,
    timeline_conn: Optional[sqlite3.Connection] = None,
) -> float:
    """Resolve episode ordering coordinate from timeline DB or known AFM epoch mapping."""
    if explicit_position is not None:
        return float(explicit_position)
    if timeline_conn is not None:
        has_ep = timeline_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodes'"
        ).fetchone()
        if has_ep:
            row = timeline_conn.execute("SELECT position FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is not None:
                return float(row[0])
    key = episode_id.strip().casefold()
    if key in EPISODE_DEFAULT_POS:
        return EPISODE_DEFAULT_POS[key]
    if key.startswith("spring-break"):
        return 10.0
    if "scoomp" in key or "awakening" in key:
        return 20.0
    if "tapped" in key:
        return 30.0
    return 10.0


def _merge_conn_state(target: sqlite3.Connection, source: sqlite3.Connection) -> None:
    """Overlay user-created canon tables from a TimelineStore connection onto a seeded workspace DB."""
    if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='branches'").fetchone():
        target.execute(
            "CREATE TABLE IF NOT EXISTS branches(id TEXT PRIMARY KEY, parent TEXT, fork_episode TEXT, fork_beat INTEGER)"
        )
        rows = source.execute("SELECT id, parent, fork_episode, fork_beat FROM branches").fetchall()
        target.executemany(
            "INSERT OR REPLACE INTO branches(id, parent, fork_episode, fork_beat) VALUES(?, ?, ?, ?)",
            [tuple(r[:4]) for r in rows],
        )
    if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='episodes'").fetchone():
        target.execute(
            "CREATE TABLE IF NOT EXISTS episodes(id TEXT PRIMARY KEY, title TEXT NOT NULL, branch TEXT NOT NULL, position REAL NOT NULL)"
        )
        rows = source.execute("SELECT id, title, branch, position FROM episodes").fetchall()
        target.executemany(
            "INSERT OR REPLACE INTO episodes(id, title, branch, position) VALUES(?, ?, ?, ?)",
            [tuple(r[:4]) for r in rows],
        )
    for table in ("universe_laws_v2", "character_minds", "character_traits", "character_memories", "state_deltas"):
        if not source.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        rows = source.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
        cols = [d[0] for d in source.execute(f"SELECT * FROM {table} LIMIT 0").description]
        target.executemany(
            f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
            [tuple(r[:len(cols)]) for r in rows],
        )


def compile_afm_state(
    *,
    universe_id: str = DEFAULT_AFM_UNIVERSE,
    branch: str = "main",
    episode_id: str = "spring-break",
    episode_position: Optional[float] = None,
    beat: int = 0,
    viewpoint: Optional[str] = None,
    timeline_conn: Optional[sqlite3.Connection] = None,
    seed_afm: bool = True,
) -> CompiledWorldState:
    """Compile cumulative world laws, character minds, traits, and deltas for one coordinate."""
    pos = resolve_episode_position(episode_id, episode_position, timeline_conn)
    coord = StoryCoord(
        universe_id=universe_id,
        branch=branch,
        episode_id=episode_id,
        episode_position=pos,
        beat=beat,
    )
    if timeline_conn is None and universe_id == DEFAULT_AFM_UNIVERSE and seed_afm:
        with _CACHE_LOCK:
            return StateCompiler(_afm_base_conn()).compile_state(coord, viewpoint=viewpoint)

    if timeline_conn is not None and not seed_afm:
        return StateCompiler(timeline_conn).compile_state(coord, viewpoint=viewpoint)

    ephemeral = sqlite3.connect(":memory:")
    ephemeral.row_factory = sqlite3.Row
    try:
        ephemeral.executescript(CANON_SCHEMA_SQL)
        if seed_afm:
            seed_afm_universe(ephemeral, universe_id=universe_id)
        if timeline_conn is not None:
            _merge_conn_state(ephemeral, timeline_conn)
        return StateCompiler(ephemeral).compile_state(coord, viewpoint=viewpoint)
    finally:
        ephemeral.close()


def check_prose_canon(
    text: str,
    *,
    universe_id: str = DEFAULT_AFM_UNIVERSE,
    branch: str = "main",
    episode_id: str = "spring-break",
    episode_position: Optional[float] = None,
    beat: int = 0,
    viewpoint: Optional[str] = None,
    timeline_conn: Optional[sqlite3.Connection] = None,
    seed_afm: bool = True,
    assertion_default: str = "narration_fact",
    source_origin: str = "author_manuscript",
    block_id: str = "text",
) -> List[ValidationFinding]:
    """Validate prose text deterministically against compiled accumulative canon."""
    state = compile_afm_state(
        universe_id=universe_id,
        branch=branch,
        episode_id=episode_id,
        episode_position=episode_position,
        beat=beat,
        viewpoint=viewpoint,
        timeline_conn=timeline_conn,
        seed_afm=seed_afm,
    )
    return validate_text(
        text,
        state,
        assertion_default=assertion_default,
        source_origin=source_origin,
        block_id=block_id,
    )


def format_finding(finding: ValidationFinding) -> str:
    return f"[{finding.code}:{finding.rule_id}] {finding.reason} (matched: '{finding.evidence}')"


def canon_conflicts(text: str, **kwargs: Any) -> List[ValidationFinding]:
    """Return only error/conflict findings from check_prose_canon."""
    return [f for f in check_prose_canon(text, **kwargs) if f.status == "conflict"]
