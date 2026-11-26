"""Score a bounded local set of labeled pairs; output scores, never passage text."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.reference_service import prepare_retrieval
from prose_engine.voice.luar_calibration import evaluate

MAX_EXAMPLES = 60
MAX_CHARS = 6000


def sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def influence_digest(path):
    path = Path(path)
    h = hashlib.sha256()
    if not path.is_file():
        h.update(b"missing")
    else:
        h.update(b"present\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
    return h.hexdigest()


def score_pairs(data, drive, pipeline):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Expected pair file schema version 1")
    if data.get("evidence_kind") not in {"synthetic", "author_reviewed"}:
        raise ValueError("Declare synthetic or author_reviewed evidence")
    examples = data.get("examples")
    if not isinstance(examples, list) or not 1 <= len(examples) <= MAX_EXAMPLES:
        raise ValueError(f"Provide between 1 and {MAX_EXAMPLES} pairs")
    prepared = []
    for row in examples:
        if not isinstance(row, dict) or set(row) - {
            "id", "document_id", "split", "decision", "reviewer", "evidence", "original", "candidate"
        }:
            raise ValueError("Unknown or invalid pair fields")
        for key in ("original", "candidate"):
            if not isinstance(row.get(key), str) or not row[key].strip() or len(row[key]) > MAX_CHARS:
                raise ValueError(f"Each {key} must contain 1 to {MAX_CHARS} characters")
        prepared.append({key: value for key, value in row.items() if key not in {"original", "candidate"}} |
                        {"before": 0.0, "after": 0.0})
    # Validate all identities, labels and document split boundaries before encoding any text.
    evaluate({"schema_version": 1, "evidence_kind": data["evidence_kind"],
              "pipeline": pipeline, "examples": prepared})
    pairs = []
    for row in examples:
        # Use the exact per-text adapter path used by conditioning.
        scores = [drive.score_text(row[key]) for key in ("original", "candidate")]
        if any(not x.get("count") or not np.isfinite(x["mean_top"]) for x in scores):
            raise ValueError("LUAR returned no finite score; do not calibrate this pair")
        cleaned = []
        for item in scores:
            n = float(item["mean_top"])
            if n < -1.000001 or n > 1.000001:
                raise ValueError("Similarity is outside the cosine range")
            cleaned.append(max(-1.0, min(1.0, n)))
        pairs.append({key: value for key, value in row.items() if key not in {"original", "candidate"}} |
                     {"before": cleaned[0], "after": cleaned[1]})
    return {"schema_version": 1, "evidence_kind": data["evidence_kind"], "pipeline": pipeline, "examples": pairs}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="Local labeled source/candidate pairs")
    parser.add_argument("--books", required=True, help="Books directory with explicit local ranking permission")
    parser.add_argument("--out", required=True, help="New score file, never overwritten")
    args = parser.parse_args(argv)
    try:
        source, target, root = Path(args.file), Path(args.out), Path(args.books)
        if target.exists():
            raise FileExistsError("Score destination already exists")
        if source.stat().st_size > 2_000_000:
            raise ValueError("Pair file exceeds the 2 MB local scoring limit")
        data = json.loads(source.read_text(encoding="utf-8"))
        index_path, policy_path = root / "luar_index.joblib", root / "reference_policy.json"
        before_index, before_policy = sha_file(index_path), sha_file(policy_path)
        before_influence = influence_digest(root / "influence.json")
        setup = prepare_retrieval(root, "luar", "local", purposes=("rank_local",))
        if setup.state != "ready":
            raise ValueError(f"{setup.state}: {setup.message}")
        pipeline = {"backend": "luar", "model": getattr(setup.drive.encoder, "model_name", "unknown"),
                    "model_revision": getattr(setup.drive.encoder, "model_revision", None) or "unverified",
                    "preprocessing": getattr(setup.drive.encoder, "preprocessing", "unverified"),
                    "index_compatibility": getattr(setup.drive, "compatibility", "unverified"),
                    "index_sha256": before_index, "policy_sha256": before_policy,
                    "influence_sha256": before_influence}
        scored = score_pairs(data, setup.drive, pipeline)
        if (sha_file(index_path) != before_index or sha_file(policy_path) != before_policy or
                influence_digest(root / "influence.json") != before_influence):
            raise ValueError("Index, policy or influence settings changed during scoring")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as out:
            json.dump(scored, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write("\n")
        print(f"Scored {len(scored['examples'])} pairs locally; passage text omitted. No provider call.")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"Scoring unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
