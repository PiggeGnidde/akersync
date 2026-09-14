import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "151_akerpuls_d1s3j_full_skane_s3_acquisition_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3j_full_skane_s3_acquisition_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3j", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3JFullSkaneS3AcquisitionV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_contract_hash_and_scope_are_frozen(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3j-full-skane-s3-acquisition-v1")
        self.assertEqual(
            self.cfg["expected_full_skane_s3_execution_contract_sha256"],
            "9764672a66938f7526c8cca9ab2140ec205d4ad993f798239b627c17c559bbc8",
        )
        self.assertEqual(self.cfg["required_d1s3i_status"], "PASS_TO_FULL_SKANE_S3_ACQUISITION")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))

    def test_frozen_domain_counts(self):
        e = self.cfg["expected"]
        self.assertEqual(e["scene_items"], 29)
        self.assertEqual(e["scene_assets"], 203)
        self.assertEqual(e["daily_tile_dates"], 593)
        self.assertEqual(e["frozen_zero_tile_dates"], 259)
        self.assertEqual(e["raster_tiles"], 142)
        self.assertEqual(e["snapshot_tiles"], 568)
        self.assertEqual(e["snapshot_count"], 4)
        self.assertEqual(e["daily_bands"], 8)
        self.assertEqual(e["snapshot_bands"], 11)

    def test_backend_is_validated_all_parent(self):
        b = self.cfg["backend"]
        self.assertEqual(b["scene_order"], "PARENT")
        self.assertEqual(b["coverage"], "SCL_NONZERO")
        self.assertEqual(b["reflectance"], "SCALE_OFFSET")
        self.assertEqual(b["resampling"], "NEAREST")
        self.assertEqual(b["clear_scl_codes"], [2, 4, 5])
        self.assertEqual(b["empty_daily_tile_policy"], "ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0")

    def test_execution_is_resumable_and_stac_process_forbidden(self):
        e = self.cfg["execution"]
        self.assertTrue(e["never_query_stac"])
        self.assertTrue(e["never_call_process_api"])
        self.assertTrue(e["never_read_process_tiles_as_source"])
        self.assertTrue(e["daily_outputs_are_resumable_with_sha256_sidecars"])
        self.assertTrue(e["snapshot_outputs_are_resumable_with_sha256_sidecars"])
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urlopen(", text)
        self.assertNotIn("query_date(", text)
        self.assertNotIn("fetch_tiff(", text)
        self.assertIn("download_assets", text)

    def test_date_and_snapshot_order_helpers(self):
        self.assertEqual(
            self.m.canonical_dates(["2026-07-09", "2026-04-08", "2026-06-27"]),
            ["2026-04-08", "2026-06-27", "2026-07-09"],
        )
        c = {"frozen_snapshots": {
            "S2_2026_JULY": ["2026-07-09"],
            "S2_2026_APRIL": ["2026-04-08", "2026-04-09"],
            "S2_2026_JUNE": ["2026-06-26", "2026-06-27"],
            "S2_2026_MAY": ["2026-05-25"],
        }}
        self.assertEqual(self.m.snapshot_order(c), ["S2_2026_APRIL", "S2_2026_MAY", "S2_2026_JUNE", "S2_2026_JULY"])

    def test_output_key_is_deterministic(self):
        a = self.m.sha256_obj({"tile": "x", "scenes": ["a", "b"]})
        b = self.m.sha256_obj({"scenes": ["a", "b"], "tile": "x"})
        c = self.m.sha256_obj({"tile": "x", "scenes": ["b", "a"]})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
