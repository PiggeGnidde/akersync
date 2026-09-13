import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "143_akerpuls_d1s3b_diagnostic_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3b_diagnostic_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3BDiagnosticV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_zero_pu_non_mutating_diagnostic_only(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3b-mismatch-diagnostic-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(
            self.cfg["expected_final_execution_contract_sha256"],
            "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19",
        )

    def test_declared_variants_are_small_and_explicit(self):
        self.assertEqual(self.cfg["diagnostic_variants"]["scene_order"], ["PARENT", "REVERSED"])
        self.assertEqual(self.cfg["diagnostic_variants"]["coverage"], ["SCL_NONZERO", "SCL_DATASET_MASK"])
        self.assertEqual(self.cfg["diagnostic_variants"]["reflectance"], ["SCALE_OFFSET", "SCALE_OFFSET_CLIP0"])

    def test_scene_interior_removes_owner_seam(self):
        mask = np.ones((7, 7), dtype=bool)
        owner = np.zeros((7, 7), dtype=np.int16)
        owner[:, 4:] = 1
        interior = self.m.scene_interior(mask, owner, 1)
        self.assertFalse(interior[:, 3:5].any())
        self.assertTrue(interior[2, 2])
        self.assertTrue(interior[2, 5])

    def test_ratio_is_stable_at_zero_denominator(self):
        a = np.array([[1.0, 0.0]], dtype=np.float32)
        b = np.array([[1.0, 0.0]], dtype=np.float32)
        got = self.m.ratio(a, b)
        self.assertAlmostEqual(float(got[0, 0]), 0.0)
        self.assertAlmostEqual(float(got[0, 1]), 0.0)


if __name__ == "__main__":
    unittest.main()
