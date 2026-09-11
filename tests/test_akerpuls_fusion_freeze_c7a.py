import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "134_akerpuls_fusion_freeze_c7a.py"
CFG = ROOT / "config" / "akerpuls_fusion_freeze_c7a.json"

spec = importlib.util.spec_from_file_location("akerpuls_c7a", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestFusionFreezeC7A(unittest.TestCase):
    def test_empirical_midrank_is_monotone_and_handles_ties(self):
        ref = np.array([1.0, 2.0, 2.0, 4.0])
        vals = np.array([0.0, 1.0, 2.0, 3.0, 5.0])
        got = mod.empirical_midrank(ref, vals)
        self.assertTrue(np.all(np.diff(got) >= 0))
        self.assertAlmostEqual(got[0], 0.0)
        self.assertAlmostEqual(got[2], 0.5)
        self.assertAlmostEqual(got[-1], 1.0)

    def test_contract_is_equal_weight_label_free(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        fc = cfg["fusion_contract"]
        self.assertEqual(fc["required_development_candidates"], 367)
        self.assertEqual(len(fc["signals"]), 3)
        self.assertAlmostEqual(sum(fc["weights"]), 1.0)
        self.assertTrue(all(abs(w - 1/3) < 1e-12 for w in fc["weights"]))
        self.assertFalse(fc["uses_visual_labels"])
        self.assertFalse(fc["uses_c3_or_c5d_labels"])
        self.assertFalse(cfg["guards"]["threshold_tuning_on_c7"])
        self.assertFalse(cfg["guards"]["product_threshold_freeze"])
        self.assertFalse(cfg["guards"]["sentinel_process_api_calls"])

    def test_holdout_requires_distance_from_three_prior_pilots(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(set(cfg["prior_pilot_dirs"]), {"B", "C", "C5"})
        self.assertEqual(cfg["holdout_selection"]["minimum_distance_from_each_prior_pilot_geometry_m"], 45000)
        self.assertEqual(cfg["holdout_selection"]["target_fields"], 1000)


if __name__ == "__main__":
    unittest.main()
