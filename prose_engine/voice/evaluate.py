"""
Evaluation harness: corpus similarity, percentile, decision ledger.

The similarity is the cosine between a text and the corpus centroid in the same embedding space
as the vector index. The percentile places a text against the distribution of the corpus's own
passages, so "0.49" becomes "this is at the 21st percentile of the books".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

DEFAULT_LEDGER = Path("eval/decisions.jsonl")


@dataclass
class Decision:
    scene: str
    paragraph: int
    accepted: bool
    similarity: float = 0.0
    percentile: float = 0.0
    style: float = 0.0
    overlap: float = 0.0
    tics: Dict[str, int] = field(default_factory=dict)
    alpha: float = 0.0
    candidates: int = 1
    provider: str = ""
    task: str = "condition"
    reason: str = ""
    run_id: str = ""
    ts_utc: str = ""
    kind: str = "scene"
    beat_id: str = ""
    model: str = ""
    prompt_sha256: str = ""
    candidates_dropped_copy: int = 0
    candidate_errors: List[str] = field(default_factory=list)
    gates: Dict = field(default_factory=dict)
    scores: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


class Evaluator:
    def __init__(
        self,
        books: str | Path | None = "books",
        vectors: Optional[np.ndarray] = None,
        encode: Optional[Callable[[str], np.ndarray]] = None,
    ):
        self.encode = encode
        if vectors is None and books is not None:
            from ..reference_service import prepare_retrieval
            setup = prepare_retrieval(books, "topic", "local", purposes=("rank_local",))
            if setup.state != "ready":
                raise ValueError(setup.message)
            index = setup.drive.index
            vectors = index.vectors
            if encode is None:
                self.encode = lambda text: index._encode([text])[0]
        if vectors is None:
            raise ValueError("either books or vectors must be provided")
        matrix = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.unit = matrix / np.maximum(norms, 1e-9)
        centroid = self.unit.mean(axis=0)
        self.centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-9)
        self.passage_scores = np.sort(self.unit @ self.centroid)

    def similarity(self, text: str) -> float:
        vector = self._encode(text)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return 0.0
        return float((vector / norm) @ self.centroid)

    def percentile(self, text: str) -> float:
        score = self.similarity(text)
        position = int(np.searchsorted(self.passage_scores, score))
        return position / max(1, len(self.passage_scores))

    def _encode(self, text: str) -> np.ndarray:
        if self.encode is None:
            raise RuntimeError("no encoder configured")
        vector = np.asarray(self.encode(text), dtype="float32")
        return vector.reshape(-1)

    def record(self, decision: Decision, ledger: str | Path = DEFAULT_LEDGER) -> Path:
        path = Path(ledger)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")
        return path


def report(ledger: str | Path = DEFAULT_LEDGER) -> Dict:
    path = Path(ledger)
    if not path.is_file():
        return {"total": 0}
    entries: List[Dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries:
        return {"total": 0}
    accepted = [entry for entry in entries if entry.get("accepted")]
    tic_totals: Dict[str, int] = {}
    for entry in entries:
        for name, value in (entry.get("tics") or {}).items():
            tic_totals[name] = tic_totals.get(name, 0) + int(value)
    return {
        "total": len(entries),
        "accepted": len(accepted),
        "accept_rate": round(len(accepted) / len(entries), 3),
        "mean_similarity_accepted": (
            round(sum(float(entry.get("similarity") or 0) for entry in accepted) / len(accepted), 4)
            if accepted else None
        ),
        "mean_percentile_accepted": (
            round(sum(float(entry.get("percentile") or 0) for entry in accepted) / len(accepted), 4)
            if accepted else None
        ),
        "mean_similarity": round(
            sum(float(entry.get("similarity") or 0) for entry in entries) / len(entries), 4
        ),
        "mean_percentile": round(
            sum(float(entry.get("percentile") or 0) for entry in entries) / len(entries), 4
        ),
        "mean_style": round(
            sum(float(entry.get("style") or 0) for entry in entries) / len(entries), 4
        ),
        "tics": dict(sorted(tic_totals.items(), key=lambda pair: -pair[1])),
    }
