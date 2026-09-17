import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "180_akerpuls_m4_target_census_diagnostic_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_target_diag", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4TargetCensusDiagnosticV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_counts_are_pinned(self):
        self.assertEqual(cls := self.m.FROZEN_N, {2021: 118190, 2022: 119101, 2023: 120330, 2024: 122065, 2025: 128636})
        self.assertEqual(len(cls), 5)

    def test_read_only_no_model_fit(self):
        low = self.text.lower()
        self.assertNotIn("lgbmclassifier(", low)
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn(".fit(", low)
        self.assertIn('"model_fit_executed": False', self.text)
        self.assertIn('"prediction_2026_executed": False', self.text)

    def test_diagnostic_checks_key_qa_fields(self):
        for token in (
            "PARTIAL_COVERAGE",
            "identity_match_confidence",
            "coverage_raw",
            "dominant_crop_share",
            "primary_f_current",
            "primary_f_historical",
            "material_overlap_anomaly",
        ):
            self.assertIn(token, self.text)

    def test_no_threshold_tuning_or_2026(self):
        self.assertNotIn("2026:", self.text)
        self.assertEqual(self.m.STATUS, "PASS_M4_TARGET_CENSUS_DIAGNOSTIC_STOP")


if __name__ == "__main__":
    unittest.main()
