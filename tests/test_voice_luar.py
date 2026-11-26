"""LUAR index contracts (no model download; uses a stub encoder)."""

import tempfile
import unittest
from unittest.mock import patch
import hashlib
import importlib.metadata
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from prose_engine.voice.luar import LuarIndex, LuarDrive, LuarEncoder, MASKED_PREPROCESSING, torch


class LuarIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = LuarIndex(
            vectors=np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype="float32"),
            texts=["a", "b", "c"],
            meta=[{"book": "x"}, {"book": "y"}, {"book": "z"}],
        )

    def test_query_orders_by_similarity(self):
        hits = self.index.query(np.array([1.0, 0.0], dtype="float32"), k=2)
        self.assertEqual(hits[0]["text"], "a")
        self.assertGreaterEqual(hits[0]["score"], hits[1]["score"])

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "luar.joblib"
            self.index.save(path)
            loaded = LuarIndex.load(path)
            self.assertEqual(len(loaded.texts), 3)
            self.assertEqual(loaded.query(np.array([0.0, 1.0], dtype="float32"), k=1)[0]["text"], "c")

    def test_zero_query_returns_empty(self):
        self.assertEqual(self.index.query(np.zeros(2, dtype="float32")), [])

    def test_build_rejects_source_changed_during_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "vector_index.joblib"
            source.write_bytes(b"original source")
            fixture = SimpleNamespace(texts=["passage"], meta=[{"book": "fixture"}])

            class ChangingEncoder:
                model_name = "fixture"
                model_revision = "abc"
                preprocessing = MASKED_PREPROCESSING

                def encode(self, texts):
                    source.write_bytes(b"changed source")
                    return np.array([[1.0, 0.0]], dtype="float32")

            with patch("prose_engine.embedding_store.load_index", return_value=fixture):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    LuarIndex.build(tmp, encoder=ChangingEncoder())

    def test_manifest_detects_mismatch_and_new_save_refuses_overwrite(self):
        texts=["sample"]; manifest={"schema_version":2,"model":"fixture","revision":"abc",
            "preprocessing":MASKED_PREPROCESSING,"dimensions":2,"source_index_sha256":"a"*64,
            "sources":["x"],"chunk_hashes":[hashlib.sha256(b"sample").hexdigest()],
            "max_length":256,"episode_tokens":32,
            "runtime":{"python":f"{sys.version_info.major}.{sys.version_info.minor}",
                       "torch":importlib.metadata.version("torch"),
                       "transformers":importlib.metadata.version("transformers")}}
        index=LuarIndex(np.array([[1.,0.]]),texts,[{"book":"x"}],manifest)
        encoder=SimpleNamespace(model_name="fixture",model_revision="abc",preprocessing=MASKED_PREPROCESSING)
        self.assertEqual(LuarDrive(index,encoder).compatibility,"manifest-matched")
        wrong=SimpleNamespace(model_name="fixture",model_revision="changed",preprocessing=MASKED_PREPROCESSING)
        with self.assertRaisesRegex(ValueError,"do not match"):
            LuarDrive(index,wrong)
        stale={**manifest,"runtime":{**manifest["runtime"],"transformers":"wrong"}}
        with self.assertRaisesRegex(ValueError,"runtime"):
            LuarDrive(LuarIndex(index.vectors,texts,index.meta,stale),encoder)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"new.joblib"
            index.save_new(path)
            self.assertEqual(LuarIndex.load(path).manifest,manifest)
            (Path(tmp)/"vector_index.joblib").write_bytes(b"changed source")
            with self.assertRaisesRegex(ValueError,"source index changed"): LuarIndex.load(path)
            (Path(tmp)/"vector_index.joblib").unlink()
            with self.assertRaises(FileExistsError): index.save_new(path)
            import joblib
            payload=joblib.load(path); payload["texts"]=["tampered"]
            joblib.dump(payload,path)
            with self.assertRaisesRegex(ValueError,"manifest"):
                LuarIndex.load(path)

    @unittest.skipIf(torch is None, "PyTorch is not available")
    def test_corrected_encoder_uses_tokenizer_mask_and_preserves_batch_consistency(self):
        class Tokenizer:
            pad_token_id=1
            def __call__(self, texts, **kwargs):
                n=kwargs["max_length"]
                ids=[]; masks=[]
                for text in texts:
                    valid=[0]+[3]*len(text)+[2]
                    valid=valid[:n]
                    ids.append(valid+[1]*(n-len(valid)))
                    masks.append([1]*len(valid)+[0]*(n-len(valid)))
                return {"input_ids":torch.tensor(ids), "attention_mask":torch.tensor(masks)}
        class Model:
            masks=[]; ids=[]
            def __call__(self,input_ids,attention_mask):
                self.masks.append(attention_mask.clone()); self.ids.append(input_ids.clone())
                sums=(input_ids*attention_mask).sum((1,2)).float()
                return torch.stack([sums,torch.ones_like(sums)],dim=1)
        enc=LuarEncoder.__new__(LuarEncoder)
        enc.tokenizer=Tokenizer(); enc.model=Model(); enc.device="cpu"; enc.preprocessing=MASKED_PREPROCESSING
        single=enc.encode(["bird"],max_length=33)
        batch=enc.encode(["bird","another"],max_length=33)
        np.testing.assert_allclose(single[0],batch[0],atol=1e-7)
        self.assertEqual(enc.model.masks[0].shape,(1,2,32))
        self.assertEqual(int(enc.model.masks[0].sum()),6)
        self.assertEqual(int(enc.model.ids[0][0,-1,-1]),1)


if __name__ == "__main__":
    unittest.main()
