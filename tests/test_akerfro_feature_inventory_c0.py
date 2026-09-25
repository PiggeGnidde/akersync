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

from analysis.akerfro_ertor_v0a.feature_inventory_c0 import derived_key, text_id


class TestAkerFroFeatureInventoryC0(unittest.TestCase):
    def test_direct_current_field_id(self):
        frame = pd.DataFrame({"current_field_id": ["1|A", "2|B"], "x": [1, 2]})
        key, rule = derived_key(frame)
        self.assertEqual(rule, "current_field_id")
        self.assertEqual(key.tolist(), ["1|A", "2|B"])

    def test_block_skifte_key(self):
        frame = pd.DataFrame({
            "blockid": [123.0, "456"],
            "skiftesbeteckning": ["A", "B"],
        })
        key, rule = derived_key(frame)
        self.assertEqual(rule, "blockid|skiftesbeteckning")
        self.assertEqual(key.tolist(), ["123|A", "456|B"])

    def test_text_id(self):
        self.assertEqual(text_id(123.0), "123")
        self.assertEqual(text_id(" A "), "A")
        self.assertEqual(text_id(None), "")


if __name__ == "__main__":
    unittest.main()
