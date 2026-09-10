import json, unittest
from pathlib import Path

class TestC3Contract(unittest.TestCase):
    def test_c3_keeps_c2_rule_and_blind_balance(self):
        root=Path(__file__).resolve().parents[1]
        c3=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c3.json').read_text(encoding='utf-8'))
        c2=json.loads((root/'config'/'akerpuls_prelim_fields_2026_c2.json').read_text(encoding='utf-8'))
        self.assertEqual(c3['locked_split_rule'],c2['locked_split_rule'])
        self.assertEqual(c3['blind_visual_set']['locked_pass_representative'],10)
        self.assertEqual(c3['blind_visual_set']['locked_reject_challenge'],10)
        self.assertFalse(c3['guards']['threshold_tuning'])
        self.assertFalse(c3['guards']['threshold_freeze'])
        self.assertEqual(c3['merge_policy'],'MERGE_CANDIDATE_ONLY')

    def test_c3_validity_merge_does_not_suffix_c2_pixel_columns(self):
        root=Path(__file__).resolve().parents[1]
        src=(root/'src'/'123_akerpuls_prelim_fields_2026_c3_blind_qa_fixed.py').read_text(encoding='utf-8')
        self.assertIn('vkeep=["parent_field_id_2025"]+[c for c in v.columns if c.startswith("valid_s2_2026_")]',src)
        self.assertIn('x=f.merge(v[vkeep]',src)
        self.assertNotIn('x=f.merge(v,on="parent_field_id_2025"',src)

if __name__=='__main__': unittest.main()