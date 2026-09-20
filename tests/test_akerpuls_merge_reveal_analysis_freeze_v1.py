import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"196_akerpuls_merge_reveal_analysis_freeze_v1.py"

def load_module():
    spec=importlib.util.spec_from_file_location("freeze_reveal",SCRIPT)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m

class TestRevealAnalysisFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load_module()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_source_hashes_pinned(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD,"237e3326bd395979271549e2a5578a628ce92115")
        self.assertEqual(self.m.EXPECTED_SUMMARY_SHA256,"f1d4314b79a531f1764d99d045acda59bd40ef8bd2fe66cc4ca04d74f8005f26")
        self.assertEqual(self.m.EXPECTED_JOIN_SHA256,"bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284")

    def test_key_science_locked(self):
        self.assertEqual(self.m.EXPECTED["HH"]["strict"],0.64)
        self.assertEqual(self.m.EXPECTED["HH"]["broad"],0.88)
        self.assertEqual(self.m.EXPECTED["HL"]["strict"],0.28)
        self.assertEqual(self.m.EXPECTED["HL"]["broad"],0.56)
        self.assertEqual(self.m.EXPECTED["LH"]["strict"],0.0)
        self.assertEqual(self.m.EXPECTED["LL"]["strict"],0.0)

    def test_no_fusion_or_sign_in_freeze(self):
        self.assertIn('"fusion_executed":False',self.text)
        self.assertIn('"fusion_weight_selected":False',self.text)
        self.assertIn('"sign_selected":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_BLIND_AUDIT_REVEAL_ANALYSIS_V1")

if __name__=="__main__":
    unittest.main()
