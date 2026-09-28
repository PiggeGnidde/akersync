from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_h0",ROOT/"src"/"108_akervatten_h0_large_groundwater_inventory.py"
)
assert spec and spec.loader
H0=importlib.util.module_from_spec(spec)
spec.loader.exec_module(H0)

class TestAkerVattenH0(unittest.TestCase):
    def test_standard_withdrawal_classes(self):
        self.assertEqual(H0.withdrawal_info(2002,"1–5 l/s")[:2],(1.0,5.0))
        self.assertEqual(H0.withdrawal_info(2004,"25–125 l/s")[:2],(25.0,125.0))
        lo,hi,_=H0.withdrawal_info(2005,">125 l/s")
        self.assertEqual(lo,125.0)
        self.assertIsNone(hi)

    def test_legacy_hourly_conversion(self):
        lo,hi,_=H0.withdrawal_info(1012,"sedimentärt berg 6 000–20 000 l/h")
        self.assertAlmostEqual(lo,6000/3600)
        self.assertAlmostEqual(hi,20000/3600)

    def test_unknown_is_not_imputed(self):
        lo,hi,_=H0.withdrawal_info(2007,"okända uttagsmöjligheter")
        self.assertIsNone(lo)
        self.assertIsNone(hi)

    def test_string_join_is_deterministic(self):
        s=pd.Series(["B","A","B",None])
        self.assertEqual(H0.string_join(s),"A | B")

if __name__=="__main__":
    unittest.main()
