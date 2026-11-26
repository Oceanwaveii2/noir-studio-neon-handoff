"""Offline calibration of LUAR similarity drops; never changes a live gate."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

MIN_PER_CLASS = 10


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def evaluate(data, *, max_false_rejection=0.10, min_detection=0.50, min_per_class=MIN_PER_CLASS):
    """Select using development groups and report untouched held-out performance.

    False rejection is the fraction of author-acceptable examples rejected.
    Detection is the fraction of off-voice examples rejected. All scores must
    already have been produced with the same policy-filtered scoring pipeline.
    """
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Expected calibration schema version 1")
    if not (0 <= max_false_rejection <= 1 and 0 <= min_detection <= 1 and
            type(min_per_class) is int and min_per_class >= 1):
        raise ValueError("Invalid evaluation criteria")
    kind = data.get("evidence_kind")
    if kind not in {"synthetic", "author_reviewed"}:
        raise ValueError("Evidence must be synthetic or author_reviewed")
    pipeline = data.get("pipeline")
    keys = ("backend", "model", "model_revision", "preprocessing", "index_sha256",
            "policy_sha256", "influence_sha256")
    if not isinstance(pipeline, dict) or any(not _nonempty(pipeline.get(k)) for k in keys):
        raise ValueError("Model, preprocessing, index and policy identities are required")
    if pipeline["backend"] != "luar":
        raise ValueError("This evaluator calibrates LUAR only")
    for k in ("index_sha256", "policy_sha256", "influence_sha256"):
        h = pipeline[k]
        if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise ValueError(f"{k} must be a lowercase SHA-256 digest")
    rows = data.get("examples")
    if not isinstance(rows, list):
        raise ValueError("Examples must be a list")
    seen = set()
    groups = {}
    partitions = {"development": [], "held_out": []}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid example")
        if set(row) - {"id", "document_id", "split", "decision", "before", "after", "reviewer", "evidence"}:
            raise ValueError("Examples must contain scores and provenance, not passage text")
        if not all(_nonempty(row.get(k)) for k in ("id", "document_id", "split", "decision")):
            raise ValueError("Example ID, document, split and decision are required")
        if row["id"] in seen:
            raise ValueError("Duplicate example ID")
        seen.add(row["id"])
        split, label, group = row["split"], row["decision"], row["document_id"]
        if split not in partitions or label not in {"acceptable", "off_voice"}:
            raise ValueError("Unknown split or decision")
        if group in groups and groups[group] != split:
            raise ValueError("A document cannot occur in both splits")
        groups[group] = split
        if kind == "author_reviewed" and not (_nonempty(row.get("reviewer")) and _nonempty(row.get("evidence"))):
            raise ValueError("Author-reviewed examples require reviewer and decision evidence")
        for field in ("before", "after"):
            n = row.get(field)
            if type(n) not in (int, float) or not math.isfinite(n) or not -1 <= n <= 1:
                raise ValueError("Cosine similarity must be finite and between -1 and 1")
        partitions[split].append((label, float(row["before"]) - float(row["after"])))

    counts = {split: {label: sum(x[0] == label for x in values)
                       for label in ("acceptable", "off_voice")} for split, values in partitions.items()}
    def metrics(values, threshold):
        ok = [drop for label, drop in values if label == "acceptable"]
        bad = [drop for label, drop in values if label == "off_voice"]
        return {"acceptable_count": len(ok), "false_rejections": sum(x > threshold for x in ok),
                "false_rejection_rate": sum(x > threshold for x in ok) / len(ok),
                "off_voice_count": len(bad), "detections": sum(x > threshold for x in bad),
                "detection_rate": sum(x > threshold for x in bad) / len(bad)}

    base = {"evidence_kind": kind, "pipeline": dict(pipeline), "counts": counts,
            "criteria": {"max_false_rejection": max_false_rejection, "min_detection": min_detection,
                         "min_per_class": min_per_class},
            "live_gate_changed": False}
    if any(count < min_per_class for part in counts.values() for count in part.values()):
        return {**base, "status": "insufficient_evidence", "candidate": None}
    candidates = sorted({0.0} | {max(0.0, drop) for _, drop in partitions["development"]})
    eligible = [(metrics(partitions["development"], x), x) for x in candidates]
    eligible = [(score, threshold) for score, threshold in eligible
                if score["false_rejection_rate"] <= max_false_rejection]
    if not eligible:
        return {**base, "status": "no_candidate", "candidate": None}
    dev, threshold = max(eligible, key=lambda item: (item[0]["detection_rate"], -item[1]))
    held = metrics(partitions["held_out"], threshold)
    passed = (held["false_rejection_rate"] <= max_false_rejection and
              held["detection_rate"] >= min_detection and dev["detection_rate"] >= min_detection)
    status = ("synthetic_only" if kind == "synthetic" else
              ("candidate_for_review" if passed else "held_out_failed"))
    return {**base, "status": status, "candidate": threshold, "development": dev,
            "held_out": held, "criteria_met": passed,
            "note": "Labels and identity are caller-declared; small samples do not prove writing quality."}


def evaluate_file(path, **kwargs):
    raw = Path(path).read_bytes()
    result = evaluate(json.loads(raw.decode("utf-8")), **kwargs)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    return result
