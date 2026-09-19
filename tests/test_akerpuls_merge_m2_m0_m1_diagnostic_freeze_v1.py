import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "189_akerpuls_merge_m2_m0_m1_diagnostic_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("m2_freeze", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


class TestM2DiagnosticFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_source_and_parent_hashes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD, "2762f33752bb06a9b0e46426b224dccd6757bf65")
        self.assertEqual(self.m.EXPECTED_M0_FREEZE_SHA256, "fd2536789931cc51466364580b3f32de90da4e405217ee025fffc35fbe917051")
        self.assertEqual(self.m.EXPECTED_M1_FREEZE_SHA256, "5d39f6fea78260bd46cfa2aa99f8043abb02f1f67f57b73a9e30ae7273d9c20f")

    def test_key_output_hashes_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_JOIN_PARQUET_SHA256, "e4cfed6a9e2488a91eeaeea5535492d040ff972287b62bdb07fad702fba7137d")
        self.assertEqual(self.m.EXPECTED_SUMMARY_SHA256, "98c25b7c3a72282557e81f9b653f47336c71d798af75d4f649e158959c88b8d4")

    def test_census_and_key_stats_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_PAIRS, 27146)
        self.assertEqual(self.m.EXPECTED_ASSESSABLE, 22358)
        self.assertAlmostEqual(self.m.EXPECTED["p_samecrop_spearman"], 0.275425)
        self.assertEqual(self.m.EXPECTED["tail90_both"], 433)
        self.assertEqual(self.m.EXPECTED["tail95_both"], 93)

    def test_freeze_is_diagnostic_only(self):
        self.assertIn('"diagnostic_only": True', self.text)
        self.assertIn('"fusion_executed": False', self.text)
        self.assertIn('"sign_selected": False', self.text)
        self.assertIn('"human_labels_used": False', self.text)
        self.assertIn('"geometry_mutated": False', self.text)

    def test_status(self):
        self.assertEqual(self.m.STATUS, "FROZEN_AKERPULS_MERGE_M2_M0_M1_DIAGNOSTIC_V1")


if __name__ == "__main__":
    unittest.main()
