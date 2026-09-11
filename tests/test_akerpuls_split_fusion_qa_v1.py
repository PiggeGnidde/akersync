from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"


class TestAkerPulsSplitFusionQAV1(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(CFG.read_text(encoding="utf-8"))

    def test_fusion_contract(self):
        f = self.cfg["fusion"]
        self.assertEqual(f["development_n"], 367)
        self.assertEqual(f["signals"], [
            "prototype_p_splitmerge_2026",
            "separation_ratio",
            "true_loo_min_child_dice",
        ])
        self.assertAlmostEqual(sum(f["weights"]), 1.0, places=12)
        for w in f["weights"]:
            self.assertAlmostEqual(w, 1.0 / 3.0, places=12)
        self.assertEqual(f["development_p90"], 0.781017)
        self.assertEqual(f["development_p95"], 0.843688)
        self.assertEqual(
            f["source_freeze_sha256"],
            "3ab2fcdd06284c15cbcffb20fba8da7de9f6b10ca102bd4026fc73a9ee0a7316",
        )

    def test_policy_is_qa_only(self):
        p = self.cfg["policy"]
        self.assertFalse(p["automatic_split"])
        self.assertFalse(p["automatic_merge"])
        self.assertFalse(p["automatic_geometry_replacement"])
        self.assertEqual(p["product_use"], "QA_RANKING_AND_REVIEW_PRIORITY_ONLY")
        self.assertFalse(self.cfg["candidate_input"]["requires_old_locked_split_gate"])
        self.assertFalse(self.cfg["candidate_input"]["requires_rejected_sep_ge_4_gate"])
        self.assertFalse(any(bool(v) for v in self.cfg["guards"].values()))

    def test_holdout_results_frozen(self):
        v = self.cfg["independent_holdout_validation"]
        self.assertEqual(v["fields"], 1000)
        self.assertEqual(v["baseline_split_candidates"], 131)
        self.assertEqual(v["p90_census_n"], 15)
        self.assertEqual(v["p95_census_n"], 9)
        self.assertEqual(v["blind_key_sha256"], "d2553241211545cb8c0ffdb110e3f063680024af3b17eef818e6fb4cf9a14879")
        self.assertEqual(v["p95"]["liberal_ty_mty_or_m"], "9/9")
        self.assertEqual(v["p95"]["f"], "0/9")
        self.assertEqual(v["p90"]["liberal_ty_mty_or_m"], "13/15")
        self.assertEqual(v["p90"]["f"], "0/15")


if __name__ == "__main__":
    unittest.main()
