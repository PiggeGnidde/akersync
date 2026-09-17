import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "175_akerpuls_m1_historical_paths_preflight_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m1_hist_paths", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM1HistoricalPathsPreflightV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_m0_freeze_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_M0_FREEZE_SHA256,
            "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051",
        )

    def test_historical_akerminne_paths_are_explicit(self):
        for p in (
            r"C:\AkerSync-Minne",
            r"C:\AkerSync-Minne\data\derived\akerminne_v1a\skane",
            r"C:\AkerSync-Minne\dist\data\akerminne",
            r"C:\AkerSync-Prestation\dist\data\akerminne",
            r"C:\AkerSyncRepo\work\akerscore_validation_csv_upload",
        ):
            self.assertIn(p, self.text)

    def test_exact_prior_inputs_are_explicit(self):
        for name in (
            "akerminne_2015_2025_selected.csv.gz",
            "field_static_context_selected.csv.gz",
            "akerscore_soil_skiften_selected.csv.gz",
            "skane_index.json",
        ):
            self.assertIn(name, self.text)

    def test_read_only_no_model_execution(self):
        low = self.text.lower()
        self.assertNotIn("predict_proba(", low)
        self.assertNotIn("lightgbm.train(", low)
        self.assertNotIn("to_file(", low)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"m4_prediction_executed": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_status_stops_for_review(self):
        self.assertEqual(self.m.STATUS, "PASS_M1_HISTORICAL_PATH_DISCOVERY_STOP")


if __name__ == "__main__":
    unittest.main()
