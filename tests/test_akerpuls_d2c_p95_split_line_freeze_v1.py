import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "161_akerpuls_d2c_p95_split_line_freeze_v1.py"
TEXT = SRC.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)


class TestAkerPulsD2CP95SplitLineFreezeV1(unittest.TestCase):
    def test_lineage_and_census_are_locked(self):
        self.assertIn('EXPECTED_D2C_FREEZE_SHA256 = "60b021a5eef2483b54ea8d369ebbc7752c164ac51b113eb7faa524c9552be950"', TEXT)
        self.assertIn('EXPECTED_HUMAN_AUDIT_FREEZE_SHA256 = "5b5bc1d5c427d8a1c8fb54d03643cbb975cc4064c57d9086f69104b1864f9be4"', TEXT)
        self.assertIn("EXPECTED_P95_FIELDS = 618", TEXT)
        self.assertIn("EXPECTED_LINE_AVAILABLE = 613", TEXT)
        self.assertIn("EXPECTED_NO_INTERFACE = 5", TEXT)
        self.assertIn("EXPECTED_CHILD_FEATURES = 1236", TEXT)

    def test_source_output_set_is_exact(self):
        for name in (
            "p95_split_proposal_summary.csv",
            "p95_b2_child_evidence_review.gpkg",
            "p95_official_2025_parents_review.gpkg",
            "p95_raw_k2_interface_review.gpkg",
            "p95_primary_split_line_review.gpkg",
        ):
            self.assertIn(name, TEXT)
        self.assertIn("if set(outputs) != REQUIRED_SOURCE_OUTPUTS", TEXT)
        self.assertIn("Source proposal output hash changed", TEXT)

    def test_geometry_contract_is_locked(self):
        self.assertIn("EXACT_D2A_B2_DETERMINISTIC_K2_WITH_ALL_OWNER_FIELD_RASTERIZATION", TEXT)
        self.assertIn("FROZEN_B2_LARGEST_CONNECTED_COMPONENT_MASK_GEOM", TEXT)
        self.assertIn("SHARED_BOUNDARY_OF_FULL_K2_10M_PIXEL_LABEL_POLYGONS", TEXT)
        self.assertIn("LONGEST_CONTIGUOUS_PART_OF_RAW_INTERFACE", TEXT)
        self.assertRegex(TEXT, r'"smoothing": False')
        self.assertRegex(TEXT, r'"gap_filling": False')

    def test_freeze_is_separate_and_immutable(self):
        self.assertIn('SOURCE_DIRNAME = "d2c_p95_split_line_review_v1"', TEXT)
        self.assertIn('OUTPUT_DIRNAME = "d2c_p95_split_line_freeze_v1"', TEXT)
        self.assertIn("if out.exists():", TEXT)
        self.assertIn("verify_existing_freeze(out)", TEXT)
        self.assertNotIn("shutil.rmtree", TEXT)
        self.assertNotIn("unlink()", TEXT)

    def test_no_model_or_geometry_generation_path(self):
        forbidden_imports = {"rasterio", "geopandas", "shapely", "scipy", "sklearn"}
        imported = set()
        for node in ast.walk(TREE):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(forbidden_imports.isdisjoint(imported), imported & forbidden_imports)
        for token in ("deterministic_k2(", "mask_geom(", "raw_and_primary_interface(", ".to_file("):
            self.assertNotIn(token, TEXT)

    def test_review_guards_are_locked(self):
        for token in (
            '"model_executed": False',
            '"thresholds_tuned": False',
            '"fusion_refit": False',
            '"merge_executed": False',
            '"official_2025_geometry_replaced": False',
            '"automatic_geometry_mutation": False',
            '"review_only": True',
        ):
            self.assertIn(token, TEXT)
        self.assertIn("NEXT=BLIND_100_FIELD_LINE_GEOMETRY_AUDIT_VIEWER", TEXT)


if __name__ == "__main__":
    unittest.main()
