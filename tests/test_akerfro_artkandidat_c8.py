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

from analysis.akerfro_ertor_v0a.build_artkandidat_c8 import (
    predecessor_policy,
    rotation_status,
)


class TestAkerFroArtKandidatC8(unittest.TestCase):
    def test_predecessor_policy_thresholds(self):
        e = pd.DataFrame({
            "crop_key": ["a", "b", "c", "d"],
            "crop_name": ["A", "B", "C", "D"],
            "positive_count": [30, 30, 30, 5],
            "positive_pct": [1, 1, 1, 1],
            "control_pct": [1, 1, 1, 1],
            "enrichment_ratio": [1.5, 1.0, 0.5, 3.0],
        })
        cfg = {"predecessor": {
            "positive_min_enrichment": 1.25,
            "negative_max_enrichment": 0.80,
            "min_positive_events": 20,
        }}
        p = predecessor_policy(e, cfg).set_index("crop_key")
        self.assertEqual(p.loc["a", "predecessor_prior"], "POSITIVE")
        self.assertEqual(p.loc["b", "predecessor_prior"], "NEUTRAL")
        self.assertEqual(p.loc["c", "predecessor_prior"], "NEGATIVE")
        self.assertEqual(p.loc["d", "predecessor_prior"], "LOW_SUPPORT")

    def test_rotation_status_is_conservative_and_explicit(self):
        f = pd.DataFrame({
            "eligible_target_any_component_6y": [True, True, True, False],
            "eligible_any_pea_clean_6y": [True, True, False, False],
            "eligible_pea_or_faba_clean_6y": [True, False, False, False],
        })
        got = rotation_status(f, 6).tolist()
        self.assertEqual(got, [
            "ROTATION_OK",
            "CAUTION_RECENT_FABA",
            "CAUTION_RECENT_OTHER_PEA",
            "CAUTION_RECENT_CONSERVART",
        ])


if __name__ == "__main__":
    unittest.main()
