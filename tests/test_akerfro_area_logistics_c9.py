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

from analysis.akerfro_ertor_v0a.area_logistics_c9 import (
    coordinate_pair,
    haversine_km,
)


class TestAkerFroAreaLogisticsC9(unittest.TestCase):
    def test_haversine_zero(self):
        d = float(haversine_km([56.0731], [12.9395], 56.0731, 12.9395)[0])
        self.assertAlmostEqual(d, 0.0, places=8)

    def test_coordinate_pair_wgs84(self):
        f = pd.DataFrame({
            "current_field_id": ["A", "B"],
            "centroid_lon": [13.0, 13.1],
            "centroid_lat": [55.8, 55.9],
        })
        self.assertEqual(
            coordinate_pair(f),
            ("centroid_lon", "centroid_lat", "EPSG:4326"),
        )

    def test_coordinate_pair_sweref(self):
        f = pd.DataFrame({
            "current_field_id": ["A", "B"],
            "centroid_x": [380000.0, 390000.0],
            "centroid_y": [6200000.0, 6210000.0],
        })
        self.assertEqual(
            coordinate_pair(f),
            ("centroid_x", "centroid_y", "EPSG:3006"),
        )


if __name__ == "__main__":
    unittest.main()
