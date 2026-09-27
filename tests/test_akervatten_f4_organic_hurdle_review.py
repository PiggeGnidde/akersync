from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location(
    "akervatten_f4", ROOT/"src"/"103_akervatten_f4_organic_hurdle_review.py"
)
assert spec and spec.loader
F4=importlib.util.module_from_spec(spec)
spec.loader.exec_module(F4)

class TestAkerVattenF4OrganicHurdle(unittest.TestCase):
    def test_zero_stays_zero_and_positive_is_positive(self):
        s=pd.Series([0.0,0.0,1.0,2.0,np.nan])
        q=F4.hurdle_percentile(s)
        self.assertEqual(q.iloc[0],0.0)
        self.assertEqual(q.iloc[1],0.0)
        self.assertGreater(q.iloc[2],0.0)
        self.assertEqual(q.iloc[3],100.0)
        self.assertTrue(pd.isna(q.iloc[4]))

    def test_positive_ties_share_rank(self):
        s=pd.Series([0.0,1.0,1.0,3.0])
        q=F4.hurdle_percentile(s)
        self.assertAlmostEqual(q.iloc[1],q.iloc[2])
        self.assertLess(q.iloc[1],q.iloc[3])

    def test_negative_rejected(self):
        with self.assertRaises(RuntimeError):
            F4.hurdle_percentile(pd.Series([0.0,-1.0,2.0]))

if __name__=="__main__":
    unittest.main()
