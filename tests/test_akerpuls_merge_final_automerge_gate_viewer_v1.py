import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"src"/"208_akerpuls_merge_final_automerge_gate_viewer_v1.py"

def load():
    s=importlib.util.spec_from_file_location("finalgate",SCRIPT)
    m=importlib.util.module_from_spec(s)
    assert s.loader is not None
    s.loader.exec_module(m)
    return m

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m=load()
        cls.text=SCRIPT.read_text(encoding="utf-8")

    def test_final_rule(self):
        self.assertEqual(self.m.S_GATE,0.95)
        self.assertEqual(self.m.H_VETO,0.25)
        self.assertEqual(self.m.SAMPLE_N,80)
        self.assertEqual(self.m.EXPECTED_PRIOR_UNION,258)

    def test_acceptance_frozen(self):
        a=self.m.ACCEPTANCE
        self.assertEqual(a["broad_rate_min"],0.90)
        self.assertEqual(a["broad_one_sided_wilson95_lower_min"],0.85)
        self.assertEqual(a["behall_rate_max"],0.05)
        self.assertEqual(a["ej_bedomdbar_max_count"],8)
        self.assertTrue(a["final_blind_test_for_current_signal_family"])
        self.assertTrue(a["no_posthoc_threshold_chase"])

    def test_c_result_hashes(self):
        self.assertEqual(self.m.EXPECTED_C_SUMMARY_SHA,"c2125f76978eb9706d2072e3b8a5059db1d452653b818d2eee0611985524d36a")
        self.assertEqual(self.m.EXPECTED_THIRD_JOIN_SHA,"8c5bad81bcf77bbbd831240573e3887c8169c2c2e7d84a1bd06181a75ace77c5")
        self.assertEqual(self.m.EXPECTED_C_PAIRED_SHA,"e493a1b311c7879fa627b5a52ac52e954fe47c4096b76be751a8dc2167e50c35")

    def test_no_mutation(self):
        self.assertIn('"automatic_merge":False',self.text)
        self.assertIn('"geometry_mutated":False',self.text)
        self.assertIn('"cross_block_merge_allowed":False',self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS,"PASS_TO_FINAL_AUTOMERGE_GATE_BLIND_VALIDATION")
        self.assertEqual(self.m.FREEZE_STATUS,"FROZEN_AKERPULS_MERGE_FINAL_AUTOMERGE_GATE_VIEWER_V1")

if __name__=="__main__":
    unittest.main()
