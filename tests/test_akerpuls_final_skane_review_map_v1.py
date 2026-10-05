import importlib.util, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"212_akerpuls_final_skane_review_map_v1.py"

def load():
    s=importlib.util.spec_from_file_location("m212",SCRIPT)
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
        self.assertEqual(self.m.EXPECTED_GPKG_SHA,"af2749b0d36199cceccf0440b5f95974fc5b09d3149bc7625f951510722624a2")
        self.assertEqual(self.m.EXPECTED_POLICY_SHA,"52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394")

    def test_counts(self):
        self.assertEqual(self.m.EXPECTED_SPLIT,613)
        self.assertEqual(self.m.EXPECTED_MERGE,2182)
        self.assertEqual(self.m.EXPECTED_MERGE_HIGH,1103)
        self.assertEqual(self.m.EXPECTED_MERGE_STANDARD,1079)
        self.assertEqual(self.m.EXPECTED_VETO,54)

    def test_semantics(self):
        self.assertIn("Boundary proposal only",self.text)
        self.assertIn('"merge_v1_proposal_only": True',self.text)
        self.assertIn('"automatic_boundary_removal": False',self.text)
        self.assertIn('"cross_block_merge_allowed": False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_FINAL_SKANE_REVIEW_MAP_V1")

if __name__=="__main__":
    unittest.main()
