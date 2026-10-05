import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "214_akerpuls_m4_2026_top3_benchmark_freeze_v1.py"

def load():
    spec = importlib.util.spec_from_file_location("m214", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_identity(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD, "fc81a4cde783a25c5558b977dcce98222682bb7c")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA, "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")
        self.assertEqual(self.m.EXPECTED_M4_PRIOR_SHA, "c595553436047132bdf280a685add4e123f579722ba353cbd8906ee778c1e3b8")

    def test_population(self):
        self.assertEqual(self.m.EXPECTED_ROWS, 128636)

    def test_future_ground_truth_guards(self):
        self.assertIn('"2026_crop_labels_used": False', self.text)
        self.assertIn('"2026_sentinel_used": False', self.text)
        self.assertIn('"predictions_may_not_be_retuned_after_future_2026_ground_truth": True', self.text)
        self.assertIn('"2026_ground_truth_joined": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_M4_2026_TOP3_BENCHMARK_V1")

if __name__ == "__main__":
    unittest.main()
