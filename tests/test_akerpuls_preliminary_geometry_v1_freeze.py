import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "165_akerpuls_preliminary_geometry_v1_freeze.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_preliminary_geometry_v1_freeze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsPreliminaryGeometryV1Freeze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()

    def test_exact_lineage_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_D2C_FREEZE_SHA256, "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950")
        self.assertEqual(self.m.EXPECTED_FIRST_HUMAN_AUDIT_FREEZE_SHA256, "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4")
        self.assertEqual(self.m.EXPECTED_PROPOSAL_FREEZE_SHA256, "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.m.EXPECTED_GEOMETRY_AUDIT_FREEZE_SHA256, "089cd1d90daa9252e93ddbe4004c7afad5f0c00ec8d54293b43fc6915e4983f0")

    def test_product_census_is_locked(self):
        self.assertEqual((self.m.EXPECTED_P95, self.m.EXPECTED_LINE_AVAILABLE, self.m.EXPECTED_NO_INTERFACE), (618, 613, 5))
        self.assertEqual(self.m.POLICY["line_available_status"], "PRELIM_2026_SPLIT_PROPOSAL")
        self.assertEqual(self.m.POLICY["no_shared_interface_status"], "NO_GEOMETRY_PROPOSAL")

    def test_validation_evidence_is_locked(self):
        self.assertEqual((self.m.EXPECTED_FIRST_AUDIT_P95_STRICT, self.m.EXPECTED_FIRST_AUDIT_P95_BROAD, self.m.EXPECTED_FIRST_AUDIT_P95_N), (19, 39, 50))
        self.assertEqual((self.m.EXPECTED_LINE_STRICT_ON_SPLIT, self.m.EXPECTED_LINE_BROAD_ON_SPLIT, self.m.EXPECTED_LINE_WRONG_ON_SPLIT, self.m.EXPECTED_GEOM_SPLIT_POSITIVE), (73, 78, 2, 80))

    def test_v1_policy_keeps_official_geometry_canonical(self):
        p = self.m.POLICY
        self.assertEqual(p["canonical_geometry"], "OFFICIAL_2025_GEOMETRY")
        self.assertEqual(p["proposal_geometry_method"], "LONGEST_CONTIGUOUS_RAW_10M_K2_INTERFACE")
        self.assertTrue(p["proposal_is_review_only"])
        self.assertFalse(p["smoothing"])
        self.assertFalse(p["gap_filling"])
        self.assertFalse(p["automatic_geometry_replacement"])
        self.assertFalse(p["merge_automation"])
        self.assertFalse(p["human_audit_labels_used_as_per_field_product_gate"])

    def test_source_has_no_model_or_geometry_generation_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("geopandas", text)
        self.assertNotIn("rasterio", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("to_file(", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("boto3", text)

    def test_status_and_version_boundary_are_explicit(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("FROZEN_AKERPULS_PRELIMINARY_GEOMETRY_V1", text)
        self.assertIn("future_smoothing_or_confidence_filter_requires_new_version", text)
        self.assertIn("future_automatic_geometry_adoption_requires_new_policy_and_validation", text)
        self.assertIn("NEXT=DOWNSTREAM_USE_AS_REVIEW_ONLY_PRELIMINARY_2026_GEOMETRY", text)


if __name__ == "__main__":
    unittest.main()
