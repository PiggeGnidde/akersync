import json, unittest
from pathlib import Path

class TestB5Contract(unittest.TestCase):
    def test_provisional_rule_is_rounded_and_conservative(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/"config"/"akerpuls_prelim_fields_2026_b5.json").read_text(encoding="utf-8"))
        r=c["provisional_split_rule"]
        self.assertEqual(r["minimum_largest_component_fraction_each_child"],0.95)
        self.assertEqual(r["edge_ratio_threshold"],1.8)
        self.assertEqual(r["minimum_supporting_edge_snapshots"],3)
        self.assertTrue(r["require_loo_all4"])
        self.assertFalse(c["merge_policy"]["automatic_merge"])
        self.assertFalse(c["guards"]["threshold_freeze"])

if __name__=="__main__": unittest.main()
