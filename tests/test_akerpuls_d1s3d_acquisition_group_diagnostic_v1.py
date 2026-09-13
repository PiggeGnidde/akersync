import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "145_akerpuls_d1s3d_acquisition_group_diagnostic_v1.py"
CFG = ROOT / "config" / "akerpuls_d1s3d_acquisition_group_diagnostic_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d1s3d", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD1S3DAcquisitionGroupDiagnosticV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_contract_is_zero_network_and_non_mutating(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d1s3d-acquisition-group-diagnostic-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(self.cfg["expected_final_execution_contract_sha256"], "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19")

    def test_item_id_acquisition_key(self):
        scene = {"item_id": "S2B_MSIL2A_20260525T103019_N0512_R108_T33VVC_20260525T140000", "datetime": "2026-05-25T10:30:19Z"}
        key = self.m.acquisition_key(scene, self.cfg["acquisition_grouping"]["regex"])
        self.assertEqual(key, "20260525T103019")

    def test_latest_group_selection_preserves_then_reverses_granule_order(self):
        scenes = [
            {"item_id": "S2A_MSIL2A_20260525T101001_X_A", "datetime": "2026-05-25T10:10:01Z"},
            {"item_id": "S2A_MSIL2A_20260525T103001_X_B", "datetime": "2026-05-25T10:30:01Z"},
            {"item_id": "S2A_MSIL2A_20260525T103001_X_C", "datetime": "2026-05-25T10:30:01Z"},
        ]
        subset, order, key = self.m.select_variant(scenes, "LATEST_ACQUISITION_REVERSED", self.cfg["acquisition_grouping"]["regex"])
        self.assertEqual(key, "20260525T103001")
        self.assertEqual(order, "REVERSED")
        self.assertEqual([s["item_id"][-1] for s in subset], ["B", "C"])

    def test_variants_are_diagnostic_only(self):
        variants = self.cfg["diagnostic_variants"]
        self.assertIn("ALL_REVERSED", variants)
        self.assertIn("LATEST_ACQUISITION_REVERSED", variants)
        self.assertIn("EARLIEST_ACQUISITION_REVERSED", variants)


if __name__ == "__main__":
    unittest.main()
