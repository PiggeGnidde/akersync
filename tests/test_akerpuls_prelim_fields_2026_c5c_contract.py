import json, unittest
from pathlib import Path

class TestC5CContract(unittest.TestCase):
    def test_frozen_rules_match_c5a_and_c5b(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c5c.json').read_text(encoding='utf-8'))
        a=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c5a.json').read_text(encoding='utf-8'))
        b=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c5b.json').read_text(encoding='utf-8'))
        self.assertEqual(c['candidate_discovery_contract'],'IDENTICAL_TO_B2')
        self.assertEqual(c['split_candidate_rule_frozen_for_test'],a['split_candidate_rule_frozen_for_test'])
        self.assertEqual(c['split_candidate_rule_frozen_for_test'],b['split_candidate_rule_frozen_for_test'])
        self.assertEqual(c['high_confidence_rule_frozen_for_test'],a['high_confidence_rule_frozen_for_test'])
        self.assertEqual(c['high_confidence_rule_frozen_for_test'],b['high_confidence_rule_frozen_for_test'])
        self.assertEqual(c['high_confidence_rule_frozen_for_test']['minimum_separation_ratio'],4.0)
        self.assertTrue(c['high_confidence_rule_frozen_for_test']['requires_split_candidate'])
        self.assertFalse(c['guards']['threshold_tuning'])
        self.assertFalse(c['guards']['threshold_freeze_for_product'])

if __name__=='__main__': unittest.main()
