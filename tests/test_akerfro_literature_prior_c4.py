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

from analysis.akerfro_ertor_v0a.literature_prior_c4 import (
    build_literature_prior,
    soft_plateau,
)


class TestAkerFroLiteraturePriorC4(unittest.TestCase):
    def test_soft_plateau_core_is_one_and_tails_are_soft(self):
        v = soft_plateau([3.0, 8.0, 15.0, 25.0, 35.0], 8.0, 25.0, 5.0, 10.0)
        self.assertLess(v[0], 1.0)
        self.assertAlmostEqual(v[1], 1.0)
        self.assertAlmostEqual(v[2], 1.0)
        self.assertAlmostEqual(v[3], 1.0)
        self.assertLess(v[4], 1.0)
        self.assertGreater(v[0], 0.0)
        self.assertGreater(v[4], 0.0)

    def test_core_texture_beats_extreme_sand_at_same_low_twi(self):
        frame = pd.DataFrame({
            "soil__clay_mean": [15.0, 5.0],
            "soil__silt_mean": [35.0, 15.0],
            "soil__sand_mean": [50.0, 80.0],
            "hydrology__twi_mean": [5.0, 5.0],
        })
        out = build_literature_prior(frame)
        self.assertGreater(
            out.loc[0, "literature_prior_score"],
            out.loc[1, "literature_prior_score"],
        )

    def test_high_twi_penalizes_fine_texture(self):
        frame = pd.DataFrame({
            "soil__clay_mean": [25.0, 25.0, 10.0, 10.0],
            "soil__silt_mean": [55.0, 55.0, 20.0, 20.0],
            "soil__sand_mean": [20.0, 20.0, 70.0, 70.0],
            "hydrology__twi_mean": [1.0, 10.0, 1.0, 10.0],
        })
        out = build_literature_prior(frame)
        self.assertLess(out.loc[1, "lit_wet_penalty"], out.loc[0, "lit_wet_penalty"])
        # Coarser texture receives less of the high-TWI fine-soil penalty.
        self.assertGreaterEqual(out.loc[3, "lit_wet_penalty"], out.loc[1, "lit_wet_penalty"])


if __name__ == "__main__":
    unittest.main()
