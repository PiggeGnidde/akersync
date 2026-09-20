import importlib.util, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"199_akerpuls_merge_ab_independent_blind_validation_viewer_v1.py"
def load():
    s=importlib.util.spec_from_file_location("x",SCRIPT);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.m=load(); cls.text=SCRIPT.read_text(encoding="utf-8")
    def test_frozen_inputs(self):
        self.assertEqual(self.m.EXPECTED_RANKING_FREEZE_SHA,"2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26")
        self.assertEqual(self.m.EXPECTED_FIRST_JOIN_SHA,"bce010ece5982599231117e83fb301f3391b78b00e5d6e39abc700588b63e284")
    def test_design(self):
        self.assertEqual(self.m.SAMPLE_PER_TIER,50)
        self.assertEqual(self.m.TIERS,["A_CONFIRMED_HIGH","B_SAT_HIGH_H_MID"])
        self.assertEqual(self.m.EXPECTED_FIRST_AUDIT,100)
    def test_analysis_predeclared(self):
        self.assertIn('"primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable"',self.text)
        self.assertIn('"no_operational_threshold_preselected":True',self.text)
    def test_blind_and_no_mutation(self):
        self.assertIn('"tier_visible":False',self.text)
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_INDEPENDENT_BLIND_AB_VALIDATION")
if __name__=="__main__": unittest.main()
