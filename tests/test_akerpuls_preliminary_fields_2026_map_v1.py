import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "166_akerpuls_preliminary_fields_2026_map_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_prelim_2026_map", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsPreliminaryFields2026MapV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_frozen_lineage_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_PRELIM_V1_FREEZE_SHA256, "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376")
        self.assertEqual(self.m.EXPECTED_PROPOSAL_FREEZE_SHA256, "d3a06356fdd941b47c713535c1f00b388b09a4f23f61acf276528c8f5929e30a")
        self.assertEqual(self.m.EXPECTED_OFFICIAL_GEOMETRY_SHA256, "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706")

    def test_full_skane_counts_are_locked(self):
        self.assertEqual(self.m.EXPECTED_FIELDS_2025, 128636)
        self.assertEqual(self.m.EXPECTED_P95, 618)
        self.assertEqual(self.m.EXPECTED_SPLIT_LINES, 613)
        self.assertEqual(self.m.EXPECTED_NO_GEOMETRY, 5)
        self.assertEqual(self.m.EXPECTED_PRELIM_FIELD_UNITS_2026, 129249)

    def test_map_is_boundary_network_not_child_polygon_invention(self):
        self.assertIn("official 2025 field boundaries + 613 frozen P95 primary split lines", self.text)
        self.assertIn('"child_polygons_materialized": False', self.text)
        self.assertNotIn("nearest", self.text.lower())
        self.assertNotIn("deterministic_k2", self.text)
        self.assertNotIn("polygonize", self.text.lower())

    def test_no_model_retuning_or_geometry_mutation(self):
        forbidden = ["thresholds_tuned\": True", "fusion_refit\": True", "smoothing\": True", "gap_filling\": True", "automatic_geometry_mutation\": True"]
        for token in forbidden:
            self.assertNotIn(token, self.text)
        self.assertIn('"model_executed": False', self.text)
        self.assertIn('"smoothing": False', self.text)
        self.assertIn('"gap_filling": False', self.text)
        self.assertIn('"official_2025_geometry_replaced": False', self.text)

    def test_exact_split_lines_and_display_only_simplification_are_separate(self):
        self.assertEqual(self.m.DISPLAY_SIMPLIFY_M, 5.0)
        self.assertIn('"split_line_display_geometry_exact": True', self.text)
        self.assertIn('"gpkg_geometry_exact": True', self.text)
        self.assertIn("display.geometry.simplify(DISPLAY_SIMPLIFY_M", self.text)
        self.assertNotIn("lines.geometry.simplify", self.text)

    def test_html_contains_required_layers_and_counts(self):
        html = self.m.make_html(["fields_001.js", "fields_002.js"])
        self.assertIn("128 636", html)
        self.assertIn("613", html)
        self.assertIn("129 249", html)
        self.assertIn("preliminära 2026 split-linjer", html)
        self.assertIn("5 P95 utan geometri", html)
        self.assertIn("p95_split_lines.js", html)
        self.assertIn("p95_no_geometry.js", html)
        self.assertIn("fields_001.js", html)

    def test_next_stop_is_human_map_review(self):
        self.assertEqual(self.m.STATUS, "PASS_TO_PRELIMINARY_2026_MAP_REVIEW")
        self.assertIn("NEXT=HUMAN_REVIEW_FULL_SKANE_PRELIMINARY_2026_FIELD_MAP", self.text)


if __name__ == "__main__":
    unittest.main()
