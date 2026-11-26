"""
Build contrast pairs for the style vector: corpus passages and the model's neutral rewrites.

    python tools/build_pairs.py --pairs 30 --out books/style_pairs.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

PLAIN = "Rewrite this passage in plain, neutral, contemporary prose. Return only the paragraph."


def load_model(name: str):
    tokenizer = AutoTokenizer.from_pretrained(name)
    config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(name, quantization_config=config, device_map={"": 0})
    model.eval()
    return model, tokenizer


def generate(model, tokenizer, text: str) -> str:
    prompt = f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output = model.generate(
            **inputs, max_new_tokens=220, do_sample=True, temperature=0.9, top_p=0.9,
            repetition_penalty=1.05, pad_token_id=tokenizer.eos_token_id,
        )
    return tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--pairs", type=int, default=30)
    parser.add_argument("--out", default="books/style_pairs.jsonl")
    args = parser.parse_args()

    from prose_engine.embedding_store import load_index

    index = load_index("books/vector_index.joblib")
    candidates = [text for text in index.texts if 300 < len(text) < 700]
    step = max(1, len(candidates) // args.pairs)
    chosen = candidates[::step][: args.pairs]

    model, tokenizer = load_model(args.model)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("w", encoding="utf-8") as handle:
        for position, passage in enumerate(chosen, 1):
            neutral = generate(model, tokenizer, f"{PLAIN}\n\n{passage}")
            if not neutral:
                continue
            handle.write(json.dumps({"corpus": passage, "neutral": neutral}) + "\n")
            written += 1
            print(f"{position}/{len(chosen)} pair written ({len(neutral.split())} words)")
    print(f"written: {target} ({written} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
