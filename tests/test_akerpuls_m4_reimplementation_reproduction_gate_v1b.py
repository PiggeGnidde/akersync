import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "181_akerpuls_m4_reimplementation_reproduction_gate_v1b.py"
PATCH = ROOT / "config" / "akerpuls_m4_target_validity_patch_v1b.json"


def load_module():
    spec = importlib.util.spec_from_file_location("m4_repro_v1b", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM4ReimplementationReproductionGateV1B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.patch = json.loads(PATCH.read_text(encoding="utf-8"))

    def test_exact_rule_is_no_public_match(self):
        self.assertEqual(self.patch["rule"]["exclude_statuses"], ["NO_PUBLIC_MATCH"])
        self.assertTrue(self.patch["rule"]["apply_to_target_validity"])
        self.assertTrue(self.patch["rule"]["apply_to_history_feature_validity"])

    def test_exact_frozen_target_census_is_recorded(self):
        self.assertEqual(
            self.patch["exact_target_census_reproduction"],
            {"2021": 118190, "2022": 119101, "2023": 120330, "2024": 122065, "2025": 128636},
        )
        self.assertEqual(self.patch["diagnostic_deltas_vs_frozen"], [0, 0, 0, 0, 0])

    def test_rule_was_selected_pre_fit(self):
        self.assertTrue(self.patch["selected_before_model_fit"])
        self.assertFalse(self.patch["model_fit_used_for_rule_selection"])
        self.assertFalse(self.patch["prediction_2026_used_for_rule_selection"])

    def test_wrapper_masks_history_and_target_via_base(self):
        self.assertIn('cls_wide = cls_wide.mask(bad, mod.UNKNOWN)', self.text)
        self.assertIn('known_wide = known_wide & (~bad.fillna(False))', self.text)
        self.assertIn('mod.prepare_base = prepare_base_v1b', self.text)

    def test_2026_not_predicted(self):
        self.assertIn('"prediction_2026_executed": False', self.text)
        self.assertNotIn("2026]", self.text)

    def test_v1_evidence_is_preserved_and_manifest_refreshed(self):
        self.assertIn("akerpuls_m4_reproduction_gate_v1", self.text)
        self.assertIn("mod.write_sha_manifest(out)", self.text)


if __name__ == "__main__":
    unittest.main()
