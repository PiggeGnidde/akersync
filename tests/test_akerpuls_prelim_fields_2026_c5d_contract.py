import json
import unittest
from pathlib import Path


class TestC5DContract(unittest.TestCase):
    def test_blind_census_and_frozen_rules(self):
        root = Path(__file__).resolve().parents[1]
        c5d = json.loads((root / 'config' / 'akerpuls_prelim_fields_2026_c5d.json').read_text(encoding='utf-8'))
        c5a = json.loads((root / 'config' / 'akerpuls_prelim_fields_2026_c5a.json').read_text(encoding='utf-8'))
        c5b = json.loads((root / 'config' / 'akerpuls_prelim_fields_2026_c5b.json').read_text(encoding='utf-8'))
        self.assertEqual(c5d['split_candidate_rule_frozen_for_test'], c5a['split_candidate_rule_frozen_for_test'])
        self.assertEqual(c5d['split_candidate_rule_frozen_for_test'], c5b['split_candidate_rule_frozen_for_test'])
        self.assertEqual(c5d['high_confidence_rule_frozen_for_test'], c5a['high_confidence_rule_frozen_for_test'])
        self.assertEqual(c5d['high_confidence_rule_frozen_for_test'], c5b['high_confidence_rule_frozen_for_test'])
        self.assertEqual(c5d['blind_visual_set']['all_high_confidence'], 6)
        self.assertEqual(c5d['blind_visual_set']['near_threshold_candidate_controls'], 6)
        self.assertFalse(c5d['guards']['sentinel_api_calls'])
        self.assertFalse(c5d['guards']['threshold_tuning'])
        self.assertFalse(c5d['guards']['threshold_freeze_for_product'])
        self.assertEqual(c5d['merge_policy'], 'MERGE_CANDIDATE_ONLY')


if __name__ == '__main__':
    unittest.main()
