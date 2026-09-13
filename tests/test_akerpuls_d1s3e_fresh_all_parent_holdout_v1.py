import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "146_akerpuls_d1s3e_fresh_all_parent_holdout_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3e_fresh_all_parent_holdout_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3e", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3EFreshAllParentHoldoutV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_scope_is_non_mutating_and_zero_process_pu(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3e-fresh-all-parent-holdout-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(
            self.cfg["expected_final_execution_contract_sha256"],
            "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19",
        )

    def test_backend_semantics_are_frozen_to_all_parent(self):
        sem = self.cfg["candidate_backend_semantics"]
        self.assertEqual(sem["scene_scope"], "ALL_ACQUISITIONS_RETURNED_BY_FROZEN_STAC_QUERY")
        self.assertEqual(sem["scene_order"], "PARENT")
        self.assertEqual(sem["coverage"], "SCL_NONZERO")
        self.assertEqual(sem["reflectance"], "SCALE_OFFSET")
        self.assertEqual(sem["resampling"], "NEAREST")
        self.assertTrue(sem["frozen_after_d1s3d_before_d1s3e_outcomes"])

    def test_holdout_is_30_fresh_unique_tiles(self):
        sel = self.cfg["selection"]
        self.assertEqual(sel["maximum_dates"], 3)
        self.assertEqual(sel["minimum_dates"], 3)
        self.assertEqual(sel["requests_per_date"], 10)
        self.assertTrue(sel["exclude_all_prior_tile_ids"])
        self.assertTrue(sel["require_unique_tile_ids_across_dates"])

    def test_acceptance_is_predeclared(self):
        a = self.cfg["acceptance"]
        self.assertTrue(a["frozen_before_holdout_outcomes"])
        self.assertEqual(a["request_ndvi_p99_max"], 0.002)
        self.assertEqual(a["request_lswi_p99_max"], 0.002)
        self.assertEqual(a["minimum_request_pass_fraction"], 0.90)
        self.assertEqual(a["aggregate_ndvi_p99_p90_max"], 0.002)
        self.assertEqual(a["aggregate_lswi_p99_p90_max"], 0.002)
        self.assertEqual(a["aggregate_ndvi_p99_max_max"], 0.01)
        self.assertEqual(a["aggregate_lswi_p99_max_max"], 0.01)

    def test_acceptance_helper(self):
        df = pd.DataFrame({
            "valid_ndvi_p99": [0.0001] * 9 + [0.003],
            "valid_lswi_p99": [0.0001] * 9 + [0.003],
            "valid_mask_agreement": [0.99] * 10,
            "scl_agreement_common_data": [0.999] * 10,
        })
        # 90% request pass, but p90 interpolates above 0.002 for this tiny toy frame;
        # helper must therefore reject on the independent aggregate criterion.
        result = self.m.evaluate_acceptance(df, self.cfg)
        self.assertEqual(result["request_pass_count"], 9)
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
