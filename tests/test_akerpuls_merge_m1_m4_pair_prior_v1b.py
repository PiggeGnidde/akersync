import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "186_akerpuls_merge_m1_m4_pair_prior_v1b.py"

def load_module():
    spec = importlib.util.spec_from_file_location("m1_v1b", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m

class TestM1M4PairPriorV1B(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_freezes_unchanged(self):
        self.assertEqual(cls := self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA256, "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")

    def test_exact_pair_universe_unchanged(self):
        self.assertEqual(self.m.EXPECTED_PAIRS, 27146)

    def test_namespace_bridge_is_explicit_and_only_prefix_strip(self):
        self.assertIn('ss.str.startswith("2025|").all()', self.text)
        self.assertIn('ss.str.slice(start=5)', self.text)
        self.assertIn('m0_id_schema', self.text)
        self.assertIn('m4_id_schema', self.text)

    def test_m0_evidence_remains_unread(self):
        self.assertIn('usecols=["field_a", "field_b"]', self.text)
        self.assertIn('"m0_satellite_features_read": False', self.text)
        self.assertIn('"m0_status_read": False', self.text)
        self.assertIn('"fusion_executed": False', self.text)

    def test_both_id_namespaces_are_persisted(self):
        for col in ("field_a_m0", "field_b_m0", "field_a_m4", "field_b_m4"):
            self.assertIn(f'"{col}"', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_M1_M4_PAIR_PRIOR_V1B_FREEZE_REVIEW")

if __name__ == "__main__":
    unittest.main()
