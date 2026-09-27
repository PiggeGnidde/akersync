from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_b", ROOT / "src/94_akervatten_b_pilot.py"
)
assert spec and spec.loader
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


class TestAkerVattenBPilot(unittest.TestCase):
    def test_deterministic_sample_exact_n(self):
        rows = []
        for m in ("A","B"):
            for i in range(10):
                rows.append({
                    "blockid": f"{m}{i}",
                    "skiftesbeteckning": "1",
                    "kommun": m,
                    "sand_mean": 20+i,
                    "clay_mean": 30-i,
                    "silt_mean": 50,
                })
        soil = pd.DataFrame(rows)
        hydro = soil[["blockid","skiftesbeteckning"]].copy()
        hydro["twi_mean"] = np.linspace(5,12,len(hydro))
        hydro["twi_p50"] = hydro["twi_mean"]
        hydro["twi_p90"] = hydro["twi_mean"]+2
        hydro["twi_n_cells"] = 30
        status = soil[["blockid","skiftesbeteckning"]].copy()
        status["a1b_data_status"] = "OLD_ROBUST"
        status["old_robust"] = True
        status.loc[status.index % 4 == 0, "a1b_data_status"] = "AVAILABLE_BUT_NOT_OLD_ROBUST"
        status.loc[status.index % 4 == 0, "old_robust"] = False

        a = B.build_deterministic_sample(soil, hydro, status, 8, "kommun")
        b = B.build_deterministic_sample(soil, hydro, status, 8, "kommun")
        self.assertEqual(len(a), 8)
        self.assertEqual(
            list(map(tuple,a[["blockid","skiftesbeteckning"]].values)),
            list(map(tuple,b[["blockid","skiftesbeteckning"]].values)),
        )
        self.assertFalse(a[["blockid","skiftesbeteckning"]].duplicated().any())

    def test_discover_svar_mapping(self):
        joined = pd.DataFrame({
            "pilot_order":[1,2,3],
            "VAROID":["A","B","C"],
        })
        coupling = pd.DataFrame({
            "AROID":["A","B","C"],
            "SUBID":["11","12","13"],
            "HARO":["1","1","1"],
        })
        q = B.discover_svar_mapping(joined, coupling, 0.95, polygon_columns=["VAROID"])
        self.assertEqual(q["best"]["polygon_column"], "VAROID")
        self.assertEqual(q["best"]["coupling_column"], "AROID")
        self.assertEqual(q["best"]["match_fraction"], 1.0)

    def test_apply_svar_mapping_adds_subid(self):
        joined = pd.DataFrame({"pilot_order":[1,2],"VAROID":["A","B"]})
        coupling = pd.DataFrame({"AROID":["A","B"],"SUBID":["11","12"],"HARO":["1","1"]})
        mapping = {"best":{"polygon_column":"VAROID","coupling_column":"AROID"}}
        out = B.apply_svar_mapping(joined,coupling,mapping)
        self.assertEqual(out["SUBID"].tolist(),["11","12"])

    def test_stable_hash_fits_signed_int64(self):
        h = B.stable_hash("61793327245", "99")
        self.assertGreaterEqual(h, 0)
        self.assertLessEqual(h, (1 << 63) - 1)

    def test_dry_wet_prefer_old_robust(self):
        soil = pd.DataFrame({
            "blockid":["1","2","3","4"],
            "skiftesbeteckning":["A","A","A","A"],
            "kommun":["X","X","X","X"],
            "sand_mean":[99,80,1,20],
            "clay_mean":[1,20,99,80],
            "silt_mean":[0,0,0,0],
        })
        hydro = soil[["blockid","skiftesbeteckning"]].copy()
        hydro["twi_mean"]=[1,2,99,80]
        hydro["twi_p50"]=hydro["twi_mean"]
        hydro["twi_p90"]=hydro["twi_mean"]
        hydro["twi_n_cells"]=30
        status = soil[["blockid","skiftesbeteckning"]].copy()
        status["a1b_data_status"]=[
            "AVAILABLE_BUT_NOT_OLD_ROBUST","OLD_ROBUST",
            "AVAILABLE_BUT_NOT_OLD_ROBUST","OLD_ROBUST"
        ]
        status["old_robust"]=[False,True,False,True]

        out = B.build_deterministic_sample(soil,hydro,status,3,"kommun")
        picked=set(out["blockid"])
        self.assertIn("2", picked)
        self.assertIn("4", picked)

    def test_mapping_rejects_field_attribute_leakage(self):
        joined = pd.DataFrame({
            "pilot_order":[1,2,3],
            "VAROID":["A","B","C"],
            "crop_code":["2","20","3"],
        })
        coupling = pd.DataFrame({
            "AROID":["A","B","C"],
            "SUBID":["2","20","3"],
        })
        q = B.discover_svar_mapping(
            joined, coupling, 0.95, polygon_columns=["VAROID"]
        )
        self.assertEqual(q["best"]["polygon_column"], "VAROID")
        self.assertEqual(q["best"]["coupling_column"], "AROID")

    def test_strict_aro_uuid_to_aroid_mapping(self):
        joined = pd.DataFrame({
            "pilot_order":[1,2,3],
            "ARO_UUID":["abc-def","ghi-jkl","mno-pqr"],
            "crop_code":["2","20","3"],
        })
        flowstats = pd.DataFrame({
            "Aroid":["ABC-DEF","GHI-JKL","MNO-PQR"],
            "Subid":["101","102","103"],
        })
        mapping, out = B.prove_aro_uuid_mapping(joined, flowstats, 0.95)
        self.assertEqual(mapping["best"]["polygon_column"], "ARO_UUID")
        self.assertEqual(mapping["best"]["coupling_column"], "Aroid")
        self.assertEqual(mapping["best"]["match_fraction"], 1.0)
        self.assertEqual(out["Subid"].tolist(), ["101","102","103"])

    def test_strict_aro_uuid_mapping_rejects_wrong_ids(self):
        joined = pd.DataFrame({
            "pilot_order":[1,2,3],
            "ARO_UUID":["A","B","C"],
            "crop_code":["2","20","3"],
        })
        flowstats = pd.DataFrame({
            "Aroid":["X","Y","Z"],
            "Subid":["2","20","3"],
        })
        with self.assertRaises(RuntimeError):
            B.prove_aro_uuid_mapping(joined, flowstats, 0.95)

    def test_wfs_params_use_plain_epsg3006_bbox(self):
        bbox = "1,2,3,4,EPSG:3006"
        p2 = B._wfs_params("WFS2_GML", "ns:layer", bbox)
        self.assertEqual(p2["bbox"], bbox)
        self.assertEqual(p2["srsName"], "EPSG:3006")
        self.assertNotIn("outputFormat", p2)

        p11 = B._wfs_params("WFS11_GML", "ns:layer", bbox)
        self.assertEqual(p11["version"], "1.1.0")
        self.assertEqual(p11["typeName"], "ns:layer")


if __name__ == "__main__":
    unittest.main()
