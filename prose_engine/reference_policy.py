"""Purpose-specific reference eligibility and source provenance.

The catalog is author configuration; an index alone grants no permission.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PURPOSES = frozenset(("rank_local", "inspect_local", "prompt", "remote_transfer", "export"))
_POLICY_LOCK = threading.RLock()

def prompt_purposes(provider_name):
    """Unknown adapters are treated as remote until explicitly classified."""
    name = str(provider_name or "").lower()
    base = ("rank_local", "prompt")
    return base if name in {"mock", "edits", "local", "local-llm", "local-transformers"} else base + ("remote_transfer",)


@dataclass(frozen=True)
class ReferencePolicy:
    sources: dict
    status: str = "configured"
    excluded_sources: frozenset = frozenset()

    @classmethod
    def load(cls, root):
        path = Path(root) / "reference_policy.json"
        if not path.is_file():
            return cls({}, "unconfigured")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1 or not isinstance(data.get("sources"), dict):
                raise ValueError("Expected schema version 1 and a sources object")
            for key, entry in data["sources"].items():
                if not isinstance(key, str) or not isinstance(entry, dict):
                    raise ValueError("Each source needs an object keyed by its source ID")
                permissions = entry.get("permissions", [])
                if not isinstance(permissions, list) or set(permissions) - PURPOSES:
                    raise ValueError("Invalid reference permissions")
            from .library_indexes import quality_exclusions
            return cls(data["sources"], excluded_sources=frozenset(quality_exclusions(root)))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"Reference policy unavailable: {exc}") from exc

    def allows(self, meta, purposes, influence=None):
        if any(meta.get(key) is not None for key in ("episode", "branch", "beat", "viewpoint")):
            # Book retrieval has no timeline scope input yet; never guess eligibility.
            return False
        source = meta.get("source_id") or meta.get("book")
        if not isinstance(source, str) or not source:
            return False
        if source in self.excluded_sources:
            return False
        if influence is not None and influence.is_off(source):
            return False
        entry = self.sources.get(source)
        if not isinstance(entry, dict) or entry.get("enabled") is not True:
            return False
        return set(purposes) <= set(entry.get("permissions", []))


def eligible_index(index, policy, purposes, influence=None):
    """Make an isolated view before scoring; unknown sources are excluded."""
    if not all(hasattr(index, name) for name in ("meta", "texts", "vectors")):
        raise ValueError("Reference index does not expose source metadata")
    if not (len(index.meta) == len(index.texts) == len(index.vectors)):
        raise ValueError("Reference index metadata and vectors do not match")
    rows = [i for i, meta in enumerate(index.meta)
            if isinstance(meta, dict) and policy.allows(meta, purposes, influence)]
    if not rows:
        return None
    result = copy.copy(index)
    result.texts = [index.texts[i] for i in rows]
    result.meta = [index.meta[i] for i in rows]
    result.vectors = np.asarray(index.vectors)[rows]
    return result


def legacy_identities(index):
    """Attach explicit index-position provenance without rewriting an old index."""
    if not (len(index.meta) == len(index.texts) == len(index.vectors)):
        raise ValueError("Reference index metadata and vectors do not match")
    if index.meta and all(isinstance(m, dict) and m.get("passage_id") and
                          m.get("source_revision") and m.get("anchor") for m in index.meta):
        return index
    h = hashlib.sha256()
    for meta, text in zip(index.meta, index.texts):
        blob = json.dumps([meta, text], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    index_hash = h.hexdigest()
    result = copy.copy(index)
    result.meta = []
    for pos, meta in enumerate(index.meta):
        entry = dict(meta)
        entry.setdefault("source_id", entry.get("book", "unknown"))
        entry.setdefault("source_revision", "unknown-legacy")
        entry.setdefault("passage_id", f"legacy:{index_hash}:{pos}")
        entry.setdefault("anchor", {"index_position": pos, "index_hash": index_hash})
        entry.setdefault("embedding_backend", type(index).__name__)
        entry.setdefault("embedding_model", getattr(index, "model_name", "unknown-legacy"))
        entry.setdefault("embedding_revision", "unknown-legacy")
        result.meta.append(entry)
    return result


def restricted_drive(drive, policy, purposes, influence=None):
    """Bind a drive to a selected index; no reference ranking when none is eligible."""
    full = legacy_identities(drive.index)
    selected = eligible_index(full, policy, purposes, influence)
    if selected is None:
        return None
    bound = copy.copy(drive)
    bound.index = selected
    bound.reference_policy = policy
    bound.reference_purposes = tuple(purposes)
    return bound


def resolve_historical_rank_id(old_id, receipt=None, index=None):
    """Resolve only when a retained receipt identifies one index passage."""
    if not isinstance(old_id, str) or not old_id:
        raise ValueError("Historical passage ID is required")
    if receipt is not None and index is not None:
        if not isinstance(receipt, dict) or receipt.get("passage_id") != old_id or not isinstance(receipt.get("text"), str):
            raise ValueError("The retained receipt must include the historical ID and exact passage text")
        enriched = legacy_identities(index)
        source = receipt.get("source_id") or receipt.get("book")
        if not isinstance(source, str) or not source:
            raise ValueError("The retained receipt must identify the source")
        matches = [meta for text, meta in zip(enriched.texts, enriched.meta)
                   if text == receipt["text"] and (meta.get("source_id") or meta.get("book")) == source]
        anchor = receipt.get("anchor")
        if anchor is not None:
            matches = [meta for meta in matches if meta.get("anchor") == anchor]
        if len(matches) == 1:
            meta = matches[0]
            return {"legacy_id": old_id, "status": "mapped", "passage_id": meta["passage_id"],
                    "source_id": meta.get("source_id"), "source_revision": meta.get("source_revision"),
                    "anchor": meta.get("anchor")}
        if len(matches) > 1:
            return {"legacy_id": old_id, "status": "ambiguous",
                    "reason": "Multiple source locations match this receipt; an exact anchor is required."}
    return {"legacy_id": old_id, "status": "unresolved",
            "reason": "Rank-based IDs require the original result receipt or query to identify a passage."}


class PolicyEditor:
    """Edit one source at a time without changing other preferences."""
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "reference_policy.json"

    def _read(self):
        if self.path.is_symlink():
            raise ValueError("Reference policy must not be a symbolic link")
        if not self.path.exists():
            return {"schema_version": 1, "sources": {}}, "missing"
        raw = self.path.read_bytes()
        ReferencePolicy.load(self.root)  # Fail closed on an invalid existing file.
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()

    def snapshot(self, metadata, influence):
        with _POLICY_LOCK:
            data, revision = self._read()
            ids = sorted({m.get("source_id") or m.get("book") for m in metadata if
                          isinstance(m, dict) and isinstance(m.get("source_id") or m.get("book"), str)})
            return {"revision": revision, "sources": [
                {"id": source, "configured":source in data['sources'], "enabled": data["sources"].get(source, {}).get("enabled") is True,
                 "permissions": data["sources"].get(source, {}).get("permissions", []),
                 "influence_off": influence.is_off(source)} for source in ids]}

    def update(self, source, enabled, permissions, expected_revision, known_sources):
        if (not isinstance(source, str) or source not in known_sources or type(enabled) is not bool or
                not isinstance(permissions, list) or any(not isinstance(x, str) for x in permissions) or
                len(set(permissions)) != len(permissions) or set(permissions) - PURPOSES):
            raise ValueError("Invalid source or permissions")
        with _POLICY_LOCK:
            data, revision = self._read()
            if revision != expected_revision:
                raise ValueError("Reference policy changed; reload before saving")
            previous = data["sources"].get(source, {})
            data["sources"][source] = {**previous, "enabled": enabled, "permissions": permissions}
            self.root.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".reference-policy-", suffix=".tmp", dir=self.root)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                    json.dump(data, out, indent=2, ensure_ascii=False)
                    out.write("\n")
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
