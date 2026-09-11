import importlib.util
import json
import sys
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = SRC / "130_akerpuls_geometry_rolling_backtest.py"
CONFIG = ROOT / "config" / "akerpuls_geometry_rolling_backtest_v0.json"

# The production runner executes the script from src/, where sibling modules such
# as akerminne_mapping_core are naturally importable. Reproduce that environment
# for the dynamic unittest import rather than requiring package installation.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

spec = importlib.util.spec_from_file_location("rolling_geometry_backtest", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class TestRollingGeometryBacktest(unittest.TestCase):
    def test_contract_is_true_rolling_zero_pu(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["years"], list(range(2015, 2026)))
        self.assertEqual(cfg["expected_municipalities"], 33)
        self.assertEqual(cfg["expected_2025_fields"], 128636)
        self.assertEqual(cfg["lineage"]["method"], "primary_predecessor_recursive")
        self.assertFalse(cfg["guards"]["download_data"])
        self.assertFalse(cfg["guards"]["sentinel_api_calls"])
        self.assertFalse(cfg["guards"]["product_prior_freeze"])

    def test_source_side_split_classification(self):
        source = gpd.GeoDataFrame(
            {"blockid": ["B"], "skiftesbeteckning": ["A"]},
            geometry=[box(0, 0, 20, 10)], crs="EPSG:3006",
        )
        future = gpd.GeoDataFrame(
            {"blockid": ["C1", "C2"], "skiftesbeteckning": ["A", "A"]},
            geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10)], crs="EPSG:3006",
        )
        cfg = mod.MatchingConfig(.9, .5, .02)
        _matches, edges, _qa = mod.map_fields(future, source, cfg)
        got = mod.classify_source_fields(source, edges, cfg)
        self.assertEqual(len(got), 1)
        self.assertEqual(got.iloc[0]["forward_status"], "split")

    def test_history_categories(self):
        x = pd.DataFrame({
            "history_n": [5, 5, 5],
            "strict_count": [5, 4, 2],
            "strict_streak": [5, 2, 0],
            "splitmerge_count": [0, 1, 2],
        })
        got = mod.add_history_categories(x)
        self.assertEqual(list(got["strict_fraction_bin"]), ["ALL_STRICT", "75_90", "LT50"])
        self.assertEqual(list(got["streak_bin"]), ["5PLUS", "2", "0"])
        self.assertEqual(list(got["prior_splitmerge_any"]), [False, True, True])


if __name__ == "__main__":
    unittest.main()
