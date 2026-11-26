"""Shared policy-aware retrieval setup for user-facing routes."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from .influence import load_influence
from .reference_policy import ReferencePolicy, eligible_index, legacy_identities, prompt_purposes


@dataclass
class RetrievalSetup:
    state: str
    message: str
    drive: object = None
    influence: object = None


_READERS = ContextVar('shared_book_readers', default=None)


class ReferenceReaders:
    """Small per-service pool of policy-filtered readers keyed by verified input bytes."""
    def __init__(self, count=2):
        self.count = count
        self._items = OrderedDict()
        self._lock = RLock()
        self._loads = {}
        self._hits = {}

    @contextmanager
    def activate(self):
        token = _READERS.set(self)
        try:
            yield
        finally:
            _READERS.reset(token)

    def read(self, key, load):
        backend = key[1]
        with self._lock:
            if key in self._items:
                self._hits[backend] = self._hits.get(backend, 0)+1
                self._items.move_to_end(key)
                return self._items[key]
            self._loads[backend] = self._loads.get(backend, 0)+1
            # Drop a stale release/policy for this slot before loading replacements.
            for old in list(self._items):
                if old[:-1] == key[:-1]:
                    del self._items[old]
            while len(self._items) >= self.count:
                self._items.popitem(last=False)
            reader = load()
            if reader.state == 'ready':
                self._items[key] = reader
            return reader

    def metrics(self):
        with self._lock:
            return {'loaded':dict(self._loads),'hits':dict(self._hits),'resident':len(self._items)}


def prepare_retrieval(root, backend, provider, *, enabled=True, profile_id="corpus", purposes=None,
                      verified_basis=None):
    required = tuple(prompt_purposes(provider) if purposes is None else purposes)
    pool = _READERS.get()
    load = lambda: _prepare_retrieval(root, backend, required, enabled, profile_id)
    if not pool or not enabled or backend == 'none' or not verified_basis or verified_basis.get('release') == 'missing':
        return load()
    key = (str(Path(root).resolve()), backend, profile_id, required, tuple(sorted(verified_basis.items())))
    return pool.read(key, load)


def _prepare_retrieval(root, backend, required, enabled, profile_id):
    if not enabled or backend == "none":
        return RetrievalSetup("disabled", "Reference retrieval is disabled.")
    root = Path(root)
    if backend not in {"topic", "luar", "style"}:
        return RetrievalSetup("unavailable", "Unknown reference backend.")
    try:
        policy = ReferencePolicy.load(root)
        influence = load_influence(root)
        if policy.status == "unconfigured":
            return RetrievalSetup("unconfigured", "Configure reference_policy.json for the sources and uses you choose.")
        from .library_indexes import ACTIVE, INDEXES, digest, index_path, validate_index
        path = index_path(root, backend)
        if not path.is_file():
            return RetrievalSetup("unavailable", f"{backend} index is missing: {path}")
        if (root / ACTIVE).is_file():
            import json
            release = json.loads((root / ACTIVE).read_text(encoding='utf-8'))
            if release['hashes'].get(INDEXES[backend]) != digest(path):
                raise ValueError('Active library index failed verification before loading')
        if backend == "topic":
            from .embedding_store import load_index
            from .vector_store import VectorSemanticDrive
            index = load_index(path)
            factory = lambda selected: VectorSemanticDrive(selected, profile_id=profile_id)
        elif backend == "luar":
            from .voice.luar import LuarDrive, LuarIndex
            index = LuarIndex.load(path)
            factory = LuarDrive
        else:
            from .voice.retrieve import StyleDrive, StyleIndex
            index = StyleIndex.load(path)
            factory = lambda selected: StyleDrive(selected, profile_id=profile_id)
        compatibility = validate_index(root, backend, index)
        if not required or "rank_local" not in required:
            return RetrievalSetup("unavailable", "Local ranking permission is required.")
        selected = eligible_index(legacy_identities(index), policy, required, influence)
        if selected is None:
            return RetrievalSetup("no_eligible", f"No eligible {backend} references; check the source policy and influence settings.", influence=influence)
        drive = factory(selected)
        drive.reference_policy = policy
        drive.reference_purposes = required
        note = ""
        if backend == "luar" and drive.compatibility == "legacy-unverified":
            note = " Legacy index compatibility is unverified; its original encoder and preprocessing are unknown."
        elif backend == "luar" and drive.compatibility == "manifest-unverified":
            note = " This index lacks a complete pinned model and runtime manifest."
        elif backend == "luar" and drive.index.source_status == "source-unavailable":
            note = " The source index is unavailable, so its fingerprint could not be checked."
        if backend == "style" and not selected.model_sha256:
            note = " Legacy style index has no model fingerprint; compatibility is unverified."
        if compatibility == "verified-release":
            note = " Versioned library release; source and encoder/runtime checks matched."
        return RetrievalSetup("ready", f"{backend}: {len(selected.texts)} eligible passages.{note}", drive, influence)
    except Exception as exc:
        return RetrievalSetup("unavailable", f"{backend} retrieval unavailable ({type(exc).__name__}): {exc}")
