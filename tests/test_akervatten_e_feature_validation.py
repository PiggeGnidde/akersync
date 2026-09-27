from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_e", ROOT / "src/98_akervatten_e_feature_validation.py"
)
assert spec and spec.loader
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


class TestAkerVattenEFeatureValidation(unittest.TestCase):
    def test_alias_resolution(self):
        cols = ["sand_mean", "TWI_MEAN", "other"]
        self.assertEqual(E.resolve_alias(cols, ["sand_mean"]), "sand_mean")
        self.assertEqual(E.resolve_alias(cols, ["twi_mean"]), "TWI_MEAN")
        self.assertIsNone(E.resolve_alias(cols, ["slope_mean"]))

    def test_oriented_pair_diagnostics(self):
        df = pd.DataFrame({
            "a":[1,2,3,4,5,6,7,8,9,10],
            "b":[10,9,8,7,6,5,4,3,2,1],
        })
        candidates = {
            "a":{"column":"a","direction":1},
            "b":{"column":"b","direction":-1},
        }
        q = E.pair_diagnostics(df, "X", candidates, 0.2)
        self.assertEqual(len(q), 1)
        self.assertAlmostEqual(q.loc[0,"spearman_oriented"], 1.0)
        self.assertAlmostEqual(q.loc[0,"top_overlap_fraction"], 1.0)

    def test_field_vs_unit_shift(self):
        stats = pd.DataFrame([
            {"family":"G","candidate":"x","weighting":"field_weighted","p10":1.0,"p50":5.0,"p90":9.0},
            {"family":"G","candidate":"x","weighting":"unit_weighted","p10":2.0,"p50":4.0,"p90":8.0},
        ])
        q = E.quantile_shift_table(stats)
        self.assertEqual(len(q), 1)
        self.assertAlmostEqual(q.loc[0,"median_shift_field_minus_unit"], 1.0)

    def test_mark_torka_and_vata_not_forced_inverse(self):
        fields = pd.DataFrame({
            "sand_mean":[90,70,30,10],
            "clay_mean":[5,20,40,60],
            "twi_mean":[2,8,3,9],
        })
        torka = {
            "sand":{"column":"sand_mean","direction":1},
            "low_twi":{"column":"twi_mean","direction":-1},
        }
        vata = {
            "clay":{"column":"clay_mean","direction":1},
            "high_twi":{"column":"twi_mean","direction":1},
        }
        qt = E.pair_diagnostics(fields, "MarkTorka", torka, 0.25)
        qv = E.pair_diagnostics(fields, "MarkVata", vata, 0.25)
        self.assertTrue(np.isfinite(qt.loc[0,"spearman_oriented"]))
        self.assertTrue(np.isfinite(qv.loc[0,"spearman_oriented"]))
        # No code path constructs one family as 1 - the other.
        self.assertNotEqual(
            qt.loc[0,"spearman_oriented"],
            -qv.loc[0,"spearman_oriented"]
        )

    def test_extremes_direction(self):
        df = pd.DataFrame({
            "omrade_id":["a","b","c","d"],
            "x":[1.0,2.0,3.0,4.0],
        })
        meta = {"column":"x","direction":-1}
        q = E.extremes(df,"G","x",meta,1)
        hi = q[q["tail"].eq("directional_high")].iloc[0]
        lo = q[q["tail"].eq("directional_low")].iloc[0]
        self.assertEqual(hi["omrade_id"], "a")
        self.assertEqual(lo["omrade_id"], "d")


if __name__ == "__main__":
    unittest.main()
