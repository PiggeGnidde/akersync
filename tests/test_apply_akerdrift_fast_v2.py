from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("apply_v2", ROOT / "src" / "47_apply_akerdrift_fast_v2.py")
APPLY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(APPLY)

from akerdrift_fast_v2_core import load_model_config  # noqa: E402


class ApplyAkerdriftFastV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_model_config(ROOT / "config" / "akerdrift_fast_v2_routecal_rc0.json")

    def frames(self):
        fast = pd.DataFrame([
            {
                "block_id": "1", "skifte_id": "A", "kommun": "Lomma", "area_ha": 5.0,
                "akerdrift_score": 70.0, "geometry_score": 70.0, "drift_terrain_factor": 1.0,
                "drift_status": "OK", "drift_model_version": "akerdrift-fast-v1-rc0",
                "rectangularity": .7, "compactness": .5, "erl": 240.0,
            },
            {
                "block_id": "2", "skifte_id": "B", "kommun": "Lomma", "area_ha": .01,
                "akerdrift_score": None, "geometry_score": 20.0, "drift_terrain_factor": None,
                "drift_status": "INSUFFICIENT_SLOPE_COVERAGE", "drift_model_version": "akerdrift-fast-v1-rc0",
                "rectangularity": .5, "compactness": .3, "erl": 20.0,
            },
        ])
        geometry = pd.DataFrame([
            {
                "blockid": "1", "skiftesbeteckning": "A", "area_ha": 5.0,
                "rectangularity": .7, "compactness_4piA_P2": .5,
                "erl_proxy_m": 240.0, "hole_count": 1,
            },
            {
                "blockid": "2", "skiftesbeteckning": "B", "area_ha": .01,
                "rectangularity": .5, "compactness_4piA_P2": .3,
                "erl_proxy_m": 20.0, "hole_count": 0,
            },
        ])
        return fast, geometry

    def test_preserves_v1_and_scores_only_eligible_rows(self):
        fast, geometry = self.frames()
        result, _, _ = APPLY.rescore_frame(fast, geometry, self.config)
        self.assertEqual(result.loc[0, "fast_v1_akerdrift_score"], 70.0)
        self.assertTrue(pd.notna(result.loc[0, "akerdrift_score"]))
        self.assertEqual(result.loc[0, "hole_count"], 1)
        self.assertTrue(pd.isna(result.loc[1, "akerdrift_score"]))
        self.assertEqual(result.loc[1, "drift_routecal_support"], "NOT_SCORED_FAST_V1")

    def test_marks_clipped_calibration_support(self):
        fast, geometry = self.frames()
        fast.loc[0, "geometry_score"] = 20.0
        result, clip, _ = APPLY.rescore_frame(fast, geometry, self.config)
        self.assertEqual(result.loc[0, "drift_routecal_support"], "CLIPPED_TO_CALIBRATION_RANGE")
        row = clip[clip["feature"].eq("fast_geometry_score")].iloc[0]
        self.assertEqual(row["n_below"], 1)


if __name__ == "__main__":
    unittest.main()
