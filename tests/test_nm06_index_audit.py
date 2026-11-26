import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np

from tools.audit_reference_indexes import inspect


class IndexAuditTests(unittest.TestCase):
    def test_inventory_has_hashes_without_text_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"luar_index.joblib"
            joblib.dump({"texts":["private fixture words"],"meta":[{"book":"fixture"}],
                         "vectors":np.ones((1,2))},path)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            report=inspect(path)
            self.assertEqual(report["sha256"],before)
            self.assertEqual(report["sources"],{"fixture":1})
            self.assertNotIn("private fixture words",json.dumps(report))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            self.assertTrue(report["legacy_unverified"])

    def test_corrupt_vectors_rejected_and_existing_report_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            joblib.dump({"texts":["a"],"meta":[{"book":"x"}],
                         "vectors":np.array([[float("nan")]])},root/"luar_index.joblib")
            with self.assertRaisesRegex(ValueError,"invalid"): inspect(root/"luar_index.joblib")
            out=root/"existing.json"; out.write_text("preserve",encoding="utf-8")
            p=subprocess.run([sys.executable,"-B","tools/audit_reference_indexes.py","--books",str(root),
                              "--out",str(out)],capture_output=True,text=True,timeout=20)
            self.assertEqual(p.returncode,2)
            self.assertEqual(out.read_text(encoding="utf-8"),"preserve")


if __name__ == "__main__":
    unittest.main()
