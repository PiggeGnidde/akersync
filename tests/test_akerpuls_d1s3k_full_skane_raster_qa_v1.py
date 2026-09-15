import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "152_akerpuls_d1s3k_full_skane_raster_qa_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3k_full_skane_raster_qa_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3k", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3KFullSkaneRasterQAV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_scope_is_zero_network_and_no_model(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3k-full-skane-raster-qa-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("download_assets", text)
        self.assertNotIn("fetch_tiff", text)
        self.assertNotIn("deterministic_k2", text)

    def test_parent_output_indexes_are_pinned(self):
        self.assertEqual(self.cfg["required_d1s3j_status"], "PASS_TO_FULL_SKANE_D1_RASTER_QA")
        self.assertEqual(self.cfg["expected_snapshot_output_index_sha256"], "a3a26d1f454a8c0d65e326a913b0d10d91c54d4ba9886315ec5d5dd1e35cafff")
        self.assertEqual(self.cfg["expected_vrt_output_index_sha256"], "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979")

    def test_frozen_domain_and_b2_reference(self):
        e = self.cfg["expected"]
        self.assertEqual(e["fields"], 128636)
        self.assertEqual(e["raster_tiles"], 142)
        self.assertEqual(e["snapshot_tiles"], 568)
        self.assertEqual(e["snapshot_count"], 4)
        self.assertEqual(e["minimum_b2_valid_pixels"], 24)
        self.assertEqual(e["resolution_m"], 10)

    def test_acceptance_is_predeclared_and_coverage_not_geometry_mutation(self):
        a = self.cfg["acceptance"]
        self.assertTrue(a["frozen_before_full_skane_field_validity_outcomes"])
        self.assertEqual(a["minimum_fraction_fields_rasterized"], 0.999)
        self.assertEqual(a["minimum_field_pixel_valid_fraction_each_snapshot"], 0.60)
        self.assertEqual(a["minimum_field_pixel_all4_valid_fraction"], 0.45)
        self.assertEqual(a["minimum_fraction_fields_with_at_least_24_all4_valid_pixels"], 0.70)
        self.assertIn("pre-B2 coverage screen", self.cfg["interpretation"])

    def test_quantile_helper(self):
        self.assertAlmostEqual(self.m.q(np.array([1.0, 2.0, 3.0]), 0.5), 2.0)
        self.assertTrue(np.isnan(self.m.q(np.array([np.nan]), 0.5)))

    def test_geometry_hash_is_pinned(self):
        self.assertEqual(self.cfg["expected_geometry_sha256"], "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706")


if __name__ == "__main__":
    unittest.main()
