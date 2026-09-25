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

from analysis.akerfro_ertor_v0a.residual_texture_c5b import (
    exact_binomial_two_sided,
    pairwise_from_predictions,
)


class TestAkerFroResidualTextureC5b(unittest.TestCase):
    def test_pairwise_accuracy(self):
        pred = pd.DataFrame([
            {"pair_id": 1, "twin_role": "positive", "score": .8},
            {"pair_id": 1, "twin_role": "unlabeled_twin", "score": .2},
            {"pair_id": 2, "twin_role": "positive", "score": .3},
            {"pair_id": 2, "twin_role": "unlabeled_twin", "score": .7},
            {"pair_id": 3, "twin_role": "positive", "score": .6},
            {"pair_id": 3, "twin_role": "unlabeled_twin", "score": .4},
        ])
        r = pairwise_from_predictions(pred)
        self.assertEqual(r["positive_higher"], 2)
        self.assertEqual(r["twin_higher"], 1)
        self.assertAlmostEqual(r["pairwise_accuracy"], 2/3)

    def test_binomial_symmetry(self):
        self.assertAlmostEqual(
            exact_binomial_two_sided(7, 10),
            exact_binomial_two_sided(3, 10),
        )

    def test_binomial_balanced_is_one(self):
        self.assertAlmostEqual(exact_binomial_two_sided(5, 10), 1.0)


if __name__ == "__main__":
    unittest.main()
