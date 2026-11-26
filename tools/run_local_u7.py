"""Run fixed, offline local editing trials. Results are candidates only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import http.client
import json
import math
import os
from pathlib import Path
from statistics import median
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.local_trial import (
    CONTEXT, MAX_TOKENS, SEED, TrialCase, assess, deterministic, synthetic_case,
)
from prose_engine.providers.local_llm import LocalTransformersProvider
from prose_engine.voice.spatial import House
from prose_engine.voice.world_state import WorldState
from tools.review_pilot import manuscript_spans
from tools.u7_runtime import LlamaRuntime, LocalRuntimeError, gpu_memory

PINS = {
    "qwen-gguf": ("unsloth/Qwen3.5-9B-GGUF", "3885219b6810b007914f3a7950a8d1b469d598a5",
                  "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"),
    "gemma-gguf": ("google/gemma-4-E4B-it-qat-q4_0-gguf", "4b4a2c1d584be7264f87aac328a1bc739ce81b6c",
                   "676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee"),
}
CURRENT_REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"


def digest(path):
    hashed = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024**2), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


def load_cases(protocol: dict) -> list[TrialCase]:
    if protocol["schema_version"] != 1 or protocol["settings"] != {
        "retrieval": "off", "context_tokens": CONTEXT, "max_output_tokens": MAX_TOKENS,
        "temperature": 0, "seed": SEED,
    }:
        raise ValueError("Incorrect frozen protocol settings.")
    files = ("source", "u5_spec", "u5_decision")
    payload = {}
    for field in files:
        path = (ROOT / protocol[field]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Frozen sources must stay in this workspace.")
        body = path.read_bytes()
        if sha256(body).hexdigest() != protocol[f"{field}_sha256"]:
            raise ValueError(f"Frozen input changed: {field}.")
        payload[field] = body
    if digest(ROOT / "books/world_state.json") != protocol["world_sha256"]:
        raise ValueError("The frozen canon inputs changed.")
    spec = json.loads(payload["u5_spec"])
    prior = json.loads(payload["u5_decision"])
    chosen = set(prior["delegated_selection"]["chosen_edit_ids"])
    source = payload["source"].decode("utf-8")
    paragraphs = manuscript_spans(source)
    frozen = tuple((span["start"], span["end"]) for span in paragraphs if span["protected"])
    by_scene = defaultdict(list)
    for i, part in enumerate(paragraphs):
        by_scene[part["scene"]].append(i)
    seeds = [synthetic_case(row) for row in protocol["smoke"]]
    if len(seeds) != 5 or len({case.id for case in seeds}) != 5:
        raise ValueError("The protocol requires five distinct smoke cases.")
    wanted = [(scene, i) for scene, ids in protocol["held_out"].items() for i in ids]
    if len(set(wanted)) != 30 or len(wanted) != 30 or len(protocol["held_out"]) < 3:
        raise ValueError("Expected 30 unique held-out action spans across at least three scenes.")
    edits = {(row["scene"], row["paragraph"]): row for row in spec["edits"]}
    for scene, i in wanted:
        row = edits[(scene, i)]
        part = paragraphs[i]
        if (part["scene"] != scene or spec["scene_split"][scene] != "held_out"
                or part["protected"] or part["text"].count(row["before"]) != 1):
            raise ValueError("A held-out action anchor changed or is frozen.")
        cid = f"scene-{scene}:passage-{i}"
        start = part["start"] + part["text"].index(row["before"])
        parts = by_scene[scene]
        seeds.append(TrialCase(
            cid, "held_out", scene, source, protocol["source_sha256"], start, start + len(row["before"]),
            part["start"], part["end"], frozen, tuple(paragraphs[j]["text"] for j in parts), parts.index(i),
            protocol["held_out_direction"], row["after"] if cid in chosen else None,
        ))
    return seeds


def summary(rows: list[dict]) -> dict:
    summaries = {}
    for split in ("smoke", "held_out"):
        selected = [r for r in rows if r["split"] == split]
        if not selected:
            continue
        counts = Counter(row["status"] for row in selected)
        times = sorted(row["elapsed_ms"] for row in selected)
        summaries[split] = {
            "cases": len(selected), "outcomes": dict(counts), "eligible": counts["ELIGIBLE"],
            "schema_ok": sum(row["schema_ok"] for row in selected),
            "hard_blocks": sum(n for status, n in counts.items() if status.startswith("BLOCKED_")),
            "p50_ms": round(median(times), 2),
            "p95_ms": round(times[math.ceil(.95 * len(times)) - 1], 2),
        }
    return summaries


def trial(cases, methods, world, house, emit):
    records = {method: [] for method in methods}
    active = list(methods)
    for i, case in enumerate(cases):
        # Rotate the first arm to limit order bias. All smoke cases are
        # evaluated before any held-out case.
        first = i % len(active)
        order = active[first:] + active[:first]
        for method in order:
            start = time.perf_counter()
            try:
                output = methods[method](case)
                audit = assess(case, output["raw"], world, house)
            except (LocalRuntimeError, OSError, http.client.HTTPException, KeyError, ValueError) as exc:
                output = {"error": type(exc).__name__, "finish_reason": None}
                audit = {"status": "RUNTIME_ERROR", "schema_ok": False}
            record = {"id": case.id, "scene": case.scene, "split": case.split, "method": method,
                      "elapsed_ms": round((time.perf_counter() - start) * 1000, 2), **output, **audit}
            records[method].append(record)
            emit(record)
        if i == 4 or (i + 1) % 5 == 0:
            print(f"Completed {i+1}/{len(cases)} cases across {len(active)} arm(s).", flush=True)
        if i == 4:
            active = [method for method in active if any(r["schema_ok"] for r in records[method])]
            for method in methods.keys() - set(active):
                print(f"{method} returned no schema-valid response in smoke; held-out skipped.", flush=True)
            if not active:
                break
    return {name: summary(rows) for name, rows in records.items()}


class CurrentRuntime:
    """Use the exact installed production loader, with frozen trial decoding."""
    def __init__(self, path):
        import torch

        if path.name != CURRENT_REVISION or not (path / "model.safetensors.index.json").is_file():
            raise ValueError("Use the pinned official Qwen3.5-9B snapshot.")
        free, total = torch.cuda.mem_get_info()
        budget = min(free - 1024**3, 14 * 1024**3)
        if budget < 5 * 1024**3:
            raise LocalRuntimeError("Current all-GPU NF4 loader does not have sufficient isolated headroom.")
        torch.cuda.set_per_process_memory_fraction(budget / total)
        torch.set_num_threads(6)
        torch.manual_seed(SEED)
        self.torch = torch
        self.provider = LocalTransformersProvider(str(path), max_new_tokens=MAX_TOKENS, load_in_4bit=True)
        start = time.perf_counter()
        self.provider._load()
        self.cold_ms = round((time.perf_counter() - start) * 1000, 2)

    def generate(self, messages):
        model, tokenizer, torch = self.provider._model, self.provider._tokenizer, self.torch
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(self.provider.device)
        used = inputs["input_ids"].shape[-1]
        if used + MAX_TOKENS > CONTEXT:
            raise ValueError("Trial input exceeds the fixed context.")
        with torch.inference_mode():
            output = model.generate(**inputs, do_sample=False, max_new_tokens=MAX_TOKENS,
                                    pad_token_id=tokenizer.eos_token_id)
        reply = output[0][used:]
        return {"raw": tokenizer.decode(reply, skip_special_tokens=True).strip(),
                "finish_reason": "length" if len(reply) == MAX_TOKENS else "stop",
                "completion_tokens": len(reply)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("deterministic", "current", *PINS), required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--protocol", type=Path, default=ROOT / "eval/u7_local_protocol.json")
    parser.add_argument("--out", type=Path, required=True, help="New report directory")
    parser.add_argument("--cpu-smoke", action="store_true", help="Run just the first smoke case with a GGUF on CPU")
    args = parser.parse_args()
    if args.cpu_smoke and args.arm not in PINS:
        parser.error("CPU smoke is only available for a GGUF arm.")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    try:
        protocol_bytes = args.protocol.read_bytes()
        protocol = json.loads(protocol_bytes)
        cases = load_cases(protocol)
        world = WorldState.load(ROOT / "books/world_state.json")
        house = House.load()
        args.out.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Cannot prepare U7: {exc}\n")
    report = {"arm": args.arm, "protocol_sha256": sha256(protocol_bytes).hexdigest(),
              "source_sha256": protocol["source_sha256"],
              "status": "MEASURED", "applied": 0, "author_review": "NOT_MEASURED"}
    try:
        with (args.out / "local-candidates.jsonl").open("x", encoding="utf-8") as stream:
            def emit(row):
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()

            if args.arm == "deterministic":
                report["results"] = trial(cases, {"delegated_cut_baseline": lambda c: {"raw": deterministic(c)}},
                                          world, house, emit)
            elif args.arm == "current":
                if not args.weights:
                    raise ValueError("Current arm requires the official local snapshot.")
                current = CurrentRuntime(args.weights.resolve())
                report.update(model="Qwen/Qwen3.5-9B NF4", revision=CURRENT_REVISION, cold_ms=current.cold_ms)
                report["results"] = trial(cases, {"strict": lambda c: current.generate(c.messages())}, world, house, emit)
                report["process_peak_mib"] = round(current.torch.cuda.max_memory_allocated() / 2**20, 2)
                report["cancel"] = {"status": "NOT_SUPPORTED_BY_CURRENT_ADAPTER"}
            else:
                if not args.runtime or not args.runtime.is_file() or not args.weights or not args.weights.is_file():
                    raise ValueError("GGUF arms require local runtime and weights files.")
                model, version, expected = PINS[args.arm]
                if digest(args.weights) != expected:
                    raise ValueError("GGUF SHA-256 does not match the pinned public artifact.")
                report.update(model=model, revision=version, weights_sha256=expected, runtime_sha256=digest(args.runtime))
                with LlamaRuntime(args.runtime, args.weights, args.out / "runtime.log", args.cpu_smoke) as local:
                    report["cold_ms"] = local.cold_ms
                    report["gpu_before_total_and_free_mib"] = local.gpu_before
                    strict = lambda c: local.generate(c.messages(), grammar=False)
                    grammar = lambda c: local.generate(c.messages(), grammar=True)
                    if args.cpu_smoke:
                        report["results"] = trial(cases[:1], {"grammar_cpu": grammar}, world, house, emit)
                    else:
                        report["results"] = trial(cases, {"strict": strict, "grammar": grammar}, world, house, emit)
                        report["schema_control"] = local.schema_probe()
                        if report["schema_control"] != {"strict": False, "grammar": True}:
                            report.update(status="UNVERIFIED_CONSTRAINT",
                                          reason="The negative control did not confirm exact schema enforcement.")
                        try:
                            report["cancel"] = local.cancel_probe()
                            retry = assess(cases[0], grammar(cases[0])["raw"], world, house)
                            report["cancel"]["followup_status"] = retry["status"]
                        except (LocalRuntimeError, OSError, http.client.HTTPException, ValueError) as exc:
                            report["cancel"] = {"status": "UNAVAILABLE", "reason": str(exc)[:180]}
                    report["allocation"] = local.allocation()
        if not args.cpu_smoke:
            measured = ["held_out" in arm for arm in report["results"].values()]
            if not all(measured):
                report.update(status="PARTIAL" if any(measured) else "SMOKE_ONLY",
                              reason="An arm produced no schema-valid response in smoke.")
        if args.cpu_smoke and report["results"]["grammar_cpu"]["smoke"]["schema_ok"] != 1:
            report.update(status="SMOKE_FAILED", reason="The CPU fallback did not produce a schema-valid response.")
    except KeyboardInterrupt:
        report.update(status="CANCELLED", reason="Interrupted locally; partial candidate receipts were kept.")
    except (LocalRuntimeError, OSError, RuntimeError, KeyError, TypeError, ValueError, ImportError) as exc:
        report.update(status="UNAVAILABLE", error_type=type(exc).__name__, reason=str(exc).splitlines()[0][:240])
    with (args.out / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "arm": args.arm, "results": report.get("results"),
                      "reason": report.get("reason"), "report": str(args.out / "report.json")}), flush=True)
    return {"MEASURED": 0, "CANCELLED": 130}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
