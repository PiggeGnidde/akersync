import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "149_akerpuls_d1s3h_c5_independent_e2e_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3h_c5_independent_e2e_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3h", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3HC5IndependentE2EV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_scope_is_zero_process_and_nonmutating(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3h-c5-backend-confirmation-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(self.cfg["expected_c5_fields"], 1000)
        self.assertEqual(self.cfg["expected_legacy_c5"]["baseline_split_candidates"], 141)
        self.assertEqual(self.cfg["expected_legacy_c5"]["locked_split_candidates"], 21)
        self.assertEqual(self.cfg["expected_legacy_c5"]["uncertain"], 4)

    def test_backend_semantics_remain_d1s3e_all_parent(self):
        s = self.cfg["candidate_backend_semantics"]
        self.assertEqual(s["scene_order"], "PARENT")
        self.assertEqual(s["coverage"], "SCL_NONZERO")
        self.assertEqual(s["reflectance"], "SCALE_OFFSET")
        self.assertEqual(s["resampling"], "NEAREST")
        self.assertTrue(s["frozen_from_d1s3e"])
        self.assertEqual(self.cfg["empty_frozen_date_policy"], "ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0")

    def test_post_c7_acceptance_is_frozen_and_outcome_relevant(self):
        a = self.cfg["acceptance"]
        self.assertTrue(a["frozen_before_c5_s3_outcomes"])
        self.assertTrue(a["global_low_tier_fusion_max_is_not_an_acceptance_metric"])
        self.assertEqual(a["fusion_score_abs_diff_p95_max"], 0.01)
        self.assertEqual(a["fusion_priority_union_abs_diff_max"], 0.03)
        self.assertEqual(a["fusion_priority_union_noncommon_candidates_max"], 0)
        self.assertNotIn("fusion_score_abs_diff_max", a)
        self.assertEqual(a["fusion_p90_symmetric_difference_max"], 2)
        self.assertEqual(a["fusion_p95_symmetric_difference_max"], 1)

    def test_fusion_freeze_is_unchanged(self):
        self.assertEqual(
            self.cfg["expected_fusion_freeze_sha256"],
            "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316",
        )
        fp = self.cfg["frozen_fusion_pipeline"]
        self.assertEqual(fp["development_p90"], 0.781017)
        self.assertEqual(fp["development_p95"], 0.843688)
        self.assertEqual(fp["locked_split_rule"]["minimum_largest_component_fraction_each_child"], 0.95)

    def test_helpers(self):
        self.assertEqual(self.m.jaccard(set(), set()), 1.0)
        self.assertAlmostEqual(self.m.jaccard({"a", "b"}, {"b", "c"}), 1 / 3)
        self.assertEqual(self.m.finite_max([], empty=0.0), 0.0)

    def test_no_process_api_execution_symbols(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("fetch_tiff(", text)
        self.assertNotIn("oauth(", text)
        self.assertIn("download_assets", text)
        self.assertIn("fusion_priority_union_abs_diff_max", text)


if __name__ == "__main__":
    unittest.main()
