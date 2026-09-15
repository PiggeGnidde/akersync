import importlib.util
import json
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "155_akerpuls_d2b_full_skane_true_loo_fusion_v1.py"
CFG = ROOT / "config" / "akerpuls_d2b_full_skane_true_loo_fusion_v1.json"
TLOO = ROOT / "config" / "akerpuls_true_loo_diagnostic_v0.json"
FORMAL = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d2b", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2BFullSkaneTrueLooFusionV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        cls.tloo = json.loads(TLOO.read_text(encoding="utf-8"))
        cls.formal = json.loads(FORMAL.read_text(encoding="utf-8"))

    def test_explicit_post_d2a_authorization_and_review_stop(self):
        self.assertEqual(self.cfg["authorization"]["status"], "AUTHORIZED_AFTER_D2A_REVIEW")
        self.assertEqual(self.cfg["authorization"]["user_command"], "GO D2B")
        self.assertEqual(self.cfg["execution"]["stage"], "D2B_ONLY")
        self.assertTrue(self.cfg["execution"]["stop_after_d2b_for_review"])

    def test_parent_d2_contract_and_d2a_census_are_pinned(self):
        p = self.cfg["parent_d2_plan"]
        self.assertEqual(p["expected_execution_contract_sha256"], "83bf7a03860a5b164b104ae49918593fa0852b59d91f7691b2ce2534a669c756")
        self.assertEqual(p["expected_cell_plan_sha256"], "e4c50ee0433adb566431f301a6dc24eb5c29a2749dae984d86fe7ed7b5c396f1")
        a = self.cfg["parent_d2a"]
        self.assertEqual(a["required_status"], "PASS_TO_D2A_REVIEW_STOP")
        self.assertEqual(a["expected_fields"], 128636)
        self.assertEqual(a["expected_split_candidates"], 12676)
        self.assertEqual(a["expected_unchanged"], 85917)
        self.assertEqual(a["expected_uncertain"], 30043)

    def test_true_loo_contract_is_not_changed(self):
        c = self.tloo["true_loo_contract"]
        e = self.cfg["expected"]
        self.assertEqual(e["minimum_reference_comparison_pixels"], c["minimum_reference_comparison_pixels"])
        self.assertEqual(c["minimum_child_fraction_each_omission_on_comparison_domain"], 0.20)
        self.assertEqual(c["minimum_each_child_dice_each_omission"], 0.75)
        self.assertEqual(c["minimum_mean_matched_child_dice_across_all_omissions"], 0.80)
        self.assertTrue(c["require_all_four_omission_refits"])
        self.assertEqual(self.cfg["execution"]["omission_refits"], 4)

    def test_fusion_contract_is_exact_formal_freeze(self):
        e = self.cfg["expected"]
        f = self.formal["fusion"]
        self.assertEqual(e["signals"], f["signals"])
        self.assertEqual(e["weights"], f["weights"])
        self.assertEqual(e["development_reference_n"], f["development_n"])
        self.assertAlmostEqual(e["development_p90"], f["development_p90"])
        self.assertAlmostEqual(e["development_p95"], f["development_p95"])
        self.assertEqual(self.cfg["frozen_inputs"]["expected_fusion_artifact_sha256"], f["source_freeze_sha256"])

    def test_empirical_midrank_matches_c7_definition(self):
        ref = np.array([0.0, 1.0, 1.0, 3.0])
        got = self.m.empirical_midrank(ref, np.array([1.0, 2.0, -1.0, 4.0]))
        np.testing.assert_allclose(got, np.array([0.5, 0.75, 0.0, 1.0]))

    def test_scope_has_no_network_tuning_or_geometry_mutation(self):
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))
        g = self.cfg["projection_geometry_policy"]
        self.assertFalse(g["persist_repaired_geometry"])
        self.assertFalse(g["automatic_geometry_replacement"])
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("urllib", text)
        self.assertNotIn("boto3", text)
        self.assertNotIn("requests.", text)
        self.assertNotIn("process_url", text)
        self.assertNotIn("visual_label", text)

    def test_candidate_outcome_rates_are_not_acceptance_thresholds(self):
        c = self.cfg["completion_contract"]
        self.assertTrue(c["true_loo_stable_rate_is_diagnostic_not_acceptance_threshold"])
        self.assertTrue(c["p90_rate_is_diagnostic_not_acceptance_threshold"])
        self.assertTrue(c["p95_rate_is_diagnostic_not_acceptance_threshold"])
        self.assertTrue(c["require_review_stop"])


if __name__ == "__main__":
    unittest.main()
