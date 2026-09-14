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

    def test_zero_scene_source_eligibility_is_pre_outcome_and_nonadaptive(self):
        s = self.cfg["source_eligibility"]
        self.assertEqual(s["minimum_stac_scenes"], 1)
        self.assertEqual(
            s["on_zero_stac_scenes"],
            "REPLACE_WITH_SAME_DATE_DETERMINISTIC_FARTHEST_FROM_CURRENT_SELECTION",
        )
        self.assertFalse(s["replacement_may_use_parity_metrics"])
        self.assertFalse(s["replacement_may_change_date"])
        self.assertTrue(s["replacement_must_preserve_global_tile_uniqueness"])
        self.assertTrue(s["frozen_after_zero_scene_block_before_any_d1s3e_parity_outcomes"])

    def test_no_scene_error_detection_is_narrow(self):
        self.assertTrue(self.m.is_no_stac_scene_error(RuntimeError("No STAC scenes for 2026-04-09 / T")))
        self.assertFalse(self.m.is_no_stac_scene_error(RuntimeError("other error")))
        self.assertFalse(self.m.is_no_stac_scene_error(ValueError("No STAC scenes for 2026-04-09 / T")))

    def test_same_date_replacement_is_deterministic_and_respects_forbidden(self):
        cached = pd.DataFrame([
            {"date":"2026-04-09","tile_id":"A","minx":0,"maxx":10,"miny":0,"maxy":10},
            {"date":"2026-04-09","tile_id":"B","minx":100,"maxx":110,"miny":0,"maxy":10},
            {"date":"2026-04-09","tile_id":"C","minx":0,"maxx":10,"miny":100,"maxy":110},
            {"date":"2026-04-09","tile_id":"D","minx":100,"maxx":110,"miny":100,"maxy":110},
            {"date":"2026-05-25","tile_id":"Z","minx":1000,"maxx":1010,"miny":1000,"maxy":1010},
        ])
        current = pd.DataFrame([
            {"date":"2026-04-09","tile_id":"A","minx":0,"maxx":10,"miny":0,"maxy":10},
        ])
        one = self.m.deterministic_same_date_replacement(cached, "2026-04-09", current, {"A","B"})
        two = self.m.deterministic_same_date_replacement(cached.sample(frac=1, random_state=4), "2026-04-09", current, {"A","B"})
        self.assertEqual(str(one.tile_id), "D")
        self.assertEqual(str(two.tile_id), "D")

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
        # With the same per-request threshold and a >=90% pass-fraction rule,
        # an interpolated P90 cannot be forced above that same threshold while
        # still keeping >=90% of observations at/below threshold. Test an
        # independent aggregate MAX guard instead: 10/11 requests pass (~90.9%),
        # P90 remains good, but one extreme outlier above 0.01 must fail overall.
        df = pd.DataFrame({
            "valid_ndvi_p99": [0.0001] * 10 + [0.0200],
            "valid_lswi_p99": [0.0001] * 10 + [0.0200],
            "valid_mask_agreement": [0.99] * 11,
            "scl_agreement_common_data": [0.999] * 11,
        })
        result = self.m.evaluate_acceptance(df, self.cfg)
        self.assertEqual(result["request_pass_count"], 10)
        self.assertGreaterEqual(result["request_pass_fraction"], 0.90)
        self.assertTrue(result["checks"]["request_pass_fraction"])
        self.assertTrue(result["checks"]["ndvi_p90"])
        self.assertTrue(result["checks"]["lswi_p90"])
        self.assertFalse(result["checks"]["ndvi_max"])
        self.assertFalse(result["checks"]["lswi_max"])
        self.assertFalse(result["pass"])


if __name__ == "__main__":
    unittest.main()
