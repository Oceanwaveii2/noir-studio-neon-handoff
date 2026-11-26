"""Versioned library artifacts; source books and legacy indexes stay in place."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import tempfile

INDEXES = {"topic": "vector_index.joblib", "luar": "luar_index.joblib", "style": "style_index.joblib"}
ACTIVE = "library_active.json"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_child(root, relative):
    root = Path(root).absolute()
    rel = Path(relative)
    if not str(relative) or rel.drive or rel.root or ".." in rel.parts or ":" in str(relative):
        raise ValueError("Library paths must stay within their selected directory")
    path = root / rel
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Library links/reparse points are not allowed")
    return path


def atomic_json_new_revision(path, value, expected):
    """Compare-and-replace one owned pointer/config; no multi-index overwrite."""
    path = Path(path)
    # Cross-process cooperating publishers cannot both win the same revision.
    lock = path.with_name(path.name + ".publish-lock")
    handle = lock.open("x", encoding="utf-8")
    try:
        with handle:
            _replace_json(path, value, expected)
    finally:
        lock.unlink()


def _replace_json(path, value, expected):
    current = digest(path) if path.is_file() else "missing"
    if current != expected:
        raise ValueError("Library configuration changed; inspect before retrying")
    fd, name = tempfile.mkstemp(prefix=".library-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if (digest(path) if path.is_file() else "missing") != expected:
            raise ValueError("Library configuration changed before publication")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def index_path(root, backend):
    root = Path(root)
    pointer = root / ACTIVE
    if backend not in INDEXES:
        raise ValueError("Unknown library index")
    if not pointer.is_file():
        return root / INDEXES[backend]
    data = json.loads(pointer.read_text(encoding="utf-8"))
    relative = data.get("directory", "")
    if (data.get("schema_version") != 1 or not relative or
            Path(relative).parts[0] != "index_releases" or not isinstance(data.get("hashes"), dict)):
        raise ValueError("Invalid active library release")
    if len(Path(relative).parts) != 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", Path(relative).name):
        raise ValueError("Invalid active library release name")
    directory = safe_child(root, relative)
    descriptor = directory / "release.json"
    if not descriptor.is_file() or digest(descriptor) != data["hashes"].get("release.json"):
        raise ValueError("Active library release receipt changed or is missing")
    return safe_child(root, Path(relative) / INDEXES[backend])


@lru_cache(maxsize=8)
def _catalog_cached(root, manifest_hash, quality_hash, stamps):
    sources = {}
    for source, relative, _size, _mtime in stamps:
        path = safe_child(root, relative)
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        sources[source] = hashlib.sha256(text.encode("utf-8")).hexdigest() if text.strip() else "blank-or-missing"
    token = hashlib.sha256(json.dumps([manifest_hash, quality_hash, sources], sort_keys=True).encode()).hexdigest()
    return {"fingerprint": token, "sources": sources}


def catalog(root):
    """Exact current source revisions, cached only while file stamps are unchanged."""
    root = Path(root).absolute()
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return {"fingerprint": "untracked", "sources": {}}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    stamps = []
    for entry in data["books"]:
        source = entry["slug"]
        relative = entry.get("file", f"text/{source}.txt")
        path = safe_child(root, relative)
        info = path.stat() if path.is_file() else None
        stamps.append((source, relative, info.st_size if info else -1, info.st_mtime_ns if info else -1))
    if len({row[0] for row in stamps}) != len(stamps):
        raise ValueError("Duplicate source IDs in library manifest")
    quality = root / "library_quality.json"
    return _catalog_cached(str(root), digest(manifest), digest(quality) if quality.is_file() else "missing", tuple(stamps))


def quality_exclusions(root):
    path = Path(root) / "library_quality.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("excluded"), dict):
        raise ValueError("Invalid library source-quality review")
    return data["excluded"]


def usable_sources(root):
    excluded = quality_exclusions(root)
    return {s for s, revision in catalog(root)["sources"].items() if revision != "blank-or-missing" and s not in excluded}


def runtime():
    return {"python": f"{sys.version_info.major}.{sys.version_info.minor}",
            **{name: importlib.metadata.version(name) for name in
               ("torch", "transformers", "numpy", "sentence-transformers", "tokenizers", "joblib")}}


def model_artifacts(repository, revision=None):
    """Pin actual cached bytes, including locally patched custom LUAR code."""
    from huggingface_hub import snapshot_download
    folder = Path(snapshot_download(repository, revision=revision, local_files_only=True))
    hashes = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json", ".txt", ".safetensors", ".bin"}:
            info = path.stat()
            hashes[path.relative_to(folder).as_posix()] = _model_digest(str(path), info.st_size, info.st_mtime_ns)
    if not hashes:
        raise ValueError("Cached model has no verifiable artifacts")
    return {"repository": repository, "revision": folder.name, "files": hashes}


@lru_cache(maxsize=128)
def _model_digest(path, size, mtime):
    value = digest(path)
    info = Path(path).stat()
    if (size, mtime) != (info.st_size, info.st_mtime_ns):
        raise ValueError("Model changed while checking its fingerprint")
    return value


def encoder_binding(root, backend):
    path = index_path(root, backend).parent / "release.json"
    if not path.is_file():
        return "legacy-unverified"
    release = json.loads(path.read_text(encoding="utf-8"))
    info = release["indexes"][backend]
    code = safe_child(Path(__file__).parent, info["encoder_code"])
    actual = {"code": digest(code), "runtime": runtime()}
    artifacts = info.get("encoder_artifacts")
    if artifacts:
        actual["model"] = model_artifacts(artifacts["repository"], artifacts["revision"])
    actual["chunker"] = digest(Path(__file__).parent / "vector_store.py")
    return hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()


def validate_index(root, backend, index):
    """Reject changed source/model/encoder versions before ranking new releases."""
    import numpy as np
    matrix = np.asarray(index.vectors)
    if matrix.ndim != 2 or len(index.texts) != len(index.meta) or len(index.texts) != len(matrix) or not np.isfinite(matrix).all():
        raise ValueError("Library index has invalid rows/vectors")
    manifest = getattr(index, "manifest", None)
    if not manifest or manifest.get("library_schema") != 1:
        return "legacy-unverified"
    if manifest.get("catalog") != catalog(root)["fingerprint"]:
        raise ValueError("Library source text or manifest changed; rebuild the candidate indexes")
    if manifest.get("library_runtime") != runtime():
        raise ValueError("Library encoder runtime changed; revalidate a separate candidate")
    if manifest.get("dimensions") != matrix.shape[1]:
        raise ValueError("Library dimensions differ from build manifest")
    if backend != "topic" and manifest.get("source_index_sha256") != digest(index_path(root, "topic")):
        raise ValueError("Derived library index was built from a different topic index")
    code = Path(__file__).parent / ("styleprint.py" if backend == "style" else "voice/luar.py" if backend == "luar" else "embedding_store.py")
    if manifest.get("encoder_code_sha256") != digest(code):
        raise ValueError("Library encoder implementation changed; revalidate a candidate")
    if manifest.get("chunker_code_sha256") != digest(Path(__file__).parent / "vector_store.py"):
        raise ValueError("Library chunker changed; revalidate a candidate")
    path = index_path(root, backend)
    pointer = Path(root) / ACTIVE
    if pointer.is_file():
        data = json.loads(pointer.read_text(encoding="utf-8"))
        if data["hashes"].get(INDEXES[backend]) != digest(path):
            raise ValueError("Active library index changed since validation")
    return "verified-release"


def library_status(root, provider):
    """No encoder construction or generation; readiness is tied to checked bytes."""
    from .reference_policy import ReferencePolicy, prompt_purposes
    from .influence import load_influence
    root = Path(root)
    policy = ReferencePolicy.load(root)
    influence = load_influence(root)
    sources = catalog(root)
    usable = usable_sources(root)
    eligible = {s for s in usable if policy.allows({"source_id": s}, prompt_purposes(provider), influence)}
    results = {}
    for backend in INDEXES:
        try:
            if policy.status == "unconfigured":
                results[backend] = {"state": "unconfigured", "message": "Book source permissions have not been configured."}
                continue
            path = index_path(root, backend)
            if not path.is_file():
                raise ValueError("Index has not been built")
            descriptor = path.parent / "release.json"
            if not descriptor.is_file():
                import joblib
                data = joblib.load(path)
                indexed = {m.get("source_id") or m.get("book") for m in data["meta"]}
                results[backend] = {"state": "incomplete", "books": len(indexed), "passages": len(data["texts"]),
                                    "eligible_books": len(indexed & eligible), "message": "Legacy index; build/model compatibility not verified."}
                continue
            release = json.loads(descriptor.read_text(encoding="utf-8"))
            pointer = json.loads((root / ACTIVE).read_text(encoding="utf-8"))
            if digest(descriptor) != pointer["hashes"].get("release.json") or digest(path) != pointer["hashes"].get(INDEXES[backend]):
                raise ValueError("Index or validation receipt changed")
            info = release["indexes"][backend]
            if release["catalog"] != sources["fingerprint"] or release["runtime"] != runtime():
                raise ValueError("Source library or runtime changed; local revalidation needed")
            if info["encoder_binding"] != encoder_binding(root, backend):
                raise ValueError("Cached encoder/model implementation changed")
            if backend == "style" and digest(path.parent / "styleprint.json") != info["style_model_sha256"]:
                raise ValueError("Style normalization model changed")
            indexed = set(info["sources"])
            ready = indexed >= usable
            state = "ready" if ready else "incomplete"
            if not eligible & indexed:
                state = "no_eligible"
            results[backend] = {"state": state, "books": len(indexed), "passages": info["passages"],
                                "eligible_books": len(indexed & eligible), "dimensions": info["dimensions"],
                                "message": "Locally built and retrieval-checked; primary-session writing is separately reviewed." if ready else "Some usable sources are not covered."}
        except Exception as exc:
            results[backend] = {"state": "unavailable", "message": str(exc)}
    return {"indexes": results, "usable_books": len(usable),
            "excluded_blank_or_missing": sum(r == "blank-or-missing" for r in sources["sources"].values()),
            "quality_quarantined": len(quality_exclusions(root)),
            "eligible_books": len(eligible), "provider": provider, "generation_started": False,
            "note": "Book craft is reference material, never story canon. Remote excerpts and exports have separate permissions."}


def configure_existing(root, *, remote, expected_revision):
    """One explicit setup for the current usable library, never a GET side effect."""
    from .reference_policy import ReferencePolicy
    from .influence import load_influence
    root = Path(root)
    ReferencePolicy.load(root)  # Fail closed on malformed existing choices.
    path = root / "reference_policy.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema_version": 1, "sources": {}}
    influence = load_influence(root)
    permissions = ["rank_local", "inspect_local", "prompt"] + (["remote_transfer"] if remote else [])
    added = []
    for source, revision in catalog(root)["sources"].items():
        if revision == "blank-or-missing" or source in data["sources"] or source in quality_exclusions(root):
            continue
        data["sources"][source] = {"enabled": not influence.is_off(source), "permissions": list(permissions),
                                   "configured_by": "author-requested-library-setup"}
        added.append(source)
    atomic_json_new_revision(path, data, expected_revision)
    return {"added": added, "preserved_existing": len(data["sources"]) - len(added),
            "remote_transfer_for_new_entries": remote, "export_enabled_by_setup": False}
