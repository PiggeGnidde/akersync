import importlib.util, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"213_akerpuls_final_skane_review_map_v1b.py"

def load():
    s=importlib.util.spec_from_file_location("m213",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_frozen_inputs(self):
        self.assertEqual(self.m.EXPECTED_GPKG_SHA,"af2749b0d36199cceccf0440b5f95974fc5b09d3149bc7625f951510722624a2")
        self.assertEqual(self.m.EXPECTED_POLICY_SHA,"52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA,"61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")
        self.assertEqual(self.m.EXPECTED_M4_PRIOR_SHA,"c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8")

    def test_counts(self):
        self.assertEqual(self.m.EXPECTED_FIELDS,128636)
        self.assertEqual(self.m.EXPECTED_SPLIT,613)
        self.assertEqual(self.m.EXPECTED_MERGE,2182)
        self.assertEqual(self.m.EXPECTED_MERGE_HIGH,1103)

    def test_ui_semantics(self):
        self.assertIn("CANONICAL_BOUNDARY_WEIGHT=1.15",self.text)
        self.assertIn("SPLIT_HIT_TARGET_WEIGHT=14",self.text)
        self.assertIn("Sentinel 2026 är inte använd",self.text)
        self.assertIn("crop_clickable",self.text)

    def test_no_new_science(self):
        self.assertIn('"geometry_mutated":False',self.text)
        self.assertIn('"thresholds_tuned":False',self.text)
        self.assertIn('"model_fit_executed":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B")

if __name__=="__main__":
    unittest.main()
