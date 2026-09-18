import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "183_akerpuls_m4_final_2026_prior_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_final_2026", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4Final2026PriorV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_formal_reimplementation_freeze_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_FREEZE_SHA256,
            "94ea57736b7aa472c1bca959aeb848b0e764240d3d47202c2a2a4dc144ed7b9a",
        )

    def test_training_census_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_TOTAL_TRAIN_N, 954786)
        self.assertEqual(self.m.EXPECTED_TRAIN_N_BY_YEAR[2025], 128636)

    def test_target_year_and_population_are_pinned(self):
        self.assertEqual(self.m.TARGET_YEAR, 2026)
        self.assertEqual(self.m.EXPECTED_FIELDS, 128636)

    def test_blind_2026_guards_exist(self):
        self.assertIn('"2026_crop_labels_used": False', self.text)
        self.assertIn('"2026_satellite_used": False', self.text)
        self.assertIn('"merge_m0_used": False', self.text)

    def test_persistent_outputs_are_required(self):
        self.assertIn("M4_2026_FINAL.txt", self.text)
        self.assertIn("M4_2026_FIELD_PRIOR.parquet", self.text)
        self.assertIn("M4_2026_FIELD_PRIOR.csv.gz", self.text)
        self.assertIn("SHA256_MANIFEST.txt", self.text)

    def test_v1b_no_public_match_rule_is_applied(self):
        self.assertIn('excluded != {"NO_PUBLIC_MATCH"}', self.text)
        self.assertIn("known_wide = known_wide & (~bad.fillna(False))", self.text)

    def test_status_stops_for_freeze_review(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_M4_2026_PRIOR_FREEZE_REVIEW")


if __name__ == "__main__":
    unittest.main()
