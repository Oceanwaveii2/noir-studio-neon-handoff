"""Shared CLI and Studio adapter for the reviewed revision workflow."""
from __future__ import annotations

from dataclasses import asdict
from difflib import unified_diff

from .editorial_revisions import RevisionError, RevisionStore, world_revision
from .editorial_service import Edit, preview, revision
from .voice.world_state import WorldState


def _edits(text: str, request: dict) -> tuple[Edit, ...]:
    batch = request.get("edits", [request])
    if not isinstance(batch, list) or not batch:
        raise RevisionError("provide at least one edit")
    result = []
    for index, item in enumerate(batch):
        if not isinstance(item, dict):
            raise RevisionError("each edit must be an object")
        expected, replacement = item.get("expected"), item.get("replacement")
        if not isinstance(expected, str) or not expected or not isinstance(replacement, str):
            raise RevisionError("provide the exact text to replace and a replacement")
        start = text.find(expected)
        if start < 0 or text.find(expected, start + 1) >= 0:
            raise RevisionError("the selected text must occur exactly once")
        span_id = "selected-span" if "edits" not in request else f"selected-span-{index}"
        result.append(Edit(span_id, start, start + len(expected), expected, replacement))
    return tuple(result)


def dispatch(
    store: RevisionStore,
    world: WorldState,
    request: dict,
    *,
    timeline_path=None,
    project_id=None,
    universe_id=None,
    episode=None,
    branch: str = "main",
    beat: int = 0,
) -> dict:
    if not isinstance(request, dict):
        raise RevisionError("request must be an object")
    action = request.get("action")
    if action == "state":
        return {**store.snapshot(),"world_hash":world_revision(world)}
    if action not in ("preview", "apply", "undo", "redo"):
        raise RevisionError("unknown editorial action")
    base = request.get("base")
    if type(base) is not int:
        raise RevisionError("stale revision; reload the document")
    if action in ("apply", "undo", "redo"):
        reviewer, op_id = request.get("reviewer"), request.get("operation_id")
        if not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(op_id, str) or not op_id:
            raise RevisionError("a reviewer and operation ID are required")
        if action in ("undo", "redo"):
            rev = (store.undo if action == "undo" else store.redo)(op_id, base, reviewer)
            history = store.history_status()
            return {
                "revision": rev,
                "status": "UNDONE" if action == "undo" else "REDONE",
                "can_undo": history["can_undo"],
                "can_redo": history["can_redo"],
                "receipt": {"id": op_id, "base": base, "revision": rev},
            }
        text, _ = store.at(base)
        candidate_hash, world_hash = request.get("candidate_hash"), request.get("world_hash")
        if not all(isinstance(h, str) and len(h) == 64 for h in (candidate_hash, world_hash)):
            raise RevisionError("preview the edit before applying it")
        # Reconstruct the original payload from its immutable base. The store
        # checks replay, staleness and current canon inside the transaction.
        number = store.apply(op_id, base, _edits(text, request), reviewer, candidate_hash, world_hash, world)
        return {
            "revision": number,
            "status": "APPLIED",
            "author_decision": "accepted",
            "receipt":{"id":op_id,"base":base,"revision":number},
        }
    number, text, frozen = store.current()
    if base != number:
        raise RevisionError("stale revision; reload the document")
    result = preview(text, revision(text), _edits(text, request), frozen, world)
    baseline_issues = [asdict(i) for i in result.baseline_issues]
    new_issues = [asdict(i) for i in result.new_issues]
    status = result.status
    effective_timeline = timeline_path or request.get("timeline")
    if not effective_timeline:
        from .scoped_service import resolve_default_timeline
        effective_timeline = resolve_default_timeline()
    if effective_timeline:
        from .scoped_service import enforce_standalone_world_laws
        scope_kw = dict(
            timeline_path=effective_timeline,
            project_id=project_id or request.get("project"),
            universe_id=universe_id or request.get("universe"),
            episode=episode or request.get("episode"),
            branch=request.get("branch") or branch,
            beat=int(request.get("beat", beat) or 0),
        )
        base_laws = enforce_standalone_world_laws(text, **scope_kw)
        cand_laws = enforce_standalone_world_laws(result.candidate, **scope_kw)
        added = sorted(set(cand_laws["violations"]) - set(base_laws["violations"]))
        for violation in added:
            new_issues.append({"code": "world_law", "reason": f"world law: {violation}"})
        if added and status == "ELIGIBLE_FOR_REVIEW":
            status = "BLOCKED"
    return {
        "revision": number, "status": status,
        "baseline_issues": baseline_issues,
        "new_issues": new_issues,
        "candidate_hash": revision(result.candidate), "world_hash": world_revision(world),
        "diff": "".join(unified_diff(text.splitlines(keepends=True), result.candidate.splitlines(keepends=True),
                                     fromfile="current", tofile="proposal")),
        "author_decision": "pending",
    }
