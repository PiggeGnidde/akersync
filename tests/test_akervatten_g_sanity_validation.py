from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_g",ROOT/"src"/"105_akervatten_g_sanity_validation.py"
)
assert spec and spec.loader
G=importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

class TestAkerVattenGSanityValidation(unittest.TestCase):
    def test_band_boundaries(self):
        bands=[
            {"min":0,"max":20,"label":"A"},
            {"min":20,"max":40,"label":"B"},
            {"min":40,"max":100.0001,"label":"C"},
        ]
        self.assertEqual(G.band_label(0,bands),"A")
        self.assertEqual(G.band_label(19.999,bands),"A")
        self.assertEqual(G.band_label(20,bands),"B")
        self.assertEqual(G.band_label(100,bands),"C")

    def test_rank_tail_count(self):
        s=pd.Series(range(100),dtype=float)
        hi=G.rank_tail_indices(s,.10,True)
        lo=G.rank_tail_indices(s,.10,False)
        self.assertEqual(len(hi),10)
        self.assertEqual(len(lo),10)
        self.assertEqual(int(s.loc[hi].min()),90)
        self.assertEqual(int(s.loc[lo].max()),9)

    def test_group_enrichment(self):
        df=pd.DataFrame({
            "g":["A"]*5+["B"]*5,
            "score":[90,80,70,60,50,40,30,20,10,0]
        })
        q=G.group_enrichment(df,"score","g",.20)
        a=q[q["group_value"].eq("A")].iloc[0]
        self.assertEqual(a["high_n"],2)
        self.assertEqual(a["low_n"],0)
        self.assertGreater(a["high_enrichment"],1.0)

if __name__=="__main__":
    unittest.main()
