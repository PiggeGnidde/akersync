#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.rotation_predecessor_c7 import (
    eligible_from_last,
    enrichment_table,
    years_since,
)


class TestAkerFroRotationPredecessorC7(unittest.TestCase):
    def test_years_since_candidate_year(self):
        last = pd.Series([2025, 2020, np.nan])
        got = years_since(2026, last)
        self.assertEqual(float(got.iloc[0]), 1.0)
        self.assertEqual(float(got.iloc[1]), 6.0)
        self.assertTrue(np.isnan(got.iloc[2]))

    def test_no_observed_is_eligible_in_scenario(self):
        last = pd.Series([2025, 2020, np.nan])
        got = eligible_from_last(2026, last, 6)
        self.assertEqual(got.tolist(), [False, True, True])

    def test_enrichment_ratio(self):
        sample = pd.DataFrame([
            {"sample_role": "positive", "predecessor_crop_key": "a", "predecessor_crop_name": "A"},
            {"sample_role": "positive", "predecessor_crop_key": "a", "predecessor_crop_name": "A"},
            {"sample_role": "matched_control", "predecessor_crop_key": "a", "predecessor_crop_name": "A"},
            {"sample_role": "matched_control", "predecessor_crop_key": "b", "predecessor_crop_name": "B"},
        ])
        out = enrichment_table(sample, 1).set_index("crop_key")
        self.assertAlmostEqual(float(out.loc["a", "enrichment_ratio"]), 2.0)
        self.assertAlmostEqual(float(out.loc["a", "difference_pp"]), 50.0)


if __name__ == "__main__":
    unittest.main()
