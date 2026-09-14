import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "150_akerpuls_d1s3i_full_skane_s3_plan_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3i_full_skane_s3_plan_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3i", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3IFullSkaneS3PlanV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_scope_is_plan_only_zero_process_zero_s3_objects(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3i-full-skane-s3-plan-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        p = self.cfg["planning"]
        self.assertTrue(p["no_asset_downloads"])
        self.assertTrue(p["no_s3_object_calls"])
        self.assertTrue(p["no_process_api_calls"])
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("download_file(", text)
        self.assertNotIn("download_assets(", text)
        self.assertNotIn("boto3", text)

    def test_frozen_full_skane_domain_is_unchanged(self):
        e = self.cfg["expected"]
        self.assertEqual(e["fields"], 128636)
        self.assertEqual(e["raster_tiles"], 142)
        self.assertEqual(e["snapshot_tiles"], 568)
        self.assertEqual(e["daily_tile_date_rows"], 593)
        self.assertEqual(e["frozen_dates"], [
            "2026-04-08", "2026-04-09", "2026-05-25",
            "2026-06-26", "2026-06-27", "2026-07-09",
        ])

    def test_backend_semantics_are_frozen_d1s3h_semantics(self):
        b = self.cfg["direct_s3_backend"]
        self.assertEqual(b["scene_order"], "PARENT")
        self.assertEqual(b["coverage"], "SCL_NONZERO")
        self.assertEqual(b["reflectance"], "SCALE_OFFSET")
        self.assertEqual(b["resampling"], "NEAREST")
        self.assertEqual(b["clear_scl_codes"], [2, 4, 5])
        self.assertEqual(b["empty_daily_tile_policy"], "ZERO_FILLED_FLOAT32_SOURCE_WITH_DATAMASK_0")
        self.assertTrue(b["frozen_from_d1s3e_and_confirmed_d1s3h"])

    def test_exact_scene_inventory_is_frozen_for_later_execution(self):
        p = self.cfg["planning"]
        self.assertTrue(p["freeze_exact_scene_ids_assets_and_tile_scene_mapping_for_execution"])
        self.assertIn("ONE_PUBLIC_STAC_BBOX_QUERY_PER_FROZEN_DATE", p["query_strategy"])
        self.assertIn("NEVER_READ_AS_SOURCE", self.cfg["direct_s3_backend"]["process_cache_policy"])

    def test_parent_hash_and_status_are_pinned(self):
        self.assertEqual(self.cfg["required_d1s3h_status"], "PASS_TO_FULL_SKANE_S3_PLAN")
        self.assertEqual(
            self.cfg["expected_final_execution_contract_sha256"],
            "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19",
        )

    def test_query_signature_is_deterministic(self):
        bbox = [12.0, 55.0, 14.0, 57.0]
        a = self.m._query_signature(self.cfg, "2026-04-08", bbox)
        b = self.m._query_signature(self.cfg, "2026-04-08", bbox)
        c = self.m._query_signature(self.cfg, "2026-04-09", bbox)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
