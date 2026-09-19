import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "188_akerpuls_merge_m2_m0_m1_diagnostic_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m2_diag", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM2M0M1DiagnosticV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_freezes_pinned(self):
        self.assertEqual(self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_M1_FREEZE_SHA256, "5d39f6fea78260bd46cfa2aa99f8043abb02f1f67f57b73a9e30ae7273d9c20f")

    def test_exact_pair_census(self):
        self.assertEqual(self.m.EXPECTED_PAIRS, 27146)
        self.assertEqual(self.m.EXPECTED_ASSESSABLE, 22358)
        self.assertEqual(sum(self.m.EXPECTED_STATUS_COUNTS.values()), 27146)

    def test_no_model_fit_fusion_or_thresholding(self):
        low = self.text.lower()
        self.assertNotIn(".fit(", low)
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("fusion_score =", low)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"fusion_score_created": False', self.text)
        self.assertIn('"sign_selected": False', self.text)
        self.assertIn('"thresholds_tuned": False', self.text)

    def test_no_human_labels(self):
        self.assertIn('"human_labels_used": False', self.text)

    def test_outputs_are_diagnostic_only(self):
        self.assertIn("M2_M0_M1_DIAGNOSTIC_JOIN.parquet", self.text)
        self.assertIn("M2_M1_P_SAMECROP_DECILES.csv", self.text)
        self.assertIn("M2_ASSESSABLE_M0_M1_DECILE_CROSSTAB.csv", self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_M2_M0_M1_DIAGNOSTIC_STOP")


if __name__ == "__main__":
    unittest.main()
