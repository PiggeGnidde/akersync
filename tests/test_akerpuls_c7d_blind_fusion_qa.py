from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "136_akerpuls_c7d_blind_fusion_qa.py"
CFG = ROOT / "config" / "akerpuls_prelim_fields_2026_c7d.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("c7d_test_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestC7DBlindFusionQA(unittest.TestCase):
    def test_config_guards_and_frozen_counts(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertFalse(any(bool(v) for v in cfg["guards"].values()))
        self.assertEqual(cfg["expected_baseline_candidates"], 131)
        self.assertEqual(cfg["expected_fusion_ge_dev_p90"], 15)
        self.assertEqual(cfg["expected_fusion_ge_dev_p95"], 9)
        self.assertEqual(cfg["blind_visual_set"]["p90_census"], 15)
        self.assertEqual(cfg["blind_visual_set"]["near_p90_controls"], 5)
        self.assertEqual(
            cfg["expected_fusion_freeze_sha256"],
            "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316",
        )

    def test_selection_is_full_p90_census_plus_top_five_controls(self):
        mod = load_mod()
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        rows = []
        for i in range(131):
            p90 = i < 15
            p95 = i < 9
            score = 0.95 - i * 0.004 if p90 else 0.780 - (i - 15) * 0.001
            rows.append({
                "parent_field_id_2025": f"2025|B|{i:03d}",
                "fusion_score": score,
                "fusion_ge_dev_p90": p90,
                "fusion_ge_dev_p95": p95,
                "june_validity_stratum": "GE80",
                "valid_s2_2026_june": 0.95,
            })
        x = pd.DataFrame(rows)
        got = mod.select_blind_cases(x, cfg)
        self.assertEqual(len(got), 20)
        selected_ids = set(got["parent_field_id_2025"])
        self.assertTrue({f"2025|B|{i:03d}" for i in range(15)}.issubset(selected_ids))
        self.assertTrue({f"2025|B|{i:03d}" for i in range(15, 20)}.issubset(selected_ids))
        self.assertEqual((got["hidden_group_internal"] == "FUSION_GE_DEV_P95_CENSUS").sum(), 9)
        self.assertEqual((got["hidden_group_internal"] == "FUSION_P90_TO_P95_CENSUS").sum(), 6)
        self.assertEqual((got["hidden_group_internal"] == "NEAR_P90_JUNE_GE80_CONTROL").sum(), 5)
        self.assertEqual(sorted(got["blind_index"].tolist()), list(range(1, 21)))

    def test_blind_hash_is_deterministic(self):
        mod = load_mod()
        a = mod.blind_hash("salt", "field")
        b = mod.blind_hash("salt", "field")
        c = mod.blind_hash("salt2", "field")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
