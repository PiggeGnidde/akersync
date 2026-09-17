import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "179_akerpuls_m4_reimplementation_reproduction_gate_v1.py"
CONFIG = ROOT / "config" / "akerpuls_m4_reimplementation_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_repro", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4ReimplementationReproductionGateV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.code = SCRIPT.read_text(encoding="utf-8")
        cls.cfg = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_2026_is_never_a_validation_year(self):
        self.assertEqual(self.cfg["history_features"]["validation_years"], [2021, 2022, 2023, 2024, 2025])
        self.assertTrue(self.cfg["persistence"]["do_not_predict_2026_in_reproduction_gate"])
        self.assertNotIn("build_year_features(2026", self.code)

    def test_lightgbm_contract_is_exactly_pinned(self):
        l = self.cfg["lightgbm"]
        self.assertEqual(l["package_version"], "4.7.0")
        self.assertEqual(l["n_estimators"], 35)
        self.assertEqual(l["num_leaves"], 31)
        self.assertEqual(l["learning_rate"], 0.12)
        self.assertEqual(l["min_child_samples"], 100)
        self.assertEqual(l["colsample_bytree"], 0.7)
        self.assertEqual(l["reg_lambda"], 5.0)
        self.assertEqual(l["random_state"], 20260907)

    def test_reproduction_tolerances_are_precommitted(self):
        t = self.cfg["reproduction_gate_tolerances_frozen_before_run"]
        self.assertTrue(t["n_must_match_exactly"])
        self.assertEqual(t["mean_abs_delta"]["log_loss"], 0.04)
        self.assertEqual(t["max_abs_delta"]["log_loss"], 0.06)
        self.assertTrue(t["ece_is_report_only"])

    def test_all_frozen_benchmark_years_present(self):
        self.assertEqual(sorted(map(int, self.cfg["frozen_benchmark_m4"].keys())), [2021, 2022, 2023, 2024, 2025])
        self.assertEqual(self.cfg["frozen_benchmark_m4"]["2025"]["n"], 128636)

    def test_models_and_manifest_are_saved(self):
        self.assertIn("booster_.save_model", self.code)
        self.assertIn("SHA256_MANIFEST.txt", self.code)
        self.assertIn("FEATURE_CONTRACT.json", self.code)
        self.assertIn("ENVIRONMENT.json", self.code)
        self.assertIn("M4_REIMPLEMENTATION_FOLD_METRICS.csv", self.code)

    def test_target_census_stops_before_fit_on_mismatch(self):
        pos_census = self.code.index("FAIL_M4_REIMPLEMENTATION_TARGET_CENSUS_GATE")
        pos_fit = self.code.index("model.fit(")
        self.assertLess(pos_census, pos_fit)
        self.assertIn("MODEL_FIT_EXECUTED=FALSE", self.code)

    def test_status_names_are_explicit(self):
        self.assertEqual(self.m.PASS_STATUS, "PASS_M4_REIMPLEMENTATION_REPRODUCTION_COMPATIBILITY_GATE")
        self.assertEqual(self.m.FAIL_STATUS, "FAIL_M4_REIMPLEMENTATION_REPRODUCTION_COMPATIBILITY_GATE")


if __name__ == "__main__":
    unittest.main()
