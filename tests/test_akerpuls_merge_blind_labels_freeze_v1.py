import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "193_akerpuls_merge_blind_labels_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("labels_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestMergeBlindLabelsFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_freezes_and_blind_key_hash_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_VIEWER_FREEZE_SHA256, "482e817753e00cca4f92972147515bd000e4a5800dd2bb1ff74af35a89e64a6a")
        self.assertEqual(self.m.EXPECTED_M2_FREEZE_SHA256, "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA256, "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee")

    def test_exact_100_labels_and_allowed_vocabulary(self):
        self.assertEqual(self.m.EXPECTED_ROWS, 100)
        self.assertEqual(self.m.ALLOWED_LABELS, ["TYDLIG_MERGE", "MÖJLIG_MERGE", "TVEKSAM", "BEHÅLL_GRÄNS", "EJ_BEDÖMBAR"])

    def test_script_never_opens_blind_key_file(self):
        self.assertNotIn("BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv", self.text)
        self.assertIn('"blind_key_contents_revealed": False', self.text)
        self.assertIn('"strata_joined": False', self.text)
        self.assertIn('"scores_joined": False', self.text)

    def test_no_fusion_or_sign_in_label_freeze(self):
        self.assertIn('"sign_selected": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"thresholds_tuned": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_LABELS_V1")


if __name__ == "__main__":
    unittest.main()
