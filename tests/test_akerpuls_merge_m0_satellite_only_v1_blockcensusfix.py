import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "170_akerpuls_merge_m0_satellite_only_v1_blockcensusfix.py"
CFG = ROOT / "config" / "akerpuls_merge_m0_satellite_only_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_merge_m0_blockfix", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsMergeM0SatelliteOnlyV1BlockCensusFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_skifte_layer_and_separate_block_layer_censuses_are_distinct(self):
        e = self.cfg["expected"]
        self.assertEqual(int(e["skifte_layer_unique_block_ids_2025"]), 99758)
        self.assertEqual(int(e["separate_block_layer_features_2025_context_only"]), 122970)
        self.assertEqual(self.m.EXPECTED_SKIFTE_LAYER_UNIQUE_BLOCK_IDS, 99758)
        self.assertEqual(self.m.CONTEXT_SEPARATE_BLOCK_LAYER_FEATURES, 122970)

    def test_adjacency_denominator_is_skifte_layer_blockid_population(self):
        self.assertEqual(
            self.cfg["adjacency"]["block_population_definition"],
            "UNIQUE_BLOCKID_VALUES_PRESENT_IN_FROZEN_2025_SKIFTE_LAYER",
        )
        self.assertIn('compat["expected"]["blocks_2025"] = EXPECTED_SKIFTE_LAYER_UNIQUE_BLOCK_IDS', self.text)

    def test_fix_does_not_enable_history_fusion_or_geometry_mutation(self):
        e = self.cfg["execution"]
        self.assertTrue(e["satellite_only"])
        for k in ("history_prior", "m4_prior", "fusion", "threshold_tuning", "automatic_merge", "geometry_mutation"):
            self.assertFalse(e[k])
        lowered = self.text.lower()
        self.assertNotIn("akerminne_selected", lowered)
        self.assertNotIn("lightgbm", lowered)
        self.assertNotIn("predict_proba", lowered)

    def test_fix_preserves_original_validator_and_loader(self):
        self.assertIn("_original_validate_config", self.text)
        self.assertIn("_original_load_frozen_context", self.text)


if __name__ == "__main__":
    unittest.main()
