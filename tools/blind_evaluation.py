"""Prepare deterministic, scene-separated blinded comparisons for author review."""
from __future__ import annotations

import hashlib
import json


def prepare(cases: list[dict], assignments: dict[str, str], seed: str) -> dict:
    if not seed or not cases or not assignments:
        raise ValueError("Cases, scene assignments and a seed are required.")
    if set(assignments.values()) != {"development", "held_out"}:
        raise ValueError("Use both development and held_out scene assignments.")
    seen = set()
    public, key = [], {}
    for case in cases:
        case_id, scene = case.get("id"), case.get("scene_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen or scene not in assignments:
            raise ValueError("Every case needs a unique ID and an assigned scene.")
        if not all(isinstance(case.get(field), str) and case[field].strip() for field in ("original", "candidate")):
            raise ValueError("Each case needs original and candidate text.")
        seen.add(case_id)
        digest = hashlib.sha256((seed + "\0" + case_id).encode("utf-8")).digest()
        options = [("original", case["original"]), ("candidate", case["candidate"])]
        if digest[0] & 1:
            options.reverse()
        token = hashlib.sha256(("case\0" + seed + "\0" + case_id).encode("utf-8")).hexdigest()[:24]
        public.append({"token": token, "split": assignments[scene],
                       "option_a": options[0][1], "option_b": options[1][1]})
        key[token] = {"case_id": case_id, "scene_id": scene, "option_a": options[0][0],
                      "option_b": options[1][0]}
    public.sort(key=lambda row: row["token"])
    return {"presentation": public, "key": key,
            "fingerprint": hashlib.sha256(json.dumps(
                {"cases": cases, "assignments": assignments, "seed": seed},
                sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()}
