import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "182_akerpuls_m4_reimplementation_v1b_freeze.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_v1b_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4ReimplementationV1BFreeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_reproduction_head_and_manifest_are_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_REPRO_GIT_HEAD,
            "74f0ad83115fb8f87985be0a78939b7ea8cde86e",
        )
        self.assertEqual(
            self.m.EXPECTED_MANIFEST_SHA256,
            "a8b108041d6fde4bcb434d7270bb88c1f620bd7327650ed418ce49eafac17e17",
        )

    def test_all_persistent_models_are_pinned(self):
        for year in range(2021, 2026):
            self.assertIn(f"models/M4_REIMPL_FOLD_{year}.txt", self.m.EXPECTED_FILES)

    def test_exact_target_census_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_TARGET_N,
            {2021: 118190, 2022: 119101, 2023: 120330, 2024: 122065, 2025: 128636},
        )

    def test_no_model_fit_or_2026_prediction_in_freeze(self):
        low = self.text.lower()
        self.assertNotIn(".fit(", low)
        self.assertNotIn("predict_proba(", low)
        self.assertIn('"model_fit_executed_in_freeze": False', self.text)
        self.assertIn('"prediction_2026_executed": False', self.text)

    def test_no_public_match_rule_is_guarded(self):
        self.assertIn('prov.get("exclude_statuses") != ["NO_PUBLIC_MATCH"]', self.text)
        self.assertIn("apply_to_history_feature_validity", self.text)

    def test_status_is_formal_freeze(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_M4_REIMPLEMENTATION_V1B")


if __name__ == "__main__":
    unittest.main()
