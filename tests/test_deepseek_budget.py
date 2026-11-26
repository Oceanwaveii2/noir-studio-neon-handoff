"""DeepSeek provider: request shape, token accounting, and the spend guard."""

import json
import tempfile
import unittest
from pathlib import Path

from prose_engine.providers.deepseek import BudgetExceeded, DeepSeekProvider


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        return self.responses.pop(0)


def response(text="ok", prompt=10, completion=5):
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


class DeepSeekTests(unittest.TestCase):
    def test_request_shape_and_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "usage.jsonl"
            transport = Transport([response("rewritten")])
            provider = DeepSeekProvider(api_key="test", transport=transport, ledger=ledger)
            result = provider.generate_rewrite(None, "prompt text")
            self.assertEqual(result, "rewritten")
            payload = transport.payloads[0]
            self.assertEqual(payload["model"], "deepseek-chat")
            self.assertIn("max_tokens", payload)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(provider.tokens, 15)
            row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["tokens"], 15)

    def test_call_budget_stops_before_spending(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeepSeekProvider(
                api_key="test", transport=Transport([response()]), ledger=Path(tmp) / "u.jsonl",
                max_calls=1, budget_tokens=1000,
            )
            provider.generate_rewrite(None, "one")
            with self.assertRaises(BudgetExceeded):
                provider.generate_rewrite(None, "two")

    def test_token_budget_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeepSeekProvider(
                api_key="test", transport=Transport([response(prompt=100, completion=100), response()]),
                ledger=Path(tmp) / "u.jsonl", max_calls=5, budget_tokens=150,
            )
            provider.generate_rewrite(None, "one")
            with self.assertRaises(BudgetExceeded):
                provider.generate_rewrite(None, "two")


if __name__ == "__main__":
    unittest.main()
