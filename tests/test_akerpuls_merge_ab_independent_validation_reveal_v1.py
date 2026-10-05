import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"202_akerpuls_merge_ab_independent_validation_reveal_v1.py"

def load():
    s=importlib.util.spec_from_file_location("ab_reveal",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_frozen_parent_hashes(self):
        self.assertEqual(self.m.EXPECTED_LABEL_FREEZE_SHA,"9c9183fe720eea38e59384a1cf63a6cda9c1fc7bebfce09a362b71431e212b1a")
        self.assertEqual(self.m.EXPECTED_LABELS_SHA,"a33763d81b50db263fed265866cca7b6cd3dbe6740ed72cfb4967063c7aab2a4")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA,"fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f")

    def test_exact_ab_design(self):
        self.assertEqual(self.m.EXPECTED_TIERS,{"A_CONFIRMED_HIGH":50,"B_SAT_HIGH_H_MID":50})
        self.assertEqual(self.m.EXPECTED_ROWS,100)

    def test_predeclared_endpoints(self):
        self.assertIn('"primary_endpoint":"broad_positive = TYDLIG_MERGE + MÖJLIG_MERGE among assessable"',self.text)
        self.assertIn('"secondary_endpoint":"strict_positive = TYDLIG_MERGE among assessable"',self.text)
        self.assertIn('"primary_contrast":"A_CONFIRMED_HIGH vs B_SAT_HIGH_H_MID"',self.text)

    def test_no_operational_mutation(self):
        self.assertIn('"fusion_executed":False',self.text)
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_AB_INDEPENDENT_VALIDATION_REVIEW")

if __name__=="__main__":
    unittest.main()
