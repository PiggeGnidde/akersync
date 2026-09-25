#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.akerfro_ertor_v0a.rotation_gap_diagnostic import (
    build_repeat_table,
    gap_counts,
    pair_counts,
)


class TestAkerFroRotationGapDiagnostic(unittest.TestCase):
    def positives(self) -> pd.DataFrame:
        rows = []
        for fid, years in {
            "F1": [2015, 2021],
            "F2": [2016, 2023],
            "F3": [2018],
            "F4": [2017, 2023],
        }.items():
            for year in years:
                rows.append({
                    "history_year": year,
                    "municipality": "Test",
                    "current_field_id": fid,
                    "current_block_id": "B" + fid[1:],
                    "current_skiftesbeteckning": "S" + fid[1:],
                    "current_area_m2": 10000.0,
                })
        return pd.DataFrame(rows)

    def test_repeat_table(self):
        r = build_repeat_table(self.positives()).set_index("current_field_id")
        self.assertEqual(set(r.index), {"F1", "F2", "F4"})
        self.assertEqual(r.loc["F1", "gap_years"], 6)
        self.assertEqual(r.loc["F2", "gap_years"], 7)
        self.assertEqual(r.loc["F4", "gap_years"], 6)

    def test_gap_counts(self):
        r = build_repeat_table(self.positives())
        g = gap_counts(r).set_index("gap_years")
        self.assertEqual(g.loc[6, "n_fields"], 2)
        self.assertEqual(g.loc[7, "n_fields"], 1)

    def test_pair_counts(self):
        r = build_repeat_table(self.positives())
        p = pair_counts(r)
        self.assertEqual(int(p["n_fields"].sum()), 3)
        self.assertEqual(len(p), 3)


if __name__ == "__main__":
    unittest.main()
