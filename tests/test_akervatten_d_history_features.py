from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "akervatten_d", ROOT / "src/97_akervatten_d_history_features.py"
)
assert spec and spec.loader
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)


class TestAkerVattenDHistoryFeatures(unittest.TestCase):
    def test_consecutive_run_resets_on_date_gap(self):
        dates = pd.to_datetime([
            "2025-06-01","2025-06-02","2025-06-03",
            "2025-06-05","2025-06-06"
        ])
        hit = pd.Series([True,True,True,True,True])
        self.assertEqual(D.consecutive_true_run(pd.Series(dates), hit), 3)

    def test_validate_sgu_history_span(self):
        df = pd.DataFrame({
            "datum":["1961-01-01","2025-01-01"],
            "omrade_id":["49060","49060"],
            "grundvattensituation_sma":["10","20"],
            "grundvattensituation_stora":["-1","-1"],
            "fyllnadsgrad_sma":["5","30"],
            "fyllnadsgrad_stora":["-1","-1"],
        })
        info = D.validate_sgu_history(df, "49060", 50)
        self.assertGreater(info["history_years"], 60)

    def test_flow_stat_header_does_not_bleed_into_unknown_group(self):
        raw = pd.DataFrame([
            [None,None,None,None,"MQ",None,None,"MLQ",None,None,"OTHER",None,None],
            ["Subid","Aroid","Area [km²]",None,
             "Total vattenföring [m³/s]","Total stationskorrigerad vattenföring [m³/s]","Total naturlig vattenföring [m³/s]",
             "Total vattenföring [m³/s]","Total stationskorrigerad vattenföring [m³/s]","Total naturlig vattenföring [m³/s]",
             "Total vattenföring [m³/s]","Total stationskorrigerad vattenföring [m³/s]","Total naturlig vattenföring [m³/s]"],
            [1,"A",10,None,5,4,6,1,0.8,1.2,99,99,99],
        ])
        header_row, stat_row, labels = D.find_flowstats_headers(raw)
        self.assertEqual(header_row, 1)
        self.assertEqual(stat_row, 0)
        self.assertEqual(labels[4:7], ["MQ","MQ","MQ"])
        self.assertEqual(labels[7:10], ["MLQ","MLQ","MLQ"])
        self.assertEqual(labels[10:13], [None,None,None])

    def test_specific_discharge_converts_m2_to_km2(self):
        c = pd.DataFrame({
            "ARO_UUID":["A"],
            "Vattenwebb_Aroid":["A"],
            "Subid":["101"],
            "AREA_UPSTREAM":[10_000_000.0],  # 10 km²
        })
        flow = pd.DataFrame({
            "Subid_flowstats":["101"],
            "Aroid_flowstats":["A"],
            "_subid":["101"],
            "_aroid":["A"],
            "sw_MQ_total_m3s":[2.0],
            "sw_MLQ_total_m3s":[1.0],
            "sw_MQ_natural_m3s":[2.0],
            "sw_MLQ_natural_m3s":[1.0],
        })
        out, info = D.prepare_surface_units(c, flow)
        self.assertEqual(info["mapped_units"], 1)
        self.assertAlmostEqual(out.loc[0,"sw_area_upstream_km2"], 10.0)
        self.assertAlmostEqual(out.loc[0,"sw_MLQ_total_lps_km2_upstream"], 100.0)
        self.assertAlmostEqual(out.loc[0,"sw_MLQ_MQ_ratio_total"], 0.5)

    def test_nadia_batches_cover_all_ids_once(self):
        cfg = {"nadia_d2_prep":{
            "batch_size_subids":50,
            "timestep":"dygn",
            "first_year":1991,
            "last_year":2025,
        }}
        ids = [str(i) for i in range(1,503)]
        with tempfile.TemporaryDirectory() as td:
            info = D.write_nadia_batches(ids, cfg, Path(td))
            self.assertEqual(info["n_batches"], 11)
            seen = []
            for b in info["batches"]:
                seen.extend(b["ids"])
            self.assertEqual(seen, ids)


if __name__ == "__main__":
    unittest.main()
