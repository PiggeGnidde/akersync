import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "160_akerpuls_d2c_p95_split_line_review_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("p95_split_line_review", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CP95SplitLineReviewV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_frozen_lineage_is_pinned(self):
        self.assertEqual(
            self.m.EXPECTED_D2C_FREEZE_SHA256,
            "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950",
        )
        self.assertEqual(
            self.m.EXPECTED_AUDIT_FREEZE_SHA256,
            "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4",
        )
        self.assertEqual(self.m.EXPECTED_P95, 618)

    def test_human_labels_cannot_select_or_shape_geometry(self):
        self.assertNotIn("d2c_visual_audit_labels.csv", self.text)
        self.assertNotIn("BLIND_KEY_DO_NOT_OPEN_BEFORE_REVIEW.csv", self.text)
        self.assertIn("HUMAN_AUDIT_LABELS_USED=FALSE", self.text)
        self.assertIn("EXACT_FROZEN_D2C_P95_TIER", self.text)

    def test_reuses_d2a_owner_rasterization_and_frozen_b2_geometry(self):
        self.assertIn("owner_ids = sorted(", self.text)
        self.assertIn("read_owner_cell_arrays", self.text)
        self.assertIn("b2.deterministic_k2", self.text)
        self.assertIn("b2.largest_component", self.text)
        self.assertIn("b2.mask_geom", self.text)
        self.assertIn("reconstructed frozen D2A metrics mismatch", self.text)

    def test_primary_line_is_raw_interface_without_smoothing(self):
        from shapely.geometry import box
        raw, primary, nfrag, raw_len, primary_len = self.m.raw_and_primary_interface(
            box(0, 0, 1, 1), box(1, 0, 2, 1)
        )
        self.assertIsNotNone(raw)
        self.assertIsNotNone(primary)
        self.assertEqual(nfrag, 1)
        self.assertAlmostEqual(raw_len, 1.0)
        self.assertAlmostEqual(primary_len, 1.0)
        self.assertIn('"smoothing": False', self.text)
        self.assertIn('"gap_filling": False', self.text)

    def test_disconnected_geometries_do_not_get_invented_connector(self):
        from shapely.geometry import box
        raw, primary, nfrag, raw_len, primary_len = self.m.raw_and_primary_interface(
            box(0, 0, 1, 1), box(2, 0, 3, 1)
        )
        self.assertIsNone(raw)
        self.assertIsNone(primary)
        self.assertEqual(nfrag, 0)
        self.assertEqual(raw_len, 0.0)
        self.assertEqual(primary_len, 0.0)

    def test_review_only_guards_are_explicit(self):
        self.assertIn("OFFICIAL_2025_GEOMETRY_REPLACED=FALSE", self.text)
        self.assertIn("AUTOMATIC_GEOMETRY_MUTATION=FALSE", self.text)
        self.assertIn("MODEL_REFIT=FALSE", self.text)
        self.assertIn("THRESHOLDS_TUNED=FALSE", self.text)
        self.assertIn("MERGE_EXECUTED=FALSE", self.text)


if __name__ == "__main__":
    unittest.main()
