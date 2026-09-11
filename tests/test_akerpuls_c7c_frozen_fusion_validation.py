import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "135_akerpuls_c7c_frozen_fusion_validation.py"
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c7c.json"

spec = importlib.util.spec_from_file_location("c7c_test_mod", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestC7CFrozenFusion(unittest.TestCase):
    def test_empirical_midrank(self):
        ref = np.array([1.0, 2.0, 2.0, 4.0])
        got = mod.empirical_midrank(ref, np.array([1.0, 2.0, 3.0, 5.0]))
        self.assertTrue(np.allclose(got, [0.125, 0.5, 0.75, 1.0]))

    def test_freeze_contract(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["expected_pilot_fields"], 1000)
        self.assertEqual(cfg["candidate_discovery_contract"], "IDENTICAL_TO_B2")
        self.assertEqual(cfg["expected_fusion_freeze_sha256"], "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316")
        self.assertAlmostEqual(cfg["fusion_tiers"]["development_p90"], 0.781017, places=6)
        self.assertAlmostEqual(cfg["fusion_tiers"]["development_p95"], 0.843688, places=6)
        self.assertTrue(all(v is False for v in cfg["guards"].values()))

    def test_locked_rule_unchanged(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        c2 = json.loads((ROOT / "config" / "akerpuls_prelim_fields_2026_c2.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["locked_split_rule"], c2["locked_split_rule"])


if __name__ == "__main__":
    unittest.main()
