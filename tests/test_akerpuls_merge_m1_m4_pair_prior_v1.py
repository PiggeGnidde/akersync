import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "185_akerpuls_merge_m1_m4_pair_prior_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m1_m4_pair_prior", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM1M4PairPriorV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_parent_freezes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA256, "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")

    def test_pair_and_field_census_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_PAIRS, 27146)
        self.assertEqual(self.m.EXPECTED_FIELDS, 128636)
        self.assertEqual(len(self.m.CLASSES), 16)

    def test_m1_reads_only_pair_identity_from_m0(self):
        self.assertIn('usecols=["field_a", "field_b"]', self.text)
        self.assertNotIn('usecols=["field_a", "field_b", "m0_status"', self.text)

    def test_no_fusion_or_merge_decision(self):
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_assumption_for_merge": False', self.text)
        self.assertIn('"automatic_merge": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_p_samecrop_and_js_are_defined(self):
        self.assertIn("p_same = np.sum(pa * pb, axis=1)", self.text)
        self.assertIn("js_divergence", self.text)
        self.assertIn("probability_overlap_mass", self.text)

    def test_status_stops_before_fusion(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_M1_M4_PAIR_PRIOR_FREEZE_REVIEW")


if __name__ == "__main__":
    unittest.main()
