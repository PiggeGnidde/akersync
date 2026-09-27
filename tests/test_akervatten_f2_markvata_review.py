from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("akervatten_f2",ROOT/"src"/"101_akervatten_f2_markvata_review.py")
assert spec and spec.loader
F2=importlib.util.module_from_spec(spec)
spec.loader.exec_module(F2)

class TestAkerVattenF2(unittest.TestCase):
    def test_harmonic_penalizes_discordance(self):
        a=pd.Series([90.0,90.0])
        b=pd.Series([90.0,10.0])
        h=F2.harmonic(a,b)
        self.assertAlmostEqual(h.iloc[0],90.0)
        self.assertLess(h.iloc[1],50.0)

    def test_top_overlap(self):
        a=pd.Series([1,2,3,4,5,6,7,8,9,10],dtype=float)
        b=a.copy()
        self.assertAlmostEqual(F2.top_overlap(a,b,0.2),1.0)

if __name__=="__main__":
    unittest.main()
