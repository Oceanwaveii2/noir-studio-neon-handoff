"""Local, revision-checked persistence and profile projection for the Studio character graph."""
from __future__ import annotations

from . import transaction_audit

import base64
import binascii
from contextlib import closing, nullcontext
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid
import zlib

from story_graph.character_forms import AFM_JUNCTIONS, CharacterForm, CharacterJunction, FormLink


NODE_KINDS = frozenset(("digital_mind", "super_character"))
APPLICATION_ID = 0x41464D46
FORMATTED_CUE_PREFIX = "cue-character-"

DEFAULT_FORM_TARGETS = (
    {"id": "node_personality_rainee", "kind": "digital_mind", "label": "Rainee Ling"},
    {"id": "node_personality_rainee_peter", "kind": "digital_mind", "label": "Rainee Peter"},
    {"id": "node_personality_francine", "kind": "digital_mind", "label": "Francine Ling"},
    {"id": "node_personality_franny_anderson", "kind": "digital_mind", "label": "Nurse Franny"},
    {"id": "node_personality_haley", "kind": "digital_mind", "label": "Haley Ling"},
    {"id": "node_personality_stella", "kind": "digital_mind", "label": "Stella Ling"},
    {"id": "node_personality_roger", "kind": "digital_mind", "label": "Roger the Alien"},
)

# These are the reference images already attached to the original Studio nodes.
# They are references, not new copies or assertions about other forms.
FORM_IMAGES = {
    ("rainee", "rainee"): "/images/image6.jpeg",
    ("rainee", "peter_griffin_celestial_variant"): "/images/image11.png",
    ("francine", "francine"): "/images/image2.jpeg",
    ("francine", "nurse_pamela_franny_anderson"): "/images/image15.jpeg",
    ("haley", "haley"): "/images/image4.png",
    ("stella", "stella"): "/images/image5.png",
    ("roger", "roger"): "/images/image17.png",
}


class StaleFormGraph(ValueError):
    pass


def cue_junctions(connection):
    """Read the empty junctions inferred from explicit manuscript speaker cues."""
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='prepared_character_cues'"
    ).fetchone():
        return {}
    return {
        ident: CharacterJunction(ident, (CharacterForm(ident, label, "base"),))
        for ident, label in connection.execute("SELECT id,label FROM prepared_character_cues ORDER BY id")
    }


def register_cue(connection, scope, key, label, source):
    """Run inside Cook's timeline transaction so a failed compile adds no sockets."""
    connection.execute("""CREATE TABLE IF NOT EXISTS prepared_character_cues (
        id TEXT PRIMARY KEY, cue_key TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
        episode TEXT NOT NULL REFERENCES episodes(id), source TEXT NOT NULL)""")
    identity = json.dumps([scope["project"], scope["universe"], key], ensure_ascii=False)
    ident = FORMATTED_CUE_PREFIX + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    connection.execute(
        "INSERT INTO prepared_character_cues VALUES (?,?,?,?,?)",
        (ident, key, label, scope["episode"], json.dumps(source, ensure_ascii=False)),
    )
    return CharacterJunction(ident, (CharacterForm(ident, label, "base"),))


def attachment_image_type(content: bytes) -> str | None:
    """Preview only recognized raster formats; everything else is a download."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _board_content(board, attachment_ids: set[str]) -> dict:
    if not isinstance(board, dict) or set(board) != {"notes", "positions"}:
        raise ValueError("Choose a valid reference board.")
    notes, positions = board["notes"], board["positions"]
    if not isinstance(notes, list) or len(notes) > 40:
        raise ValueError("A board can hold up to 40 notes.")
    keys = {"portrait", "mind"} | {f"file:{ident}" for ident in attachment_ids}
    for note in notes:
        if (not isinstance(note, dict) or set(note) != {"id", "text"}
                or not isinstance(note["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", note["id"])
                or not isinstance(note["text"], str) or len(note["text"]) > 4000):
            raise ValueError("A note needs a valid ID and at most 4,000 characters.")
        key = f"note:{note['id']}"
        if key in keys:
            raise ValueError("Board note IDs must be unique.")
        keys.add(key)
    if len(json.dumps(notes, ensure_ascii=False).encode("utf-8")) > 200_000:
        raise ValueError("This board has too much note text.")
    if not isinstance(positions, dict) or len(positions) > 256:
        raise ValueError("A board can store up to 256 card positions.")
    for key, point in positions.items():
        if (key not in keys or not isinstance(point, dict) or set(point) != {"x", "y"}
                or type(point["x"]) is not int or not 0 <= point["x"] <= 3200
                or type(point["y"]) is not int or not 0 <= point["y"] <= 24_000):
            raise ValueError("Choose a valid position for a card on this form's board.")
    return {"notes": notes, "positions": positions}


class FormGraphStore:
    def __init__(self, path: Path | None, builtins: list[dict] | tuple[dict, ...] = DEFAULT_FORM_TARGETS, imported=None):
        self.path = path.resolve() if path is not None else None
        self.builtins = {node["id"]: dict(node) for node in builtins}
        self.imported = imported or {}

    @staticmethod
    def _empty() -> dict:
        return {"nodes": {}, "links": {}, "stella_stages": []}

    def _read(self, db, schema="main") -> tuple[int, dict]:
        row = db.execute(f"SELECT revision, data FROM {schema}.form_graph WHERE id=1").fetchone()
        return (row[0], json.loads(row[1])) if row else (0, self._empty())

    def _nodes(self, data: dict) -> dict:
        return {**self.builtins, **data["nodes"]}

    @staticmethod
    def _extract_node_fields(cid: str, form: CharacterForm, is_base: bool,
                             char_node_data: dict, linked: bool) -> list[dict]:
        """Project saved node_data fields onto canonical profile entries for a form."""
        if not isinstance(char_node_data, dict):
            return []
        candidate_keys = []
        if is_base:
            candidate_keys.append(f"character:{cid}:junction")
        port_id = f"character:{cid}:form:{form.id}"
        candidate_keys.append(port_id)
        if linked:
            candidate_keys.append(f"data:{port_id}")
        text_category = {
            "personality": "personality",
            "voice": "voice",
            "notes": "author_note",
            "author_note": "author_note",
            "behavior": "behavior",
        }
        valid_categories = frozenset({
            "personality", "voice", "author_note", "behavior",
            "relationship", "goal", "physical_state", "knowledge", "objective",
        })
        valid_confidences = frozenset({"author", "verified", "reviewed", "uncertain"})
        fields = []
        seen_ids = set()
        for node_key in candidate_keys:
            entry = char_node_data.get(node_key)
            if not isinstance(entry, dict):
                continue
            text_fields = entry.get("text_fields")
            if isinstance(text_fields, dict):
                for key, cat in text_category.items():
                    val = text_fields.get(key)
                    if isinstance(val, str) and val.strip():
                        fid = f"{node_key}:{key}"
                        if fid not in seen_ids:
                            seen_ids.add(fid)
                            fields.append({
                                "id": fid,
                                "category": cat,
                                "text": val.strip()[:500],
                                "source_type": "universal_author",
                                "source_id": f"form-graph:{node_key}",
                                "confidence": "author",
                            })
            structured = entry.get("structured_data")
            if isinstance(structured, dict):
                for key, val in structured.items():
                    if key == "fields" and isinstance(val, list):
                        for item in val:
                            if not isinstance(item, dict):
                                continue
                            iid = item.get("id")
                            cat = item.get("category")
                            txt = item.get("text")
                            stype = item.get("source_type")
                            sid = item.get("source_id")
                            conf = item.get("confidence")
                            if (isinstance(iid, str) and iid and iid not in seen_ids
                                    and cat in valid_categories
                                    and isinstance(txt, str) and txt.strip()
                                    and stype in ("universal_author", "event")
                                    and isinstance(sid, str) and sid
                                    and conf in valid_confidences):
                                seen_ids.add(iid)
                                fields.append({
                                    "id": iid,
                                    "category": cat,
                                    "text": txt.strip()[:500],
                                    "source_type": stype,
                                    "source_id": sid,
                                    "confidence": conf,
                                })
                    elif isinstance(val, str) and val.strip() and isinstance(key, str) and key.strip():
                        if key in ("personality", "voice", "author_note", "behavior"):
                            cat = key
                            txt = val.strip()[:500]
                        elif key == "notes":
                            cat = "author_note"
                            txt = val.strip()[:500]
                        else:
                            cat = "author_note"
                            txt = f"{key.strip()}: {val.strip()}"[:500]
                        safe_key = re.sub(r"[^A-Za-z0-9_.:/-]+", "_", key.strip()).strip("_") or "field"
                        fid = f"{node_key}:structured:{safe_key}"[:160]
                        if fid not in seen_ids:
                            seen_ids.add(fid)
                            fields.append({
                                "id": fid,
                                "category": cat,
                                "text": txt,
                                "source_type": "universal_author",
                                "source_id": f"form-graph:{node_key}",
                                "confidence": "author",
                            })
        return fields

    def _junctions(self, data: dict, revision: int = 0) -> dict[str, CharacterJunction]:
        targets = self._nodes(data)
        result = {}
        from story_graph.character_relationships import override_records
        from story_graph.source_imports import merge_junctions
        junctions = merge_junctions(AFM_JUNCTIONS, self.imported)
        for cid, label in data.get("characters", {}).items():
            if cid in junctions:
                raise ValueError("Character graph ID conflicts with an existing character.")
            junctions[cid] = CharacterJunction(cid, (CharacterForm(cid, label, "base"),))
        all_node_data = data.get("node_data", {})
        for cid, junction in junctions.items():
            forms = junction.forms
            if cid == "stella" and data["stella_stages"]:
                stage_forms = []
                after = forms[0].id
                for stage in data["stella_stages"]:
                    stage_forms.append(CharacterForm(stage["id"], stage["label"], "stage", after=after))
                    after = stage["id"]
                canonical = AFM_JUNCTIONS["stella"].forms
                forms = (
                    canonical[0],
                    *stage_forms,
                    replace(canonical[-1], after=after),
                    *tuple(f for f in forms if f.id not in {x.id for x in canonical}),
                )
            seen_form_ids = {f.id for f in forms}
            custom_forms = []
            for custom in data.get("custom_forms", {}).get(cid, ()):
                fid = custom.get("id")
                if not fid or fid in seen_form_ids:
                    continue
                after_id = custom.get("after") if custom.get("after") in seen_form_ids else forms[0].id
                custom_forms.append(
                    CharacterForm(
                        fid,
                        custom.get("label") or fid,
                        custom.get("kind", "transformation"),
                        after=after_id,
                    )
                )
                seen_form_ids.add(fid)
            if custom_forms:
                forms = (*forms, *custom_forms)
            linked = []
            mind_behaviors = {}
            for form in forms:
                port = f"{junction.id}:form:{form.id}"
                if port in data["links"]:
                    node = targets[data["links"][port]]
                    form = replace(form, link=FormLink(node["kind"], node["id"]))
                if form.link:
                    content = all_node_data.get(cid, {}).get("data:" + port, {})
                    text_fields = content.get("text_fields")
                    if isinstance(text_fields, dict) and isinstance(text_fields.get("behavior"), str):
                        mind_behaviors[form.id] = text_fields["behavior"].strip()
                linked.append(form)
            base_id = next((f.id for f in linked if f.kind == "base"), linked[0].id)
            char_node_data = all_node_data.get(cid, {})
            node_profiles = []
            relationship_overrides = {}
            for form in linked:
                port = f"{junction.id}:form:{form.id}"
                node = char_node_data.get(port, {})
                structured = node.get("structured_data") if isinstance(node, dict) else None
                if isinstance(structured, dict) and "relationship_overrides" in structured:
                    relationship_overrides[form.id] = override_records(structured["relationship_overrides"])
                extracted = self._extract_node_fields(
                    cid, form, form.id == base_id, char_node_data, form.link is not None
                )
                if extracted:
                    node_profiles.append({
                        "character_id": cid,
                        "form_id": form.id,
                        "node_id": form.link.node_id if form.link else f"{junction.id}:form:{form.id}",
                        "kind": form.link.kind if form.link else "form_card",
                        "revision": int(revision),
                        "fields": extracted,
                    })
            result[cid] = CharacterJunction(
                cid, tuple(linked), tuple(node_profiles), mind_behaviors, relationship_overrides,
                tuple(edge for edge in data.get("relationship_edges", ()) if edge["from"]["character"] == cid),
                tuple(route for route in data.get("staging", ()) if route["character"] == cid),
            )
        return result

    def _payload(self, revision: int, data: dict) -> dict:
        groups = [group.project(planning=True) for group in self._junctions(data, revision).values()]
        for group in groups:
            group["label"] = "Francine" if group["character_id"] == "francine" else group["forms"][0]["label"]
            group["positions"] = data.get("layouts", {}).get(group["character_id"], {})
            group["can_undo_position"] = bool(data.get("layout_history", {}).get(group["character_id"]))
            group["can_redo_position"] = bool(data.get("layout_redo", {}).get(group["character_id"]))
            group["node_data"] = data.get("node_data", {}).get(group["character_id"], {})
            group["staging"] = [route for route in data.get("staging", ()) if route["character"] == group["character_id"]]
            group["node_data_undo"] = {
                node: bool(history)
                for node, history in data.get("node_data_history", {}).get(group["character_id"], {}).items()
            }
            group["node_data_redo"] = {
                node: bool(history)
                for node, history in data.get("node_data_redo", {}).get(group["character_id"], {}).items()
            }
            group["attachments"] = [
                item for item in data.get("attachments", {}).values() if item["character"] == group["character_id"]
            ]
            group["boards"] = {
                form["port_id"]: data["boards"][form["port_id"]]
                for form in group["forms"] if form["port_id"] in data.get("boards", {})
            }
            for form in group["forms"]:
                if group["character_id"].startswith(FORMATTED_CUE_PREFIX):
                    form["status"] = "planning_only"
                labels = {
                    ("rainee", "rainee"): "2 Broke Girls Max Rainee (Normal)",
                    ("francine", "francine"): "Francine (Normal)",
                    ("francine", "nurse_pamela_franny_anderson"): "Nurse Franny Anderson",
                }
                form["display_label"] = labels.get((group["character_id"], form["id"]), form["label"])
                form["historical_source_form"] = form["id"].startswith("ag1-")
                form["image"] = data.get("images", {}).get(
                    form["port_id"], FORM_IMAGES.get((group["character_id"], form["id"]))
                )
                form["can_undo_image"] = bool(data.get("image_history", {}).get(form["port_id"]))
        return {
            "revision": revision,
            "editable": self.path is not None,
            "can_undo_graph": bool(data.get("_graph_undo", [])),
            "can_redo_graph": bool(data.get("_graph_redo", [])),
            "nodes": list(self._nodes(data).values()),
            "junctions": groups,
            "relationship_edges": data.get("relationship_edges", []),
        }

    def _load(self) -> tuple[int, dict]:
        if self.path is None or not self.path.exists():
            return 0, self._empty()
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            if app_id != APPLICATION_ID:
                if app_id == 0 and not db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                    return 0, self._empty()
                raise ValueError("File is not a Studio character graph store.")
            return self._read(db)

    def read(self) -> dict:
        return self._payload(*self._load())

    def junctions(self) -> dict[str, CharacterJunction]:
        """Read the authoring graph; the compiler applies story availability."""
        revision, data = self._load()
        return self._junctions(data, revision)

    def attachment(self, ident):
        if not isinstance(ident, str) or self.path is None or not self.path.exists():
            raise ValueError("Attachment not found.")
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)) as db:
            _, data = self._read(db)
            meta = data.get("attachments", {}).get(ident)
            if not meta or meta.get("removed"):
                raise ValueError("Attachment not found.")
            row = db.execute("SELECT content FROM form_attachments WHERE id=?", (ident,)).fetchone()
            if not row or hashlib.sha256(row[0]).hexdigest() != meta["sha256"]:
                raise ValueError("Attachment is missing or damaged.")
            return meta, row[0]

    @staticmethod
    def _label(request: dict) -> str:
        label = request.get("label")
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80 or not label.strip().isprintable():
            raise ValueError("Enter a name between 1 and 80 printable characters.")
        return label.strip()

    def change(self, request: dict, *, _history_path=None, _connection=None) -> dict:
        if self.path is None:
            raise ValueError("This workspace has no character graph store.")
        if not isinstance(request, dict) or type(request.get("revision")) is not int:
            raise ValueError("Load the current character graph first.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        own = _connection is None
        schema = "main" if own else "form_db"
        history_schema = ("history_db" if _history_path is not None else None) if own else "main"
        if own and _history_path is not None and self.path == _history_path:
            raise ValueError("Timeline and form graph stores must use different files.")
        connection = closing(sqlite3.connect(self.path)) if own else nullcontext(_connection)
        with connection as db, (db if own else nullcontext()):
            if own:
                if _history_path is not None:
                    transaction_audit.attach_history_store(db, _history_path, "history_db")
                db.execute("BEGIN IMMEDIATE")
            app_id = db.execute(f"PRAGMA {schema}.application_id").fetchone()[0]
            if app_id != APPLICATION_ID:
                if app_id != 0 or db.execute(f"SELECT 1 FROM {schema}.sqlite_master LIMIT 1").fetchone():
                    raise ValueError("File is not a Studio character graph store.")
                db.execute(f"PRAGMA {schema}.application_id={APPLICATION_ID}")
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {schema}.form_graph (id INTEGER PRIMARY KEY CHECK(id=1), "
                "revision INTEGER NOT NULL, data TEXT NOT NULL)"
            )
            revision, data = self._read(db, schema)
            if revision != request["revision"]:
                raise StaleFormGraph("The graph changed in another tab. Reload the links and try again.")
            action = request.get("action")
            undo_stack = data.pop("_graph_undo", [])
            redo_stack = data.pop("_graph_redo", [])
            before = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {schema}.form_graph_journal(id TEXT PRIMARY KEY,before_data BLOB NOT NULL,after_data BLOB NOT NULL)"
            )
            if action in ("undo_graph", "redo_graph"):
                source = undo_stack if action == "undo_graph" else redo_stack
                if not source:
                    raise ValueError(
                        "No character graph change to " + ("undo" if action == "undo_graph" else "redo") + "."
                    )
                ident = source[-1]
                entry = db.execute(
                    f"SELECT before_data,after_data FROM {schema}.form_graph_journal WHERE id=?", (ident,)
                ).fetchone()
                if not entry:
                    raise ValueError("Character graph history is unavailable.")
                earlier, later = (zlib.decompress(entry[0]), zlib.decompress(entry[1]))
                if before != (later if action == "undo_graph" else earlier):
                    raise ValueError("Character graph history changed; reload before continuing.")
                data = json.loads(earlier if action == "undo_graph" else later)
                source.pop()
                (redo_stack if action == "undo_graph" else undo_stack).append(ident)
            elif action in ("save_node_data", "undo_node_data", "redo_node_data"):
                cid, node_id = request.get("character"), request.get("node")
                groups = self._junctions(data, revision)
                if not isinstance(cid, str) or cid not in groups:
                    raise ValueError("Choose an existing character graph.")
                group = groups[cid]
                ports = {f["port_id"] for f in group.project(planning=True)["forms"]}
                allowed = {group.id} | ports | {"data:" + item["port_id"] for item in group.project(planning=True)["forms"] if item["link"]}
                if not isinstance(node_id, str) or node_id not in allowed:
                    raise ValueError("Choose a node in this character graph.")
                records = data.setdefault("node_data", {}).setdefault(cid, {})
                history = data.setdefault("node_data_history", {}).setdefault(cid, {}).setdefault(node_id, [])
                future = data.setdefault("node_data_redo", {}).setdefault(cid, {}).setdefault(node_id, [])
                if action == "undo_node_data":
                    if not history:
                        raise ValueError("There is no earlier node data to restore.")
                    future.append(records.get(node_id))
                    previous = history.pop()
                    if previous is None:
                        records.pop(node_id, None)
                    else:
                        records[node_id] = previous
                elif action == "redo_node_data":
                    if not future:
                        raise ValueError("There is no node data to redo.")
                    history.append(records.get(node_id))
                    following = future.pop()
                    if following is None:
                        records.pop(node_id, None)
                    else:
                        records[node_id] = following
                else:
                    content = request.get("content")
                    if not isinstance(content, dict):
                        raise ValueError("Node data must be an object.")
                    try:
                        encoded = json.dumps(content, ensure_ascii=False, allow_nan=False)
                    except (TypeError, ValueError, RecursionError):
                        raise ValueError("Node data is not valid JSON.")
                    if len(encoded.encode("utf-8")) > 200000:
                        raise ValueError("Node data is too large.")
                    if records.get(node_id) == content:
                        data["_graph_undo"] = undo_stack
                        data["_graph_redo"] = redo_stack
                        return self._payload(revision, data)
                    history.append(records.get(node_id))
                    future.clear()
                    records[node_id] = content
            elif action == "save_board":
                cid, port = request.get("character"), request.get("port")
                groups = self._junctions(data, revision)
                group = groups.get(cid) if isinstance(cid, str) else None
                if (not group or not isinstance(port, str)
                        or port not in {f["port_id"] for f in group.project(planning=True)["forms"]}):
                    raise ValueError("Choose a board on an existing character form.")
                attachments = {item["id"] for item in data.get("attachments", {}).values()
                               if item["character"] == cid and item["node"] == port}
                board = _board_content(request.get("board"), attachments)
                boards = data.setdefault("boards", {})
                if boards.get(port, {"notes": [], "positions": {}}) == board:
                    data["_graph_undo"] = undo_stack
                    data["_graph_redo"] = redo_stack
                    return self._payload(revision, data)
                boards[port] = board
            elif action in ("add_attachment", "remove_attachment", "restore_attachment"):
                cid, node_id = request.get("character"), request.get("node")
                groups = self._junctions(data, revision)
                if not isinstance(cid, str) or cid not in groups:
                    raise ValueError("Choose an existing character graph.")
                ports = {f["port_id"] for f in groups[cid].project(planning=True)["forms"]}
                if node_id not in ({groups[cid].id} | ports | {"data:" + item["port_id"] for item in groups[cid].project(planning=True)["forms"] if item["link"]}):
                    raise ValueError("Choose a node in this character graph.")
                attachments = data.setdefault("attachments", {})
                if action == "add_attachment":
                    name = request.get("name")
                    encoded = request.get("content")
                    if (
                        not isinstance(name, str)
                        or not name.strip()
                        or len(name) > 255
                        or not name.isprintable()
                        or "/" in name
                        or "\\" in name
                    ):
                        raise ValueError("Choose a file with a valid name.")
                    try:
                        raw = base64.b64decode(encoded, validate=True)
                    except (TypeError, ValueError, binascii.Error):
                        raise ValueError("The file could not be read.")
                    if not raw or len(raw) > 20_000_000:
                        raise ValueError("Choose a nonempty file up to 20 MB.")
                    image_type = attachment_image_type(raw)
                    if request.get("image_only") is True and image_type is None:
                        raise ValueError("Choose a PNG, JPEG or WebP image.")
                    ident = uuid.uuid4().hex
                    db.execute(f"CREATE TABLE IF NOT EXISTS {schema}.form_attachments(id TEXT PRIMARY KEY,content BLOB NOT NULL)")
                    db.execute(f"INSERT INTO {schema}.form_attachments VALUES(?,?)", (ident, raw))
                    attachments[ident] = {
                        "id": ident,
                        "character": cid,
                        "node": node_id,
                        "name": name.strip(),
                        "size": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "image_type": image_type,
                        "removed": False,
                    }
                else:
                    item = attachments.get(request.get("attachment"))
                    if not item or item["character"] != cid or item["node"] != node_id:
                        raise ValueError("Choose an attachment on this node.")
                    desired = action == "remove_attachment"
                    if item["removed"] == desired:
                        raise ValueError("The attachment has already changed.")
                    item["removed"] = desired
            elif action in ("move_node", "undo_position", "redo_position"):
                cid = request.get("character")
                groups = self._junctions(data, revision)
                if not isinstance(cid, str) or cid not in groups:
                    raise ValueError("Choose an existing character graph.")
                positions = data.setdefault("layouts", {}).setdefault(cid, {})
                history = data.setdefault("layout_history", {}).setdefault(cid, [])
                future = data.setdefault("layout_redo", {}).setdefault(cid, [])
                if action == "undo_position":
                    if not history:
                        raise ValueError("There is no earlier node position to restore.")
                    previous = history.pop()
                    future.append({"node": previous["node"], "position": positions.get(previous["node"])})
                    if previous["position"] is None:
                        positions.pop(previous["node"], None)
                    else:
                        positions[previous["node"]] = previous["position"]
                elif action == "redo_position":
                    if not future:
                        raise ValueError("There is no node position to redo.")
                    following = future.pop()
                    history.append({"node": following["node"], "position": positions.get(following["node"])})
                    if following["position"] is None:
                        positions.pop(following["node"], None)
                    else:
                        positions[following["node"]] = following["position"]
                else:
                    node_id = request.get("node")
                    group = groups[cid]
                    ports = {f["port_id"] for f in group.project(planning=True)["forms"]}
                    allowed = {group.id} | ports | {"data:" + item["port_id"] for item in group.project(planning=True)["forms"] if item["link"]}
                    if not isinstance(node_id, str) or node_id not in allowed:
                        raise ValueError("Choose a node in this character graph.")
                    position = request.get("position")
                    if (
                        not isinstance(position, dict)
                        or set(position) != {"x", "y"}
                        or any(
                            type(position[k]) not in (int, float)
                            or not math.isfinite(position[k])
                            or abs(position[k]) > 100000
                            for k in ("x", "y")
                        )
                    ):
                        raise ValueError("Choose a valid node position.")
                    position = {"x": position["x"], "y": position["y"]}
                    if positions.get(node_id) == position:
                        data["_graph_undo"] = undo_stack
                        data["_graph_redo"] = redo_stack
                        return self._payload(revision, data)
                    history.append({"node": node_id, "position": positions.get(node_id)})
                    future.clear()
                    positions[node_id] = position
            elif action == "add_character":
                label = self._label(request)
                existing_junctions = self._junctions(data, revision)
                if any(g.forms[0].label.casefold() == label.casefold() for g in existing_junctions.values()):
                    raise ValueError("A character graph already has this name.")
                requested_id = request.get("character_id")
                if requested_id is not None:
                    if not isinstance(requested_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", requested_id):
                        raise ValueError("Choose a valid lowercase character ID.")
                    if requested_id in existing_junctions:
                        raise ValueError("A character graph already uses this ID.")
                    cid = requested_id
                else:
                    cid = "character-" + uuid.uuid4().hex
                data.setdefault("characters", {})[cid] = label
            elif action == "set_image":
                port, image = request.get("port"), request.get("image")
                ports = {
                    f["port_id"] for g in self._junctions(data, revision).values() for f in g.project(planning=True)["forms"]
                }
                if port not in ports:
                    raise ValueError("Choose an existing character form.")
                if not isinstance(image, str) or not image.startswith(
                    ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")
                ):
                    raise ValueError("Choose a PNG, JPEG or WebP image.")
                try:
                    header, encoded = image.split(",", 1)
                    raw = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise ValueError("The image could not be read.")
                if len(raw) > 5_000_000 or not raw:
                    raise ValueError("Choose an image no larger than 5 MB.")
                signatures = {
                    "data:image/png;base64": b"\x89PNG\r\n\x1a\n",
                    "data:image/jpeg;base64": b"\xff\xd8\xff",
                    "data:image/webp;base64": b"RIFF",
                }
                if not raw.startswith(signatures[header]) or (header.endswith("webp;base64") and raw[8:12] != b"WEBP"):
                    raise ValueError("The image format does not match the file.")
                images = data.setdefault("images", {})
                data.setdefault("image_history", {}).setdefault(port, []).append(images.get(port))
                images[port] = image
            elif action == "undo_image":
                port = request.get("port")
                ports = {
                    f["port_id"] for g in self._junctions(data, revision).values() for f in g.project(planning=True)["forms"]
                }
                history = data.get("image_history", {}).get(port, [])
                if port not in ports or not history:
                    raise ValueError("No previous image is available for this form.")
                previous = history.pop()
                if previous is None:
                    data.setdefault("images", {}).pop(port, None)
                else:
                    data.setdefault("images", {})[port] = previous
            elif action == "set_link":
                port, node_id = request.get("port"), request.get("node_id")
                ports = {
                    form["port_id"]
                    for group in self._junctions(data, revision).values()
                    for form in group.project(planning=True)["forms"]
                }
                if not isinstance(port, str) or port not in ports:
                    raise ValueError("Choose an existing form data port.")
                if node_id is not None and (not isinstance(node_id, str) or node_id not in self._nodes(data)):
                    raise ValueError("Choose an existing Digital Mind or Super Character.")
                if data["links"].get(port) == node_id:
                    data["_graph_undo"] = undo_stack
                    data["_graph_redo"] = redo_stack
                    return self._payload(revision, data)
                if node_id is None:
                    data["links"].pop(port, None)
                else:
                    data["links"][port] = node_id
            elif action in ("stage_form", "set_relationship"):
                from .universe_scope import checked_id

                episode = checked_id(request.get("episode"), "Episode")
                branch = checked_id(request.get("branch"), "Branch")
                groups = self._junctions(data, revision)

                def endpoint(character, form):
                    if not isinstance(character, str) or character not in groups:
                        raise ValueError("Choose an existing character.")
                    if not any(item.id == form for item in groups[character].forms):
                        raise ValueError("Choose an existing form on that character.")
                    return {"character": character, "form": form}

                origin = endpoint(request.get("character"), request.get("form"))
                if action == "stage_form":
                    position = request.get("_episode_position")
                    if type(position) is not int:
                        raise ValueError("Load the saved episode position before routing forms.")
                    route = {**origin, "episode": episode, "branch": branch}
                    group = replace(groups[origin["character"]], staging=(route,))
                    if group.route_at(episode, branch, position,
                                      time_travel_override=request.get("_time_travel_override") is True)[0] is None:
                        raise ValueError("This form or its predecessor is locked at the episode position.")
                    data["staging"] = [
                        item for item in data.get("staging", ())
                        if (item["episode"], item["branch"], item["character"]) != (episode, branch, origin["character"])
                    ] + [route]
                else:
                    target = endpoint(request.get("target_character"), request.get("target_form"))
                    if target["character"] == origin["character"]:
                        raise ValueError("Choose a different character for a directed relationship.")
                    patience, friction = (request.get(key) for key in ("patience", "friction"))
                    if any(type(value) not in (int, float) or not 0 <= value <= 1 for value in (patience, friction)):
                        raise ValueError("Patience and friction must be between 0 and 1.")
                    direction = request.get("bridging_direction", "")
                    if not isinstance(direction, str) or len(direction) > 300 or any(ch in direction for ch in "\r\n\0"):
                        raise ValueError("Give one line of bridging direction up to 300 characters.")
                    basis = {"episode": episode, "branch": branch, "from": origin, "to": target}
                    edges = data.setdefault("relationship_edges", [])
                    index = next((i for i, edge in enumerate(edges)
                                  if all(edge[key] == value for key, value in basis.items())), None)
                    edge = {**basis, "kind": "dialogue_stance", "patience": patience, "friction": friction,
                            "bridging_direction": direction.strip(), "retired": request.get("retired") is True}
                    if index is None:
                        edges.append(edge)
                    else:
                        edges[index] = edge
            elif action in ("add_node", "create_mind_link"):
                label = self._label(request)
                kind = request.get("kind")
                if not isinstance(kind, str) or kind not in NODE_KINDS:
                    raise ValueError("Choose Digital Mind or Super Character.")
                if any(
                    node["kind"] == kind and node["label"].casefold() == label.casefold()
                    for node in self._nodes(data).values()
                ):
                    raise ValueError("A data node of that type already has this name.")
                if action == "create_mind_link":
                    port = request.get("port")
                    ports = {f["port_id"] for group in self._junctions(data, revision).values()
                             for f in group.project(planning=True)["forms"]}
                    if not isinstance(port, str) or port not in ports:
                        raise ValueError("Choose an existing form data port.")
                node_id = "form-data:" + uuid.uuid4().hex
                node = {"id": node_id, "kind": kind, "label": label}
                if kind == "super_character":
                    payload = request.get("mind_payload", {})
                    if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 200000:
                        raise ValueError("Super Character payload is too large.")
                    node.update(schema_mode="open", mind_payload=payload)
                data["nodes"][node_id] = node
                if action == "create_mind_link":
                    data["links"][port] = node_id
            elif action == "add_stella_stage":
                label = self._label(request)
                labels = [stage["label"] for stage in data["stella_stages"]]
                labels += [form.label for form in AFM_JUNCTIONS["stella"].forms]
                if label.casefold() in {name.casefold() for name in labels}:
                    raise ValueError("Stella already has a form or stage with this name.")
                data["stella_stages"].append({"id": "stage-" + uuid.uuid4().hex, "label": label})
            elif action == "add_form":
                cid = request.get("character")
                groups = self._junctions(data, revision)
                if not isinstance(cid, str) or cid not in groups:
                    raise ValueError("Choose an existing character graph.")
                label = self._label(request)
                kind = request.get("kind", "transformation")
                if kind not in {"persona", "transformation", "stage"}:
                    raise ValueError("Form kind must be persona, transformation, or stage.")
                group = groups[cid]
                if any(f.label.casefold() == label.casefold() for f in group.forms):
                    raise ValueError("This character already has a form with this name.")
                fid = request.get("form_id") or ("form-" + uuid.uuid4().hex[:16])
                if not isinstance(fid, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", fid):
                    raise ValueError("Choose a valid form ID.")
                if any(f.id == fid for f in group.forms):
                    raise ValueError("This character already uses this form ID.")
                after = request.get("after") or group.forms[0].id
                if after not in {f.id for f in group.forms}:
                    raise ValueError("Parent form does not exist on this character.")
                data.setdefault("custom_forms", {}).setdefault(cid, []).append(
                    {"id": fid, "label": label, "kind": kind, "after": after}
                )
            else:
                raise ValueError("Unknown character graph change.")
            if action not in ("undo_graph", "redo_graph"):
                after = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ident = uuid.uuid4().hex
                db.execute(
                    f"INSERT INTO {schema}.form_graph_journal VALUES(?,?,?)",
                    (ident, zlib.compress(before), zlib.compress(after)),
                )
                undo_stack.append(ident)
                redo_stack = []
            data["_graph_undo"] = undo_stack
            data["_graph_redo"] = redo_stack
            if history_schema and action in ("undo_graph", "redo_graph"):
                transaction_audit.step_project_edit(
                    db, domain="forms", target="", token=ident, next_token=ident,
                    undo=action == "undo_graph", schema=history_schema)
            elif history_schema:
                transaction_audit.record_project_edit(
                    db, domain="forms", target="", operation=action, token=ident,
                    before_patch={"form_journal": ident, "side": "before"},
                    after_patch={"form_journal": ident, "side": "after"}, schema=history_schema)
            revision += 1
            result = self._payload(revision, data)
            db.execute(
                f"INSERT INTO {schema}.form_graph (id, revision, data) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET revision=excluded.revision, data=excluded.data",
                (revision, json.dumps(data, ensure_ascii=False)),
            )
            return result
