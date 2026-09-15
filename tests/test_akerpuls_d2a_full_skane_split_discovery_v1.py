import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "154_akerpuls_d2a_full_skane_split_discovery_v1.py"
CFG = ROOT / "config" / "akerpuls_d2a_full_skane_split_discovery_v1.json"
B2CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_b2.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d2a", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2AFullSkaneSplitDiscoveryV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        cls.b2 = json.loads(B2CFG.read_text(encoding="utf-8"))

    def test_parent_plan_hashes_are_pinned(self):
        p = self.cfg["parent_d2_plan"]
        self.assertEqual(p["required_status"], "PASS_TO_D2A_SPLIT_DISCOVERY_EXECUTION")
        self.assertEqual(p["expected_execution_contract_sha256"], "83bf7a03860a5b164b104ae49918593fa0852b59d91f7691b2ce2534a669c756")
        self.assertEqual(p["expected_cell_plan_sha256"], "e4c50ee0433adb566431f301a6dc24eb5c29a2749dae984d86fe7ed7b5c396f1")

    def test_scope_is_d2a_only_and_d2b_blocked(self):
        e = self.cfg["execution"]
        self.assertEqual(e["stage"], "D2A_ONLY")
        self.assertTrue(e["stop_after_d2a"])
        self.assertTrue(e["d2b_requires_separate_authorization"])
        self.assertFalse(e["merge_discovery"])
        self.assertFalse(e["true_loo"])
        self.assertFalse(e["history_prior"])
        self.assertFalse(e["fusion"])
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))

    def test_frozen_full_skane_domain(self):
        e = self.cfg["expected"]
        self.assertEqual(e["fields"], 128636)
        self.assertEqual(e["analysis_cells"], 46)
        self.assertEqual(e["minimum_normalization_fields"], 200)
        self.assertEqual(e["minimum_b2_valid_pixels"], 24)
        self.assertEqual(e["pre_b2_ge24_all4_fields_from_d1s3k"], 99735)
        self.assertEqual(e["zero_raster_pixel_fields_from_d1s3k"], 39)

    def test_b2_split_thresholds_are_not_redeclared_differently(self):
        sp = self.b2["split"]
        self.assertEqual(sp["interior_erosion_pixels"], 1)
        self.assertEqual(sp["minimum_valid_pixels"], 24)
        self.assertEqual(sp["minimum_child_pixels"], 30)
        self.assertAlmostEqual(sp["minimum_child_fraction"], 0.20)
        self.assertAlmostEqual(sp["minimum_spatial_coherence"], 0.80)
        self.assertAlmostEqual(sp["minimum_total_separation_ratio"], 1.80)
        self.assertAlmostEqual(sp["snapshot_support_ratio"], 1.25)
        self.assertEqual(sp["minimum_supporting_snapshots"], 2)

    def test_normalization_contract_matches_d2_plan(self):
        e = self.cfg["execution"]
        self.assertEqual(e["normalization_population"], "FULL_2025_FIELD_PIXELS_FOR_ALL_FIELDS_INTERSECTING_EXACT_D0B_RESOLVED_WINDOW")
        self.assertEqual(e["normalization_validity"], "FOUR_SNAPSHOT_VALID_INTERSECTION")
        self.assertIn("ROBUST_MEDIAN_MAD", e["normalization_method"])
        self.assertEqual(e["owner_output_rule"], "ONLY_FIELDS_OWNED_BY_ANALYSIS_CELL_PRODUCE_FINAL_ROWS")

    def test_geometry_repair_is_raster_only_and_bounded(self):
        g = self.cfg["projection_geometry_policy"]
        self.assertTrue(g["require_source_geometry_valid_before_reprojection"])
        self.assertTrue(g["repair_invalid_projected_geometry_for_raster_operations_only"])
        self.assertEqual(g["maximum_absolute_area_change_m2"], 1.0)
        self.assertEqual(g["maximum_relative_area_change"], 0.000001)
        self.assertFalse(g["persist_repaired_geometry"])
        self.assertFalse(g["automatic_geometry_replacement"])

    def test_source_has_no_network_or_later_stage_imports(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("download_assets", text)
        self.assertNotIn("process_dataset(", text)
        self.assertNotIn("empirical_midrank", text)


if __name__ == "__main__":
    unittest.main()
