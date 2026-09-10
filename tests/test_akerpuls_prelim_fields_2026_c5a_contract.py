import json
import unittest
from pathlib import Path


class TestC5AContract(unittest.TestCase):
    def test_third_holdout_rules_are_frozen_for_test_only(self):
        root = Path(__file__).resolve().parents[1]
        c5 = json.loads((root / "config" / "akerpuls_prelim_fields_2026_c5a.json").read_text(encoding="utf-8"))
        c2 = json.loads((root / "config" / "akerpuls_prelim_fields_2026_c2.json").read_text(encoding="utf-8"))
        self.assertEqual(c5["split_candidate_rule_frozen_for_test"], c2["locked_split_rule"])
        hc = c5["high_confidence_rule_frozen_for_test"]
        self.assertTrue(hc["requires_split_candidate"])
        self.assertEqual(hc["minimum_separation_ratio"], 4.0)
        self.assertEqual(hc["status"], "TEST_ONLY_NOT_PRODUCT_FROZEN")
        self.assertEqual(c5["selection"]["minimum_distance_from_prior_pilot_geometry_m"], 45000)
        self.assertFalse(c5["guards"]["threshold_tuning"])
        self.assertFalse(c5["guards"]["threshold_freeze_for_product"])
        self.assertFalse(c5["guards"]["sentinel_api_calls"])
        self.assertEqual(c5["merge_policy"], "MERGE_CANDIDATE_ONLY")


if __name__ == "__main__":
    unittest.main()
