"""
Local transformers provider: runs a small instruct model on this machine (GPU if available).

No API, no network after the model is downloaded. Used to generate rewrite candidates that the
vector index then ranks.
"""

from __future__ import annotations

import os
from typing import Optional

from ..models import ProseRewriteRequest
from .base import BaseProseProvider

DEFAULT_LOCAL_MODEL = "Qwen/Qwen3.5-9B"
SYSTEM_PROMPT = (
    "You are a screenwriter doing a line edit. Rewrite the paragraph so it is physical and "
    "specific, keeps every fact, character and line of dialogue, and matches the voice of the "
    "reference passages. Return only the rewritten paragraph, no preamble."
)


class LocalTransformersProvider(BaseProseProvider):
    name = "local"

    def __init__(
        self,
        model_name: str = DEFAULT_LOCAL_MODEL,
        max_new_tokens: int = 512,
        temperature: float = 0.85,
        load_in_4bit: Optional[bool] = None,
        steer_path: Optional[str] = None,
        steer_alpha: float = 0.0,
        steer_layer: Optional[int] = None,
        ban_comparisons: bool = False,
        **_: object,
    ):
        super().__init__(model_name=model_name)
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.steer_path = steer_path
        self.steer_alpha = float(steer_alpha)
        self.steer_layer = steer_layer
        self.ban_comparisons = ban_comparisons
        # Default on when a GPU is present; set PROSE_LOCAL_4BIT=0 to force fp16.
        self.load_in_4bit = (
            (os.getenv("PROSE_LOCAL_4BIT", "1") != "0")
            if load_in_4bit is None
            else load_in_4bit
        )
        self._tokenizer = None
        self._model = None
        self.device = "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        if self.device == "cuda" and self.load_in_4bit:
            from transformers import BitsAndBytesConfig

            config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                self.model_name, quantization_config=config, device_map={"": 0}
            ).eval()
            return

        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self._model = (
            AutoModelForCausalLM.from_pretrained(self.model_name, torch_dtype=dtype)
            .to(self.device)
            .eval()
        )

    def _steer_context(self):
        from contextlib import nullcontext

        if not self.steer_path or not self.steer_alpha:
            return nullcontext()
        from ..voice.style_vector import StyleHook, StyleVector

        vector = StyleVector.load(self.steer_path)
        layer = self.steer_layer if self.steer_layer is not None else vector.layer
        return StyleHook(self._model, vector.vector, layer, self.steer_alpha, first_k=32)

    def _logit_processors(self, prompt_length: int):
        if not self.ban_comparisons:
            return None
        from ..voice.logit_rules import BannedPhraseProcessor

        return [
            BannedPhraseProcessor(
                self._tokenizer, ["like", "as if", "resembling"], prompt_length=prompt_length
            )
        ]

    def generate_rewrite(self, request: ProseRewriteRequest, prompt: str) -> str:
        import torch

        self._load()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        try:
            text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        inputs = self._tokenizer(text, return_tensors="pt").to(self.device)
        prompt_length = inputs["input_ids"].shape[1]
        with self._steer_context():
            with torch.inference_mode():
                output = self._model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=True,
                    temperature=self.temperature,
                    top_p=0.9,
                    repetition_penalty=1.05,
                    pad_token_id=self._tokenizer.eos_token_id,
                    logits_processor=self._logit_processors(prompt_length),
                )
        generated = output[0][inputs["input_ids"].shape[1] :]
        return self._tokenizer.decode(generated, skip_special_tokens=True).strip()

    def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        fake = ProseRewriteRequest(
            request_id="local",
            project_id="prose_engine",
            document_id="document",
            base_revision=1,
            target_span_id="span",
            original_text="",
        )
        return self.generate_rewrite(fake, prompt)
