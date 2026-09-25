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

from analysis.akerfro_ertor_v0a.matched_ranking_c3 import (
    matched_sample,
    stable_hash,
)


class TestAkerFroMatchedRankingC3(unittest.TestCase):
    def test_stable_hash_is_deterministic(self):
        self.assertEqual(stable_hash("abc"), stable_hash("abc"))
        self.assertNotEqual(stable_hash("abc"), stable_hash("abd"))

    def test_matching_retains_all_common_support_positives(self):
        rows = []
        for i in range(2):
            rows.append({
                "current_field_id": f"P{i}", "local_match_stratum": "S1",
                "is_positive": True,
            })
        for i in range(20):
            rows.append({
                "current_field_id": f"U{i}", "local_match_stratum": "S1",
                "is_positive": False,
            })
        frame = pd.DataFrame(rows)
        out = matched_sample(frame, controls_per_positive=3)
        self.assertEqual(int(out["is_positive"].sum()), 2)
        self.assertEqual(int((~out["is_positive"]).sum()), 6)

    def test_matching_caps_when_few_unlabeled(self):
        frame = pd.DataFrame([
            {"current_field_id": "P1", "local_match_stratum": "S", "is_positive": True},
            {"current_field_id": "P2", "local_match_stratum": "S", "is_positive": True},
            {"current_field_id": "U1", "local_match_stratum": "S", "is_positive": False},
        ])
        out = matched_sample(frame, controls_per_positive=8)
        self.assertEqual(int(out["is_positive"].sum()), 2)
        self.assertEqual(int((~out["is_positive"]).sum()), 1)


if __name__ == "__main__":
    unittest.main()
