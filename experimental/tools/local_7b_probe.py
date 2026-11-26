import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL = "Qwen/Qwen2.5-7B-Instruct"
config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16, bnb_4bit_quant_type="nf4")
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=config, device_map={"": 0})
model.eval()
print("loaded", MODEL)

messages = [
    {"role": "system", "content": "You are a line editor. Return only the rewritten paragraph."},
    {"role": "user", "content": "Rewrite in one sentence, keeping the facts: 'She was angry and left the room.'"},
]
prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(prompt, return_tensors="pt").to("cuda")

for run in range(2):
    start = time.perf_counter()
    out = model.generate(**inputs, max_new_tokens=60, do_sample=True, temperature=0.8, top_p=0.9)
    elapsed = time.perf_counter() - start
    new = out[0][inputs["input_ids"].shape[1]:]
    print(f"run {run}: {len(new)} tokens in {elapsed:.1f}s = {len(new)/elapsed:.1f} tok/s")
    print(tokenizer.decode(new, skip_special_tokens=True).strip())
print("VRAM GB:", round(torch.cuda.max_memory_allocated() / 1e9, 1))
