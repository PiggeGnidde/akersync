from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_f5",ROOT/"src"/"104_akervatten_f5_final_candidate.py"
)
assert spec and spec.loader
F5=importlib.util.module_from_spec(spec)
spec.loader.exec_module(F5)

class TestAkerVattenF5(unittest.TestCase):
    def test_hurdle_zero_and_positive(self):
        s=pd.Series([0.0,1.0,2.0,np.nan])
        q=F5.hurdle_percentile(s)
        self.assertEqual(q.iloc[0],0.0)
        self.assertGreater(q.iloc[1],0.0)
        self.assertEqual(q.iloc[2],100.0)
        self.assertTrue(pd.isna(q.iloc[3]))

    def test_top_overlap_identical(self):
        s=pd.Series(range(1,11),dtype=float)
        self.assertAlmostEqual(F5.top_overlap(s,s,.2),1.0)

if __name__=="__main__":
    unittest.main()
