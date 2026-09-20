import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"197_akerpuls_merge_sh_gated_ranking_v1.py"

def load_module():
    spec=importlib.util.spec_from_file_location("sh_rank",SCRIPT)
    m=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m

class TestSHGatedRankingV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load_module()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_prelabel_thresholds_locked(self):
        self.assertEqual(cls := self.m.S_GATE,0.90)
        self.assertEqual(self.m.H_LOW,0.25)
        self.assertEqual(self.m.H_HIGH,0.75)

    def test_terminology_and_hard_wall(self):
        self.assertIn("S2026",self.text)
        self.assertIn("Hprior",self.text)
        self.assertIn('"block_boundary_hard_wall": True',self.text)
        self.assertIn('"cross_block_merge_allowed": False',self.text)

    def test_no_fitted_fusion_or_mutation(self):
        self.assertIn('"continuous_fusion": False',self.text)
        self.assertIn('"fitted_weights": False',self.text)
        self.assertIn('"automatic_merge": False',self.text)
        self.assertIn('"geometry_mutated": False',self.text)

    def test_expected_prelabel_extreme_counts_are_guards(self):
        self.assertIn('counts["A_CONFIRMED_HIGH"] != 1011',self.text)
        self.assertIn('counts["C_SAT_HIGH_H_LOW"] != 54',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_SH_GATED_RANKING_REVIEW")

if __name__=="__main__":
    unittest.main()
