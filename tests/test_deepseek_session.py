"""DeepSeek session provider: injected handler, call budget, no stored credentials."""

import tempfile
import unittest
from pathlib import Path

from prose_engine.providers.deepseek import BudgetExceeded
from prose_engine.providers.deepseek_session import DeepSeekSessionProvider


class Handler:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


class SessionTests(unittest.TestCase):
    def test_handler_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = Handler(["rewritten beat"])
            provider = DeepSeekSessionProvider(session_handler=handler, ledger=Path(tmp) / "u.jsonl")
            self.assertEqual(provider.generate_rewrite(None, "prompt"), "rewritten beat")
            self.assertEqual(handler.prompts, ["prompt"])

    def test_call_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeepSeekSessionProvider(
                session_handler=Handler(["a"]), ledger=Path(tmp) / "u.jsonl", max_calls=1
            )
            provider.generate_rewrite(None, "one")
            with self.assertRaises(BudgetExceeded):
                provider.generate_rewrite(None, "two")

    def test_missing_handler_is_a_clear_error(self):
        import os

        previous = os.environ.pop("DEEPSEEK_SESSION_HANDLER", None)
        try:
            with self.assertRaises(ValueError):
                DeepSeekSessionProvider()
        finally:
            if previous is not None:
                os.environ["DEEPSEEK_SESSION_HANDLER"] = previous


if __name__ == "__main__":
    unittest.main()
