import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "174_akerpuls_m1_m4_zip_preflight_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_m1_m4_zip_preflight", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestAkerPulsM1M4ZipPreflightV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_m0_freeze_is_exactly_pinned(self):
        self.assertEqual(cls := self.m.EXPECTED_M0_FREEZE_SHA256,
                         "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")

    def test_zip_is_inspected_in_place(self):
        self.assertIn("zipfile.ZipFile", self.text)
        self.assertIn("testzip()", self.text)
        self.assertNotIn("extractall(", self.text)
        self.assertNotIn("extract(", self.text)

    def test_no_model_prediction_or_geometry_mutation(self):
        low = self.text.lower()
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("lightgbm.train(", low)
        self.assertNotIn("to_file(", low)
        for token in ('"model_executed": False', '"m4_prediction_executed": False',
                      '"fusion_executed": False', '"thresholds_tuned": False',
                      '"geometry_mutated": False'):
            self.assertIn(token, self.text)

    def test_categories_cover_exact_m1_needs(self):
        for key in ("manifest_like", "model_card_like", "contract_like",
                    "feature_or_prediction_code_like", "model_like",
                    "prior_2026_export_like", "data_input_like"):
            self.assertIn(key, self.text)

    def test_status_stops_before_m1_execution(self):
        self.assertEqual(self.m.STATUS, "PASS_M1_M4_ZIP_DISCOVERY_STOP")
        self.assertIn("IMPLEMENT_M1_ON_FROZEN_27146_PAIR_UNIVERSE", self.text)


if __name__ == "__main__":
    unittest.main()
