from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "140_akerpuls_full_skane_d1_acquisition_v1.py"
CFG = ROOT / "config" / "akerpuls_full_skane_d1_acquisition_v1.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("d1_acq_test_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAkerPulsFullSkaneD1AcquisitionV1(unittest.TestCase):
    def test_contract_and_guards_are_pinned(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["schema_version"], "akerpuls-full-skane-d1-acquisition-v1")
        self.assertEqual(cfg["expected_final_execution_contract_sha256"], "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19")
        self.assertEqual(cfg["expected_process_requests"], 593)
        self.assertEqual(cfg["expected_snapshot_tiles"], 568)
        self.assertEqual(cfg["expected_raster_tiles"], 142)
        self.assertAlmostEqual(cfg["estimated_pu_upper"], 5534.67, places=2)
        self.assertFalse(any(bool(v) for v in cfg["guards"].values()))

    def test_payload_keeps_frozen_preprocessing(self):
        m = load_mod()
        source = {
            "collection":"sentinel-2-l2a",
            "processing_upsampling":"NEAREST",
            "processing_downsampling":"NEAREST",
            "harmonize_values":True,
        }
        p = m.process_payload("2026-05-25", [100,200,10340,10440], 1024, 1024, source)
        d = p["input"]["data"][0]
        self.assertEqual(d["processing"]["upsampling"], "NEAREST")
        self.assertEqual(d["processing"]["downsampling"], "NEAREST")
        self.assertTrue(d["processing"]["harmonizeValues"])
        self.assertEqual(p["output"]["width"], 1024)
        self.assertEqual(p["output"]["height"], 1024)

    def test_pair_rule_prefers_clear_then_lower_cld(self):
        m = load_mod()
        h = w = 3
        a = np.zeros((8,h,w), dtype=np.float32)
        b = np.zeros((8,h,w), dtype=np.float32)
        a[7] = 1; b[7] = 1
        a[5] = 4; b[5] = 4
        a[6] = 30; b[6] = 10
        a[2] = .2; a[3] = .4; a[4] = .1
        b[2] = .2; b[3] = .6; b[4] = .1
        out = m.combine_snapshot([(0,a),(1,b)], w, h, {2,4,5})
        self.assertEqual(out.shape, (11,h,w))
        self.assertTrue(np.all(out[10] == 1))
        self.assertTrue(np.all(out[7] == 1))
        self.assertTrue(np.allclose(out[3], .6))

    def test_single_second_date_preserves_source_date_index(self):
        m = load_mod()
        h = w = 2
        b = np.zeros((8,h,w), dtype=np.float32)
        b[7] = 1; b[5] = 4; b[6] = 10
        out = m.combine_snapshot([(1,b)], w, h, {2,4,5})
        self.assertTrue(np.all(out[10] == 1))
        empty = m.combine_snapshot([], w, h, {2,4,5})
        self.assertTrue(np.all(empty[7] == 0))
        self.assertTrue(np.all(empty[10] == -1))


if __name__ == "__main__":
    unittest.main()
