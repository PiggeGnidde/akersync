import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "213_akerpuls_final_skane_review_map_v1b_cropprior.py"

def load():
    spec = importlib.util.spec_from_file_location("m213", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_parents(self):
        self.assertEqual(self.m.EXPECTED_POLICY_SHA, "52e0e46f1fe07735c510664f67353cc6fa2e7818cbb31e1542688a2f70755394")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA, "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")
        self.assertEqual(self.m.EXPECTED_M4_PRIOR_SHA, "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8")

    def test_counts(self):
        self.assertEqual(self.m.EXPECTED_FIELDS, 128636)
        self.assertEqual(self.m.EXPECTED_SPLIT, 613)
        self.assertEqual(self.m.EXPECTED_MERGE, 2182)
        self.assertEqual(self.m.EXPECTED_MERGE_HIGH, 1103)

    def test_blind_benchmark_guards(self):
        self.assertIn('"2026_crop_labels_used": False', self.text)
        self.assertIn('"2026_sentinel_used": False', self.text)
        self.assertIn('"automatic_boundary_removal": False', self.text)
        self.assertIn('"field_click_top3_crop_prior": True', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_FINAL_SKANE_REVIEW_MAP_V1B_CROPPRIOR")

if __name__ == "__main__":
    unittest.main()
