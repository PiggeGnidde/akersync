import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "131_akerpuls_geometry_prior_sentinel_fusion.py"
CONFIG = ROOT / "config" / "akerpuls_geometry_prior_sentinel_fusion_v0.json"

spec = importlib.util.spec_from_file_location("akerpuls_fusion", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


class TestAkerpulsFusion(unittest.TestCase):
    def test_contract_zero_pu_no_tuning(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(len(cfg["labels"]["C3"]), 20)
        self.assertEqual(len(cfg["labels"]["C5D"]), 12)
        self.assertFalse(cfg["guards"]["sentinel_api_calls"])
        self.assertFalse(cfg["guards"]["threshold_tuning"])
        self.assertFalse(cfg["guards"]["new_split_rule"])
        self.assertFalse(cfg["guards"]["product_prior_freeze"])

    def test_field_id_normalization(self):
        self.assertEqual(mod.normalize_field_id("2025|62503166115|49A"), "62503166115|49A")
        self.assertEqual(mod.normalize_field_id("62503166115|49A"), "62503166115|49A")

    def test_auc_rank_perfect(self):
        score = pd.Series([0.9, 0.8, 0.2, 0.1])
        positive = pd.Series([True, True, False, False])
        auc, npos, nneg, _p = mod.auc_rank(score, positive)
        self.assertAlmostEqual(auc, 1.0)
        self.assertEqual((npos, nneg), (2, 2))


if __name__ == "__main__":
    unittest.main()
