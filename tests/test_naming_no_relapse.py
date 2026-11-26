"""No-relapse CI tripwire tests for ProseCore / CharStudio naming & path discipline."""

from __future__ import annotations

import ast
import json
import os
import re
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest import mock

from prose_engine import paths as prose_paths

SCAN_DIRS = (
    "prose_engine",
    "story_graph",
    "telemetry",
    "tools",
    "tests",
    "experimental",
)

RE_BANNED_REFS = re.compile(
    r"H:[/\\]+AI Work|D:[/\\]+0(?:[/\\]|$)|scatter graph engine|rednote[-_]scatter|"
    r"rns_paths|rns-layout\.json|rns_backend|rns_kernel|rns_harvester|"
    r"01_Mining_App|RedScatter_Clean_Rebuild|RedNote_Engine|RedNote_Browser|"
    r"Red Note Gemini|\b50307\b|\b50308\b|\b50309\b|"
    r"[/\\]narrative[ _]engine|narrative[ _]engine[/\\]",
    re.I,
)
RE_WINDOWS_DRIVE = re.compile(r"(?<![A-Za-z0-9_])(?:[A-Za-z]:\\|[C-Zc-z]:/(?!/))", re.I)

EXPECTED_WINDOWS_DRIVE_PY_FILES = frozenset(
    {
        "tests/test_library_indexes.py",
        "tools/build_foxy_reader.py",
        "tools/build_reader.py",
        "tools/extract_pulp_script.py",
        "tools/extract_typed_draft.py",
        "tools/package_scene.py",
        "tools/scene_map.py",
    }
)


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                ids.add(id(first.value))
    return ids


class TestNamingNoRelapse(unittest.TestCase):
    """Ensure ProseCore never relapses to hardcoded drive roots, spaces-in-code paths, or RNS names."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]

    def test_workspace_identity_beacon(self) -> None:
        identity_file = self.root / "WORKSPACE_IDENTITY.json"
        self.assertTrue(identity_file.is_file(), f"Missing {identity_file}")
        data = json.loads(identity_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "agy.workspace-identity/1")
        self.assertEqual(data.get("canonical_id"), "PROSE")
        self.assertEqual(data.get("product_name"), "ProseCore")
        self.assertEqual(data.get("target_folder_name"), "narrative-engine")
        self.assertEqual(data.get("current_folder_name"), "narrative-engine")
        self.assertEqual(self.root.name, "narrative-engine")

    def test_prose_paths_cwd_independent_and_honors_env_override(self) -> None:
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                with mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("PROSE_ROOT", None)
                    self.assertEqual(prose_paths.root().resolve(), self.root.resolve())
                    self.assertEqual(
                        prose_paths.books("sub", "book.txt").resolve(),
                        (self.root / "books" / "sub" / "book.txt").resolve(),
                    )
                    self.assertEqual(
                        prose_paths.asset("packs", "sample.json").resolve(),
                        (self.root / "packs" / "sample.json").resolve(),
                    )

                override = Path(tmpdir) / "custom_prose"
                with mock.patch.dict(os.environ, {"PROSE_ROOT": str(override)}):
                    self.assertEqual(prose_paths.root(), override)
                    self.assertEqual(prose_paths.books("a.txt"), override / "books" / "a.txt")
            finally:
                os.chdir(orig_cwd)

    def test_ast_zero_relapse_and_cross_repo_isolation(self) -> None:
        self_rel = Path(__file__).resolve().relative_to(self.root.resolve()).as_posix()
        banned_hits: list[tuple[str, int, str]] = []
        drive_files: set[str] = set()

        for folder in SCAN_DIRS:
            base = self.root / folder
            if not base.exists():
                continue
            for path in sorted(base.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                rel = path.relative_to(self.root).as_posix()
                if rel == self_rel:
                    continue
                with tokenize.open(path) as handle:
                    source = handle.read()
                tree = ast.parse(source, filename=str(path))
                docs = _docstring_node_ids(tree)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                        and id(node) not in docs
                    ):
                        val = node.value
                        line = getattr(node, "lineno", 0)
                        if RE_BANNED_REFS.search(val):
                            banned_hits.append((rel, line, val[:100]))
                        if RE_WINDOWS_DRIVE.search(val):
                            drive_files.add(rel)

        self.assertEqual(
            banned_hits,
            [],
            f"Banned legacy path, RNS symbol/port, or drive root found: {banned_hits}",
        )
        self.assertEqual(
            drive_files,
            EXPECTED_WINDOWS_DRIVE_PY_FILES,
            f"Windows drive literal allowlist drifted. extra={sorted(drive_files - EXPECTED_WINDOWS_DRIVE_PY_FILES)} missing={sorted(EXPECTED_WINDOWS_DRIVE_PY_FILES - drive_files)}",
        )


if __name__ == "__main__":
    unittest.main()
