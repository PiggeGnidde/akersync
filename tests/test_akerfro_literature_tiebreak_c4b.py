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

from analysis.akerfro_ertor_v0a.literature_tiebreak_c4b import (
    add_ilr,
    robust_scale_reference,
)


class TestAkerFroLiteratureTiebreakC4b(unittest.TestCase):
    def test_ilr_is_finite_for_zero_fraction_with_pseudocount(self):
        frame = pd.DataFrame({
            "soil__clay_mean": [0.0, 10.0],
            "soil__silt_mean": [20.0, 30.0],
            "soil__sand_mean": [80.0, 60.0],
        })
        out = add_ilr(frame)
        self.assertTrue(np.isfinite(out["texture_ilr1"]).all())
        self.assertTrue(np.isfinite(out["texture_ilr2"]).all())

    def test_ilr_changes_with_composition(self):
        frame = pd.DataFrame({
            "soil__clay_mean": [10.0, 20.0],
            "soil__silt_mean": [30.0, 30.0],
            "soil__sand_mean": [60.0, 50.0],
        })
        out = add_ilr(frame)
        self.assertNotAlmostEqual(out.loc[0, "texture_ilr1"], out.loc[1, "texture_ilr1"])

    def test_robust_scale_positive(self):
        frame = pd.DataFrame({
            "a": [1, 2, 3, 4, 5],
            "b": [10, 20, 30, 40, 50],
        })
        ref = robust_scale_reference(frame, ["a", "b"])
        self.assertGreater(ref["a"][1], 0)
        self.assertGreater(ref["b"][1], 0)


if __name__ == "__main__":
    unittest.main()
