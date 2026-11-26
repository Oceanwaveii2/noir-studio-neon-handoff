"""Unit tests for release_tests module discovery, sharding, and output formatting."""
import unittest

from tools.release_tests import (
    _format_failure_details,
    discover_modules,
    partition_modules,
)


class ReleaseTestShardingTests(unittest.TestCase):
    def test_partition_keeps_shared_workspace_modules_in_single_shard(self):
        modules, omitted = discover_modules(include_models=False)
        self.assertEqual(set(omitted), {"tests.test_coprocessor_reranker", "tests.test_voice_steer"})
        shards = partition_modules(modules, workers=6)
        self.assertGreater(len(shards), 1)
        flat = [m for shard in shards for m in shard]
        self.assertEqual(len(flat), len(modules))
        self.assertEqual(set(flat), set(modules))

        shared_shards = [
            shard for shard in shards
            if any(m.startswith("tests.test_prose_engine_") or m in {"tests.test_coprocessor_harness", "tests.test_s7_budget"} for m in shard)
        ]
        self.assertEqual(len(shared_shards), 1)

    def test_partition_single_worker_keeps_single_shard(self):
        modules = ["tests.test_a", "tests.test_prose_engine_x", "tests.test_b"]
        self.assertEqual(partition_modules(modules, workers=1), [modules])

    def test_format_failure_details_strips_worker_footer(self):
        raw = (
            "...F\n"
            "======================================================================\n"
            "FAIL: test_one\n"
            "----------------------------------------------------------------------\n"
            "Traceback...\n"
            "\n"
            "----------------------------------------------------------------------\n"
            "Ran 10 tests in 1.234s\n\n"
            "FAILED (failures=1)\n"
        )
        cleaned = _format_failure_details(raw)
        self.assertIn("FAIL: test_one", cleaned)
        self.assertNotIn("Ran 10 tests", cleaned)


if __name__ == "__main__":
    unittest.main()
