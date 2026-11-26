"""
Decoding-time rules: ban surface markers so the model cannot reach for them.

The processor suppresses the *next token* when the generated prefix already matches the start of
a banned phrase. It is a hard constraint, not a suggestion; alpha-level style control is the other
module.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

try:
    from transformers import LogitsProcessor
except Exception:  # pragma: no cover
    class LogitsProcessor:  # type: ignore
        pass


class BannedPhraseProcessor(LogitsProcessor):
    def __init__(self, tokenizer, phrases: Sequence[str], prompt_length: int = 0):
        self.tokenizer = tokenizer
        self.prompt_length = prompt_length
        self.sequences: List[List[int]] = []
        self.single: set[int] = set()
        for phrase in phrases:
            for variant in (phrase, " " + phrase):
                ids = tokenizer.encode(variant, add_special_tokens=False)
                if ids and ids not in self.sequences:
                    self.sequences.append(list(ids))
                    if len(ids) == 1:
                        self.single.add(ids[0])

    def _banned_next(self, prefix: Sequence[int]) -> List[int]:
        banned = []
        for sequence in self.sequences:
            length = len(sequence)
            if length < 2:
                continue
            for start in range(max(0, len(prefix) - length + 1), len(prefix)):
                tail = list(prefix[start:])
                if len(tail) < length and sequence[: len(tail)] == tail:
                    banned.append(sequence[len(tail)])
        return banned

    def __call__(self, input_ids, scores):
        for row in range(input_ids.shape[0]):
            prefix = input_ids[row].tolist()
            if len(prefix) <= self.prompt_length:
                continue
            banned = set(self.single) | set(self._banned_next(prefix))
            for token in banned:
                if 0 <= token < scores.shape[-1]:
                    scores[row, token] = float("-inf")
        return scores


def ban_comparisons(tokenizer, prompt_length: int = 0) -> BannedPhraseProcessor:
    return BannedPhraseProcessor(tokenizer, ["like", "as if", "resembling"], prompt_length)
