from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_a1", ROOT / "src/91_akervatten_a1_local_inventory.py"
)
assert spec and spec.loader
A1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A1)


class TestAkerVattenA1LocalInventory(unittest.TestCase):
    def test_key_profile_detects_unique_pair(self):
        df = pd.DataFrame({
            "blockid": ["1", "2"],
            "skiftesbeteckning": ["A", "B"],
            "x": [1, 2],
        })
        p = A1.key_profile("x", df)
        self.assertEqual(p["key_columns"], ["blockid", "skiftesbeteckning"])
        self.assertEqual(p["unique_keys"], 2)
        self.assertEqual(p["missing_key_rows"], 0)
        self.assertEqual(p["duplicate_key_rows"], 0)

    def test_key_profile_detects_duplicates(self):
        df = pd.DataFrame({
            "blockid": ["1", "1"],
            "skiftesbeteckning": ["A", "A"],
        })
        p = A1.key_profile("x", df)
        self.assertEqual(p["duplicate_key_rows"], 2)

    def test_old_heuristics_reconstruct(self):
        df = pd.DataFrame({
            "clay_pctile": [0.25, 1.0],
            "sand_pctile": [1.0, 0.25],
            "wetness_pctile": [1.0, 0.25],
            "dryness_pctile": [0.25, 1.0],
        })
        df["drainage_challenge_score"] = 100*np.sqrt(df.clay_pctile*df.wetness_pctile)
        df["irrigation_sensitivity_score"] = 100*np.sqrt(df.sand_pctile*df.dryness_pctile)
        q = A1.verify_old_heuristics(df)
        self.assertEqual(q["status"], "PASS")
        self.assertLessEqual(q["drainage_max_abs_error"], 1e-12)
        self.assertLessEqual(q["irrigation_max_abs_error"], 1e-12)

    def test_overlap_pair_key(self):
        a = pd.DataFrame({"blockid": ["1", "2"], "skiftesbeteckning": ["A", "B"]})
        b = pd.DataFrame({"blockid": ["2", "3"], "skiftesbeteckning": ["B", "C"]})
        rows = A1.overlap_rows({"a": a, "b": b})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["intersection"], 1)
        self.assertEqual(rows[0]["union"], 3)


if __name__ == "__main__":
    unittest.main()
