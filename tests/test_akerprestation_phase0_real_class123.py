#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from importlib.machinery import SourceFileLoader

module = SourceFileLoader(
    "real_class123_gate",
    str(ROOT / "src" / "73_verify_akerprestation_phase0_real_class123.py"),
).load_module()


class RealClass123SelectionTests(unittest.TestCase):
    def test_selects_only_requested_dominant_class(self):
        frame = pd.DataFrame(
            [
                {"current_field_id": "a", "dominant_soil_class": 1, "dominant_soil_class_share": .9, "soil_class_coverage_unique": 1.0},
                {"current_field_id": "b", "dominant_soil_class": 2, "dominant_soil_class_share": .99, "soil_class_coverage_unique": 1.0},
                {"current_field_id": "c", "dominant_soil_class": 1, "dominant_soil_class_share": .8, "soil_class_coverage_unique": .95},
            ]
        )
        out = module.select_dominant_target_rows(frame, 1, required=5)
        self.assertEqual(out["current_field_id"].tolist(), ["a", "c"])

    def test_selection_is_deterministic_by_share_coverage_and_id(self):
        frame = pd.DataFrame(
            [
                {"current_field_id": "z", "dominant_soil_class": 3, "dominant_soil_class_share": .8, "soil_class_coverage_unique": 1.0},
                {"current_field_id": "a", "dominant_soil_class": 3, "dominant_soil_class_share": .9, "soil_class_coverage_unique": .9},
                {"current_field_id": "b", "dominant_soil_class": 3, "dominant_soil_class_share": .9, "soil_class_coverage_unique": 1.0},
                {"current_field_id": "c", "dominant_soil_class": 3, "dominant_soil_class_share": .9, "soil_class_coverage_unique": 1.0},
            ]
        )
        out = module.select_dominant_target_rows(frame, 3, required=3)
        self.assertEqual(out["current_field_id"].tolist(), ["b", "c", "a"])

    def test_zero_coverage_is_rejected(self):
        frame = pd.DataFrame(
            [
                {"current_field_id": "a", "dominant_soil_class": 2, "dominant_soil_class_share": 1.0, "soil_class_coverage_unique": 0.0},
                {"current_field_id": "b", "dominant_soil_class": 2, "dominant_soil_class_share": .7, "soil_class_coverage_unique": .7},
            ]
        )
        out = module.select_dominant_target_rows(frame, 2, required=5)
        self.assertEqual(out["current_field_id"].tolist(), ["b"])


if __name__ == "__main__":
    unittest.main()
