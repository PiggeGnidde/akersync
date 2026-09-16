import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "169_akerpuls_merge_m0_satellite_only_v1.py"
CFG = ROOT / "config" / "akerpuls_merge_m0_satellite_only_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_merge_m0", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsMergeM0SatelliteOnlyV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def test_stage_is_satellite_only_and_non_mutating(self):
        e = self.cfg["execution"]
        self.assertTrue(e["satellite_only"])
        self.assertFalse(e["history_prior"])
        self.assertFalse(e["m4_prior"])
        self.assertFalse(e["fusion"])
        self.assertFalse(e["threshold_tuning"])
        self.assertFalse(e["automatic_merge"])
        self.assertFalse(e["geometry_mutation"])
        self.assertTrue(e["stop_after_m0"])
        self.assertEqual(self.m.STATUS, "PASS_TO_M0_SATELLITE_MERGE_REVIEW_STOP")

    def test_candidate_universe_is_same_block_touching_only(self):
        self.assertEqual(self.cfg["adjacency"]["scope"], "SAME_2025_BLOCK_ONLY")
        self.assertTrue(self.cfg["adjacency"]["require_positive_shared_boundary"])
        self.assertEqual(float(self.cfg["adjacency"]["minimum_shared_boundary_m"]), 1.0)
        self.assertIn('groupby("block_id_2025"', self.text)
        self.assertIn("boundary.intersection", self.text)

    def test_frozen_pilot_merge_thresholds_are_reused(self):
        mg = self.cfg["merge"]
        self.assertEqual(int(mg["boundary_dilation_pixels"]), 3)
        self.assertEqual(int(mg["minimum_strip_pixels_per_side"]), 4)
        self.assertEqual(float(mg["maximum_field_mean_distance"]), 0.60)
        self.assertEqual(float(mg["maximum_between_within_ratio"]), 1.00)
        self.assertEqual(float(mg["maximum_boundary_median_distance"]), 0.60)
        self.assertEqual(float(mg["strong_edge_distance"]), 0.90)
        self.assertEqual(int(mg["maximum_strong_edge_snapshots"]), 1)
        self.assertEqual(int(mg["minimum_valid_boundary_snapshots"]), 3)
        self.assertEqual(float(mg["minimum_confidence"]), 0.68)

    def test_merge_decision_behaves_as_expected(self):
        mg = self.cfg["merge"]
        status, conf, bmed, valid, strong = self.m.merge_score_and_decision(
            mg, 0.20, 0.40, [0.20, 0.25, 0.30, 0.22]
        )
        self.assertEqual(status, "MERGE_CANDIDATE")
        self.assertGreaterEqual(conf, 0.68)
        self.assertEqual(valid, 4)
        self.assertEqual(strong, 0)
        self.assertLessEqual(bmed, 0.60)

        status2, *_ = self.m.merge_score_and_decision(
            mg, 0.20, 0.40, [1.20, 1.10, 1.30, 1.00]
        )
        self.assertEqual(status2, "KEEP_BOUNDARY")

        status3, *_ = self.m.merge_score_and_decision(
            mg, 0.20, 0.40, [0.20, None, None, 0.25]
        )
        self.assertEqual(status3, "UNCERTAIN")

    def test_frozen_d2a_local_scales_are_used(self):
        self.assertEqual(self.cfg["normalization"]["source"], "FROZEN_D2A_LOCAL_NORMALIZATION_SCALE")
        self.assertEqual(self.cfg["normalization"]["cross_cell_rule"], "GEOMETRIC_MEAN_OF_TWO_CELL_SCALES")
        self.assertIn('meta.get("normalization_scale"', self.text)
        self.assertIn("np.sqrt(sa * sb)", self.text)

    def test_no_history_or_m4_data_are_loaded(self):
        lowered = self.text.lower()
        self.assertNotIn("akerminne_selected", lowered)
        self.assertNotIn("lightgbm", lowered)
        self.assertNotIn("predict_proba", lowered)
        self.assertIn('"history_prior_used": False', self.text)
        self.assertIn('"m4_prior_used": False', self.text)
        self.assertIn('"fusion_used": False', self.text)

    def test_full_skane_lineage_is_pinned(self):
        self.assertEqual(self.m.EXPECTED_PRELIM_FREEZE_SHA256, "c2f4fd7ee03124f330d3a06a1d1465592399072ed5729a38e5a66ac27dcef376")
        self.assertEqual(self.cfg["official_2025_geometry_sha256"], "63f256c012a8f8aab75f22699bc729e60036913429caeb070306f57c19b31706")
        self.assertEqual(self.cfg["expected_vrt_index_sha256"], "0210f78b9780f6b586be0c89109e5a696202167b5283d5bae6b20a24d23c8979")
        self.assertEqual(int(self.cfg["expected"]["fields_2025"]), 128636)
        self.assertEqual(int(self.cfg["expected"]["blocks_2025"]), 122970)


if __name__ == "__main__":
    unittest.main()
