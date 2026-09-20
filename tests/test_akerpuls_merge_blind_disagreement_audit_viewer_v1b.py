import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "191_akerpuls_merge_blind_disagreement_audit_viewer_v1b.py"

def load_module():
    spec = importlib.util.spec_from_file_location("merge_audit_v1b", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m

class TestMergeBlindDisagreementAuditViewerV1B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_freeze_unchanged(self):
        self.assertEqual(self.m.EXPECTED_M2_FREEZE_SHA256, "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859")

    def test_v1b_design_is_m0_decile_m1_quartile(self):
        self.assertEqual(self.m.M0_HIGH_Q, 0.90)
        self.assertEqual(self.m.M0_LOW_Q, 0.10)
        self.assertEqual(self.m.M1_HIGH_Q, 0.75)
        self.assertEqual(self.m.M1_LOW_Q, 0.25)
        self.assertEqual(self.m.SAMPLE_PER_STRATUM, 25)
        self.assertEqual(self.m.EXPECTED_SAMPLE, 100)

    def test_v1_failure_is_documented_prelabel(self):
        self.assertIn('"v1_failed_prelabel_stratum_counts": {"HH": 433, "HL": 14, "LH": 36, "LL": 181}', self.text)
        self.assertIn('"design_revision": "V1B_AFTER_PRELABEL_V1_FEASIBILITY_STOP_HL14"', self.text)

    def test_blindness_and_no_fusion_unchanged(self):
        self.assertIn('"scores_visible": False', self.text)
        self.assertIn('"stratum_visible": False', self.text)
        self.assertIn('"pair_id_visible": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_selected": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_BLIND_MERGE_DISAGREEMENT_AUDIT_V1B")

if __name__ == "__main__":
    unittest.main()
