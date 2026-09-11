import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c7b.json"
B1 = ROOT / "src" / "112_akerpuls_prelim_fields_2026_b1_rasters.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestC7BContract(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.b1 = load(B1, "akerpuls_b1_c7b_test")

    def test_preprocessing_is_identical_to_b1(self):
        self.assertEqual(self.cfg["preprocessing_contract"], "IDENTICAL_TO_B1_C1_C5B")
        self.assertEqual(self.cfg["source_bands"], self.b1.SOURCE_BANDS)
        self.assertEqual(self.cfg["snapshot_bands"], self.b1.SNAPSHOT_BANDS)
        self.assertEqual(self.cfg["clear_scl_codes"], [2, 4, 5])
        self.assertEqual(self.cfg["resolution_m"], 10)

    def test_fusion_freeze_is_hash_pinned(self):
        self.assertEqual(
            self.cfg["fusion_freeze_sha256_expected"],
            "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316",
        )
        self.assertEqual(self.cfg["fusion_contract_status"], "FROZEN_FOR_C7_INDEPENDENT_TEST_NOT_PRODUCT_RULE")

    def test_no_c7_tuning_or_product_actions(self):
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        self.assertEqual(self.cfg["expected_pilot_fields"], 1000)
        self.assertLessEqual(self.cfg["maximum_total_reported_pu"], 300)


if __name__ == "__main__":
    unittest.main()
