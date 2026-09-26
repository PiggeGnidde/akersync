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

from analysis.akerfro_ertor_v0a.contract_shock_c7c import (
    RAPS,
    SUGAR_BEET,
    WINTER_WHEAT,
    prior_any_crop,
    prior_same_slot,
)


class TestAkerFroContractShockC7c(unittest.TestCase):
    def setUp(self):
        self.wide = pd.DataFrame({
            2019: [RAPS, "x"],
            2020: [WINTER_WHEAT, SUGAR_BEET],
            2021: [SUGAR_BEET, "x"],
            2022: [RAPS, RAPS],
            2023: [WINTER_WHEAT, WINTER_WHEAT],
            2024: ["x", "x"],
        }, index=["A", "B"])

    def test_prior_any_crop_is_year_blind(self):
        got = prior_any_crop(self.wide, self.wide.index, 2024, SUGAR_BEET)
        self.assertEqual(got.tolist(), [True, True])

    def test_same_slot_repeat_detects_completed_prior_triplet(self):
        got = prior_same_slot(self.wide, self.wide.index, 2024)
        self.assertEqual(got.tolist(), [True, False])

    def test_same_slot_never_uses_target_year(self):
        got = prior_same_slot(self.wide, pd.Index(["A"]), 2021)
        self.assertEqual(got.tolist(), [False])


if __name__ == "__main__":
    unittest.main()
