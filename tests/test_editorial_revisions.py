import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.editorial_revisions import RevisionError, RevisionStore, world_revision
from prose_engine.editorial_service import Edit, preview, revision
from prose_engine.voice.world_state import WorldState


class RevisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = json.loads(Path("tests/fixtures/editorial_pilot.json").read_text(encoding="utf-8"))
        self.text = fixture["document"].replace("\n", "\r\n")
        self.world = WorldState.load(fixture["canon"])
        locked, action, _ = fixture["beats"]
        a = self.text.index(locked["expected_text"])
        self.frozen = ((a, a + len(locked["expected_text"])),)
        start = self.text.index(action["expected_text"])
        self.edit = Edit("action", start, start + len(action["expected_text"]), action["expected_text"],
                         action["proposals"][0]["replacement"])
        self.store = RevisionStore.create(self.root / "revisions.sqlite", self.text, self.frozen)

    def apply(self, op="one", base=0, edit=None, reviewer="Author", candidate=None, world_hash=None):
        edits = (edit or self.edit,)
        candidate = candidate or revision(preview(self.text, revision(self.text), edits, self.frozen, self.world).candidate)
        return self.store.apply(op, base, edits, reviewer, candidate, world_hash or world_revision(self.world), self.world)

    def test_apply_reopen_retry_and_undo(self):
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.apply(), 1)
        reopened = RevisionStore(self.root / "revisions.sqlite")
        number, updated, frozen = reopened.current()
        self.assertEqual(number, 1)
        self.assertEqual(updated[self.frozen[0][0]:self.frozen[0][1]], self.text[self.frozen[0][0]:self.frozen[0][1]])
        self.assertIn("\r\n", updated)
        self.assertEqual(reopened.undo("undo", 1, "Author"), 2)
        self.assertEqual(reopened.undo("undo", 1, "Author"), 2)
        self.assertEqual(reopened.current(), (2, self.text, self.frozen))

    def test_review_and_revision_guards(self):
        with self.assertRaises(RevisionError):
            self.apply(reviewer=" ")
        with self.assertRaises(RevisionError):
            self.apply(candidate="incorrect")
        with self.assertRaises(RevisionError):
            self.apply(world_hash="stale")
        locked = Edit("locked", *self.frozen[0], self.text[slice(*self.frozen[0])], "changed")
        with self.assertRaisesRegex(RevisionError, "BLOCKED_FROZEN_SPAN"):
            self.apply(edit=locked)
        self.apply()
        with self.assertRaisesRegex(RevisionError, "stale"):
            self.apply(op="different")
        with self.assertRaisesRegex(RevisionError, "different request"):
            self.apply(reviewer="Other")

    def test_interruption_rolls_back_and_retry_succeeds(self):
        with patch("prose_engine.editorial_revisions.preview", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.apply(candidate="known")
        self.assertEqual(self.store.current(), (0, self.text, self.frozen))
        self.assertEqual(self.apply(), 1)

    def test_export_does_not_overwrite_and_can_retry(self):
        self.apply()
        target = self.root / "export.txt"
        target.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.store.export(target)
        self.assertEqual(target.read_bytes(), b"keep")
        self.store.export(self.root / "new.txt")
        self.assertEqual((self.root / "new.txt").read_bytes(), self.store.current()[1].encode("utf-8"))

    def test_initial_store_never_replaces_existing_file(self):
        target = self.root / "occupied"
        target.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            RevisionStore.create(target, self.text, self.frozen)
        self.assertEqual(target.read_bytes(), b"existing")

    def test_shifted_lock_and_new_canon_issue(self):
        prefix = Edit("prefix", 0, 3, "###", "### 🦊")
        candidate = preview(self.text, revision(self.text), (prefix,), self.frozen, self.world).candidate
        self.store.apply("prefix", 0, (prefix,), "Author", revision(candidate), world_revision(self.world), self.world)
        _, text, frozen = self.store.current()
        self.assertEqual(frozen[0][0], self.frozen[0][0] + 2)
        locked = Edit("lock", frozen[0][0], frozen[0][1], text[slice(*frozen[0])], "changed")
        with self.assertRaisesRegex(RevisionError, "BLOCKED_FROZEN_SPAN"):
            self.store.apply("bad-lock", 1, (locked,), "Author", revision(text), world_revision(self.world), self.world)
        start = text.index(self.edit.expected)
        bad = Edit("bad", start, start + len(self.edit.expected), self.edit.expected, "Mrs. Smith arrived.")
        with self.assertRaisesRegex(RevisionError, "BLOCKED_NEW_CANON_ISSUE"):
            self.store.apply("bad-canon", 1, (bad,), "Author", revision(text), world_revision(self.world), self.world)
        self.assertEqual(self.store.current()[0], 1)

    def test_multi_step_undo_redo_history_status_adapter_and_workbench(self):
        from prose_engine.editorial_adapter import dispatch
        from tools.workbench import Workbench

        self.assertEqual(self.store.history_status(), {"revision": 0, "can_undo": False, "can_redo": False})
        with self.assertRaisesRegex(RevisionError, "initial revision"):
            self.store.undo("undo-0", 0, "Author")
        with self.assertRaisesRegex(RevisionError, "no undone revision"):
            self.store.redo("redo-0", 0, "Author")

        self.apply(op="op-1", base=0)
        prefix = Edit("prefix", 0, 3, "###", "### Notice")
        _, text1, _ = self.store.current()
        cand2 = preview(text1, revision(text1), (prefix,), self.frozen, self.world).candidate
        self.store.apply("op-2", 1, (prefix,), "Author", revision(cand2), world_revision(self.world), self.world)
        self.assertEqual(self.store.history_status(), {"revision": 2, "can_undo": True, "can_redo": False})

        self.assertEqual(self.store.undo("undo-1", 2, "Author"), 3)
        self.assertEqual(self.store.current()[0], 3)
        self.assertEqual(self.store.undo("undo-2", 3, "Author"), 4)
        self.assertEqual(self.store.current()[1], self.text)
        self.assertEqual(self.store.history_status(), {"revision": 4, "can_undo": False, "can_redo": True})
        with self.assertRaisesRegex(RevisionError, "initial revision"):
            self.store.undo("undo-3", 4, "Author")

        redone1 = dispatch(self.store, self.world, {"action": "redo", "base": 4, "reviewer": "Author", "operation_id": "redo-1"})
        self.assertEqual((redone1["revision"], redone1["status"], redone1["can_undo"], redone1["can_redo"]),
                         (5, "REDONE", True, True))
        redone2 = dispatch(self.store, self.world, {"action": "redo", "base": 5, "reviewer": "Author", "operation_id": "redo-2"})
        self.assertEqual((redone2["revision"], redone2["can_redo"]), (6, False))
        self.assertIn("### Notice", self.store.current()[1])
        with self.assertRaisesRegex(RevisionError, "no undone revision"):
            dispatch(self.store, self.world, {"action": "redo", "base": 6, "reviewer": "Author", "operation_id": "redo-3"})

        doc_path = self.root / "doc.txt"
        doc_path.write_bytes(self.text.encode("utf-8"))
        bench = Workbench(doc_path, self.root / "out.txt", None, review_store=self.store, use_retrieval=False)
        bench.world = self.world
        undone_bench = bench.save({"action": "undo", "base": 6, "reviewer": "Author", "operation_id": "wb-undo"})
        self.assertEqual(undone_bench["revision"], 7)
        redone_bench = bench.save({"action": "redo", "base": 7, "reviewer": "Author", "operation_id": "wb-redo"})
        self.assertEqual(redone_bench["revision"], 8)
        state = dispatch(self.store, self.world, {"action": "state"})
        self.assertEqual((state["revision"], state["can_undo"], state["can_redo"]), (8, True, False))
