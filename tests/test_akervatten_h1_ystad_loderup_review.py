from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_h1",ROOT/"src"/"109_akervatten_h1_ystad_loderup_review.py"
)
assert spec and spec.loader
H1=importlib.util.module_from_spec(spec)
spec.loader.exec_module(H1)

class TestAkerVattenH1(unittest.TestCase):
    def test_norm_id(self):
        self.assertEqual(H1.norm_id("123.0"),"123")
        self.assertEqual(H1.norm_id(" abc "),"ABC")
        self.assertIsNone(H1.norm_id(None))

    def test_join_text(self):
        self.assertEqual(H1.join_text(pd.Series(["B","A","B",None])),"A | B")

    def test_distance(self):
        a=pd.Series({"x3006":1000.0,"y3006":2000.0})
        b=pd.Series({"x3006":4000.0,"y3006":6000.0})
        self.assertAlmostEqual(H1.pair_distance_km(a,b),5.0)

if __name__=="__main__":
    unittest.main()
