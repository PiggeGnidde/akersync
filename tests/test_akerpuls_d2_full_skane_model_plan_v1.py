import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "153_akerpuls_d2_full_skane_model_plan_v1.py"
CFG = ROOT / "config" / "akerpuls_d2_full_skane_model_plan_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d2plan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2FullSkaneModelPlanV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_plan_only_zero_network_zero_model(self):
        self.assertEqual(self.cfg["schema_version"], "akerpuls-d2-full-skane-model-plan-v1")
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("deterministic_k2", text)
        self.assertNotIn("process_dataset(", text)

    def test_frozen_domain(self):
        e = self.cfg["expected"]
        self.assertEqual(e["fields"], 128636)
        self.assertEqual(e["analysis_cells"], 46)
        self.assertEqual(e["sparse_expanded_cells"], 6)
        self.assertEqual(e["minimum_normalization_fields"], 200)
        self.assertEqual(e["minimum_b2_valid_pixels"], 24)

    def test_model_freeze(self):
        f = self.cfg["frozen_model"]
        self.assertEqual(f["expected_fusion_artifact_sha256"], "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316")
        self.assertEqual(f["development_reference_n"], 367)
        self.assertAlmostEqual(f["development_p90"], 0.781017)
        self.assertAlmostEqual(f["development_p95"], 0.843688)
        self.assertEqual(f["weights"], [1/3, 1/3, 1/3])

    def test_d0b_bindings(self):
        d = self.cfg["parent_d0b"]
        self.assertEqual(d["expected_execution_contract_sha256"], "d2c2a88d0978cffcd720dbb7a7982049fbc5c09ae41f3f7be2e959ad254aec19")
        self.assertEqual(d["expected_resolved_normalization_windows_sha256"], "0e3faedd3da470a261a7348d4d4129d52d938c10f34350ccea328b47581c6dc8")

    def test_mandatory_d2a_stopping_point(self):
        p = self.cfg["execution_plan"]
        self.assertEqual(p["stage_d2a"], "FULL_SKANE_B2_BASELINE_SPLIT_DISCOVERY_ONLY")
        self.assertTrue(p["stop_after_d2a_before_true_loo_fusion"])
        self.assertEqual(p["true_loo_candidate_scope"], "D2A_B2_SPLIT_CANDIDATES_ONLY")
        self.assertIn("SEPARATE_AUTHORIZATION", p["stage_d2b"])

    def test_geometry_never_automatic(self):
        g = self.cfg["geometry_policy"]
        self.assertFalse(g["automatic_split"])
        self.assertFalse(g["automatic_merge"])
        self.assertFalse(g["automatic_geometry_replacement"])
        self.assertFalse(g["persist_repaired_geometry"])

    def test_normalize_field_id(self):
        self.assertEqual(self.m.normalize_field_id("2025|123|A"), "123|A")
        self.assertEqual(self.m.normalize_field_id("123|A"), "123|A")


if __name__ == "__main__":
    unittest.main()
