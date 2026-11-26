"""Source-pinned, scene-local cast for the FX06 Studio pilot."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from .character_forms import AFM_JUNCTIONS, CharacterForm


PROJECT = "noir-fx06-pilot"
UNIVERSE = "american-foxy-mom"
EPISODE = "fx06-rainee-split"
BRANCH = "fx06-scratch-base"
PETER = "peter_griffin_celestial_variant"
CAST = ("rainee-split-1", "rainee-split-2", "rainee-split-3")
SPEAKERS = ("Rainee 1", "Rainee 2", "Rainee 3")
ROLES = ("Frame setter", "Alliance keeper", "Literal interrupter")
EVENTS = (
    "release-1", "scent-arrives", "haley-smells", "haley-line", "split", "roast",
    "intervention", "rejoin", "peter", "release-2", "payoff",
)
FUSION = "complete-cutaway:01:57.400-01:57.500"
PERFUME_LINE = "It smells like a flower shop died!"
TIMING = {
    "fg-s17e13-wine-lunch": "Keep the conversation moving through small interruptions. Give each reaction its own turn.",
    "ad-s03e07-francine-password": "Let a small pause set the expectation before the last beat overturns it.",
}


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _encoded(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _asset(root: Path, name: str) -> Path:
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("FX06 asset is outside its package")
    return path


def load_bundle(root: Path) -> dict:
    """Compile bounded writer inputs from the staged manifests, never media bytes."""
    root = root.resolve(strict=True)
    fingerprints = {}

    def read(name):
        path = _asset(root, name)
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError("FX06 manifest exceeds its size limit")
        fingerprints[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    manifest = read("mind_bundle.json")
    if (manifest["schema"] != "noir.fx06.mental-node-inputs/1"
            or manifest["owner_identity"] != "rainee"
            or manifest["activation"]["memory_store"] is not None
            or any(manifest["activation"].get(k) is not False for k in ("writes_canon", "preview_can_activate"))
            or tuple(p["target"] for p in manifest["mind_ports"]) != CAST
            or any(p["target"] != p["select_actor_card_by_target"] for p in manifest["mind_ports"])):
        raise ValueError("FX06 mind manifest has an incompatible cast or activation policy")
    src = manifest["personality_source"]
    donor = read(src["donor_override"])
    evidence = read(src["linked_evidence"])
    movie = read(src["chapter_and_moment_index"])
    if (donor["schema"] != "noir.fx06.plastics-early.donor-override/1"
            or donor["access"]["source"] != "mean-girls-2004"
            or donor["access"]["allow_interval_ms"] != [0, 1595000]
            or movie["source"]["edition"] != 2004
            or donor["access"]["sha256"] != movie["source"]["full_file_sha256"]):
        raise ValueError("FX06 requires the scoped 2004 film evidence")
    media_moments = {m["id"]: m for m in movie["admitted_moments"]}
    allowed = set(evidence["admitted_ids"]) - set(evidence["quarantined_ids"])
    receipts = {}
    for row in evidence["moments"]:
        if row["id"] not in allowed:
            continue
        a, b = row["span_ms"]
        mapped = media_moments[row["id"]]
        if (row["eligibility"] != "transfer" or row["sha256"] != donor["access"]["sha256"]
                or not 0 <= a < b <= 1595000
                or mapped["source_range_s"] != [a / 1000, b / 1000]):
            raise ValueError("FX06 donor evidence is outside its allowed source window")
        receipts[row["id"]] = {"id": row["id"], "source": "mean-girls-2004", "span_ms": [a, b]}
    cards = donor["actor_cards"]
    if tuple(c["target"] for c in cards) != CAST:
        raise ValueError("FX06 must keep three distinct actor cards")
    actors = []
    for i, (card, name, role) in enumerate(zip(cards, SPEAKERS, ROLES), 1):
        moves = []
        for move in card["tendencies"]:
            if not move["evidence"] or not set(move["evidence"]) <= receipts.keys():
                raise ValueError("FX06 actor card uses unadmitted evidence")
            moves.append({"when": move["when"], "try": move["try"], "evidence": move["evidence"]})
        if not moves:
            raise ValueError("Missing a mind's conditional behavior")
        actors.append({"form_id": card["target"], "speaker": name, "role": role,
                       "mind_label": f"FX06 Mind {i} · {role}", "tendencies": moves,
                       "constraint": card["constraint"]})
    edges = []
    for edge in donor["optional_local_relationship_edges"]:
        if (edge["from"] not in CAST or edge["to"] not in CAST or not edge["evidence"]
                or not set(edge["evidence"]) <= receipts.keys()):
            raise ValueError("FX06 relationship edge is unscoped")
        edges.append(edge)
    graph = manifest["separate_graph_evidence"]
    recipe = read(graph["recipe"])
    if (recipe["schema_version"] != "noir.fx06.performance-pilot/1"
            or recipe["mode"] != "scene_only_no_memory"
            or tuple(recipe["scope"]["author_scene_sequence"]) != EVENTS
            or tuple(recipe["character_family"]["manifestations"]) != CAST
            or recipe["character_family"]["root"] != "rainee"
            or recipe["character_family"]["standalone_roster_entries"] is not False
            or recipe["law_fixture"]["protected_payoff"]["text"] != PERFUME_LINE):
        raise ValueError("FX06 use requires the authored base scene and its exact lock")
    split, merge = recipe["transformation_overrides"]
    for edge, anchor, operation in ((split, "split", "invert_three_to_one_shape"),
                                     (merge, "rejoin", "reuse_three_to_one_shape")):
        if (edge["anchor"], edge["operator"], edge["from"]) != (anchor, operation, FUSION):
            raise ValueError("FX06 cutaway mapping is not bound to its authored beats")
    if merge["requires"] != ["intervention"]:
        raise ValueError("Francine must intervene before reunion")
    provenance = read("Neural Graph/source_manifest.json")
    cutaway = _asset(root, graph["complete_cutaway"])
    with cutaway.open("rb") as video:
        cutaway_digest = hashlib.file_digest(video, "sha256").hexdigest()
    if cutaway_digest != provenance["gag_source"]["original_sha256"]:
        raise ValueError("FX06 cutaway copy changed")
    performance = read(manifest["performance_examples"][0]["reference"])
    timing = []
    for ident, hint in TIMING.items():
        row = next((r for r in performance["rows"] if r["id"] == ident), None)
        if (not row or row["category"] != "direct_emitter"
                or row["can_supply_personality_memory_or_canon"] is not False):
            raise ValueError("FX06 timing reference is unavailable")
        timing.append({"id": ident, "episode": row["episode"],
                       "source_range_s": row["source_range_s"], "hint": hint})
    return {"actors": actors, "relationships": edges, "evidence": receipts,
            "timing": timing, "cutaway": {"sha256": cutaway_digest, "window_ms": [117400, 117500],
                                          "split": split["operator"], "rejoin": merge["operator"]},
            "manifests": fingerprints}


def source_sections() -> tuple[tuple[str, int, str], ...]:
    """Pilot prose anchors. The only editable section is the roast."""
    return (
        ("before", 3, "INT. HALL – OUTSIDE THE BATHROOM\n\n"
         "Through the gap under the bathroom door, the gas reached the hall as overpowering floral perfume. "
         "Haley stopped in the doorway. Rainee was still one person.\n\n"
         f"Haley: {PERFUME_LINE}\n\n"),
        ("roast", 5, "Rainee splits into three manifestations of herself. The three turn to Haley, "
         "who doubts the cloud counts as clearing the bathroom. They roast her, taking distinct turns. "
         "The wall fan's indicator is dark.\n\n"),
        ("rejoined", 7, "Francine stepped between them and called them back together. "
         "The three converged into one Rainee again.\n\n"),
        ("peter", 10, "Only then did Rainee become Rainee Peter. A second blast sent Haley reeling back down the hall.\n"),
    )


def register(store, bundle: dict, script: str) -> dict:
    """Bind a prepared scratch workspace to exact source text; no timeline events are published."""
    rows, offset = [], 0
    for name, beat, text in source_sections():
        width = len(text.rstrip("\n")) if name == "roast" else len(text)
        rows.append({"id": name, "beat": beat, "start": offset, "end": offset + width})
        offset += len(text)
    if "".join(text for _, _, text in source_sections()) != script:
        raise ValueError("FX06 script does not match the pilot scene")
    if (set(bundle.get("mind_nodes", {})) != set(CAST)
            or len(set(bundle["mind_nodes"].values())) != len(CAST)
            or not all(isinstance(k, str) and k for k in bundle["mind_nodes"].values())):
        raise ValueError("FX06 cannot register without three distinct Mind node bindings")
    payload = {**bundle, "source_sha256": fingerprint(script), "phases": rows}
    body = _encoded(payload)
    with store._connect() as c:
        from .universe_scope import verify_scope
        verify_scope(c, project_id=PROJECT, universe_id=UNIVERSE)
        ep = c.execute("SELECT branch FROM episodes WHERE id=?", (EPISODE,)).fetchone()
        if not ep or ep["branch"] != BRANCH:
            raise ValueError("FX06 must use its isolated branch")
        c.execute("""CREATE TABLE fx06_scene (episode TEXT PRIMARY KEY, branch TEXT NOT NULL,
                   body TEXT NOT NULL, sha256 TEXT NOT NULL)""")
        c.execute("INSERT INTO fx06_scene VALUES(?,?,?,?)", (EPISODE, BRANCH, body, fingerprint(body)))
    return payload


def read(c, episode: str = EPISODE) -> dict | None:
    if episode != EPISODE or not c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fx06_scene'").fetchone():
        return None
    from .universe_scope import verify_scope
    verify_scope(c, project_id=PROJECT, universe_id=UNIVERSE)
    row = c.execute("SELECT * FROM fx06_scene WHERE episode=?", (episode,)).fetchone()
    if not row or row["branch"] != BRANCH or fingerprint(row["body"]) != row["sha256"]:
        raise ValueError("FX06 scene binding is damaged")
    return json.loads(row["body"]) | {"binding_sha256": row["sha256"]}


def with_cast(junctions: dict, registered: dict) -> dict:
    group = junctions.get("rainee", AFM_JUNCTIONS["rainee"])
    seen = {f.id for f in group.forms}
    forms = tuple(CharacterForm(a["form_id"], a["speaker"], "transformation", after="rainee")
                  for a in registered["actors"] if a["form_id"] not in seen)
    return {**junctions, "rainee": replace(group, forms=group.forms + forms)}


def add_forms(c, junctions: dict) -> dict:
    registered = read(c)
    return with_cast(junctions, registered) if registered else junctions


def project(c, episode, branch, beat, start, end, script) -> dict | None:
    plan = read(c, episode)
    if not plan:
        return None
    if branch != BRANCH:
        raise ValueError("FX06 scene must stay on its original branch")
    if fingerprint(script) != plan["source_sha256"]:
        raise ValueError("FX06 test source changed; its scene boundaries need re-binding")
    phase = next((p for p in plan["phases"] if p["beat"] == beat
                  and p["start"] <= start < end <= p["end"]), None)
    if phase is None:
        if beat == 0:
            return None  # ordinary Studio document overview, with no split mind context
        raise ValueError("Select the saved FX06 phase at its own beat")
    form, fired = "rainee", []
    cast = []
    for event in EVENTS[:beat + 1]:
        if event == "split":
            if form != "rainee" or "haley-line" not in fired:
                raise ValueError("FX06 cannot split before the authored line")
            form, cast = "split", list(CAST)
        if event == "rejoin":
            if not cast or "intervention" not in fired:
                raise ValueError("FX06 cannot rejoin before Francine intervenes")
            form, cast = "rainee", []
        if event == "peter":
            if cast or "rejoin" not in fired:
                raise ValueError("FX06 Peter form requires the prior reunion")
            form = PETER
        fired.append(event)
    active = [a | {"node_id": plan["mind_nodes"][a["form_id"]]}
              for a in plan["actors"] if a["form_id"] in cast]
    return {"phase": phase["id"], "binding_sha256": plan["binding_sha256"],
            "root": "rainee", "root_form": form, "active_cast": active,
            "applied_events": fired, "memory": None, "writes_canon": False,
            "override": ({"operator": plan["cutaway"]["split"], "evidence": plan["cutaway"]["window_ms"]}
                         if cast else {"operator": plan["cutaway"]["rejoin"],
                                       "evidence": plan["cutaway"]["window_ms"]}
                         if "rejoin" in fired else None),
            "relationships": plan["relationships"] if cast else [],
            "timing": plan["timing"] if cast else []}


def writer_context(scene: dict | None) -> str:
    if not scene or not scene["active_cast"]:
        return ""
    actors = [{k: a[k] for k in ("speaker", "role", "constraint")} |
              {"tendencies": [{k: t[k] for k in ("when", "try")} for t in a["tendencies"]]}
              for a in scene["active_cast"]]
    return (
        "FX06 ACTIVE SCENE CAST (this governs Rainee's active bodies for the selected beat):\n"
        "All three are manifestations of Rainee. Haley is present and skeptical. The hall smells of overpowering "
        "floral perfume. The fan indicator is visibly dark. Show the roast with original wording and a distinct "
        "observable action and speaking tactic for each. Stop before Francine intervenes. No other speaker lines, "
        "split or rejoin action, new form, imported identity, biography or memories.\n"
        "Use exactly three turns, in order. For each turn write one line beginning 'Rainee 1:', 'Rainee 2:' or "
        "'Rainee 3:' as appropriate, then one line beginning 'Action:'. No preface or markdown fences.\n"
        + _encoded({"actors": actors,
                    "interaction": [{"from": e["from"], "to": e["to"], "when": e["context"], "effect": e["effect"]}
                                    for e in scene["relationships"]],
                    "timing": [v["hint"] for v in scene["timing"]]}) + "\n\n"
    )


def validate_turns(text: str) -> list[str]:
    """Structure check only; it cannot judge whether the choices feel distinct."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if len(lines) != 6:
        return ["FX06 needs three distinct actor turns, each with a dialogue line and an action"]
    for i, speaker in enumerate(SPEAKERS):
        if not re.fullmatch(re.escape(speaker) + r":\s*\S.*", lines[2 * i], re.I):
            return ["FX06 actor turns are missing, duplicated or out of order"]
        if not re.fullmatch(r"Action:\s*\S.*", lines[2 * i + 1], re.I):
            return ["FX06 actor turn is missing an observable action"]
    return []
