from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "139_akerpuls_full_skane_d0b_sparse_norm_v1.py"
CFG = ROOT / "config" / "akerpuls_full_skane_d0b_sparse_norm_v1.json"


def load_mod():
    spec = importlib.util.spec_from_file_location("d0b_sparse_norm_test_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAkerPulsFullSkaneD0BSparseNormV1(unittest.TestCase):
    def test_contract_is_zero_pu_and_non_mutating(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["schema_version"], "akerpuls-full-skane-d0b-sparse-norm-v1")
        self.assertFalse(any(bool(v) for v in cfg["guards"].values()))
        self.assertEqual(cfg["base_d0"]["expected_analysis_cells"], 46)
        self.assertEqual(cfg["base_d0"]["expected_sparse_cells"], 6)
        self.assertEqual(cfg["base_d0"]["expected_minimum_normalization_fields"], 200)
        self.assertEqual(cfg["base_d0"]["expected_planned_process_requests"], 593)
        self.assertAlmostEqual(cfg["base_d0"]["expected_estimated_pu_upper"], 5534.67, places=2)

    def test_fallback_is_predeclared_and_local(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        fb = cfg["normalization_fallback"]
        self.assertEqual(fb["base_grid_size_m"], 20000)
        self.assertEqual(fb["minimum_normalization_fields"], 200)
        self.assertEqual(fb["expansion_steps_m"], [10000, 20000])
        self.assertEqual(fb["maximum_window_side_m"], 60000)
        self.assertTrue(fb["apply_only_when_base_cell_has_fewer_than_minimum"])
        self.assertTrue(fb["no_nearest_n_selection"])
        self.assertTrue(fb["no_label_use"])
        self.assertTrue(fb["no_parameter_tuning"])

    def test_cell_parser_and_window_bounds(self):
        mod = load_mod()
        self.assertEqual(mod.parse_cell_id("A_E0023_N0313"), (23, 313))
        self.assertEqual(mod.window_bounds(23, 313, 20000, 0), (460000, 6260000, 480000, 6280000))
        self.assertEqual(mod.window_bounds(23, 313, 20000, 10000), (450000, 6250000, 490000, 6290000))
        self.assertEqual(mod.window_bounds(23, 313, 20000, 20000), (440000, 6240000, 500000, 6300000))

    def test_base_contract_hash_is_pinned(self):
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        self.assertEqual(
            cfg["base_d0"]["expected_execution_contract_sha256"],
            "4cf28a8cf43848f279d06917aadfb1eb0b54499e1acadf57f8296557dff940a1",
        )


if __name__ == "__main__":
    unittest.main()
