from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_h2",ROOT/"src"/"110_akervatten_h2_product_dimensions.py"
)
assert spec and spec.loader
H2=importlib.util.module_from_spec(spec)
spec.loader.exec_module(H2)

class TestAkerVattenH2(unittest.TestCase):
    def test_score_bands(self):
        self.assertEqual(H2.score_band(0),"Mycket låg")
        self.assertEqual(H2.score_band(19.99),"Mycket låg")
        self.assertEqual(H2.score_band(20),"Låg")
        self.assertEqual(H2.score_band(40),"Måttlig")
        self.assertEqual(H2.score_band(60),"Hög")
        self.assertEqual(H2.score_band(80),"Mycket hög")
        self.assertEqual(H2.score_band(100),"Mycket hög")

    def test_highest_capacity_uses_known_lower_bound(self):
        q=pd.DataFrame({
            "withdrawal_lower_lps":[0.0,5.0,25.0,None],
            "withdrawal_upper_lps":[1.0,25.0,125.0,None],
            "withdrawal_label_norm":["<1","5-25","25-125","unknown"],
            "unik_magasinsidentitet":["A","B","C","D"],
            "unik_delomradesidentitet":["1","2","3","4"]
        })
        r=H2.choose_highest_mapped_capacity(q)
        self.assertIsNotNone(r)
        self.assertEqual(r["withdrawal_label_norm"],"25-125")
        self.assertEqual(float(r["withdrawal_lower_lps"]),25.0)

    def test_unknown_capacity_is_not_promoted(self):
        q=pd.DataFrame({
            "withdrawal_lower_lps":[None,None],
            "withdrawal_upper_lps":[None,None],
            "withdrawal_label_norm":["unknown","not assessed"],
            "unik_magasinsidentitet":["A","B"],
            "unik_delomradesidentitet":["1","2"]
        })
        self.assertIsNone(H2.choose_highest_mapped_capacity(q))

if __name__=="__main__":
    unittest.main()
