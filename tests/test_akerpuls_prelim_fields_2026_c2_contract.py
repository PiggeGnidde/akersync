import json, unittest
from pathlib import Path

class TestC2Contract(unittest.TestCase):
    def test_c2_rule_and_guards_are_locked(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c2.json').read_text(encoding='utf-8'))
        r=c['locked_split_rule']
        self.assertEqual(c['candidate_discovery_contract'],'IDENTICAL_TO_B2')
        self.assertEqual(c['expected_pilot_fields'],1000)
        self.assertEqual(r['minimum_largest_component_fraction_each_child'],0.95)
        self.assertEqual(r['edge_ratio_threshold'],1.8)
        self.assertEqual(r['minimum_supporting_edge_snapshots'],3)
        self.assertTrue(r['require_loo_all4'])
        self.assertEqual(c['merge_policy'],'MERGE_CANDIDATE_ONLY')
        self.assertFalse(c['guards']['threshold_tuning'])
        self.assertFalse(c['guards']['sentinel_api_calls'])

if __name__=='__main__': unittest.main()
