from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import numpy as np
from affine import Affine
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.affinity import translate

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from rapskartan_local_candidate import reference_polygon_mask, reference_reflectance, reference_percentiles, reference_metrics
from rapskartan_map_product_core import aggregate_local_scene_timeseries


class CandidateTests(unittest.TestCase):
    def test_original_is_still_default_and_production_does_not_opt_in(self):
        self.assertEqual(inspect.signature(aggregate_local_scene_timeseries).parameters['engine_profile'].default,'original')
        runner=(ROOT/'src/100_generate_rapskartan_2025_map_product.py').read_text()
        self.assertNotIn('reference_pixels_v2',runner)
        self.assertNotIn('engine_profile=',runner)

    def test_rectangles_holes_multipolygons_and_memory_stripes(self):
        hole=Polygon([(0,0),(5,0),(5,5),(0,5)],holes=[[(1,1),(4,1),(4,4),(1,4)]])
        geometries=[hole,Polygon([(0.03,.14),(4.92,1.03),(2.17,4.85)]),MultiPolygon([box(0,0,1,1),box(3,3,4,4)])]
        for geometry in geometries:
            normal=reference_polygon_mask(geometry,Affine.identity(),(5,5))
            striped=reference_polygon_mask(geometry,Affine.identity(),(5,5),max_bytes=5*2048)
            np.testing.assert_array_equal(normal,striped)
            moved=reference_polygon_mask(translate(geometry,400000,6200000),Affine.translation(400000,6200000),(5,5))
            np.testing.assert_array_equal(normal,moved)
        self.assertEqual(int(reference_polygon_mask(hole,Affine.identity(),(5,5)).sum()),16)

    def test_mask_guard_stops_before_large_allocation(self):
        with self.assertRaisesRegex(RuntimeError,'memory guard'):
            reference_polygon_mask(box(0,0,1,1),Affine.identity(),(10,10),max_bytes=10)
        with self.assertRaises(ValueError):
            reference_polygon_mask(Polygon(),Affine.identity(),(1,1))

    def test_reflectance_truncates_before_harmonization_and_indices(self):
        actual=reference_reflectance(np.array([0.,999.9,1000.,1001.9,2345.999]),.0001,-.1)
        np.testing.assert_array_equal(actual,np.array([0,0,0,.0001,.1345],dtype='float32'))
        self.assertEqual(actual.dtype,np.float32)
        with self.assertRaises(ValueError):reference_reflectance(np.array([1]),0,0)

    def test_percentile_uses_higher_not_interpolation(self):
        values=np.array([0,1,3,10],dtype='float32')
        np.testing.assert_array_equal(reference_percentiles(values),[1,3,10])
        self.assertNotEqual(reference_percentiles(values)[1],np.percentile(values,50))
        with self.assertRaises(ValueError):reference_percentiles(np.array([np.nan]))

    def test_metrics_agree_with_actual_frozen_javascript(self):
        node=shutil.which('node')
        if not node:self.skipTest('Node is only needed for the developer equivalence test')
        from rapskartan_model_core import load_model_contract
        from rapskartan_s2_pilot_core import stat_evalscript
        names=['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12']
        rng=np.random.default_rng(104)
        raw=rng.integers(0,10000,size=(64,10));raw[0]=0
        bands={name:(raw[:,i]/10000).astype('float32') for i,name in enumerate(names)}
        metrics=reference_metrics(bands)
        samples=[{**dict(zip(names,row/10000)), 'SCL':4,'dataMask':1,'CLD':0} for row in raw]
        script=stat_evalscript(load_model_contract(ROOT))
        code="const vm=require('vm');let b='';process.stdin.on('data',v=>b+=v);process.stdin.on('end',()=>{let d=JSON.parse(b),c=vm.createContext({});vm.runInContext(d.script,c);process.stdout.write(JSON.stringify(d.samples.map(s=>c.evaluatePixel(s).default.slice(0,17))));});"
        r=subprocess.run([node,'-e',code],input=json.dumps({'script':script,'samples':samples}),text=True,capture_output=True,check=True)
        expected=np.array(json.loads(r.stdout),dtype='float32')
        order=names+['NDVI','NDRE','EVI2','GNDVI','LSWI','NIRV','YELLOWNESS']
        np.testing.assert_array_equal(np.stack([metrics[name] for name in order],axis=1),expected)

    def test_candidate_launcher_is_offline_and_uses_separate_output(self):
        runner=(ROOT/'RUN_RAPSKARTAN_CANDIDATE_PARITY.bat').read_text()
        self.assertIn('--engine-profile reference_pixels_v2',runner)
        self.assertIn('2025_candidate_parity_v2',runner)
        self.assertNotIn('powershell',runner.lower())
        self.assertNotIn('104_fetch',runner)


if __name__=='__main__':unittest.main()
