#!/usr/bin/env python3
from __future__ import annotations
import unittest
from analysis.akeraccess_v0a.path_profile_core import parse_metric_m

class TestAkerAccessPathProfileCore(unittest.TestCase):
    def test_metric_parser(self):
        self.assertEqual(parse_metric_m("4.5"),4.5)
        self.assertEqual(parse_metric_m("4,2 m"),4.2)
        self.assertAlmostEqual(parse_metric_m("450 cm"),4.5)
        self.assertIsNone(parse_metric_m(None))
        self.assertIsNone(parse_metric_m("unknown"))

if __name__=="__main__":
    unittest.main()
