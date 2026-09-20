import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "195_akerpuls_merge_reveal_blind_audit_analysis_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("reveal_analysis", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestRevealBlindAuditAnalysisV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_parents_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_LABEL_FREEZE_SHA256, "de4b7fc7e9a6587c966304bb70d9456f4f8d6f65cbb869c47ce6339e90057ba8")
        self.assertEqual(self.m.EXPECTED_LABELS_SHA256, "4bd2583ea4f1d4255997acbe5c602b7b0743641f7dd12ad961a8132e87969e70")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA256, "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee")

    def test_four_strata_are_exactly_25(self):
        self.assertEqual(self.m.EXPECTED_STRATA, {"HH": 25, "HL": 25, "LH": 25, "LL": 25})

    def test_predeclared_contrasts_are_locked(self):
        names = [x[0] for x in self.m.CONTRASTS]
        self.assertEqual(names, ["HH_vs_HL", "LH_vs_LL", "HH_vs_LH", "HL_vs_LL"])

    def test_endpoint_definitions(self):
        self.assertIn('"TYDLIG_MERGE"', self.text)
        self.assertIn('["TYDLIG_MERGE", "MÖJLIG_MERGE"]', self.text)
        self.assertIn('"EJ_BEDÖMBAR"', self.text)

    def test_no_fusion_or_sign_selection(self):
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"fusion_weight_selected": False', self.text)
        self.assertIn('"sign_selected": False', self.text)
        self.assertIn('"thresholds_tuned": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_MERGE_AUDIT_REVEAL_REVIEW")


if __name__ == "__main__":
    unittest.main()
