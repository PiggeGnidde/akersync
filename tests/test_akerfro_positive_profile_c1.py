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

from analysis.akerfro_ertor_v0a.build_positive_profile_c1 import (
    describe_feature,
    field_key,
    rank_auc,
)


class TestAkerFroPositiveProfileC1(unittest.TestCase):
    def test_field_key_variants(self):
        a = pd.DataFrame({"blockid": ["1"], "skiftesbeteckning": ["A"]})
        self.assertEqual(field_key(a).iloc[0], "1|A")
        b = pd.DataFrame({"block_id": ["2"], "skifte_id": ["B"]})
        self.assertEqual(field_key(b).iloc[0], "2|B")

    def test_rank_auc_direction(self):
        self.assertAlmostEqual(rank_auc(np.array([10., 11.]), np.array([1., 2.])), 1.0)
        self.assertAlmostEqual(rank_auc(np.array([1., 2.]), np.array([10., 11.])), 0.0)
        self.assertAlmostEqual(rank_auc(np.array([1., 2.]), np.array([1., 2.])), 0.5)

    def test_describe_feature(self):
        frame = pd.DataFrame({
            "is_positive": [True, True, False, False],
            "x__feature": [10., 12., 2., 4.],
        })
        row = describe_feature(frame, "x__feature")
        self.assertEqual(row["n_positive"], 2)
        self.assertEqual(row["n_unlabeled"], 2)
        self.assertGreater(row["standardized_mean_difference"], 0)
        self.assertEqual(row["rank_auc_positive_gt_unlabeled"], 1.0)


if __name__ == "__main__":
    unittest.main()
