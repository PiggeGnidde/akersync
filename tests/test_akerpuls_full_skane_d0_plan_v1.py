from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "138_akerpuls_full_skane_d0_plan_v1.py"
CFG = ROOT / "config" / "akerpuls_full_skane_d0_plan_v1.json"
FREEZE = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("d0_plan_test_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAkerPulsFullSkaneD0PlanV1(unittest.TestCase):
    def test_contract_is_frozen_and_non_mutating(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["schema_version"], "akerpuls-full-skane-d0-plan-v1")
        self.assertFalse(any(bool(v) for v in cfg["guards"].values()))
        self.assertEqual(cfg["frozen_geometry_2025"]["expected_fields"], 128636)
        self.assertEqual(cfg["a0_reference"]["expected_tiles"], 142)
        self.assertEqual(cfg["a0_reference"]["expected_planned_requests"], 593)
        self.assertAlmostEqual(cfg["a0_reference"]["expected_estimated_pu_upper"], 5534.67, places=2)
        self.assertEqual(cfg["analysis_partition"]["grid_size_m"], 20000)
        self.assertEqual(cfg["analysis_partition"]["minimum_normalization_fields"], 200)
        self.assertFalse(cfg["model_application"]["automatic_geometry_mutation"])

    def test_formal_fusion_freeze_is_pinned(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        frz = json.loads(FREEZE.read_text(encoding="utf-8"))
        self.assertEqual(cfg["split_fusion_freeze"]["tag"], "akerpuls-split-fusion-qa-v1.0")
        self.assertEqual(cfg["split_fusion_freeze"]["commit"], "bd8ef176ffdb1c29c2db42bcdbf83fb4bdca8899")
        self.assertEqual(
            cfg["split_fusion_freeze"]["fusion_artifact_sha256"],
            "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316",
        )
        self.assertAlmostEqual(frz["fusion"]["development_p90"], 0.781017, places=6)
        self.assertAlmostEqual(frz["fusion"]["development_p95"], 0.843688, places=6)
        self.assertFalse(frz["policy"]["automatic_split"])
        self.assertFalse(frz["policy"]["automatic_merge"])
        self.assertFalse(frz["policy"]["automatic_geometry_replacement"])

    def test_resource_formula_reproduces_a0(self):
        mod = load_mod()
        pu = mod.resource_estimate(593, 1024, 7)
        self.assertAlmostEqual(pu, 5534.666666666667, places=9)

    def test_grid_ids_are_deterministic(self):
        mod = load_mod()
        self.assertEqual(mod.raster_tile_id(378880, 6144000), "E0378880_N6144000")
        self.assertEqual(mod.analysis_cell_id(19, 307), "A_E0019_N0307")


if __name__ == "__main__":
    unittest.main()
