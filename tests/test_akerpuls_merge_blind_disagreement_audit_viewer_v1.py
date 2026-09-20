import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "190_akerpuls_merge_blind_disagreement_audit_viewer_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("merge_audit", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestMergeBlindDisagreementAuditViewerV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_m2_freeze_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_M2_FREEZE_SHA256,
            "54a567c2a198e9724761f131d6fb6b438b3df897358f461cc41349cf4175c859",
        )
        self.assertEqual(
            self.m.EXPECTED_M2_JOIN_SHA256,
            "e4cfed6a9e2488a91eeaeea5535492d040ff972287b62bdb07fad702fba7137d",
        )

    def test_predeclared_sample_is_4x25_extreme_deciles(self):
        self.assertEqual(self.m.SAMPLE_PER_STRATUM, 25)
        self.assertEqual(self.m.EXPECTED_SAMPLE, 100)
        self.assertEqual(self.m.HIGH_Q, 0.90)
        self.assertEqual(self.m.LOW_Q, 0.10)
        for s in ("HH", "HL", "LH", "LL"):
            self.assertIn(f'"{s}"', self.text)

    def test_blindness_and_no_fusion(self):
        self.assertIn('"scores_visible": False', self.text)
        self.assertIn('"stratum_visible": False', self.text)
        self.assertIn('"pair_id_visible": False', self.text)
        self.assertIn('"m0_status_visible": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_selected": False', self.text)

    def test_labels_and_same_crop_warning(self):
        self.assertEqual(
            self.m.LABELS,
            ["TYDLIG_MERGE", "MÖJLIG_MERGE", "TVEKSAM", "BEHÅLL_GRÄNS", "EJ_BEDÖMBAR"],
        )
        self.assertIn("samma gröda/färg på båda sidor räcker inte i sig för merge", self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_BLIND_MERGE_DISAGREEMENT_AUDIT")


if __name__ == "__main__":
    unittest.main()
