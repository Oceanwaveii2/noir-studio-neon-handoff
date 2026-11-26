import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

model_id = "Qwen/Qwen2.5-0.5B-Instruct"
config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
tokenizer = AutoTokenizer.from_pretrained(model_id)
model = AutoModelForCausalLM.from_pretrained(
    model_id, quantization_config=config, device_map={"": 0}
)
print("4-bit load ok | first param dtype:", next(model.parameters()).dtype)
inputs = tokenizer("Say hello in five words.", return_tensors="pt").to("cuda")
out = model.generate(**inputs, max_new_tokens=20)
print(tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True))
