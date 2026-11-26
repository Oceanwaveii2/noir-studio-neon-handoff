"""Compare scoped reference ranking arms with local, pinned models."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import sqlite3
from statistics import mean, median
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prose_engine.guards import copy_issues
from prose_engine.voice.retrieval_experiment import (
    ARMS, FUNCTION_BOOST, FUSION_K, RERANK_CANDIDATES, SOURCE_USE, ExperimentIndex, parse_fixture,
)
from tools.eval_retrieval_ids import evaluate

MINILM_ID = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_REV = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
QWEN_ID = "Qwen/Qwen3-Reranker-0.6B"
QWEN_REV = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
RERANK_INSTRUCTION = (
    "Find an example of the same narrative technique and progression as the query. "
    "A shared topic or prop alone is insufficient."
)
QWEN_CONTEXT = 256
THREADS = 4
SEED = 60719


def file_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def local_snapshot(path: Path, revision: str, model: str) -> Path:
    path = path.resolve()
    if path.name != revision or not (path / "model.safetensors").is_file():
        raise ValueError(f"Use the pinned local {model} snapshot ({revision}).")
    return path


def duration_ms(since: int) -> float:
    return (perf_counter_ns() - since) / 1e6


class QwenReranker:
    """Score the publisher's yes/no classifier locally without generating text."""

    def __init__(self, path: Path, device: str):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = device
        self.torch = torch
        if device == "cuda":
            if not torch.cuda.is_available() or torch.cuda.mem_get_info()[0] < 3 * 1024**3:
                raise ValueError("The CUDA reranker requires at least 3 GiB free; use CPU or release other GPU work.")
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), padding_side="left",
                                                       local_files_only=True, trust_remote_code=False)
        self.dtype = torch.bfloat16 if device == "cuda" and torch.cuda.is_bf16_supported() else (
            torch.float16 if device == "cuda" else torch.float32
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            str(path), dtype=self.dtype, local_files_only=True, trust_remote_code=False, use_safetensors=True,
        ).to(device).eval()
        prefix = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
                  'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
                  '<|im_start|>user\n')
        suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        self.prefix = self.tokenizer.encode(prefix, add_special_tokens=False)
        self.suffix = self.tokenizer.encode(suffix, add_special_tokens=False)
        self.yes = self.tokenizer.convert_tokens_to_ids("yes")
        self.no = self.tokenizer.convert_tokens_to_ids("no")
        if not isinstance(self.yes, int) or not isinstance(self.no, int) or self.yes == self.no:
            raise ValueError("The reranker tokenizer does not expose distinct yes/no tokens.")
        self.truncated_pairs = 0

    def __call__(self, query: str, passages: list[str]) -> list[float]:
        prompts = [f"<Instruct>: {RERANK_INSTRUCTION}\n<Query>: {query}\n<Document>: {doc}" for doc in passages]
        inputs = self.tokenizer(prompts, padding=False, add_special_tokens=False, return_attention_mask=False)
        limit = QWEN_CONTEXT - len(self.prefix) - len(self.suffix)
        self.truncated_pairs += sum(len(ids) > limit for ids in inputs["input_ids"])
        padded = self.tokenizer.pad({"input_ids": [self.prefix + ids[:limit] + self.suffix
                                                    for ids in inputs["input_ids"]]},
                                    padding=True, return_attention_mask=True, return_tensors="pt").to(self.device)
        with self.torch.inference_mode():
            logits = self.model(**padded, use_cache=False, logits_to_keep=1).logits[:, -1, :].float()
            return (logits[:, self.yes] - logits[:, self.no]).cpu().tolist()


def warm_times(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"count": len(samples), "p50_ms": round(median(samples), 3),
            "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3)}


def evaluate_arm(index, arm, queries, labels, repeats, reranker) -> dict:
    results, samples, divergences = {}, [], set()
    for q in queries[:3]:
        index.rank(arm, q, reranker)
    for trial in range(repeats):
        order = list(queries)
        random.Random(SEED + trial).shuffle(order)
        for q in order:
            start = perf_counter_ns()
            found = index.rank(arm, q, reranker)
            samples.append(duration_ms(start))
            if trial == 0:
                results[q.id] = found
            elif results[q.id] != found:
                divergences.add(q.id)
    copy_controls = query_overlap = ranking_leaks = 0
    copy_trials = 0
    groups = defaultdict(list)
    for q in queries:
        selected = results[q.id]
        invalid = [p for p in selected if p not in index.eligible or index.eligible[p].edition != q.edition]
        ranking_leaks += len(invalid)
        if invalid:
            continue
        refs = [index.eligible[rid].text for rid in selected]
        if refs:
            copy_trials += 1
            # Inject a verbatim source passage as a fake draft. The query
            # overlap probe measures input similarity; neither is generation.
            copy_controls += bool(copy_issues(refs[0], refs))
            query_overlap += bool(copy_issues(q.text, refs))
        groups[q.edition].append(q.id)
    if ranking_leaks:
        raise RuntimeError(f"{arm}: a ranking crossed a rights or edition boundary.")
    scored = evaluate({q.id: labels[q.id] for q in queries}, results)
    return {
        "status": "MEASURED", **scored, "ranked_ids": results, "warm_latency": warm_times(samples),
        "rank_divergent_queries": len(divergences), "policy_leaks": ranking_leaks,
        "copy_probe": {"verbatim_caught": copy_controls, "verbatim_tests": copy_trials,
                       "queries_flagged_for_source_overlap": query_overlap},
        "by_edition": {edition: {
            "queries": len(ids),
            "recall_at_5": mean(scored["per_query"][qid]["recall_at_5"] for qid in ids),
            "ndcg_at_5": mean(scored["per_query"][qid]["ndcg_at_5"] for qid in ids),
        } for edition, ids in groups.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "eval/u6_reference_fixture.json")
    parser.add_argument("--minilm", type=Path, required=True, help="Pinned local MiniLM snapshot")
    parser.add_argument("--reranker", type=Path, help="Pinned local Qwen3-Reranker-0.6B snapshot")
    parser.add_argument("--rerank-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True, help="New ID-only JSON report")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5 or args.out.exists():
        parser.error("Use 1–5 timing passes and a new output file.")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    try:
        from sentence_transformers import SentenceTransformer
        import torch

        torch.set_num_threads(THREADS)
        data = json.loads(args.fixture.read_text(encoding="utf-8"))
        documents, queries, editions, labels = parse_fixture(data)
        held_out = sorted((q for q in queries if editions[q.edition] == "held_out"), key=lambda q: q.id)
        dev = [q for q in queries if editions[q.edition] == "development"]
        if not 30 <= len(held_out) <= 50 or len({q.edition for q in held_out}) < 3 or not dev:
            raise ValueError("Use 30–50 held-out queries across at least three editions and a separate development set.")
        mini_path = local_snapshot(args.minilm, MINILM_REV, MINILM_ID)
        start = perf_counter_ns()
        minilm = SentenceTransformer(str(mini_path), device="cpu", local_files_only=True, trust_remote_code=False)
        mini_load = duration_ms(start)

        def encode(texts):
            return minilm.encode(texts, batch_size=64, convert_to_numpy=True,
                                 normalize_embeddings=True, show_progress_bar=False)

        start = perf_counter_ns()
        index = ExperimentIndex(documents, encode)
        build_ms = duration_ms(start)
        models = {"minilm": {"model": MINILM_ID, "revision": MINILM_REV,
                             "weights_sha256": file_hash(mini_path / "model.safetensors"),
                             "device": "cpu", "load_ms": round(mini_load, 2)}}
        arms = {}
        try:
            for arm in ARMS[:-1]:
                arms[arm] = evaluate_arm(index, arm, held_out, labels, args.repeats, None)
                print(f"{arm}: held-out Recall@5 {arms[arm]['mean_recall_at_5']:.3f}", flush=True)
            if args.reranker:
                qwen_path = local_snapshot(args.reranker, QWEN_REV, QWEN_ID)
                start = perf_counter_ns()
                reranker = QwenReranker(qwen_path, args.rerank_device)
                models["reranker"] = {"model": QWEN_ID, "revision": QWEN_REV,
                                      "weights_sha256": file_hash(qwen_path / "model.safetensors"),
                                      "device": args.rerank_device, "dtype": str(reranker.dtype),
                                      "load_ms": round(duration_ms(start), 2)}
                if args.rerank_device == "cuda":
                    torch.cuda.reset_peak_memory_stats()
                arms["qwen_rerank"] = evaluate_arm(index, "qwen_rerank", held_out, labels, args.repeats, reranker)
                models["reranker"]["truncated_pairs_including_warmup"] = reranker.truncated_pairs
                if args.rerank_device == "cuda":
                    models["reranker"]["peak_process_allocated_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
                    models["reranker"]["gpu"] = torch.cuda.get_device_name()
                print(f"qwen_rerank: held-out Recall@5 {arms['qwen_rerank']['mean_recall_at_5']:.3f}", flush=True)
            else:
                arms["qwen_rerank"] = {"status": "NOT_RUN", "reason": "No local reranker snapshot was provided."}
        finally:
            index.close()
        baseline = arms["minilm"]["mean_recall_at_5"]
        deltas = {arm: {
            "recall_at_5_minus_minilm": arms[arm]["mean_recall_at_5"] - baseline,
            "passes_synthetic_recall_target": arms[arm]["mean_recall_at_5"] - baseline >= 0.10,
            "passes_synthetic_latency_target": arms[arm]["warm_latency"]["p95_ms"] <= (
                1000 if arm == "qwen_rerank" else 300),
        } for arm in ARMS[2:] if arms[arm]["status"] == "MEASURED"}
        report = {
            "schema_version": 1, "fixture_sha256": file_hash(args.fixture), "fixture_kind": "original_synthetic",
            "held_out_queries": len(held_out), "development_queries_excluded": len(dev),
            "held_out_without_function_tag": sum(q.function is None for q in held_out),
            "passages": len(documents), "eligible_passages": len(index.eligible),
            "rights_exclusions_before_index": len(documents) - len(index.eligible),
            "settings": {"fusion_k": FUSION_K, "function_boost": FUNCTION_BOOST,
                         "rerank_candidates": RERANK_CANDIDATES, "rerank_context": QWEN_CONTEXT,
                         "seed": SEED, "repeats": args.repeats, "torch_cpu_threads": THREADS,
                         "sqlite": sqlite3.sqlite_version,
                         "packages": {name: importlib.metadata.version(name)
                                      for name in ("sentence-transformers", "transformers", "torch", "numpy")}},
            "models": models, "scratch_index_build_ms": round(build_ms, 2),
            "source_use": {key: sorted(value) for key, value in SOURCE_USE.items()},
            "arms": arms, "compared_with_minilm": deltas,
            "production_promotion": "KEEP_CURRENT_INDEX",
            "limits": [
                "Original synthetic texts and desk judgments; the private book corpus and manuscript were not ranked.",
                "All arms share rights and edition restrictions. Recall and timing are fixture results, not production benchmarks.",
                "Function tags are supplied metadata, not inferred labels.",
                "Copy probes are not generation outcomes; prose copying and named author preference were not measured.",
            ],
        }
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if any(p.text in rendered for p in documents) or any(q.text in rendered for q in queries):
            raise RuntimeError("Report would expose passage or query text.")
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
        print(f"ID-only report: {args.out}", flush=True)
        return 0
    except (OSError, RuntimeError, TypeError, AttributeError, KeyError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"U6 comparison unavailable: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
