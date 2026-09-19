import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "187_akerpuls_merge_m1_m4_pair_prior_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m1_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM1M4PairPriorFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_and_parent_freezes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD, "7741eecd6500265e8476f65894e3aa85d5b45255")
        self.assertEqual(self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_M4_FREEZE_SHA256, "61766d03b238d792c773664d40493b184a69823f984f3b7915185dbcda330f95")

    def test_source_artifact_hashes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_PARQUET_SHA256, "a2e6c2d091ad3b71b9112dea2627704c2d966fdb178a295db6af66df0c55a9f4")
        self.assertEqual(self.m.EXPECTED_CSV_GZ_SHA256, "7ba95180ff0c08a40af60ddd52e0ccd7fe97afa4e790f2c0e462dddef4a4c27e")
        self.assertEqual(self.m.EXPECTED_SUMMARY_SHA256, "a639d1acf7e761ce99053195387ef50878020be951f6689cc4e8f0590d532520")

    def test_pair_descriptive_census_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_PAIRS, 27146)
        self.assertEqual(self.m.EXPECTED_TOP1_SAME, 8195)
        self.assertEqual(self.m.EXPECTED_TOP3_OVERLAP_COUNTS, {0: 8257, 1: 6151, 2: 7686, 3: 5052})
        self.assertEqual(sum(self.m.EXPECTED_TOP3_OVERLAP_COUNTS.values()), 27146)

    def test_no_fusion_or_decision_in_freeze(self):
        low = self.text.lower()
        self.assertNotIn("satellite_merge_score", low.split("def verify_source")[0])
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_assumption_for_merge": False', self.text)
        self.assertIn('"candidate_or_merge_decision_created": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_exact_namespace_bridge_is_verified(self):
        self.assertIn('str.slice(5) == df["field_a_m4"]', self.text)
        self.assertIn('str.slice(5) == df["field_b_m4"]', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_MERGE_M1_M4_PAIR_PRIOR_V1")


if __name__ == "__main__":
    unittest.main()
