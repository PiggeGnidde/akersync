from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("visual_qa", ROOT / "src" / "48_prepare_akerdrift_hybrid_visual_qa.py")
visual_qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(visual_qa)


class HybridVisualQaTests(unittest.TestCase):
    def test_selection_is_bounded_unique_and_deterministic(self):
        rows = []
        for index in range(80):
            fallback = index >= 60
            area = .35 if fallback else 1 + index / 3
            rows.append({
                "kommun": "Lomma", "block_id": str(1000 + index), "skifte_id": "A",
                "area_ha": area, "hole_count": int(index % 7 == 0),
                "fast_v1_akerdrift_score": 50 + index / 4,
                "akerdrift_score": 50 + index / 4 + ((index % 21) - 10),
                "score_delta_hybrid_minus_v1": (index % 21) - 10,
                "fast_v1_geometry_score": 55 + index / 4,
                "rectangularity": .1 + index / 100,
                "compactness": .05 + index / 150,
                "erl": 70 + index * 4,
                "drift_score_source": "FAST_V1_FALLBACK_OUTSIDE_CALIBRATION" if fallback else "FAST_V2_ROUTECAL",
            })
        config = {"geometry_model": {"clip_ranges": {
            "fast_geometry_score": [49, 92], "log_area_ha": [-1.01, 4.52],
            "rectangularity": [.04, .99], "compactness": [.02, .88],
            "log_erl_m": [4.03, 7.20],
        }}}
        frame = pd.DataFrame(rows)
        first = visual_qa.select_review_rows(frame, config)
        second = visual_qa.select_review_rows(frame.sample(frac=1, random_state=4), config)
        self.assertGreaterEqual(len(first), 40)
        self.assertLessEqual(len(first), 50)
        self.assertFalse(first[["block_id", "skifte_id"]].duplicated().any())
        self.assertEqual(set(first["block_id"]), set(second["block_id"]))
        self.assertIn("largest_negative", set(first["qa_category"]))
        self.assertIn("largest_positive", set(first["qa_category"]))
        self.assertTrue(first["local_url"].str.contains("lager=drift").all())


if __name__ == "__main__":
    unittest.main()
