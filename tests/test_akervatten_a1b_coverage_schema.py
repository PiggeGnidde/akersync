from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_a1b", ROOT / "src/92_akervatten_a1b_coverage_schema.py"
)
assert spec and spec.loader
A1B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A1B)


class TestAkerVattenA1bCoverageSchema(unittest.TestCase):
    def test_reconstruct_old_filter(self):
        soil = pd.DataFrame({
            "blockid":["1","2","3"],
            "skiftesbeteckning":["A","B","C"],
            "area_ha":[2.0,0.5,2.0],
            "clay_mean":[20,20,None],
            "sand_mean":[40,40,40],
            "clay_coverage_pct":[95,95,95],
            "sand_coverage_pct":[95,95,95],
            "clay_n_pix":[20,20,20],
            "sand_n_pix":[20,20,20],
        })
        hydro = pd.DataFrame({
            "blockid":["1","2","3"],
            "skiftesbeteckning":["A","B","C"],
            "twi_mean":[8,8,8],
            "twi_n_cells":[30,30,30],
        })
        cfg={"old_robust_filter":{
            "min_area_ha":1.0,
            "min_soil_coverage_pct":90.0,
            "min_soil_pixels":10,
            "min_twi_cells":25,
        }}
        out=A1B.reconstruct_old_eligibility(soil,hydro,cfg)
        self.assertEqual(out.loc[0,"a1b_data_status"],"OLD_ROBUST")
        self.assertEqual(out.loc[1,"a1b_data_status"],"AVAILABLE_BUT_NOT_OLD_ROBUST")
        self.assertEqual(out.loc[2,"a1b_data_status"],"DATA_MISSING")

    def test_static_context_pattern_match(self):
        df=pd.DataFrame({
            "current_field_id":["1","2"],
            "slope_p90":[1.2,2.3],
            "foo":[1,2],
            "tpi150_mean":[0.1,-0.2],
        })
        matches, allcols=A1B.static_context_inventory(df,["slope","tpi","hydro"])
        self.assertEqual(set(matches["column"]),{"slope_p90","tpi150_mean"})
        self.assertEqual(len(allcols),4)

    def test_exact_old_subset_match(self):
        rec=pd.DataFrame({
            "blockid":["1","2"],
            "skiftesbeteckning":["A","B"],
            "old_robust":[True,False],
        })
        old=pd.DataFrame({"blockid":["1"],"skiftesbeteckning":["A"]})
        q=A1B.verify_old_subset_matches(rec,old)
        self.assertTrue(q["exact_key_match"])
        self.assertEqual(q["intersection"],1)


if __name__=="__main__":
    unittest.main()
