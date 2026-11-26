"""Persistent project/universe identity and copy-first legacy migration."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import stat
from uuid import uuid4


@dataclass(frozen=True)
class NarrativeContext:
    schema_version: int
    project_id: str
    universe_id: str
    scope_revision: int
    episode: str
    branch: str
    beat: int
    viewpoint: str | None
    script_revision: int
    world_law_revision: int
    graph_revision: int
    graph_sha256: str
    form_projection_sha256: str
    source_name: str
    source_sha256: str

    def public(self):
        return asdict(self)


def checked_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError(label + ' must be a nonempty stable identifier')
    return value


def create_scope(connection, project_id=None, universe_id=None, *, kind='generic'):
    if kind not in ('generic', 'afm-starters', 'legacy-unverified'):
        raise ValueError('Invalid universe kind')
    project_id = checked_id(project_id or 'project-' + uuid4().hex, 'Project ID')
    universe_id = checked_id(universe_id or 'universe-' + uuid4().hex, 'Universe ID')
    connection.execute('''CREATE TABLE project_scope(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        project_id TEXT NOT NULL, universe_id TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL)''')
    connection.execute('INSERT INTO project_scope VALUES(1,?,?,?,0)', (project_id, universe_id, kind))
    return scope_in_connection(connection)


def scope_in_connection(connection):
    row = connection.execute('SELECT project_id,universe_id,kind,revision FROM project_scope WHERE singleton=1').fetchone()
    if row is None:
        raise ValueError('Project/universe binding is missing')
    return {'project_id':row['project_id'], 'universe_id':row['universe_id'],
            'kind':row['kind'], 'scope_revision':row['revision']}


def verify_scope(connection, *, project_id=None, universe_id=None):
    scope = scope_in_connection(connection)
    if project_id is not None and project_id != scope['project_id']:
        raise ValueError('Project does not match this timeline')
    if universe_id is not None and universe_id != scope['universe_id']:
        raise ValueError('Universe does not match this timeline')
    return scope


def migrate_legacy_copy(source, destination, *, project_id, universe_id, afm=False):
    """Online-backup a legacy DB to a new file and migrate the copy only.

    The source is opened read-only. Original law tables are retained verbatim;
    the new scope and per-universe tables are added transactionally to the copy.
    An existing destination is never replaced.
    """
    checked_id(project_id, 'Project ID'); checked_id(universe_id, 'Universe ID')
    source, destination = Path(source), Path(destination)
    info = source.lstat()
    if source.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        raise ValueError('Source database must not be a link')
    source = source.resolve(strict=True)
    if not source.is_file() or destination.resolve() == source:
        raise ValueError('Choose a separate destination file')
    if not destination.parent.is_dir():
        raise ValueError('Destination directory must already exist')
    with destination.open('xb'):
        pass
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)) as src:
        with closing(sqlite3.connect(str(destination),timeout=10)) as dst:
            src.backup(dst, pages=256, sleep=0.1)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Legacy backup integrity check failed')
            dst.row_factory = sqlite3.Row
            dst.execute('PRAGMA foreign_keys=ON')
            dst.execute('BEGIN IMMEDIATE')
            tables={r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'project_scope' in tables:
                raise ValueError('Source is already scoped; use a normal SQLite backup')
            if not {'episodes','branches','revisions'} <= tables:
                raise ValueError('Source is not a recognized timeline')
            scope = create_scope(dst, project_id, universe_id, kind='afm-starters' if afm else 'legacy-unverified')
            dst.execute('''CREATE TABLE universe_law_head(universe_id TEXT PRIMARY KEY, revision INTEGER NOT NULL)''')
            dst.execute('''CREATE TABLE universe_law_revisions(universe_id TEXT NOT NULL, revision INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(universe_id,revision))''')
            if ('world_law_head' in tables) != ('world_law_revisions' in tables):
                raise ValueError('Legacy law history is incomplete')
            if 'world_law_head' in tables and 'world_law_revisions' in tables:
                head=dst.execute('SELECT revision FROM world_law_head WHERE singleton=1').fetchone()
                rows=dst.execute('SELECT revision,payload FROM world_law_revisions ORDER BY revision').fetchall()
                if not head or not rows or not any(r['revision']==head['revision'] for r in rows):
                    raise ValueError('Legacy law history is incomplete')
                for row in rows:
                    json.loads(row['payload'])
                    dst.execute('INSERT INTO universe_law_revisions VALUES(?,?,?)',(universe_id,row['revision'],row['payload']))
                dst.execute('INSERT INTO universe_law_head VALUES(?,?)',(universe_id,head['revision']))
            dst.commit()
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Migrated copy integrity check failed')
    return {'source':str(source), 'destination':str(destination.resolve()), 'scope':scope,
            'status':'copied-and-migrated', 'legacy_tables_preserved':True}
