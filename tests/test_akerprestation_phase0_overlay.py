#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from akerprestation_phase0_overlay_core import (
    SOIL_SPEC, SKO_SPEC, overlay_fields, combine_context,
    field_id, text_id, checkpoint_valid, atomic_parquet, atomic_json,
)

def gf(geom, block="b1", skifte="s1"):
    return gpd.GeoDataFrame([{"blockid": block, "skiftesbeteckning": skifte, "geometry": geom}], crs=3006)

def refs(rows):
    return gpd.GeoDataFrame(rows, crs=3006)

class OverlaySyntheticTests(unittest.TestCase):
    def run_layer(self, field_geom, ref_rows, spec):
        s,c,q = overlay_fields(gf(field_geom), refs(ref_rows), spec, "Test", progress_every=0, progress=lambda _: None)
        return s.iloc[0], c, q

    def test_single_class_and_sko(self):
        f = Polygon([(0,0),(10,0),(10,10),(0,10)])
        s,c,_ = self.run_layer(f,[{"OBJECTID_12":1,"KLASS":4,"geometry":f}],SOIL_SPEC)
        self.assertEqual(s.dominant_soil_class,4); self.assertAlmostEqual(s.soil_class_coverage_raw,1)
        s2,c2,_ = self.run_layer(f,[{"id":1,"skordeomrade":"0731","geometry":f}],SKO_SPEC)
        self.assertEqual(s2.dominant_sko_id,"0731"); self.assertAlmostEqual(s2.sko_coverage_raw,1)

    def test_60_40_soil_split(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"OBJECTID_12":1,"KLASS":3,"geometry":Polygon([(0,0),(6,0),(6,10),(0,10)])},
              {"OBJECTID_12":2,"KLASS":4,"geometry":Polygon([(6,0),(10,0),(10,10),(6,10)])}]
        s,c,_=self.run_layer(f,rows,SOIL_SPEC)
        self.assertEqual(s.dominant_soil_class,3); self.assertAlmostEqual(s.dominant_soil_class_share,.6); self.assertEqual(s.soil_class_count,2)

    def test_sko_split(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"id":1,"skordeomrade":"1211","geometry":Polygon([(0,0),(7,0),(7,10),(0,10)])},
              {"id":2,"skordeomrade":"1212","geometry":Polygon([(7,0),(10,0),(10,10),(7,10)])}]
        s,_,_=self.run_layer(f,rows,SKO_SPEC)
        self.assertTrue(s.crosses_sko_boundary); self.assertEqual(s.dominant_sko_id,"1211")

    def test_partial_soil_coverage(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        r=Polygon([(0,0),(5,0),(5,10),(0,10)])
        s,_,_=self.run_layer(f,[{"OBJECTID_12":1,"KLASS":2,"geometry":r}],SOIL_SPEC)
        self.assertAlmostEqual(s.soil_class_coverage_raw,.5); self.assertAlmostEqual(s.unclassified_soil_share,.5)

    def test_no_soil_coverage(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        r=Polygon([(20,20),(30,20),(30,30),(20,30)])
        s,c,_=self.run_layer(f,[{"OBJECTID_12":1,"KLASS":2,"geometry":r}],SOIL_SPEC)
        self.assertEqual(len(c),0); self.assertAlmostEqual(s.soil_class_coverage_raw,0)

    def test_partial_sko_coverage(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        r=Polygon([(0,0),(8,0),(8,10),(0,10)])
        s,_,_=self.run_layer(f,[{"id":1,"skordeomrade":"1211","geometry":r}],SKO_SPEC)
        self.assertAlmostEqual(s.sko_coverage_unique,.8)

    def test_overlapping_soil_coverage_gt_one(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"OBJECTID_12":1,"KLASS":3,"geometry":f},{"OBJECTID_12":2,"KLASS":4,"geometry":f}]
        s,_,_=self.run_layer(f,rows,SOIL_SPEC)
        self.assertAlmostEqual(s.soil_class_coverage_raw,2); self.assertAlmostEqual(s.soil_class_coverage_unique,1)
        self.assertIn("DUPLICATE_CLASS_OVERLAP",s.soil_class_reason_flags)

    def test_overlapping_sko_coverage_gt_one(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"id":1,"skordeomrade":"1211","geometry":f},{"id":2,"skordeomrade":"1212","geometry":f}]
        s,_,_=self.run_layer(f,rows,SKO_SPEC)
        self.assertAlmostEqual(s.sko_coverage_raw,2); self.assertIn("DUPLICATE_SKO_OVERLAP",s.sko_reason_flags)

    def test_tiny_sliver_is_preserved(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"OBJECTID_12":1,"KLASS":5,"geometry":Polygon([(0,0),(9.999,0),(9.999,10),(0,10)])},
              {"OBJECTID_12":2,"KLASS":4,"geometry":Polygon([(9.999,0),(10,0),(10,10),(9.999,10)])}]
        s,c,_=self.run_layer(f,rows,SOIL_SPEC)
        self.assertEqual(len(c),2); self.assertGreater(float(c["intersection_area_m2"].min()),0)

    def test_invalid_repairable_field(self):
        bow=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
        ref=Polygon([(-1,-1),(11,-1),(11,11),(-1,11)])
        s,_,q=self.run_layer(bow,[{"OBJECTID_12":1,"KLASS":3,"geometry":ref}],SOIL_SPEC)
        self.assertIn("REPAIRED_FIELD_GEOMETRY",s.soil_class_reason_flags); self.assertEqual(q["field_repaired"],1)

    def test_invalid_repairable_reference(self):
        f=Polygon([(-1,-1),(11,-1),(11,11),(-1,11)])
        bow=Polygon([(0,0),(10,10),(0,10),(10,0),(0,0)])
        s,_,q=self.run_layer(f,[{"OBJECTID_12":1,"KLASS":3,"geometry":bow}],SOIL_SPEC)
        self.assertGreaterEqual(q["reference_geometry"]["repaired"],1)

    def test_empty_geometry(self):
        empty=Polygon()
        s,_,q=self.run_layer(empty,[{"OBJECTID_12":1,"KLASS":3,"geometry":Polygon([(0,0),(1,0),(1,1),(0,1)])}],SOIL_SPEC)
        self.assertEqual(s.soil_class_geometry_status,"EMPTY")

    def test_unknown_soil_code_is_not_silenced(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        s,c,_=self.run_layer(f,[{"OBJECTID_12":1,"KLASS":99,"geometry":f}],SOIL_SPEC)
        self.assertIn("UNVERIFIED_CLASS_CODE",s.soil_class_reason_flags)
        self.assertEqual(str(c.iloc[0].soil_class_raw),"99")
        self.assertTrue(pd.isna(c.iloc[0].soil_class_normalized))

    def test_sko_leading_zero(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        s,c,_=self.run_layer(f,[{"id":1,"skordeomrade":"0731","geometry":f}],SKO_SPEC)
        self.assertEqual(s.dominant_sko_id,"0731"); self.assertEqual(c.iloc[0].sko_id,"0731")

    def test_blank_sko_id_is_preserved_and_flagged(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        s,c,_=self.run_layer(f,[{"id":999,"skordeomrade":None,"geometry":f}],SKO_SPEC)
        self.assertIn("UNVERIFIED_SKO_ID",s.sko_reason_flags)
        self.assertEqual(c.iloc[0].sko_id,"")

    def test_missing_crs_rejected(self):
        f=gpd.GeoDataFrame([{"blockid":"b","skiftesbeteckning":"s","geometry":Polygon([(0,0),(1,0),(1,1),(0,1)])}])
        r=refs([{"OBJECTID_12":1,"KLASS":1,"geometry":Polygon([(0,0),(1,0),(1,1),(0,1)])}])
        with self.assertRaises(ValueError): overlay_fields(f,r,SOIL_SPEC,"Test",progress_every=0,progress=lambda _:None)

    def test_deterministic_component_sort(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        rows=[{"OBJECTID_12":2,"KLASS":4,"geometry":Polygon([(5,0),(10,0),(10,10),(5,10)])},
              {"OBJECTID_12":1,"KLASS":3,"geometry":Polygon([(0,0),(5,0),(5,10),(0,10)])}]
        _,c1,_=self.run_layer(f,rows,SOIL_SPEC); _,c2,_=self.run_layer(f,list(reversed(rows)),SOIL_SPEC)
        self.assertEqual(c1[["soil_class_raw","component_rank"]].to_dict("records"),c2[["soil_class_raw","component_rank"]].to_dict("records"))

    def test_context_join_one_to_one(self):
        f=Polygon([(0,0),(10,0),(10,10),(0,10)])
        soil,_,_=overlay_fields(gf(f),refs([{"OBJECTID_12":1,"KLASS":4,"geometry":f}]),SOIL_SPEC,"Test",progress_every=0,progress=lambda _:None)
        sko,_,_=overlay_fields(gf(f),refs([{"id":1,"skordeomrade":"0731","geometry":f}]),SKO_SPEC,"Test",progress_every=0,progress=lambda _:None)
        x=combine_context(soil,sko,"m1")
        self.assertEqual(len(x),1); self.assertEqual(x.iloc[0].context_status,"COMPLETE_SINGLE_CONTEXT")

    @unittest.skipUnless(__import__("importlib").util.find_spec("pyarrow") is not None or __import__("importlib").util.find_spec("fastparquet") is not None, "Parquet engine not installed in test runtime")
    def test_checkpoint_requires_complete_valid_files(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); s=d/"s.parquet"; c=d/"c.parquet"; m=d/"m.json"
            df=pd.DataFrame([{"current_field_id":"a"}])
            atomic_parquet(df,s); atomic_parquet(df,c)
            expected={"schema_version":"x"}
            self.assertFalse(checkpoint_valid(s,c,m,expected))
            atomic_json({"schema_version":"x","summary_rows":1,"component_rows":1},m)
            self.assertTrue(checkpoint_valid(s,c,m,expected))
            (d/"s.tmp.parquet").write_bytes(b"incomplete")
            self.assertTrue(checkpoint_valid(s,c,m,expected))

if __name__ == "__main__":
    unittest.main()
