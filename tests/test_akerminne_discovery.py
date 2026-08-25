from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def load_script():
    spec = importlib.util.spec_from_file_location("akerminne_discovery", SRC / "akerminne_discovery_core.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


m = load_script()


class CandidateTests(unittest.TestCase):
    def test_candidate_score_prefers_year_kind_and_gpkg(self):
        good = Path("arslager_skifte_2020.gpkg")
        bad = Path("misc_2020.gpkg")
        self.assertGreater(m.candidate_score(good, "skiften", 2020), m.candidate_score(bad, "skiften", 2020))

    def test_find_candidates_accepts_year_in_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "jv_2020"
            raw.mkdir()
            candidate = raw / "arslager_skifte.gpkg"
            candidate.touch()
            self.assertEqual(m.find_candidates(Path(tmp), "skiften", 2020), [candidate])

    def test_resolve_2025_prefers_project_local_paths(self):
        local_cfg = {"raw_root": "X", "year_sources": {}}
        project_cfg = {"skiften": r"C:\raw\skiften.gpkg", "blocks": r"C:\raw\blocks.gpkg"}
        got = m.resolve_source(local_cfg, project_cfg, 2025, "skiften")
        self.assertEqual(got["resolution"], "project_local_paths_2025")
        self.assertTrue(got["path"].endswith("skiften.gpkg"))


class GisInspectionTests(unittest.TestCase):
    def test_inspect_and_skurup_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocks_path = root / "arslager_block_2020.gpkg"
            skiften_path = root / "arslager_skifte_2020.gpkg"
            blocks = gpd.GeoDataFrame(
                {
                    "arslager": [2020, 2020],
                    "blockid": ["1264A", "1286B"],
                    "region_kod": ["12640", "12860"],
                },
                geometry=[box(0, 0, 100, 100), box(1000, 1000, 1100, 1100)],
                crs="EPSG:3006",
            )
            skiften = gpd.GeoDataFrame(
                {
                    "arslager": [2020, 2020, 2020],
                    "blockid": ["1264A", "1264A", "1286B"],
                    "skiftesbeteckning": ["A", "B", "A"],
                    "grdkod_mar": [4, 47, 20],
                    "grdkod_und": [None, None, None],
                },
                geometry=[box(0, 0, 50, 100), box(50, 0, 100, 100), box(1000, 1000, 1100, 1100)],
                crs="EPSG:3006",
            )
            blocks.to_file(blocks_path, layer="arslager_block", driver="GPKG")
            skiften.to_file(skiften_path, layer="arslager_skifte", driver="GPKG")
            bm = m.inspect_dataset(blocks_path, "blocks", 2020, do_hash=False)
            sm = m.inspect_dataset(skiften_path, "skiften", 2020, do_hash=False)
            self.assertEqual(bm["crs"], "EPSG:3006")
            self.assertEqual(sm["feature_count"], 3)
            contract = {
                "region_column": "region_kod",
                "current_block_column": "blockid",
                "current_field_column": "skiftesbeteckning",
                "crop_code_column": "grdkod_mar",
                "crop_subcategory_column": "grdkod_und",
            }
            subset = m.inspect_skurup_subset(sm, bm, contract, "1264")
            self.assertTrue(subset["available"])
            self.assertEqual(subset["skifte_rows"], 2)
            self.assertEqual(subset["block_rows"], 1)
            self.assertEqual(subset["duplicate_field_key_rows"], 0)
            self.assertTrue(subset["crop_code_available"])

    def test_choose_layer_uses_kind_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi.gpkg"
            g = gpd.GeoDataFrame({"x": [1]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:3006")
            g.to_file(path, layer="other", driver="GPKG")
            g.to_file(path, layer="arslager_skifte", driver="GPKG", append=True)
            self.assertEqual(m.choose_layer(path, "skiften"), "arslager_skifte")


if __name__ == "__main__":
    unittest.main()
