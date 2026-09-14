import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "147_akerpuls_d1s3f_c7_end_to_end_parity_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3f_c7_end_to_end_parity_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3f", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3FC7EndToEndParityV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_zero_process_nonmutating_scope(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3f-c7-end-to-end-parity-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(self.cfg["expected_c7_fields"], 1000)
        self.assertEqual(self.cfg["expected_fusion_freeze_sha256"], "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316")

    def test_backend_is_exact_d1s3e_all_parent(self):
        s = self.cfg["candidate_backend_semantics"]
        self.assertEqual(s["scene_scope"], "ALL_ACQUISITIONS_RETURNED_BY_FROZEN_STAC_QUERY")
        self.assertEqual(s["scene_order"], "PARENT")
        self.assertEqual(s["coverage"], "SCL_NONZERO")
        self.assertEqual(s["reflectance"], "SCALE_OFFSET")
        self.assertEqual(s["resampling"], "NEAREST")
        self.assertTrue(s["frozen_from_d1s3e"])

    def test_acceptance_is_frozen_before_c7_s3_outcomes(self):
        a = self.cfg["acceptance"]
        self.assertTrue(a["frozen_before_s3_c7_outcomes"])
        self.assertEqual(a["field_discovery_exact_agreement_min"], 0.995)
        self.assertEqual(a["baseline_candidate_jaccard_min"], 0.97)
        self.assertEqual(a["fusion_p90_symmetric_difference_max"], 2)
        self.assertEqual(a["fusion_p95_symmetric_difference_max"], 1)
        self.assertEqual(a["reference_p95_falling_below_s3_p90_max"], 0)

    def test_jaccard_helper(self):
        self.assertEqual(self.m.jaccard(set(), set()), 1.0)
        self.assertAlmostEqual(self.m.jaccard({"a", "b"}, {"b", "c"}), 1/3)

    def test_zero_scene_policy_is_explicit_and_empty_source_is_zero(self):
        self.assertEqual(
            self.cfg["empty_frozen_date_policy"],
            "ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0",
        )
        arr = self.m.empty_daily_source(3, 4)
        self.assertEqual(arr.shape, (8, 3, 4))
        self.assertEqual(arr.dtype, np.float32)
        self.assertTrue(np.all(arr == 0.0))
        self.assertTrue(np.all(arr[7] == 0.0))

    def test_only_exact_no_scene_error_is_treated_as_empty(self):
        row = SimpleNamespace(date="2026-04-09", tile_id="C7_FULL")
        self.assertTrue(self.m.is_no_scene_error(RuntimeError("No STAC scenes for 2026-04-09 / C7_FULL"), row))
        self.assertFalse(self.m.is_no_scene_error(RuntimeError("HTTP 503"), row))
        self.assertFalse(self.m.is_no_scene_error(RuntimeError("No STAC scenes for 2026-04-08 / C7_FULL"), row))

    def test_no_process_api_symbols_in_execution_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("fetch_tiff(", text)
        self.assertNotIn("oauth(", text)
        self.assertIn("download_assets", text)


if __name__ == "__main__":
    unittest.main()
