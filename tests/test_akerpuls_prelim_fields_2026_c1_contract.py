import json, unittest
from pathlib import Path

class TestC1Contract(unittest.TestCase):
    def test_validation_preprocessing_and_rule_are_locked(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/"config"/"akerpuls_prelim_fields_2026_c1.json").read_text(encoding="utf-8"))
        self.assertEqual(c["preprocessing_contract"],"IDENTICAL_TO_B1")
        self.assertEqual(c["expected_pilot_fields"],1000)
        self.assertEqual(c["resolution_m"],10)
        self.assertEqual(c["locked_split_rule"]["minimum_largest_component_fraction_each_child"],0.95)
        self.assertEqual(c["locked_split_rule"]["edge_ratio_threshold"],1.8)
        self.assertEqual(c["locked_split_rule"]["minimum_supporting_edge_snapshots"],3)
        self.assertTrue(c["locked_split_rule"]["require_loo_all4"])
        self.assertEqual(c["merge_policy"],"MERGE_CANDIDATE_ONLY")
        self.assertFalse(c["guards"]["threshold_tuning"])

if __name__=="__main__": unittest.main()
