"""Regression cases for the import boundary that the local CI enforces."""

import json
import tempfile
import unittest
from pathlib import Path

from tools.check_architecture import MAP, check


class ArchitectureCheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for package in ("graph", "prose", "studio"):
            (self.root / package).mkdir()
        self.map = self.root / MAP
        self.map.parent.mkdir(parents=True)
        self.modules = [
            {"id": "graph", "path": "graph", "layer": 1, "dependencies": []},
            {"id": "prose", "path": "prose", "layer": 2, "dependencies": ["graph"]},
            {"id": "studio", "path": "studio", "layer": 3, "dependencies": ["prose"]},
        ]
        self.save_map()

    def save_map(self, legacy_imports=()):
        self.map.write_text(
            json.dumps({"modules": self.modules, "legacy_imports": legacy_imports}), encoding="utf-8"
        )

    def test_allows_documented_direction_and_ignores_comments_and_strings(self):
        (self.root / "prose" / "operation.py").write_text(
            'from graph.state import State\n# import studio\nexample = "import studio"\n',
            encoding="utf-8",
        )
        count, edges, violations = check(self.root)
        self.assertEqual((count, edges, violations), (1, {("prose", "graph"): 1}, []))

    def test_reports_reverse_import_even_inside_a_function(self):
        (self.root / "graph" / "operation.py").write_text(
            "def action():\n    import json, studio.shell as shell\n", encoding="utf-8",
        )
        _, _, violations = check(self.root)
        self.assertEqual(violations, ["graph/operation.py:2: graph -> studio is not declared"])

    def test_rejects_undeclared_shortcut_between_lower_layers(self):
        (self.root / "studio" / "shell.py").write_text("from graph import state\n", encoding="utf-8")
        _, _, violations = check(self.root)
        self.assertEqual(violations, ["studio/shell.py:1: studio -> graph is not declared"])

    def test_rejects_a_map_that_would_legalize_a_reverse_dependency(self):
        self.modules[0]["dependencies"] = ["studio"]
        self.save_map()
        with self.assertRaisesRegex(ValueError, "known, lower layer"):
            check(self.root)

    def test_legacy_exception_only_applies_to_the_named_file_and_import(self):
        self.save_map([{"source": "graph/legacy.py", "import": "studio.shell", "gap": "CASE-001"}])
        (self.root / "graph" / "legacy.py").write_text(
            "import studio.shell\nimport studio.other\n", encoding="utf-8",
        )
        (self.root / "graph" / "new.py").write_text("import studio.shell\n", encoding="utf-8")
        _, _, violations = check(self.root)
        self.assertEqual(violations, [
            "graph/legacy.py:2: graph -> studio is not declared",
            "graph/new.py:1: graph -> studio is not declared",
        ])
