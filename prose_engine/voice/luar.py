"""
LUAR style embeddings: authorship-attribution vectors rather than topic similarity.

LUAR expects a document as a series of 32-token episodes, shape (batch, episodes, 32).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.metadata
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import joblib
import numpy as np

try:
    import torch
except Exception:
    torch = None

MODEL = "rrivera1849/LUAR-MUD"
MODEL_REVISION = "f1db50251805ed69b43cf4f72ea2f0e231f36a1c"
EPISODE = 32
MAX_LENGTH = 256
LEGACY_PREPROCESSING = "legacy-ones-v1"
MASKED_PREPROCESSING = "token-mask-v2"


def _episodes(ids: torch.Tensor, max_length: int, pad_value: int = 0) -> torch.Tensor:
    if torch is None:
        raise RuntimeError("torch is required for Luar episodes")
    ids = ids[:max_length]
    count = max(1, (len(ids) + EPISODE - 1) // EPISODE)
    padded = torch.full((count * EPISODE,), pad_value, dtype=ids.dtype)
    padded[: len(ids)] = ids
    return padded.view(count, EPISODE)


class LuarEncoder:
    def __init__(self, model_name: str = MODEL, device: Optional[str] = None, *,
                 preprocessing: str = LEGACY_PREPROCESSING, revision: Optional[str] = None):
        if torch is None:
            raise RuntimeError("torch is required for LuarEncoder")
        from transformers import AutoModel, AutoTokenizer, RobertaTokenizer

        if preprocessing not in (LEGACY_PREPROCESSING, MASKED_PREPROCESSING):
            raise ValueError("Unknown LUAR preprocessing version")
        self.model_name = model_name
        self.model_revision = revision or (MODEL_REVISION if model_name == MODEL else None)
        self.preprocessing = preprocessing
        from ..library_indexes import model_artifacts
        self.artifacts = model_artifacts(model_name, self.model_revision)
        tokenizer_class = RobertaTokenizer if model_name == MODEL else AutoTokenizer
        self.tokenizer = tokenizer_class.from_pretrained(model_name, revision=self.model_revision, local_files_only=True)
        self.model = AutoModel.from_pretrained(model_name, revision=self.model_revision,
                                                trust_remote_code=True, local_files_only=True).eval()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)

    def encode(self, texts: Sequence[str], batch_size: int = 8, max_length: int = MAX_LENGTH) -> np.ndarray:
        if type(batch_size) is not int or batch_size < 1 or type(max_length) is not int or max_length < 1:
            raise ValueError("LUAR batch size and maximum length must be positive integers")
        vectors: List[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            tokenized = self.tokenizer(
                batch, return_tensors="pt", truncation=True, max_length=max_length, padding="max_length"
            )
            ids = tokenized["input_ids"]
            if self.preprocessing == MASKED_PREPROCESSING:
                pad_id = self.tokenizer.pad_token_id
                if pad_id is None:
                    raise ValueError("LUAR tokenizer has no padding token")
                episodes = torch.stack([_episodes(row, max_length, pad_id) for row in ids])
                mask = torch.stack([_episodes(row, max_length, 0) for row in tokenized["attention_mask"]])
            else:
                episodes = torch.stack([_episodes(row, max_length) for row in ids])
                mask = torch.ones_like(episodes)
            with torch.no_grad():
                out = self.model(
                    input_ids=episodes.to(self.device), attention_mask=mask.to(self.device)
                )
            vectors.append(out.float().cpu().numpy())
        matrix = np.concatenate(vectors, axis=0) if vectors else np.zeros((0, 1), dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return (matrix / np.maximum(norms, 1e-9)).astype("float32")


class LuarIndex:
    def __init__(self, vectors: np.ndarray, texts: Sequence[str], meta: Sequence[Dict], manifest=None):
        self.vectors = np.asarray(vectors, dtype="float32")
        self.texts = list(texts)
        self.meta = list(meta)
        self.manifest = manifest
        self.source_status = "not-checked" if manifest is not None else "legacy-unverified"

    @classmethod
    def build(cls, books: str | Path = "books", encoder: Optional[LuarEncoder] = None, limit: Optional[int] = None, *, batch_size=None):
        from ..embedding_store import load_index

        root = Path(books)
        source = root / "vector_index.joblib"
        def source_hash():
            h = hashlib.sha256()
            with source.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
            return h.hexdigest()
        original_source_hash = source_hash()
        index = load_index(source)
        texts = index.texts[: limit] if limit else index.texts
        meta = index.meta[: limit] if limit else index.meta
        if not texts:
            raise ValueError("Cannot build a LUAR index without passages")
        encoder = encoder or LuarEncoder(preprocessing=MASKED_PREPROCESSING)
        vectors = encoder.encode(texts, **({"batch_size": batch_size} if batch_size is not None else {}))
        meta = [{**entry, "embedding_backend": "luar",
                 "embedding_model": getattr(encoder, "model_name", "unknown"),
                 "embedding_revision": getattr(encoder, "model_revision", None) or "unversioned",
                 "embedding_preprocessing": getattr(encoder, "preprocessing", "unknown")} for entry in meta]
        if source_hash() != original_source_hash:
            raise ValueError("Source index changed during LUAR index build")
        runtime = {"python": f"{sys.version_info.major}.{sys.version_info.minor}",
                   "torch": importlib.metadata.version("torch"),
                   "transformers": importlib.metadata.version("transformers")}
        manifest = {"schema_version": 2, "model": getattr(encoder, "model_name", "unknown"),
                    "revision": getattr(encoder, "model_revision", None),
                    "preprocessing": getattr(encoder, "preprocessing", "unknown"),
                    "max_length": MAX_LENGTH, "episode_tokens": EPISODE, "runtime": runtime,
                    "dimensions": int(vectors.shape[1]), "source_index_sha256": original_source_hash,
                    "sources": sorted({entry.get("source_id") or entry.get("book", "unknown") for entry in meta}),
                    "chunk_hashes": [hashlib.sha256(text.encode("utf-8")).hexdigest() for text in texts]}
        built = cls(vectors, texts, meta, manifest)
        built.source_status = "matched"
        return built

    def query(self, vector: np.ndarray, k: int = 6) -> List[Dict]:
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return []
        scores = self.vectors @ (vector / norm)
        order = np.argsort(-scores)[:k]
        return [
            {"score": float(scores[index]), "text": self.texts[index], "meta": self.meta[index]}
            for index in order
        ]

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"vectors": self.vectors, "texts": self.texts, "meta": self.meta,
                     "manifest": self.manifest}, target)
        return target

    def save_new(self, path: str | Path) -> Path:
        """Write a separately named index; never replace an existing file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            joblib.dump({"vectors": self.vectors, "texts": self.texts,
                         "meta": self.meta, "manifest": self.manifest}, stream)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "LuarIndex":
        data = joblib.load(Path(path))
        result = cls(data["vectors"], data["texts"], data["meta"], data.get("manifest"))
        manifest = result.manifest
        if manifest is not None:
            if (not isinstance(manifest, dict) or manifest.get("schema_version") not in (1, 2) or result.vectors.ndim != 2 or
                len(result.texts) != len(result.meta) or len(result.texts) != len(result.vectors) or
                manifest.get("dimensions") != result.vectors.shape[1] or
                not isinstance(manifest.get("source_index_sha256"), str) or len(manifest["source_index_sha256"]) != 64 or
                manifest.get("chunk_hashes") != [hashlib.sha256(t.encode("utf-8")).hexdigest() for t in result.texts]):
                raise ValueError("LUAR index manifest does not match its contents")
            source = Path(path).resolve().parent / "vector_index.joblib"
            if source.is_file():
                h = hashlib.sha256()
                with source.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        h.update(block)
                if h.hexdigest() != manifest.get("source_index_sha256"):
                    raise ValueError("LUAR source index changed since this index was built")
                result.source_status = "matched"
            else:
                result.source_status = "source-unavailable"
        return result


class LuarDrive:
    """Adapter for the conditioner; style retrieval through LUAR."""
    similarity_threshold = None  # The legacy 0.10 threshold was never calibrated for LUAR.

    def __init__(self, index: LuarIndex, encoder: Optional[LuarEncoder] = None):
        from ..reference_policy import legacy_identities
        self.index = legacy_identities(index)
        manifest = self.index.manifest
        if manifest is not None and (not isinstance(manifest, dict) or
                                     manifest.get("schema_version") not in (1, 2)):
            raise ValueError("Invalid LUAR index manifest")
        self.encoder = encoder or LuarEncoder(
            model_name=manifest["model"] if manifest else MODEL,
            preprocessing=manifest["preprocessing"] if manifest else LEGACY_PREPROCESSING,
            revision=manifest["revision"] if manifest else None)
        self.compatibility = "legacy-unverified" if not manifest else "manifest-unverified"
        if manifest is not None:
            if manifest.get("encoder_artifacts") and manifest["encoder_artifacts"] != getattr(self.encoder, "artifacts", None):
                raise ValueError("LUAR cached model/tokenizer/code artifacts changed since index build")
            if (manifest.get("schema_version") not in (1, 2) or
                manifest.get("model") != getattr(self.encoder, "model_name", None) or
                manifest.get("revision") != getattr(self.encoder, "model_revision", None) or
                manifest.get("preprocessing") != getattr(self.encoder, "preprocessing", None) or
                self.index.vectors.ndim != 2 or manifest.get("dimensions") != self.index.vectors.shape[1]):
                raise ValueError("LUAR encoder and index manifest do not match")
            if manifest.get("schema_version") == 2:
                runtime = {"python": f"{sys.version_info.major}.{sys.version_info.minor}",
                           "torch": importlib.metadata.version("torch"),
                           "transformers": importlib.metadata.version("transformers")}
                if (manifest.get("max_length") != MAX_LENGTH or manifest.get("episode_tokens") != EPISODE or
                        manifest.get("runtime") != runtime):
                    raise ValueError("LUAR index preprocessing or runtime does not match")
            if (manifest.get("schema_version") == 2 and manifest.get("revision") and
                    manifest.get("preprocessing") in (MASKED_PREPROCESSING, LEGACY_PREPROCESSING)):
                self.compatibility = "manifest-matched"

    def retrieve_passages(self, profile_id, query_text, scene_type=None, max_results=6, influence=None):
        from ..semantic_drive import ReferencePassage

        vector = self.encoder.encode([query_text])[0]
        hits = self.index.query(vector, k=len(self.index.texts) if influence is not None else max_results)
        if influence is not None:
            from ..influence import select
            hits = [dict(score=s, text=t, meta=m) for s,t,m in
                    select([(h["score"],h["text"],h["meta"]) for h in hits],max_results,influence)]
        return [
            ReferencePassage(
                passage_id=hit["meta"].get("passage_id", f"{hit['meta'].get('book', '?')}-{number}"),
                profile_id=profile_id,
                text=hit["text"],
                scene_type="luar",
                tags=[str(hit["meta"].get("book", ""))],
                provenance={key: hit["meta"][key] for key in ("source_id", "source_revision", "anchor", "chunker", "embedding_backend", "embedding_model", "embedding_revision", "embedding_preprocessing") if key in hit["meta"]},
            )
            for number, hit in enumerate(hits)
        ]

    def score_text(self, text: str, k: int = 3) -> dict:
        """Score with the same encoder and eligible index used by retrieval."""
        if not text.strip() or not self.index.texts:
            return {"max": 0.0, "mean_top": 0.0, "count": 0}
        vector = np.asarray(self.encoder.encode([text])[0], dtype="float32")
        if vector.ndim != 1 or not np.isfinite(vector).all():
            raise ValueError("LUAR returned an invalid embedding")
        if self.index.vectors.ndim != 2 or self.index.vectors.shape[1] != vector.shape[0]:
            raise ValueError("LUAR embedding and index dimensions differ")
        hits = self.index.query(vector, k=max(1, k))
        if not hits:
            return {"max": 0.0, "mean_top": 0.0, "count": 0}
        scores = [hit["score"] for hit in hits]
        if not np.isfinite(scores).all():
            raise ValueError("LUAR returned a non-finite similarity")
        return {"max": max(scores), "mean_top": sum(scores) / len(scores), "count": len(scores)}


class LuarScorer:
    """Voice signal for best-of-N: best cosine between a candidate and the book passages."""

    def __init__(self, index: LuarIndex, encoder: Optional[LuarEncoder] = None):
        self.index = index
        self.encoder = encoder or LuarEncoder()

    def score(self, text: str) -> float:
        vector = self.encoder.encode([text])[0]
        matrix = self.index.vectors
        norms = np.linalg.norm(matrix, axis=1) * float(np.linalg.norm(vector)) + 1e-9
        return float(np.max(matrix @ vector / norms))
