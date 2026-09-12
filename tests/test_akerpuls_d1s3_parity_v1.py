import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "142_akerpuls_d1s3_parity_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3_parity_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3ParityV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_contract_is_zero_pu_and_non_mutating(self):
        cfg = self.cfg
        self.assertEqual(cfg["schema_version"], "akerpuls-d1s3-process-s3-parity-v1")
        self.assertEqual(
            cfg["expected_final_execution_contract_sha256"],
            "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19",
        )
        self.assertTrue(all(v is False for v in cfg["guards"].values()))
        self.assertEqual(cfg["preprocessing"]["reflectance_resampling"], "NEAREST")
        self.assertEqual(cfg["preprocessing"]["quality_resampling"], "NEAREST")
        self.assertEqual(cfg["preprocessing"]["mosaicking_order"], "mostRecent")

    def test_required_direct_assets_are_frozen(self):
        self.assertEqual(
            self.cfg["assets"],
            {
                "B02": "B02_10m",
                "B03": "B03_10m",
                "B04": "B04_10m",
                "B08": "B08_10m",
                "B11": "B11_20m",
                "SCL": "SCL_20m",
                "CLD": "CLD_20m",
            },
        )

    def test_scene_order_is_most_recent_first_when_sorted_reverse(self):
        older = {"id": "A", "properties": {"datetime": "2026-04-08T10:20:00Z", "created": "2026-04-08T12:00:00Z"}}
        newer = {"id": "B", "properties": {"datetime": "2026-04-08T10:25:00Z", "created": "2026-04-08T12:00:00Z"}}
        ordered = sorted([older, newer], key=self.m.scene_sort_key, reverse=True)
        self.assertEqual(ordered[0]["id"], "B")

    def test_equal_arrays_pass_parity(self):
        arr = np.zeros((8, 400, 400), dtype=np.float32)
        arr[0:5] = 0.2
        arr[5] = 4.0
        arr[6] = 10.0
        arr[7] = 1.0
        rows, summary = self.m.compare_arrays(arr, arr.copy(), self.cfg["parity_thresholds"])
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["compared_pixels"], 160000)
        self.assertEqual(summary["datamask_agreement"], 1.0)
        self.assertEqual(summary["scl_agreement"], 1.0)
        self.assertTrue(all(row["pass"] for row in rows))


if __name__ == "__main__":
    unittest.main()
