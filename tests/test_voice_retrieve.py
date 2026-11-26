"""Style retrieval contract."""

import unittest
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from prose_engine.voice.retrieve import StyleDrive, StyleIndex


class StyleIndexTests(unittest.TestCase):
    def setUp(self):
        self.vectors = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.9, 0.1, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ]
        )
        self.texts = ["short a", "short b", "long c", "medium d"]
        self.meta = [{"book": "a"}, {"book": "b"}, {"book": "c"}, {"book": "d"}]
        self.index = StyleIndex(self.vectors, self.texts, self.meta, encode=lambda _t: self.vectors[0])

    def test_query_returns_vectors_in_similarity_order(self):
        hits = self.index.query("ignored", k=3, encode=lambda _t: self.vectors[0])
        self.assertEqual(len(hits), 3)
        self.assertGreaterEqual(hits[0].score, hits[1].score)
        self.assertGreaterEqual(hits[1].score, hits[2].score)

    def test_exact_match_ranks_first(self):
        hits = self.index.query("ignored", k=1, encode=lambda _t: self.vectors[0])
        self.assertEqual(hits[0].text, "short a")

    def test_save_and_load_round_trip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "style.joblib"
            self.index.save(path)
            loaded = StyleIndex.load(path)
            self.assertEqual(len(loaded.texts), 4)
            self.assertEqual(loaded.query("ignored", k=1, encode=lambda _t: self.vectors[0])[0].text, "short a")

    def test_style_drive_returns_reference_passages(self):
        drive = StyleDrive(self.index)
        passages = drive.retrieve_passages("corpus", "ignored", max_results=2)
        self.assertEqual(len(passages), 2)
        self.assertEqual(passages[0].profile_id, "corpus")

    def test_indexes_use_their_own_corpus_and_detect_changed_style_model(self):
        from prose_engine.styleprint import NAMES
        n=len(NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a=root/"a"; b=root/"b"; other=root/"other"
            for p in (a,b,other): p.mkdir()
            vector=np.zeros(n); vector[0]=1
            matrix=np.zeros((2,n)); matrix[0,0]=1; matrix[1,1]=1
            for folder,mean in ((a,np.zeros(n)),(b,np.array([1.,-1.]+[0.]*(n-2)))):
                raw=json.dumps({"mean":mean.tolist(),"sd":[1.]*n}).encode()
                (folder/"styleprint.json").write_bytes(raw)
                StyleIndex(matrix,["first","second"],[{"book":"x"},{"book":"x"}],
                           books_dir=folder,model_sha256=hashlib.sha256(raw).hexdigest()).save(folder/"style_index.joblib")
            old=Path.cwd()
            try:
                os.chdir(other)
                with patch("prose_engine.voice.retrieve.fingerprint",return_value=vector):
                    first=StyleIndex.load(a/"style_index.joblib")
                    second=StyleIndex.load(b/"style_index.joblib")
                    self.assertEqual(first.query("text",k=1)[0].text,"first")
                    self.assertEqual(second.query("text",k=1)[0].text,"second")
                    (a/"styleprint.json").write_text("{}",encoding="utf-8")
                    with self.assertRaisesRegex(ValueError,"does not match"): first.query("text")
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
