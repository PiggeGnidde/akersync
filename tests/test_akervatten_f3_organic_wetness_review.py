from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("akervatten_f3",ROOT/"src"/"102_akervatten_f3_organic_wetness_review.py")
assert spec and spec.loader
F3=importlib.util.module_from_spec(spec)
spec.loader.exec_module(F3)

class TestAkerVattenF3(unittest.TestCase):
    def test_percentile_direction(self):
        s=pd.Series([1.0,2.0,3.0])
        self.assertEqual(F3.pct(s,1).tolist(),[0.0,50.0,100.0])

    def test_top_overlap_identical(self):
        s=pd.Series(range(1,11),dtype=float)
        self.assertAlmostEqual(F3.top_overlap(s,s,.2),1.0)

if __name__=="__main__":
    unittest.main()
