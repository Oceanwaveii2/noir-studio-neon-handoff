import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from prose_engine.library_indexes import (ACTIVE, INDEXES, atomic_json_new_revision, catalog,
    configure_existing, digest, index_path, library_status, runtime, safe_child, validate_index, usable_sources)
from prose_engine.embedding_store import EmbeddingIndex
from tools.library_rebuild import activate, pin


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / "text").mkdir()
        for name, text in {"old": "Old words. " * 30, "off": "Disabled words. " * 30, "blank": " \n", "new": "New words. " * 30}.items():
            (self.root / "text" / (name + ".txt")).write_text(text, encoding="utf-8")
        self.write("manifest.json", {"books": [{"slug": s} for s in ("old", "off", "blank", "new")]})
        self.write("reference_policy.json", {"schema_version": 1, "sources": {
            "old": {"enabled": False, "permissions": ["export"], "note": "keep me"}}})
        self.write("influence.json", {"books": {"off": {"level": 0, "name": "off"}}})

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def candidate(self):
        folder = self.root / "candidate"; folder.mkdir()
        info = {}
        cat = catalog(self.root)
        for backend, filename in INDEXES.items():
            sources = sorted(usable_sources(self.root))
            index = EmbeddingIndex([s + " words." for s in sources],
                [{"source_id": s, "source_revision": cat["sources"][s]} for s in sources], np.eye(len(sources), dtype="float32"))
            info[backend] = pin(index, backend, cat)
            info[backend]["probes"] = [{"source_id": s, "source_in_top5": True, "fixture": True} for s in sources]
            index.save(folder / filename); info[backend]["sha256"] = digest(folder / filename)
        (folder / "styleprint.json").write_text("{}", encoding="utf-8")
        info["style"]["style_model_sha256"] = digest(folder / "styleprint.json")
        report = {"status": "PASS", "catalog": cat["fingerprint"], "runtime": runtime(),
                  "indexes": info, "expected_pointer": "missing"}
        (folder / "release.json").write_text(json.dumps(report), encoding="utf-8")
        return folder

    def test_path_escape_and_drive_relative_rejected(self):
        for path in ("../escape", "C:escape", "C:/escape", "/escape", "index_releases/../../escape"):
            with self.subTest(path=path), self.assertRaises(ValueError): safe_child(self.root, path)

    def test_bad_pointer_does_not_fall_back_to_legacy(self):
        (self.root / INDEXES["topic"]).write_bytes(b"old")
        self.write(ACTIVE, {"schema_version": 1, "directory": "../other", "hashes": {}})
        with self.assertRaises(ValueError): index_path(self.root, "topic")

    def test_catalog_source_edit_invalidates(self):
        first = catalog(self.root)
        (self.root / "text/old.txt").write_text("changed", encoding="utf-8")
        self.assertNotEqual(first["fingerprint"], catalog(self.root)["fingerprint"])

    def test_configuration_preserves_choices_and_excludes_blank(self):
        result = configure_existing(self.root, remote=True, expected_revision=digest(self.root / "reference_policy.json"))
        sources = json.loads((self.root / "reference_policy.json").read_text())["sources"]
        self.assertEqual(sources["old"], {"enabled": False, "permissions": ["export"], "note": "keep me"})
        self.assertFalse(sources["off"]["enabled"]); self.assertNotIn("blank", sources)
        self.assertIn("remote_transfer", sources["new"]["permissions"]); self.assertNotIn("export", sources["new"]["permissions"])
        self.assertEqual(result["preserved_existing"], 1)

    def test_stale_configuration_is_unchanged(self):
        before = (self.root / "reference_policy.json").read_bytes()
        with self.assertRaises(ValueError): configure_existing(self.root, remote=True, expected_revision="stale")
        self.assertEqual(before, (self.root / "reference_policy.json").read_bytes())

    def test_quarantine_excludes_corpus_policy_and_batch_setup(self):
        from prose_engine.corpus import load_corpus
        from prose_engine.reference_policy import ReferencePolicy, eligible_index
        self.write("library_quality.json", {"schema_version": 1, "excluded": {"new": "wrong title"}})
        self.assertNotIn("new", usable_sources(self.root))
        self.assertNotIn("new", {b.slug for b in load_corpus(self.root)})
        result = configure_existing(self.root, remote=True, expected_revision=digest(self.root / "reference_policy.json"))
        self.assertNotIn("new", result["added"])
        data = json.loads((self.root / "reference_policy.json").read_text())
        data["sources"]["new"] = {"enabled": True, "permissions": ["rank_local", "prompt"]}
        self.write("reference_policy.json", data)
        index = EmbeddingIndex(["suspect"], [{"book": "new"}], np.ones((1, 3)))
        self.assertIsNone(eligible_index(index, ReferencePolicy.load(self.root), ("rank_local",)))
        self.assertTrue(json.loads((self.root / "reference_policy.json").read_text())["sources"]["new"]["enabled"])
        self.assertTrue((self.root / "text/new.txt").is_file())

    def test_quality_edit_invalidates_catalog_and_draft_binding(self):
        from prose_engine.scoped_references import fingerprint
        (self.root / INDEXES["topic"]).write_bytes(b"fixture")
        before = fingerprint(self.root, "topic")
        self.write("library_quality.json", {"schema_version": 1, "excluded": {"new": "wrong title"}})
        self.assertNotEqual(before, fingerprint(self.root, "topic"))

    def test_invalid_quality_fails_closed(self):
        from prose_engine.corpus import load_corpus
        from prose_engine.reference_policy import ReferencePolicy
        self.write("library_quality.json", {"schema_version": 1, "excluded": []})
        with self.assertRaises(ValueError): load_corpus(self.root)
        with self.assertRaises(ValueError): ReferencePolicy.load(self.root)

    def test_failed_activation_preserves_previous_indexes(self):
        folder = self.candidate(); old = self.root / INDEXES["topic"]; old.write_bytes(b"legacy")
        (folder / INDEXES["luar"]).write_bytes(b"broken")
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertFalse((self.root / ACTIVE).exists()); self.assertEqual(old.read_bytes(), b"legacy")

    def test_source_drift_blocks_activation(self):
        folder = self.candidate(); (self.root / "text/new.txt").write_text("drift", encoding="utf-8")
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertFalse((self.root / ACTIVE).exists())

    def test_model_drift_blocks_activation(self):
        folder = self.candidate()
        report = json.loads((folder / "release.json").read_text()); report["indexes"]["topic"]["encoder_binding"] = "changed"
        (folder / "release.json").write_text(json.dumps(report))
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertFalse((self.root / ACTIVE).exists())

    def test_style_model_drift_blocks_activation(self):
        folder = self.candidate(); (folder / "styleprint.json").write_text('{"changed":true}')
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertFalse((self.root / ACTIVE).exists())

    def test_stale_pointer_blocks_publication(self):
        folder = self.candidate(); self.write(ACTIVE, {"changed": True}); before = (self.root / ACTIVE).read_bytes()
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertEqual(before, (self.root / ACTIVE).read_bytes())

    def test_activation_and_readiness_without_inference(self):
        folder = self.candidate()
        with patch("prose_engine.embedding_store.EmbeddingIndex._encoder", side_effect=AssertionError("inference")):
            activate(self.root, folder, "fixture")
            self.assertEqual(index_path(self.root, "topic"), self.root / "index_releases/fixture/vector_index.joblib")
            result = library_status(self.root, "mock")
        self.assertFalse(result["generation_started"])
        self.assertEqual(result["indexes"]["topic"]["books"], 3)
        self.assertEqual(result["indexes"]["topic"]["state"], "no_eligible")
        with self.assertRaises(FileExistsError): activate(self.root, folder, "fixture")

    def test_changed_release_receipt_is_unavailable(self):
        folder = self.candidate(); activate(self.root, folder, "fixture")
        (self.root / "index_releases/fixture/release.json").write_text("{}")
        self.assertTrue(all(v["state"] == "unavailable" for v in library_status(self.root, "mock")["indexes"].values()))

    def test_incomplete_coverage_and_missing_probes_block_activation(self):
        folder = self.candidate()
        report = json.loads((folder / "release.json").read_text())
        report["indexes"]["topic"]["sources"] = ["old"]
        (folder / "release.json").write_text(json.dumps(report))
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        report["indexes"]["topic"]["sources"] = sorted(usable_sources(self.root))
        report["indexes"]["topic"]["probes"] = []
        (folder / "release.json").write_text(json.dumps(report))
        with self.assertRaises(ValueError): activate(self.root, folder, "fixture")
        self.assertFalse((self.root / ACTIVE).exists())

    def test_activation_does_not_rehash_catalog_for_every_passage(self):
        folder = self.candidate()
        with patch("tools.library_rebuild.catalog", wraps=catalog) as lookup:
            activate(self.root, folder, "fixture")
        self.assertLessEqual(lookup.call_count, 3)

    def test_publish_lock_and_expected_revision(self):
        path = self.root / "config.json"; path.write_text("{}")
        with self.assertRaises(ValueError): atomic_json_new_revision(path, {"new": True}, "wrong")
        self.assertFalse(path.with_name(path.name + ".publish-lock").exists())
        atomic_json_new_revision(path, {"new": True}, digest(path)); self.assertTrue(json.loads(path.read_text())["new"])

    def test_validation_rejects_stale_source_and_runtime(self):
        index = EmbeddingIndex(["a"], [{"source_id": "old"}], np.ones((1, 3)))
        pin(index, "topic", catalog(self.root)); self.assertEqual(validate_index(self.root, "topic", index), "verified-release")
        index.manifest["library_runtime"] = {}
        with self.assertRaises(ValueError): validate_index(self.root, "topic", index)


if __name__ == "__main__": unittest.main()
