import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"211_akerpuls_merge_v1_policy_proposal_geometry.py"

def load():
    s=importlib.util.spec_from_file_location("m211",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_parent_hashes(self):
        self.assertEqual(self.m.EXPECTED_DECISION_SHA,"f1cdb4f3cce62467a763c2a0fa6e4f8a190939e1518bf6a85f72b0e7ff873a71")
        self.assertEqual(self.m.EXPECTED_RANKING_FREEZE_SHA,"2f98d504c61ba71da396e4d459ffd6b3e5d2feaacbe5a8faaab9635d2882ef26")
        self.assertEqual(self.m.EXPECTED_SPLIT_FREEZE_SHA,"c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376")

    def test_policy_counts(self):
        self.assertEqual(self.m.EXPECTED_SPLIT_PROPOSALS,613)
        self.assertEqual(self.m.EXPECTED_MERGE_PROPOSALS,2182)
        self.assertEqual(self.m.EXPECTED_LOW_HPRIOR_VETO,54)

    def test_policy_guards(self):
        self.assertIn('"automatic_boundary_removal":False',self.text)
        self.assertIn('"merge_v1_is_proposal_only":True',self.text)
        self.assertIn('"no_more_threshold_search_with_same_signals":True',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"FROZEN_AKERPULS_MERGE_V1_POLICY_PROPOSAL_GEOMETRY_V1")

if __name__=="__main__":
    unittest.main()
