from __future__ import annotations
import sys
import unittest
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from akerminne_status_core import HistoryStatusConfig, apply_history_status  # noqa: E402


def summary(coverage=1.0, flags=""):
    return pd.DataFrame([{
        "history_year": 2020, "current_field_id": "B|A", "current_area_m2": 100.0,
        "coverage_raw": coverage, "coverage_display": min(max(coverage, 0), 1),
        "reason_flags": flags,
    }])


def comps(parts):
    return pd.DataFrame([{
        "history_year": 2020, "current_field_id": "B|A", "crop_code_raw": code,
        "crop_subcategory_raw": sub, "intersection_m2": area,
    } for code, sub, area in parts])


class StatusTests(unittest.TestCase):
    def test_same_crop_fragments_are_not_mixed(self):
        out, crops = apply_history_status(summary(), comps([("4", None, 60), ("4", None, 40)]))
        self.assertEqual(len(crops), 1)
        self.assertEqual(out.iloc[0].status, "SINGLE_CROP")
        self.assertEqual(out.iloc[0].second_crop_share, 0.0)

    def test_mixed_at_five_percent(self):
        out, _ = apply_history_status(summary(), comps([("4", None, 95), ("47", None, 5)]))
        self.assertEqual(out.iloc[0].status, "MIXED_CROPS")
        self.assertIn("MULTIPLE_CROPS", out.iloc[0].reason_flags)

    def test_minor_crop_below_five_percent_stays_single_but_visible_at_one_percent(self):
        out, _ = apply_history_status(summary(), comps([("4", None, 96), ("47", None, 4)]))
        self.assertEqual(out.iloc[0].status, "SINGLE_CROP")
        self.assertEqual(out.iloc[0].significant_crop_count, 2)

    def test_partial_precedes_mixed(self):
        out, _ = apply_history_status(summary(.94), comps([("4", None, 80), ("47", None, 14)]))
        self.assertEqual(out.iloc[0].status, "PARTIAL_COVERAGE")
        self.assertIn("LOW_COVERAGE", out.iloc[0].reason_flags)

    def test_zero_is_no_public_match(self):
        out, _ = apply_history_status(summary(0.0), comps([]))
        self.assertEqual(out.iloc[0].status, "NO_PUBLIC_MATCH")
        self.assertNotIn("BELOW_MIN_MATCH_COVERAGE", out.iloc[0].reason_flags)

    def test_below_one_percent_is_no_public_match(self):
        out, _ = apply_history_status(summary(.009), comps([("4", None, .9)]))
        self.assertEqual(out.iloc[0].status, "NO_PUBLIC_MATCH")
        self.assertIn("BELOW_MIN_MATCH_COVERAGE", out.iloc[0].reason_flags)

    def test_exactly_one_percent_is_partial(self):
        out, _ = apply_history_status(summary(.01), comps([("4", None, 1.0)]))
        self.assertEqual(out.iloc[0].status, "PARTIAL_COVERAGE")
        self.assertIn("LOW_COVERAGE", out.iloc[0].reason_flags)

    def test_overlap_materiality_is_separate(self):
        out, _ = apply_history_status(summary(1.006), comps([("4", None, 100.6)]))
        self.assertEqual(out.iloc[0].status, "SINGLE_CROP")
        self.assertTrue(out.iloc[0].material_overlap_anomaly)
        self.assertIn("DUPLICATE_OVERLAP", out.iloc[0].reason_flags)


if __name__ == "__main__":
    unittest.main()
