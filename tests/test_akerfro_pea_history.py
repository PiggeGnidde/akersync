#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analysis.akerfro_ertor_v0a.build_history import (
    HISTORY_END_YEAR,
    build_field_history,
    clean_positive_field_years,
)


class TestAkerFroPeaHistory(unittest.TestCase):
    def synthetic(self) -> pd.DataFrame:
        rows = []
        for year in range(2015, 2026):
            rows.append({
                "municipality": "Test",
                "history_year": year,
                "current_field_id": "F1",
                "current_block_id": "B1",
                "current_skiftesbeteckning": "S1",
                "current_area_m2": 10000.0,
                "dominant_crop_name": (
                    "Konservärter" if year in (2016, 2023)
                    else "Ärter (ej konservärter)" if year == 2019
                    else "Åkerbönor" if year == 2020
                    else "Vete (höst)"
                ),
                "dominant_crop_known": True,
                "status": "SINGLE_CROP",
                "identity_match_confidence": "one_to_one_strict",
                "coverage_display": 1.0,
                "akerfro_group": (
                    "CONSERVART" if year in (2016, 2023)
                    else "OTHER_PEA" if year == 2019
                    else "FABA_BEAN" if year == 2020
                    else None
                ),
                "is_clean": True,
            })
        # A second field has a target label only in a mixed year and must not
        # become a primary positive.
        for year in range(2015, 2026):
            rows.append({
                "municipality": "Test",
                "history_year": year,
                "current_field_id": "F2",
                "current_block_id": "B2",
                "current_skiftesbeteckning": "S2",
                "current_area_m2": 20000.0,
                "dominant_crop_name": "Konservärter" if year == 2021 else "Vete (höst)",
                "dominant_crop_known": True,
                "status": "MIXED_CROPS" if year == 2021 else "SINGLE_CROP",
                "identity_match_confidence": "one_to_one_strict",
                "coverage_display": 1.0,
                "akerfro_group": "CONSERVART" if year == 2021 else None,
                "is_clean": year != 2021,
            })
        return pd.DataFrame(rows)

    def test_clean_positive_excludes_mixed(self):
        x = clean_positive_field_years(self.synthetic())
        self.assertEqual(list(x["history_year"]), [2016, 2023])
        self.assertEqual(set(x["current_field_id"]), {"F1"})

    def test_field_episode_variables(self):
        h = build_field_history(self.synthetic()).set_index("current_field_id")
        f1 = h.loc["F1"]
        self.assertEqual(f1["n_target_pea_years_2015_2025"], 2)
        self.assertEqual(f1["first_target_pea_year"], 2016)
        self.assertEqual(f1["last_target_pea_year"], 2023)
        self.assertEqual(f1["years_since_last_target_pea"], HISTORY_END_YEAR - 2023)
        self.assertEqual(f1["target_pea_years_list"], [2016, 2023])
        self.assertEqual(f1["n_other_pea_years"], 1)
        self.assertEqual(f1["n_faba_bean_years"], 1)
        self.assertEqual(f1["legume_years_list"], [2016, 2019, 2020, 2023])

        f2 = h.loc["F2"]
        self.assertEqual(f2["n_target_pea_years_2015_2025"], 0)
        self.assertIsNone(f2["last_target_pea_year"] if pd.isna(f2["last_target_pea_year"]) else None)

    def test_usable_history_years_are_clean_only(self):
        h = build_field_history(self.synthetic()).set_index("current_field_id")
        self.assertEqual(h.loc["F1", "usable_history_years"], 11)
        self.assertEqual(h.loc["F2", "usable_history_years"], 10)


if __name__ == "__main__":
    unittest.main()
