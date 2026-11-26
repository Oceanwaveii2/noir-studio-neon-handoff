"""Inspect beat declarations for world-state transaction contract mismatches."""
from __future__ import annotations


def inspect_transactions(dag, world) -> list[dict]:
    issues = []
    for beat in dag.nodes.values():
        for index, tx in enumerate(beat.transactions):
            problem = None
            if tx.action == "somatic_update":
                if tx.actor not in world.characters:
                    problem = "somatic update actor is not a registered character"
                elif not isinstance(tx.params.get("somatic"), dict) or not tx.params["somatic"]:
                    problem = "somatic update has no somatic values; operation would do nothing"
            elif tx.action == "take" and tx.target not in world.props:
                problem = "prop is missing from initial world; later creation must be verified"
            if problem:
                issues.append({"beat_id": beat.id, "transaction": index, "action": tx.action,
                               "actor": tx.actor, "target": tx.target, "issue": problem})
    return issues


def attach_history_store(db, path, alias):
    """Keep changes to the two existing SQLite files in one commit."""
    if alias not in ('history_db', 'form_db'):
        raise ValueError('Invalid history database')
    db.execute(f'ATTACH DATABASE ? AS {alias}', (str(path),))
    for schema in ('main', alias):
        mode = db.execute(f'PRAGMA {schema}.journal_mode').fetchone()[0]
        if mode not in ('delete', 'truncate', 'persist'):
            raise ValueError('Project history requires rollback journals on both workspace files')


def _tables(db, schema):
    return db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name='project_history_head'").fetchone()


def _revision(db, schema):
    if not _tables(db, schema):
        return 0
    return db.execute(f'SELECT revision FROM {schema}.project_history_head WHERE singleton=1').fetchone()[0]


def _advance(db, schema):
    db.execute(f'UPDATE {schema}.project_history_head SET revision=revision+1 WHERE singleton=1')
    return _revision(db, schema)


def record_project_edit(db, *, domain, target, operation, token, before_patch, after_patch, schema='main'):
    import json
    from datetime import datetime, timezone
    from uuid import uuid4
    db.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.project_history_head(
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL)""")
    db.execute(f'INSERT OR IGNORE INTO {schema}.project_history_head VALUES(1,0)')
    db.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.project_history_entries(
        tx_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, domain TEXT NOT NULL, target TEXT NOT NULL,
        operation TEXT NOT NULL, token TEXT NOT NULL, state TEXT NOT NULL, ordering INTEGER NOT NULL,
        before_patch TEXT NOT NULL, after_patch TEXT NOT NULL)""")
    rev = _advance(db, schema)
    db.execute(f"UPDATE {schema}.project_history_entries SET state='discarded' WHERE state='undone'")
    db.execute(f'INSERT INTO {schema}.project_history_entries VALUES(?,?,?,?,?,?,?,?,?,?)',
               (uuid4().hex, datetime.now(timezone.utc).isoformat(), domain, target, operation,
                str(token), 'applied', rev, json.dumps(before_patch), json.dumps(after_patch)))


def step_project_edit(db, *, domain, target, token, next_token, undo, schema='main'):
    if not _tables(db, schema):
        return
    previous, following = ('applied', 'undone') if undo else ('undone', 'applied')
    rev = _advance(db, schema)
    db.execute(f"""UPDATE {schema}.project_history_entries SET state=?, token=?, ordering=?
        WHERE tx_id=(SELECT tx_id FROM {schema}.project_history_entries
        WHERE domain=? AND target=? AND token=? AND state=? ORDER BY ordering DESC LIMIT 1)""",
               (following, str(next_token), rev, domain, target, str(token), previous))


def project_history_top(db, undo):
    if not _tables(db, 'main'):
        return None
    return db.execute("""SELECT tx_id,timestamp,domain,target,operation,token,before_patch,after_patch
        FROM project_history_entries WHERE state=? ORDER BY ordering DESC LIMIT 1""",
                      ('applied' if undo else 'undone',)).fetchone()


def project_history_state(db):
    return {'revision': _revision(db, 'main'),
            **{f'next_{kind}': (dict(row) if (row := project_history_top(db, kind == 'undo')) else None)
               for kind in ('undo', 'redo')}}
