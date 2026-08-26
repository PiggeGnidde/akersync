from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerminne_reference_sample import build_reference_checklist  # noqa: E402


def make_rows():
    rows = []
    for year in range(2015, 2025):
        for i in range(8):
            rows += [
                {"history_year": year, "current_field_id": f"S{year}_{i}", "status": "SINGLE_CROP", "coverage_display": 1.0, "second_crop_share": 0.0, "identity_match_confidence": "direct_id", "overlap_excess_raw": 0.0, "material_overlap_anomaly": False},
                {"history_year": year, "current_field_id": f"T{year}_{i}", "status": "SINGLE_CROP", "coverage_display": 1.0, "second_crop_share": 0.01, "identity_match_confidence": "merge" if i % 2 else "split", "overlap_excess_raw": 0.0, "material_overlap_anomaly": False},
                {"history_year": year, "current_field_id": f"M{year}_{i}", "status": "MIXED_CROPS", "coverage_display": 1.0, "second_crop_share": 0.2, "identity_match_confidence": "one_to_one_relaxed", "overlap_excess_raw": 0.0, "material_overlap_anomaly": False},
                {"history_year": year, "current_field_id": f"P{year}_{i}", "status": "PARTIAL_COVERAGE", "coverage_display": 0.8, "second_crop_share": 0.0, "identity_match_confidence": "unmatched", "overlap_excess_raw": 0.0, "material_overlap_anomaly": False},
                {"history_year": year, "current_field_id": f"N{year}_{i}", "status": "NO_PUBLIC_MATCH", "coverage_display": 0.0, "second_crop_share": 0.0, "identity_match_confidence": "unmatched", "overlap_excess_raw": 0.0, "material_overlap_anomaly": False},
                {"history_year": year, "current_field_id": f"X{year}_{i}", "status": "MIXED_CROPS", "coverage_display": 1.0, "second_crop_share": 0.3, "identity_match_confidence": "ambiguous", "overlap_excess_raw": 0.01 + i / 100, "material_overlap_anomaly": True},
            ]
    return pd.DataFrame(rows)


class ReferenceSampleTests(unittest.TestCase):
    def test_sample_has_20_unique_fields_and_all_statuses(self):
        out = build_reference_checklist(make_rows())
        self.assertEqual(len(out), 20)
        self.assertEqual(out.current_field_id.nunique(), 20)
        self.assertTrue({"SINGLE_CROP", "MIXED_CROPS", "PARTIAL_COVERAGE", "NO_PUBLIC_MATCH"}.issubset(set(out.status)))

    def test_status_edge_has_mixed_partial_and_no_match(self):
        out = build_reference_checklist(make_rows())
        x = out[out.qa_category == "status_edge"]
        self.assertEqual(len(x), 5)
        self.assertEqual((x.status == "MIXED_CROPS").sum(), 2)
        self.assertEqual((x.status == "PARTIAL_COVERAGE").sum(), 2)
        self.assertEqual((x.status == "NO_PUBLIC_MATCH").sum(), 1)

    def test_sample_spans_years(self):
        out = build_reference_checklist(make_rows())
        self.assertGreaterEqual(out.history_year.nunique(), 5)


if __name__ == "__main__":
    unittest.main()
