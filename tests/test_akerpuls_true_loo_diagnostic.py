import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "132_akerpuls_true_loo_diagnostic.py"
CFG = ROOT / "config" / "akerpuls_true_loo_diagnostic_v0.json"

spec = importlib.util.spec_from_file_location("akerpuls_true_loo", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestTrueLooDiagnostic(unittest.TestCase):
    def test_optimal_binary_dice_handles_label_swap(self):
        ref = np.array([0, 0, 0, 1, 1, 1], dtype=np.int8)
        pred = 1 - ref
        d0, d1, swapped = mod.optimal_binary_dice(ref, pred)
        self.assertTrue(swapped)
        self.assertAlmostEqual(d0, 1.0)
        self.assertAlmostEqual(d1, 1.0)

    def test_partial_dice(self):
        ref = np.array([0, 0, 1, 1], dtype=np.int8)
        pred = np.array([0, 1, 1, 1], dtype=np.int8)
        d0, d1, _ = mod.optimal_binary_dice(ref, pred)
        self.assertAlmostEqual(d0, 2.0 / 3.0)
        self.assertAlmostEqual(d1, 4.0 / 5.0)

    def test_contract_is_frozen_diagnostic_not_product_rule(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        c = cfg["true_loo_contract"]
        self.assertEqual(c["minimum_reference_comparison_pixels"], 24)
        self.assertAlmostEqual(c["minimum_child_fraction_each_omission_on_comparison_domain"], 0.20)
        self.assertAlmostEqual(c["minimum_each_child_dice_each_omission"], 0.75)
        self.assertAlmostEqual(c["minimum_mean_matched_child_dice_across_all_omissions"], 0.80)
        self.assertTrue(c["require_all_four_omission_refits"])
        self.assertFalse(cfg["guards"]["threshold_tuning"])
        self.assertFalse(cfg["guards"]["new_product_split_rule"])
        self.assertFalse(cfg["guards"]["sentinel_api_calls"])


if __name__ == "__main__":
    unittest.main()
