import json
import unittest
from pathlib import Path


class TestC5BContract(unittest.TestCase):
    def test_preprocessing_and_frozen_test_rules_are_unchanged(self):
        root = Path(__file__).resolve().parents[1]
        c5a = json.loads((root / "config" / "akerpuls_prelim_fields_2026_c5a.json").read_text(encoding="utf-8"))
        c5b = json.loads((root / "config" / "akerpuls_prelim_fields_2026_c5b.json").read_text(encoding="utf-8"))
        self.assertEqual(c5b["preprocessing_contract"], "IDENTICAL_TO_B1")
        self.assertEqual(c5b["expected_pilot_fields"], 1000)
        self.assertEqual(c5b["resolution_m"], 10)
        self.assertEqual(c5b["split_candidate_rule_frozen_for_test"], c5a["split_candidate_rule_frozen_for_test"])
        self.assertEqual(c5b["high_confidence_rule_frozen_for_test"], c5a["high_confidence_rule_frozen_for_test"])
        self.assertEqual(c5b["high_confidence_rule_frozen_for_test"]["minimum_separation_ratio"], 4.0)
        self.assertFalse(c5b["guards"]["threshold_tuning"])
        self.assertFalse(c5b["guards"]["threshold_freeze_for_product"])
        self.assertEqual(c5b["merge_policy"], "MERGE_CANDIDATE_ONLY")


if __name__ == "__main__":
    unittest.main()
