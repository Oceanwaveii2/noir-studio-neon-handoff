import unittest
import tempfile
from pathlib import Path
from experimental.evidence_sidecar import Evidence, compare_ocr, compare_timed, save_evidence, load_evidence

class EvidenceSidecarTests(unittest.TestCase):
    def test_ocr_detects_order_missing_and_candidate_only(self):
        r = compare_ocr('one\ntwo\nthree', 'two\none\nfour')
        self.assertEqual(r['omitted_lines'], ['three'])
        self.assertEqual(r['candidate_only_lines'], ['four'])
        self.assertFalse(r['shared_line_order_matches'])
        self.assertGreater(r['word_errors'], 0)

    def test_context_requires_both_review_and_permission(self):
        for e in [Evidence('ocr','edition','page 1','v1','raw'), Evidence('ocr','edition','page 1','v1','raw','corrected','reviewer','denied')]:
            with self.assertRaises(PermissionError): e.context()
        e = Evidence('ocr','edition','page 1','v1','raw','corrected','reviewer','permitted')
        self.assertEqual(e.context()['text'], 'corrected')
        self.assertEqual(e.record()['raw'], 'raw')

    def test_timed_overlap_and_missing_event(self):
        a=[{'id':'a','start':0,'end':2,'speaker':'A','label':'speech'}, {'id':'b','start':1,'end':3,'label':'sound'}]
        b=[{'id':'a','start':0.5,'end':2,'speaker':'B','label':'speech'}]
        r=compare_timed(a,b)
        self.assertEqual(r['missing_ids'], ['b'])
        self.assertFalse(r['matched'][0]['speaker_matches'])
        self.assertEqual(r['matched'][0]['start_error_seconds'], .5)
        with self.assertRaises(ValueError): compare_timed(a,[{'id':'x','start':1,'end':1}])

    def test_persistent_record_preserves_raw_and_refuses_overwrite(self):
        e = Evidence('ocr','edition','page 1','v1','raw','corrected','reviewer','permitted')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'record.json'
            save_evidence(e,path)
            self.assertEqual(load_evidence(path),e)
            with self.assertRaises(FileExistsError): save_evidence(e,path)
