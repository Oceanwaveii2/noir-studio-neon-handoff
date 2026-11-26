import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

tokenizer = AutoTokenizer.from_pretrained(MODEL)
device = "cuda" if torch.cuda.is_available() else "cpu"
dtype = torch.float16 if device == "cuda" else torch.float32
model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=dtype).to(device)
model.eval()

messages = [
    {"role": "system", "content": "You are a line editor. Rewrite the paragraph. Return only the paragraph."},
    {
        "role": "user",
        "content": (
            "Rewrite this screenplay action line so it is physical and specific, keeping the facts: "
            "'She was angry.'"
        ),
    },
]
prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(prompt, return_tensors="pt").to(device)

for run in range(3):
    start = time.perf_counter()
    output = model.generate(
        **inputs,
        max_new_tokens=80,
        do_sample=True,
        temperature=0.8,
        top_p=0.9,
        pad_token_id=tokenizer.eos_token_id,
    )
    elapsed = time.perf_counter() - start
    generated = output[0][inputs["input_ids"].shape[1] :]
    new_tokens = len(generated)
    print(f"run {run}: {new_tokens} tokens in {elapsed:.1f}s = {new_tokens / elapsed:.1f} tok/s")
    print(tokenizer.decode(generated, skip_special_tokens=True))
