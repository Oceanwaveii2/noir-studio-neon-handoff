"""
Build an appearance canon from a reference image with Qwen3.5 (image-text-to-text).

    python tools/build_appearance.py --image images/rainee_peter.png --entity rainee

Writes appearances/<entity>.json, hash-pinned to the image. Review and edit the JSON; the story
gates read that file, never the image.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3_5ForConditionalGeneration

from prose_engine.voice.appearance import PROMPT, parse_schema


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--entity", required=True)
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    processor = AutoProcessor.from_pretrained(args.model)
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        args.model,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16
        ),
        device_map={"": 0},
    ).eval()

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(image_path)},
                {"type": "text", "text": PROMPT},
            ],
        }
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=text, images=[str(image_path)], return_tensors="pt").to(model.device)
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=400, do_sample=False)
    reply = processor.decode(output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)

    appearance = parse_schema(reply, entity=args.entity, image=str(image_path))
    target = Path(args.out) if args.out else Path("appearances") / f"{args.entity}.json"
    appearance.save(target)
    print(appearance.prompt_block())
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
