"""
GPU calibration for the style vector.

    python tools/calibrate_steering.py --model Qwen/Qwen3.5-9B --pairs 6

For each alpha: generate a rewrite of the eval paragraph with the steering hook, then report
corpus similarity, style distance and tics. Writes reports/steering_calibration.json.
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

PLAIN = "Rewrite this passage in plain, neutral, contemporary prose. Return only the paragraph."


def load_model(name: str):
    tokenizer = AutoTokenizer.from_pretrained(name)
    config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        name, quantization_config=config, device_map={"": 0}
    )
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
                **inputs, max_new_tokens=220, do_sample=True, temperature=0.85,
                top_p=0.9, repetition_penalty=1.05, pad_token_id=tokenizer.eos_token_id,
            )
    return tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--pairs", type=int, default=6)
    parser.add_argument("--pairs-file", default=None)
    parser.add_argument("--layer", type=int, default=14)
    parser.add_argument("--alphas", default="0,0.5,1.0,1.5")
    parser.add_argument("--file", default="work/familyguy/before.md")
    parser.add_argument("--out", default="reports/steering_calibration.json")
    args = parser.parse_args()

    model, tokenizer = load_model(args.model)
    evaluator = Evaluator(books="books")
    eval_text = next(
        p.strip()
        for p in Path(args.file).read_text(encoding="utf-8").split("\n\n")
        if p.startswith("The next noise")
    )

    if args.pairs_file:
        pairs = []
        for line in Path(args.pairs_file).read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("corpus") and entry.get("neutral"):
                pairs.append((entry["corpus"], entry["neutral"]))
    else:
        from prose_engine.embedding_store import load_index

        index = load_index("books/vector_index.joblib")
        sample = [text for text in index.texts if 200 < len(text) < 600][: args.pairs]
        pairs = []
        for passage in sample:
            neutral = generate(model, tokenizer, f"{PLAIN}\n\n{passage}")
            if neutral:
                pairs.append((passage, neutral))
    print(f"pairs: {len(pairs)}")

    vector = extract(model, tokenizer, pairs, layer=args.layer)
    vector.save("voice/style_vector.npz")

    style_model = load_style_model("books")
    base_distance = style_distance(fingerprint(eval_text), style_model) if style_model else 0.0
    rows = []
    for alpha in [float(value) for value in args.alphas.split(",")]:
        text = eval_text if alpha == 0 else generate(model, tokenizer, eval_text, vector, alpha, args.layer)
        distance = style_distance(fingerprint(text), style_model) if style_model else 0.0
        rows.append(
            {
                "alpha": alpha,
                "similarity": round(evaluator.similarity(text), 4),
                "percentile": round(evaluator.percentile(text), 3),
                "style": round(distance, 3),
                "style_delta": round(distance - base_distance, 3),
                "tics": counts(text),
                "words": len(text.split()),
            }
        )
        print(f"alpha={alpha}: sim={rows[-1]['similarity']} pct={rows[-1]['percentile']} "
              f"style={rows[-1]['style']} words={rows[-1]['words']}")

    report = {
        "model": args.model,
        "layer": args.layer,
        "pairs": len(pairs),
        "base_style": round(base_distance, 3),
        "rows": rows,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
