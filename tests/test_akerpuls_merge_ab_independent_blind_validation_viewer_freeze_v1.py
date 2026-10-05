import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"200_akerpuls_merge_ab_independent_blind_validation_viewer_freeze_v1.py"

def load():
    s=importlib.util.spec_from_file_location("ab_freeze",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_frozen_design(self):
        self.assertEqual(cls.m.EXPECTED_SAMPLE,100)
        self.assertEqual(cls.m.EXPECTED_PER_TIER,50)
        self.assertEqual(cls.m.EXPECTED_ELIGIBLE,{"A_CONFIRMED_HIGH":986,"B_SAT_HIGH_H_MID":1171})

    def test_hashes(self):
        self.assertEqual(cls.m.EXPECTED_RANKING_FREEZE_SHA,"2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26")
        self.assertEqual(cls.m.EXPECTED_SAMPLE_POPULATION_SHA,"f5df348a57660df3eadbd8ab7c0bc35b90985b9f22f5540735e2cf56bf0ed677")
        self.assertEqual(cls.m.EXPECTED_BLIND_KEY_SHA,"fec621243d0b7cefc33d345be6ee361bd06cdba802a2d72b3925fa3257f7dc5f")

    def test_prelabel_blindness(self):
        self.assertIn('"blind_key_contents_revealed": False',cls.text)
        self.assertIn('"human_labels_created": False',cls.text)
        self.assertIn('"tier_visible": False',cls.text)

    def test_no_operational_mutation(self):
        self.assertIn('"cross_block_merge_allowed": False',cls.text)
        self.assertIn('"automatic_merge": False',cls.text)
        self.assertIn('"geometry_mutated": False',cls.text)

    def test_status(self):
        self.assertEqual(cls.m.STATUS,"FROZEN_AKERPULS_MERGE_AB_INDEPENDENT_BLIND_VALIDATION_VIEWER_V1")

if __name__=="__main__":
    unittest.main()
