from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_f", ROOT / "src/100_akervatten_f_component_candidates.py"
)
assert spec and spec.loader
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class TestAkerVattenFComponentCandidates(unittest.TestCase):
    def test_empirical_percentile_direction(self):
        s = pd.Series([1.0,2.0,3.0])
        up = F.empirical_percentile(s,+1)
        down = F.empirical_percentile(s,-1)
        self.assertEqual(up.tolist(),[0.0,50.0,100.0])
        self.assertEqual(down.tolist(),[100.0,50.0,0.0])

    def test_empirical_percentile_ties(self):
        s = pd.Series([1.0,1.0,3.0])
        q = F.empirical_percentile(s,+1)
        self.assertAlmostEqual(q.iloc[0],25.0)
        self.assertAlmostEqual(q.iloc[1],25.0)
        self.assertAlmostEqual(q.iloc[2],100.0)

    def test_component_strict_missing(self):
        df = pd.DataFrame({"a":[1.0,2.0,np.nan],"b":[1.0,np.nan,3.0]})
        q,info = F.build_component(
            df,"MarkTorka",{"a":1,"b":-1},{"a":0.5,"b":0.5},"average"
        )
        self.assertEqual(info["n_complete"],1)
        self.assertTrue(pd.isna(q.loc[1,info["score_column"]]))
        self.assertTrue(pd.isna(q.loc[2,info["score_column"]]))

    def test_unit_weighting_differs_from_field_replication(self):
        units = pd.Series([1.0,2.0,100.0])
        unit_pct = F.empirical_percentile(units,+1)
        self.assertEqual(unit_pct.tolist(),[0.0,50.0,100.0])

        fields = pd.Series([1.0]*100 + [2.0] + [100.0])
        field_pct = F.empirical_percentile(fields,+1)
        # The middle hydrological unit should not inherit this field-weighted
        # percentile in the production design.
        self.assertNotAlmostEqual(float(field_pct.iloc[100]),50.0)

    def test_validate_aggregation_requires_exact_frozen_set(self):
        primary={"A":{"x":1,"y":-1}}
        F.validate_aggregation(primary,{"A":{"x":0.5,"y":0.5}})
        with self.assertRaises(RuntimeError):
            F.validate_aggregation(primary,{"A":{"x":1.0}})


if __name__ == "__main__":
    unittest.main()
