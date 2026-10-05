import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"203_akerpuls_merge_ab_independent_validation_reveal_freeze_v1.py"
def load():
    s=importlib.util.spec_from_file_location("abv",SCRIPT); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load(); cls.text=SCRIPT.read_text(encoding="utf-8")
    def test_hashes(self):
        self.assertEqual(self.m.EXPECTED_SUMMARY_SHA,"8b0fa1b5e6965a02bb11ed29df8f43c161603f81b5a75ceeef219bf7e22d3295")
        self.assertEqual(self.m.EXPECTED_JOIN_SHA,"ef17c26b588428895c6e0e158b2d91edbdf4a75e50cc997aa1584fde00ec51b5")
    def test_result_locked(self):
        self.assertAlmostEqual(self.m.EXPECTED["A_CONFIRMED_HIGH"]["broad"],0.8163265306122449)
        self.assertAlmostEqual(self.m.EXPECTED["B_SAT_HIGH_H_MID"]["broad"],0.82)
        self.assertEqual(self.m.EXPECTED_BROAD_P,1.0)
    def test_no_policy_yet(self):
        self.assertIn('"policy_selected":False',self.text)
        self.assertIn('"automatic_merge":False',self.text)
    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_VALIDATION_REVEAL_V1")
if __name__=="__main__": unittest.main()
