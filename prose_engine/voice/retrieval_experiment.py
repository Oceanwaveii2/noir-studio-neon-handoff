"""Offline retrieval trial over original, edition-scoped benchmark passages."""
from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Callable

import numpy as np


FUNCTIONS = frozenset({
    "delayed_recognition", "deadpan_deflection", "staged_escalation",
    "partial_overhear", "status_reversal", "hard_cut",
})
# Rights are purpose-specific. Unknown rights grant nothing, and synthetic
# allowlists do not grant rights to real books or manuscripts.
SOURCE_USE = {"original_u6": frozenset(("rank_local", "inspect_local", "report_ids")),
              "blocked_probe": frozenset(), "unclassified": frozenset()}
ARMS = ("no_references", "minilm", "lexical_dense", "function_hybrid", "qwen_rerank")
FUSION_K = 12
FUNCTION_BOOST = 0.04
RERANK_CANDIDATES = 10


@dataclass(frozen=True)
class Passage:
    id: str
    edition: str
    rights: str
    functions: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class Query:
    id: str
    edition: str
    function: str | None
    text: str


def allows(rights: str, purpose: str) -> bool:
    return purpose in SOURCE_USE.get(rights, ())


def parse_fixture(data: dict) -> tuple[list[Passage], list[Query], dict, dict]:
    if data.get("schema_version") != 1 or data.get("origin") != "original_u6":
        raise ValueError("The experiment needs an original U6 fixture.")
    editions = data["editions"]
    if not editions or set(editions.values()) != {"development", "held_out"}:
        raise ValueError("Use non-overlapping development and held-out editions.")
    passages: dict[str, Passage] = {}
    for raw in data["documents"]:
        p = Passage(raw["id"], raw["edition"], raw["rights"], tuple(raw["functions"]), raw["text"])
        if not p.id or p.id in passages or p.edition not in editions or not p.text.strip():
            raise ValueError("Invalid or duplicate passage ID or edition.")
        if set(p.functions) - FUNCTIONS or len(p.functions) != len(set(p.functions)):
            raise ValueError("Invalid or duplicate function tags.")
        passages[p.id] = p
    queries: dict[str, Query] = {}
    for raw in data["queries"]:
        q = Query(raw["id"], raw["edition"], raw["function"], raw["text"])
        if (not q.id or q.id in queries or q.edition not in editions or not q.text.strip()
                or (q.function is not None and q.function not in FUNCTIONS)):
            raise ValueError("Invalid or duplicate query ID, edition or function.")
        queries[q.id] = q
    labels = data["judgments"]
    if not queries or set(queries) != set(labels):
        raise ValueError("Every query needs exactly one set of judgments.")
    for q in queries.values():
        grades = labels[q.id]
        if not grades or any(type(v) is not int or not 0 <= v <= 3 for v in grades.values()):
            raise ValueError("Judgments use integer grades from 0 to 3.")
        if not any(grades.values()):
            raise ValueError("Each query needs a positive judgment.")
        for doc_id in grades:
            doc = passages.get(doc_id)
            if doc is None or doc.edition != q.edition or not allows(doc.rights, "rank_local"):
                raise ValueError("Judgment names an unknown, excluded or wrong-edition passage.")
    return list(passages.values()), list(queries.values()), editions, labels


_STOP = frozenset("a an and are as at be by for from has have in is it of on or so the their them they to was were what when which who will with".split())


def _match_terms(text: str) -> str:
    # The tokenizer removes FTS syntax and quotation marks. Bind the actual
    # MATCH expression as a parameter.
    terms = {word for word in re.findall(r"[a-z0-9]+", text.casefold()) if word not in _STOP}
    return " OR ".join(f'"{word}"' for word in sorted(terms))


class EditionIndex:
    def __init__(self, passages: list[Passage], vectors: np.ndarray):
        self.passages = {p.id: p for p in passages}
        self.ids = tuple(self.passages)
        self.vectors = vectors
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE passages USING fts5(id UNINDEXED, body)")
        self.db.executemany("INSERT INTO passages (id, body) VALUES (?, ?)", [(p.id, p.text) for p in passages])

    def dense(self, vector: np.ndarray) -> list[str]:
        similarity = self.vectors @ vector
        return [self.ids[i] for i in sorted(range(len(self.ids)), key=lambda i: (-similarity[i], self.ids[i]))]

    def lexical(self, text: str) -> list[str]:
        expression = _match_terms(text)
        if not expression:
            return []
        return [row[0] for row in self.db.execute(
            "SELECT id FROM passages WHERE passages MATCH ? ORDER BY bm25(passages), id", (expression,),
        )]

    def fuse(self, dense: list[str], lexical: list[str], function: str | None) -> list[str]:
        scores = {doc_id: 1 / (FUSION_K + rank) for rank, doc_id in enumerate(dense, 1)}
        for rank, doc_id in enumerate(lexical, 1):
            scores[doc_id] += 1 / (FUSION_K + rank)
        if function:
            # Keep unlabeled and mixed-function passages eligible; ingestion
            # annotations are incomplete and may be noisy.
            for doc_id, passage in self.passages.items():
                if function in passage.functions:
                    scores[doc_id] += FUNCTION_BOOST
        return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))


class ExperimentIndex:
    def __init__(self, passages: list[Passage], encode: Callable[[list[str]], np.ndarray]):
        self.encode = encode
        eligible = sorted((p for p in passages if allows(p.rights, "rank_local") and
                           allows(p.rights, "report_ids")), key=lambda p: p.id)
        if not eligible:
            raise ValueError("No locally eligible passages.")
        self.eligible = {p.id: p for p in eligible}
        vectors = np.asarray(encode([p.text for p in eligible]), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(eligible) or not np.isfinite(vectors).all():
            raise ValueError("Unexpected or non-finite document embeddings.")
        self.scopes = {}
        for edition in sorted({p.edition for p in eligible}):
            rows = [i for i, p in enumerate(eligible) if p.edition == edition]
            self.scopes[edition] = EditionIndex([eligible[i] for i in rows], vectors[rows])

    def close(self) -> None:
        for scope in self.scopes.values():
            scope.db.close()

    def rank(self, arm: str, q: Query, rerank=None) -> list[str]:
        if arm not in ARMS:
            raise ValueError(f"Unknown ranking arm: {arm}")
        if arm == "no_references":
            return []
        scope = self.scopes.get(q.edition)
        if scope is None:
            return []
        vector = np.asarray(self.encode([q.text]), dtype=np.float32)
        if vector.shape != (1, scope.vectors.shape[1]) or not np.isfinite(vector).all():
            raise ValueError("Unexpected or non-finite query embedding.")
        dense = scope.dense(vector[0])
        if arm == "minilm":
            return dense[:5]
        fused = scope.fuse(dense, scope.lexical(q.text), q.function if arm != "lexical_dense" else None)
        if arm != "qwen_rerank":
            return fused[:5]
        if rerank is None:
            raise ValueError("Reranker is unavailable.")
        shortlist = fused[:RERANK_CANDIDATES]
        scores = rerank(q.text, [scope.passages[doc_id].text for doc_id in shortlist])
        if len(scores) != len(shortlist) or not np.isfinite(scores).all():
            raise ValueError("Unexpected or non-finite reranker scores.")
        order = sorted(range(len(shortlist)), key=lambda i: (-scores[i], i))
        return [shortlist[i] for i in order[:5]]
