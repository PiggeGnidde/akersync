import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"210_akerpuls_merge_final_automerge_gate_decision_freeze_v1.py"
def load():
    s=importlib.util.spec_from_file_location("d",SCRIPT); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load(); cls.text=SCRIPT.read_text(encoding="utf-8")
    def test_hashes(self):
        self.assertEqual(self.m.EXPECTED_LABEL_FREEZE_SHA,"b45074558cdc63188b5ff0bd28aff437787d1970c7081c9774900dd44488a685")
        self.assertEqual(self.m.EXPECTED_LABELS_SHA,"ece6775bf4651ce48e00f5c78aa65edb896a5fd4261bc042b626f96c8c1c2b02")
    def test_wilson(self):
        self.assertAlmostEqual(self.m.wilson_lower_one_sided(72,80),0.831099146151965,places=12)
    def test_no_reveal(self):
        self.assertIn('"blind_key_contents_revealed":False',self.text)
        self.assertIn('"no_more_threshold_search_with_same_signals":True',self.text)
    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_DECISION_V1")
if __name__=="__main__": unittest.main()
