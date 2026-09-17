import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "173_akerpuls_m1_m4_input_preflight_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_m1_m4_preflight", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsM1M4InputPreflightV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_m0_freeze_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_M0_FREEZE_SHA256,
            "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051",
        )

    def test_preflight_is_read_only_with_respect_to_models_and_geometry(self):
        low = self.text.lower()
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("lgbmclassifier(", low)
        self.assertNotIn("lightgbm.train(", low)
        self.assertNotIn("to_file(", low)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"m4_prediction_executed": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"thresholds_tuned": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_expected_vaxfoljd_freeze_location_is_explicit(self):
        self.assertIn(r"C:\AkerSyncRepo\work\vaxtfoljd_prior_v1_freeze", self.text)

    def test_candidate_groups_include_exact_m1_needs(self):
        for key in ("manifest_like", "model_like", "feature_builder_like", "prior_export_like", "contract_like"):
            self.assertIn(key, self.text)

    def test_status_stops_before_m1_execution(self):
        self.assertEqual(self.m.STATUS, "PASS_M1_M4_INPUT_DISCOVERY_STOP")
        self.assertIn("REVIEW_EXACT_M4_ARTEFACTS_THEN_BUILD_2026_FIELD_PRIOR_AND_PAIR_PRIOR", self.text)


if __name__ == "__main__":
    unittest.main()
