import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "171_akerpuls_merge_m0_satellite_only_freeze_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_merge_m0_freeze", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsMergeM0SatelliteOnlyFreezeV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_exact_census_is_predeclared(self):
        self.assertEqual(self.m.EXPECTED["same_block_touching_pairs"], 27146)
        self.assertEqual(self.m.EXPECTED["assessable_pairs"], 22358)
        self.assertEqual(self.m.EXPECTED["merge_candidate"], 2398)
        self.assertEqual(self.m.EXPECTED["keep_boundary"], 19960)
        self.assertEqual(self.m.EXPECTED["uncertain"], 4788)
        self.assertEqual(self.m.EXPECTED["cross_analysis_cell_pairs"], 348)

    def test_exact_score_quantiles_are_predeclared(self):
        self.assertAlmostEqual(self.m.EXPECTED_Q["p50"], 0.5210865)
        self.assertAlmostEqual(self.m.EXPECTED_Q["p90"], 0.7905282)
        self.assertAlmostEqual(self.m.EXPECTED_Q["p95"], 0.8424368)
        self.assertAlmostEqual(self.m.EXPECTED_Q["p99"], 0.90247635)

    def test_source_code_and_lineage_are_pinned(self):
        self.assertEqual(self.m.EXPECTED_SOURCE_GIT_HEAD, "f93964d6460b813ff90e6139b9c58b0e579aba52")
        self.assertEqual(self.m.EXPECTED_PARENT_PRELIM_FREEZE, "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376")
        self.assertEqual(self.m.EXPECTED_OFFICIAL_GEOM_SHA, "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706")

    def test_freeze_requires_pure_satellite_only_guards(self):
        self.assertIn('scope.get("satellite_only") is not True', self.text)
        self.assertIn('scope.get("history_prior_used") is not False', self.text)
        self.assertIn('scope.get("m4_prior_used") is not False', self.text)
        self.assertIn('scope.get("fusion_used") is not False', self.text)
        self.assertIn('"thresholds_tuned"', self.text)
        self.assertIn('"automatic_merge"', self.text)
        self.assertIn('"automatic_geometry_mutation"', self.text)

    def test_freeze_does_not_run_satellite_or_m4_model(self):
        lowered = self.text.lower()
        self.assertNotIn("rasterio", lowered)
        self.assertNotIn("lightgbm", lowered)
        self.assertNotIn("predict_proba", lowered)
        self.assertNotIn("deterministic_k2", lowered)

    def test_required_source_output_set_is_exact(self):
        self.assertEqual(self.m.REQUIRED_OUTPUTS, {
            "m0_satellite_merge_pairs.csv",
            "m0_satellite_merge_boundaries.gpkg",
            "M0_SATELLITE_ONLY_MERGE_SUMMARY_V1.json",
            "M0_SATELLITE_ONLY_MERGE_REPORT_V1.md",
        })


if __name__ == "__main__":
    unittest.main()
