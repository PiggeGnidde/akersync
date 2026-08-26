#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
spec = importlib.util.spec_from_file_location("akerminne_pilot_download", SRC / "51_download_akerminne_pilot.py")
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class CqlTests(unittest.TestCase):
    def test_block_cql(self):
        self.assertEqual(mod.block_cql(2015, "1264"), "arslager=2015 AND region_kod LIKE '1264%'")

    def test_skifte_bbox_cql(self):
        actual = mod.skifte_bbox_cql(2020, (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(actual, "arslager=2020 AND BBOX(geom,1.000,2.000,3.000,4.000,'EPSG:3006')")


class ValidationTests(unittest.TestCase):
    def blocks(self):
        return gpd.GeoDataFrame(
            {
                "arslager": [2015, 2015],
                "blockid": ["B1", "B2"],
                "region_kod": ["1264010", "1264020"],
                "geometry": [box(0, 0, 10, 10), box(20, 0, 30, 10)],
            },
            crs="EPSG:3006",
        )

    def candidates(self):
        return gpd.GeoDataFrame(
            {
                "arslager": [2015, 2015, 2015],
                "blockid": ["B1", "B2", "OUT"],
                "skiftesbeteckning": ["1A", "2A", "3A"],
                "grdkod_mar": [4, 5, 6],
                "grdkod_und": [0, 0, 0],
                "ansokt_areal_ha": [1.0, 1.0, 1.0],
                "faststalld_areal_ha": [1.0, 1.0, 1.0],
                "geometry": [box(0, 0, 5, 5), box(20, 0, 25, 5), box(40, 0, 45, 5)],
            },
            crs="EPSG:3006",
        )

    def test_validate_blocks_accepts_pilot(self):
        mod.validate_blocks(self.blocks(), 2015, "1264")

    def test_validate_blocks_rejects_wrong_region(self):
        blocks = self.blocks()
        blocks.loc[1, "region_kod"] = "1280010"
        with self.assertRaises(RuntimeError):
            mod.validate_blocks(blocks, 2015, "1264")

    def test_filter_skiften_to_blocks(self):
        out = mod.filter_skiften_to_blocks(self.candidates(), self.blocks(), 2015, "1264")
        self.assertEqual(list(out["blockid"]), ["B1", "B2"])
        self.assertEqual(list(out["region_kod"]), ["1264010", "1264020"])

    def test_download_year_synthetic_end_to_end(self):
        blocks = self.blocks()
        candidates = self.candidates()
        def fake_download(typename, path, cql):
            return blocks.copy() if typename == mod.BLOCK_TYPENAME else candidates.copy()
        def fake_hits(typename, cql):
            return ((len(blocks), "2.0.0") if typename == mod.BLOCK_TYPENAME else (len(candidates), "2.0.0"))
        with tempfile.TemporaryDirectory() as td, \
             patch.object(mod, "download_gpkg", side_effect=fake_download), \
             patch.object(mod, "hit_count_query", side_effect=fake_hits):
            manifest = mod.download_year(Path(td), 2015, "Skurup", "1264", resume=True)
            self.assertEqual(manifest["blocks"]["rows"], 2)
            self.assertEqual(manifest["skiften"]["rows"], 2)
            self.assertTrue((Path(td) / "2015" / "arslager_block_skurup_2015.gpkg").exists())
            self.assertTrue((Path(td) / "2015" / "arslager_skifte_skurup_2015.gpkg").exists())
            self.assertTrue((Path(td) / "2015" / "manifest_skurup_2015.json").exists())


if __name__ == "__main__":
    unittest.main()
