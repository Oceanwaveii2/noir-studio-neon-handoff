"""Build/evaluate immutable library candidates, then atomically select a release.

No remote model calls/downloads, no source-text writes, no canonical-index overwrite.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prose_engine.library_indexes import (ACTIVE, INDEXES, atomic_json_new_revision, catalog,
    configure_existing, digest, model_artifacts, runtime, safe_child, usable_sources, quality_exclusions)


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)


def pin(index, backend, source_catalog, artifacts=None):
    code = "styleprint.py" if backend == "style" else "voice/luar.py" if backend == "luar" else "embedding_store.py"
    index.manifest = {**(getattr(index, "manifest", None) or {}), "library_schema": 1,
                      "library_runtime": runtime(), "catalog": source_catalog["fingerprint"],
                      "source_revisions": source_catalog["sources"], "dimensions": index.vectors.shape[1],
                      "encoder_code_sha256": digest(ROOT / "prose_engine" / code),
                      "chunker_code_sha256": digest(ROOT / "prose_engine/vector_store.py")}
    if artifacts:
        index.manifest["encoder_artifacts"] = artifacts
    binding = {"code": index.manifest["encoder_code_sha256"], "runtime": runtime(),
               "chunker": index.manifest["chunker_code_sha256"]}
    if artifacts:
        binding["model"] = artifacts
    return {"encoder_code": code, "encoder_binding": hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest(),
            "encoder_artifacts": artifacts, "sources": sorted({m.get("source_id") or m["book"] for m in index.meta}),
            "passages": len(index.texts), "dimensions": int(index.vectors.shape[1])}


def probes(index, backend, encoder=None, batch_size=8):
    import numpy as np
    from prose_engine.styleprint import fingerprint
    groups = {}
    for pos, meta in enumerate(index.meta):
        groups.setdefault(meta.get("source_id") or meta["book"], []).append(pos)
    duplicates = Counter(hashlib.sha256(t.encode()).hexdigest() for t in index.texts)
    chosen = []
    for source, rows in sorted(groups.items()):
        rotated = rows[len(rows)//2:] + rows[:len(rows)//2]
        pos = next((p for p in rotated if duplicates[hashlib.sha256(index.texts[p].encode()).hexdigest()] == 1), rotated[0])
        chosen.append((source, pos))
    if backend == "topic":
        queries = index._encoder().encode([index.texts[p] for _, p in chosen], batch_size=batch_size,
            convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False).astype("float32")
    elif backend == "luar":
        queries = encoder.encode([index.texts[p] for _, p in chosen], batch_size=batch_size)
    else:
        model = json.loads((index.books_dir / "styleprint.json").read_text(encoding="utf-8"))
        queries = np.clip((np.array([fingerprint(index.texts[p]) for _, p in chosen]) - model["mean"]) / model["sd"], -3, 3)
        queries /= np.maximum(np.linalg.norm(queries, axis=1, keepdims=True), 1e-9)
    results = []
    for (source, pos), query in zip(chosen, queries):
        scores = index.vectors @ query
        top = np.argsort(-scores)[:5]
        returned = [index.meta[i].get("source_id") or index.meta[i]["book"] for i in top]
        # Exact duplicate editions can tie. Retain identities; never delete either.
        tied = bool(abs(float(scores[pos]) - float(scores[top[0]])) < 2e-5)
        results.append({"source_id": source, "query_sha256": hashlib.sha256(index.texts[pos].encode()).hexdigest(),
                        "top5_sources": returned, "source_in_top5": source in returned, "self_tied_best": tied})
    if not all(r["source_in_top5"] or r["self_tied_best"] for r in results):
        raise ValueError(f"{backend} failed an exact-source retrieval probe")
    return results


def build(root, out, batch_size, max_cuda_mb=2048):
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer
    from prose_engine.corpus import load_corpus
    from prose_engine.vector_store import chunk_books
    from prose_engine.embedding_store import EmbeddingIndex
    from prose_engine.styleprint import NAMES, fingerprint
    from prose_engine.voice.retrieve import StyleIndex
    from prose_engine.voice.luar import LuarEncoder, LuarIndex, MASKED_PREPROCESSING
    if batch_size < 1 or max_cuda_mb < 1:
        raise ValueError("Batch size and CUDA memory budget must be positive")
    torch.set_num_threads(4)
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        budget = min(max_cuda_mb * 1024 * 1024, free - 512 * 1024 * 1024)
        if budget < 1024 * 1024 * 1024:
            raise ValueError("Less than 1 GiB safe CUDA headroom; leave other activity alone and retry later")
        torch.cuda.set_per_process_memory_fraction(budget / total)
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    source_catalog = catalog(root)
    code_before = {name: digest(ROOT / "prose_engine" / name) for name in
                   ("embedding_store.py", "voice/luar.py", "styleprint.py", "vector_store.py")}
    initial_pointer = digest(root / ACTIVE) if (root / ACTIVE).is_file() else "missing"
    required = usable_sources(root)
    books = [b for b in load_corpus(root) if b.slug in required]
    chunks = chunk_books(books)
    if {c["source_id"] for c in chunks} != required:
        raise ValueError("Usable sources were omitted by chunking; inspect before building")
    write_new(out / "build-start.json", {"catalog": source_catalog, "expected_pointer": initial_pointer,
              "sources": len(books), "passages": len(chunks), "runtime": runtime(), "provider_calls": 0})
    records = {}
    artifacts = model_artifacts("sentence-transformers/all-MiniLM-L6-v2")
    model = SentenceTransformer(artifacts["repository"], revision=artifacts["revision"], local_files_only=True)
    vectors = model.encode([c["text"] for c in chunks], batch_size=batch_size, convert_to_numpy=True,
                           normalize_embeddings=True, show_progress_bar=True).astype("float32")
    topic = EmbeddingIndex([c["text"] for c in chunks],
        [{**c, "embedding_backend": "transformer", "embedding_model": artifacts["repository"],
          "embedding_revision": artifacts["revision"]} for c in chunks], vectors, artifacts["repository"], model)
    records["topic"] = pin(topic, "topic", source_catalog, artifacts)
    topic.save(out / INDEXES["topic"])
    records["topic"]["probes"] = probes(topic, "topic", batch_size=batch_size)
    topic._model = None
    del model, topic, vectors
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("Topic candidate saved and checked; building token-mask-v2 LUAR.", flush=True)
    encoder = LuarEncoder(preprocessing=MASKED_PREPROCESSING)
    luar = LuarIndex.build(out, encoder, batch_size=batch_size)
    records["luar"] = pin(luar, "luar", source_catalog, encoder.artifacts)
    luar.save_new(out / INDEXES["luar"])
    records["luar"]["probes"] = probes(luar, "luar", encoder, batch_size=batch_size)
    del luar, encoder
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("LUAR candidate saved and checked; building 83-feature style replacement.", flush=True)
    per_book = np.array([fingerprint(b.text) for b in books])
    style_model = {"names": NAMES, "books": [b.slug for b in books], "mean": per_book.mean(axis=0).tolist(),
                   "sd": np.maximum(per_book.std(axis=0), 1e-6).tolist(), "preprocessing": "styleprint-83-zclip3-v1"}
    write_new(out / "styleprint.json", style_model)
    style = StyleIndex.build(out)
    style.manifest = {"source_index_sha256": digest(out / INDEXES["topic"])}
    records["style"] = pin(style, "style", source_catalog)
    records["style"]["style_model_sha256"] = digest(out / "styleprint.json")
    style.save(out / INDEXES["style"])
    records["style"]["probes"] = probes(style, "style")
    # Read actual saved bytes back; no candidate is published on any failure.
    from tools.audit_reference_indexes import inspect
    for backend, filename in INDEXES.items():
        checked = inspect(out / filename)
        if set(checked["sources"]) != required:
            raise ValueError(f"{backend}: saved candidate source coverage changed")
        records[backend]["sha256"] = checked["sha256"]
    if catalog(root) != source_catalog:
        raise ValueError("Source library changed during build; candidate must not be activated")
    for name, original in code_before.items():
        if digest(ROOT / "prose_engine" / name) != original:
            raise ValueError("Encoder changed during build")
    report = {"schema_version": 1, "status": "PASS", "identity": out.name,
              "catalog": source_catalog["fingerprint"], "runtime": runtime(), "indexes": records,
              "expected_pointer": initial_pointer, "created_utc": datetime.now(timezone.utc).isoformat(),
              "elapsed_seconds": round(time.monotonic() - start, 2), "live_provider_calls": 0,
              "quality_exclusions": quality_exclusions(root), "batch_size": batch_size, "max_cuda_mb": max_cuda_mb,
              "legacy_note": "Separately built replacements, not a compatibility claim about the old LUAR/style indexes."}
    write_new(out / "release.json", report)
    print(json.dumps({"status": "PASS", "sources": len(required), "passages": len(chunks), "elapsed_seconds": report["elapsed_seconds"]}), flush=True)


def activate(root, candidate, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", name):
        raise ValueError("Release name must be a simple version label")
    report = json.loads((candidate / "release.json").read_text(encoding="utf-8"))
    current_catalog = catalog(root)
    if report.get("status") != "PASS" or report["catalog"] != current_catalog["fingerprint"] or report["runtime"] != runtime():
        raise ValueError("Candidate is incomplete, stale or built with a different runtime")
    from tools.audit_reference_indexes import inspect
    required = usable_sources(root)
    target = safe_child(root, f"index_releases/{name}")
    if target.exists():
        raise FileExistsError("Release directory already exists; never overwrite a release")
    # Validate every candidate before any active-pointer change.
    for backend, filename in INDEXES.items():
        if digest(candidate / filename) != report["indexes"][backend]["sha256"]:
            raise ValueError("Candidate changed after its local validation")
        # Evaluate bindings with the candidate's descriptor without touching the live pointer.
        info = report["indexes"][backend]
        checked = inspect(candidate / filename)
        if (set(checked["sources"]) != required or set(info["sources"]) != required or
                checked["rows"] != info["passages"] or checked["dimensions"] != info["dimensions"]):
            raise ValueError("Candidate omits usable sources or has inconsistent coverage/dimensions")
        if (not checked["manifest"] or checked["manifest"].get("library_schema") != 1 or
                checked["manifest"].get("catalog") != report["catalog"] or
                any(row["source_revision"] != current_catalog["sources"].get(row["source_id"]) for row in checked["chunks"])):
            raise ValueError("Saved candidate provenance differs from the source library")
        results = info.get("probes", [])
        if ({r.get("source_id") for r in results} != required or len(results) != len(required) or
                not all(r.get("source_in_top5") is True or r.get("self_tied_best") is True for r in results)):
            raise ValueError("Candidate lacks passing retrieval probes for every usable source")
        binding = {"code": digest(safe_child(ROOT / "prose_engine", info["encoder_code"])),
                   "runtime": runtime(), "chunker": digest(ROOT / "prose_engine/vector_store.py")}
        artifacts = info.get("encoder_artifacts")
        if artifacts:
            binding["model"] = model_artifacts(artifacts["repository"], artifacts["revision"])
        if hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest() != info["encoder_binding"]:
            raise ValueError("Candidate encoder/model changed since build")
    if digest(candidate / "styleprint.json") != report["indexes"]["style"]["style_model_sha256"]:
        raise ValueError("Candidate style normalization changed")
    target.mkdir(parents=True)
    hashes = {}
    for filename in [*INDEXES.values(), "styleprint.json", "release.json"]:
        source = candidate / filename
        with source.open("rb") as inp, (target / filename).open("xb") as out:
            shutil.copyfileobj(inp, out, 1024 * 1024)
        hashes[filename] = digest(target / filename)
        expected = report["indexes"][next(b for b, f in INDEXES.items() if f == filename)]["sha256"] if filename in INDEXES.values() else digest(source)
        if hashes[filename] != expected:
            raise ValueError("Release copy verification failed; old pointer remains active")
    if catalog(root)["fingerprint"] != report["catalog"]:
        raise ValueError("Sources changed before activation; old pointer remains active")
    previous = root / ACTIVE
    write_new(target / "activation-before.json", {"pointer": json.loads(previous.read_text(encoding="utf-8")) if previous.is_file() else None,
              "expected_revision": report["expected_pointer"], "legacy_indexes_preserved": True})
    atomic_json_new_revision(root / ACTIVE, {"schema_version": 1, "directory": target.relative_to(root).as_posix(),
                             "hashes": hashes}, report["expected_pointer"])
    print(json.dumps({"status": "ACTIVE", "directory": str(target), "legacy_indexes_overwritten": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", type=Path, default=ROOT / "books")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("build"); p.add_argument("--out", type=Path, required=True); p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--max-cuda-mb", type=int, default=2048)
    p = sub.add_parser("activate"); p.add_argument("--candidate", type=Path, required=True); p.add_argument("--name", required=True)
    p = sub.add_parser("configure"); p.add_argument("--expected-revision", required=True); p.add_argument("--remote", action="store_true")
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    root = args.books.absolute()
    if args.action == "build":
        existed = args.out.exists()
        try:
            build(root, args.out.absolute(), args.batch_size, args.max_cuda_mb)
        except Exception as exc:
            if not existed and args.out.is_dir() and not (args.out / "build-failure.json").exists():
                write_new(args.out / "build-failure.json", {"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc), "active_pointer_changed": False})
            raise
    elif args.action == "activate": activate(root, args.candidate.absolute(), args.name)
    else: print(json.dumps(configure_existing(root, remote=args.remote, expected_revision=args.expected_revision)))


if __name__ == "__main__":
    main()
