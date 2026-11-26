"""
Steering calibration v2: length-matched pairs and a layer sweep.

The first attempt used pairs whose corpus and neutral sides differed in length, so the direction
learned formatting rather than voice. This version keeps only pairs within a length band, sweeps
layers 10-18 and three alphas, and reports similarity, style distance and tics per setting.

    python tools/calibrate_steering_v2.py --pairs-file books/style_pairs.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from prose_engine.styleprint import distance as style_distance, fingerprint, load_model as load_style_model
from prose_engine.voice.evaluate import Evaluator
from prose_engine.voice.style_vector import StyleHook, extract
from prose_engine.voice.tics import counts

EVAL_PARAGRAPHS = ["work/familyguy/paragraph.md", "work/humanize/before.md", "work/eval_narration.md"]


def load_model(name: str):
    tokenizer = AutoTokenizer.from_pretrained(name)
    config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(name, quantization_config=config, device_map={"": 0})
    model.eval()
    return model, tokenizer


def generate(model, tokenizer, text: str, vector=None, alpha: float = 0.0, layer: int = 14) -> str:
    prompt = f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    hook = (
        StyleHook(model, vector.vector if vector is not None else np.zeros(1), layer, alpha, first_k=32)
        if alpha and vector is not None
        else nullcontext()
    )
    with hook:
        with torch.no_grad():
            output = model.generate(
                **inputs, max_new_tokens=200, do_sample=True, temperature=0.85, top_p=0.9,
                repetition_penalty=1.05, pad_token_id=tokenizer.eos_token_id,
            )
    return tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def load_pairs(path: str, low: float = 0.75, high: float = 1.35):
    pairs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        corpus, neutral = entry.get("corpus", ""), entry.get("neutral", "")
        if not corpus or not neutral:
            continue
        ratio = len(neutral.split()) / max(1, len(corpus.split()))
        if low <= ratio <= high:
            pairs.append((corpus, neutral))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--pairs-file", default="books/style_pairs.jsonl")
    parser.add_argument("--layers", default="10,12,14,16,18")
    parser.add_argument("--alphas", default="0.5,1.0,1.5")
    parser.add_argument("--evals", type=int, default=2)
    parser.add_argument("--out", default="reports/steering_v2.json")
    args = parser.parse_args()

    pairs = load_pairs(args.pairs_file)
    if len(pairs) < 8:
        raise SystemExit(f"not enough length-matched pairs: {len(pairs)}")
    print(f"length-matched pairs: {len(pairs)}")

    model, tokenizer = load_model(args.model)
    evaluator = Evaluator(books="books")
    style_model = load_style_model("books")
    profiles = [counts(Path(name).read_text(encoding="utf-8")) for name in EVAL_PARAGRAPHS]
    baseline = {
        "similarity": round(sum(evaluator.similarity(Path(n).read_text(encoding="utf-8")) for n in EVAL_PARAGRAPHS) / len(EVAL_PARAGRAPHS), 4),
        "style": round(style_distance(fingerprint(Path(EVAL_PARAGRAPHS[0]).read_text(encoding="utf-8")), style_model), 3),
    }
    print("baseline:", baseline)

    rows = []
    for layer in [int(value) for value in args.layers.split(",")]:
        vector = extract(model, tokenizer, pairs[:24], layer=layer)
        for alpha in [float(value) for value in args.alphas.split(",")]:
            sims, styles, tic_totals = [], [], 0
            for name in EVAL_PARAGRAPHS[: args.evals]:
                source = Path(name).read_text(encoding="utf-8").strip()
                text = generate(model, tokenizer, source, vector, alpha, layer)
                sims.append(evaluator.similarity(text))
                styles.append(style_distance(fingerprint(text), style_model))
                tic_totals += sum(counts(text).values())
            rows.append(
                {
                    "layer": layer,
                    "alpha": alpha,
                    "similarity": round(float(np.mean(sims)), 4),
                    "style": round(float(np.mean(styles)), 3),
                    "tics": tic_totals,
                }
            )
            print(f"layer {layer} alpha {alpha}: sim {rows[-1]['similarity']} style {rows[-1]['style']} tics {tic_totals}")

    gain = lambda row: (row["similarity"] - baseline["similarity"]) - 0.05 * (row["style"] - baseline["style"])
    best = max(rows, key=gain)
    vector = extract(model, tokenizer, pairs[:24], layer=int(best["layer"]))
    vector.alpha = float(best["alpha"])
    vector.save("voice/style_vector_v2.npz")

    report = {
        "model": args.model,
        "pairs": len(pairs),
        "baseline": baseline,
        "rows": rows,
        "best": best,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"best: layer {best['layer']} alpha {best['alpha']} | written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
