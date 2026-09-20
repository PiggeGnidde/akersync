import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "192_akerpuls_merge_blind_disagreement_audit_viewer_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("merge_audit_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestMergeBlindAuditViewerFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_and_parent_are_pinned(self):
        self.assertEqual(cls := self.m.EXPECTED_SOURCE_GIT_HEAD, "8e59dd6f83b5819bf5f5aab83fa1018521aa35bd")
        self.assertEqual(self.m.EXPECTED_M2_FREEZE_SHA256, "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859")

    def test_sample_and_blind_key_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_SAMPLE_POPULATION_SHA256, "c2e22aee44e012e11a77f76baec0218aec74557e644537c9d9e808a6cc2d39bb")
        self.assertEqual(self.m.EXPECTED_BLIND_KEY_SHA256, "706d800769ac2bd1eb9deb5ff6d035aaef2407b4586501bd2a0cfc5ad87feeee")
        self.assertEqual(self.m.EXPECTED_SAMPLE, 100)
        self.assertEqual(self.m.EXPECTED_PER_STRATUM, 25)

    def test_stratum_populations_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_STRATUM_COUNTS, {"HH": 1011, "HL": 54, "LH": 335, "LL": 533})

    def test_freeze_does_not_reveal_or_label(self):
        self.assertIn('"blind_key_contents_revealed": False', self.text)
        self.assertIn('"human_labels_created": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_selected": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_MERGE_BLIND_DISAGREEMENT_AUDIT_VIEWER_V1")


if __name__ == "__main__":
    unittest.main()
