"""Transactional, local revision store for explicitly reviewed editorial edits.

This API does not integrate with existing CLI or Studio routes. Database creation
is explicit; the supplied path must be new. Offsets are Unicode code points.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .editorial_service import Edit, preview, revision
from .voice.world_state import WorldState


class RevisionError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def world_revision(world: WorldState) -> str:
    return hashlib.sha256(_json(dataclasses.asdict(world)).encode("utf-8")).hexdigest()


@contextmanager
def _connect(path: Path):
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        yield db
    finally:
        if db.in_transaction:
            db.rollback()
        db.close()


class RevisionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise RevisionError("revision store does not exist")

    @classmethod
    def create(cls, path: str | Path, text: str, frozen: tuple[tuple[int, int], ...]):
        path = Path(path)
        if any(type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text) for a, b in frozen):
            raise RevisionError("invalid frozen range")
        # Exclusive creation prevents replacing an existing document or store.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            with _connect(path) as db:
                db.executescript("""
                    CREATE TABLE revisions (
                        number INTEGER PRIMARY KEY, text TEXT NOT NULL, frozen TEXT NOT NULL,
                        op_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                        reviewer TEXT NOT NULL, kind TEXT NOT NULL, parent INTEGER
                    );
                    CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), head INTEGER NOT NULL,
                        FOREIGN KEY(head) REFERENCES revisions(number));
                """)
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO revisions VALUES (0,?,?,?,?,?,?,NULL)",
                           (text, _json(frozen), "initial", "{}", "", "initial"))
                db.execute("INSERT INTO state VALUES (1,0)")
                db.commit()
        except Exception:
            # Leave an incomplete new store visible for diagnosis; never touch an existing path.
            raise
        return cls(path)

    def current(self):
        with _connect(self.path) as db:
            row = db.execute("SELECT r.number,r.text,r.frozen FROM state s JOIN revisions r ON r.number=s.head").fetchone()
        if row is None:
            raise RevisionError("store is incomplete")
        return row[0], row[1], tuple(tuple(x) for x in json.loads(row[2]))

    def at(self, number: int):
        """Read the immutable base of a request, even after the head advances."""
        with _connect(self.path) as db:
            row = db.execute("SELECT text,frozen FROM revisions WHERE number=?", (number,)).fetchone()
        if row is None:
            raise RevisionError("stale revision; reload the document")
        return row[0], tuple(tuple(x) for x in json.loads(row[1]))

    def apply(self, op_id: str, base: int, edits: tuple[Edit, ...], reviewer: str,
              reviewed_candidate_hash: str, reviewed_world_hash: str, world: WorldState):
        if not op_id or op_id == "initial" or not reviewer.strip():
            raise RevisionError("operation ID and named reviewer are required")
        payload = _json({"kind": "apply", "base": base, "edits": [dataclasses.asdict(e) for e in edits],
                         "reviewer": reviewer, "candidate": reviewed_candidate_hash, "world": reviewed_world_hash})
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT number,payload FROM revisions WHERE op_id=?", (op_id,)).fetchone()
            if previous:
                if previous[1] != payload:
                    raise RevisionError("operation ID already used for a different request")
                return previous[0]
            row = db.execute("SELECT r.number,r.text,r.frozen FROM state s JOIN revisions r ON r.number=s.head").fetchone()
            if row is None or row[0] != base:
                raise RevisionError("stale revision")
            frozen = tuple(tuple(x) for x in json.loads(row[2]))
            if world_revision(world) != reviewed_world_hash:
                raise RevisionError("world changed after review")
            result = preview(row[1], revision(row[1]), edits, frozen, world)
            if result.status != "ELIGIBLE_FOR_REVIEW":
                raise RevisionError(result.status)
            if revision(result.candidate) != reviewed_candidate_hash:
                raise RevisionError("candidate changed after review")
            ordered = sorted(edits, key=lambda e: e.start)
            shifted = tuple((a + sum(len(e.replacement) - (e.end-e.start) for e in ordered if e.end <= a),
                             b + sum(len(e.replacement) - (e.end-e.start) for e in ordered if e.end <= b))
                            for a, b in frozen)
            number = row[0] + 1
            db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                       (number, result.candidate, _json(shifted), op_id, payload, reviewer, "apply", row[0]))
            db.execute("UPDATE state SET head=? WHERE id=1", (number,))
            db.commit()
            return number

    @staticmethod
    def _stacks(db):
        rows = db.execute("SELECT number,kind FROM revisions ORDER BY number").fetchall()
        undo_stack = [0]
        redo_stack = []
        for number, kind in rows:
            if number == 0:
                continue
            if kind == "apply":
                undo_stack.append(number)
                redo_stack.clear()
            elif kind == "undo":
                if len(undo_stack) > 1:
                    redo_stack.append(undo_stack.pop())
            elif kind == "redo":
                if redo_stack:
                    undo_stack.append(redo_stack.pop())
        return undo_stack, redo_stack

    def history_status(self) -> dict:
        with _connect(self.path) as db:
            row = db.execute("SELECT head FROM state WHERE id=1").fetchone()
            if row is None:
                raise RevisionError("store is incomplete")
            undo_stack, redo_stack = self._stacks(db)
            return {
                "revision": row[0],
                "can_undo": len(undo_stack) > 1,
                "can_redo": len(redo_stack) > 0,
            }

    def snapshot(self) -> dict:
        """Take the text, head and history flags from one read transaction."""
        with _connect(self.path) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT r.number,r.text,r.frozen FROM state s JOIN revisions r ON r.number=s.head").fetchone()
            if row is None:
                raise RevisionError("store is incomplete")
            undo, redo = self._stacks(db)
            return {"revision":row[0],"text":row[1],"frozen":json.loads(row[2]),
                    "can_undo":len(undo)>1,"can_redo":bool(redo)}

    def undo(self, op_id: str, base: int, reviewer: str):
        if not op_id or op_id == "initial" or not reviewer.strip():
            raise RevisionError("operation ID and named reviewer are required")
        payload = _json({"kind": "undo", "base": base, "reviewer": reviewer})
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT number,payload FROM revisions WHERE op_id=?", (op_id,)).fetchone()
            if previous:
                if previous[1] != payload:
                    raise RevisionError("operation ID already used for a different request")
                return previous[0]
            row = db.execute("SELECT r.number,r.parent FROM state s JOIN revisions r ON r.number=s.head").fetchone()
            if row is None or row[0] != base:
                raise RevisionError("stale revision")
            undo_stack, _ = self._stacks(db)
            if len(undo_stack) <= 1:
                raise RevisionError("initial revision cannot be undone")
            target_rev = undo_stack[-2]
            prior = db.execute("SELECT text,frozen FROM revisions WHERE number=?", (target_rev,)).fetchone()
            number = row[0] + 1
            db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                       (number, prior[0], prior[1], op_id, payload, reviewer, "undo", row[0]))
            db.execute("UPDATE state SET head=? WHERE id=1", (number,))
            db.commit()
            return number

    def redo(self, op_id: str, base: int, reviewer: str):
        if not op_id or op_id == "initial" or not reviewer.strip():
            raise RevisionError("operation ID and named reviewer are required")
        payload = _json({"kind": "redo", "base": base, "reviewer": reviewer})
        with _connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT number,payload FROM revisions WHERE op_id=?", (op_id,)).fetchone()
            if previous:
                if previous[1] != payload:
                    raise RevisionError("operation ID already used for a different request")
                return previous[0]
            row = db.execute("SELECT r.number FROM state s JOIN revisions r ON r.number=s.head").fetchone()
            if row is None or row[0] != base:
                raise RevisionError("stale revision")
            _, redo_stack = self._stacks(db)
            if not redo_stack:
                raise RevisionError("no undone revision to redo")
            target_rev = redo_stack[-1]
            target = db.execute("SELECT text,frozen FROM revisions WHERE number=?", (target_rev,)).fetchone()
            number = row[0] + 1
            db.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                       (number, target[0], target[1], op_id, payload, reviewer, "redo", target_rev))
            db.execute("UPDATE state SET head=? WHERE id=1", (number,))
            db.commit()
            return number

    def export(self, destination: str | Path):
        """Publish an immutable copy without overwriting an existing destination."""
        destination = Path(destination)
        _, text, _ = self.current()
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temp:
                temp_name = temp.name
                temp.write(text.encode("utf-8"))
                temp.flush()
                os.fsync(temp.fileno())
            os.link(temp_name, destination)
        finally:
            if temp_name is not None:
                os.unlink(temp_name)
