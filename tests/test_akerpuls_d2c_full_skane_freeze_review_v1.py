import importlib.util
import json
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "156_akerpuls_d2c_full_skane_freeze_review_v1.py"
CFG = ROOT / "config" / "akerpuls_d2c_full_skane_freeze_review_v1.json"
FORMAL = ROOT / "config" / "akerpuls_split_fusion_qa_v1.json"


def load_module():
    spec = importlib.util.spec_from_file_location("akerpuls_d2c", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestAkerPulsD2CFullSkaneFreezeReviewV1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_module()
        cls.cfg = json.loads(CFG.read_text(encoding="utf-8"))
        cls.formal = json.loads(FORMAL.read_text(encoding="utf-8"))

    def test_go_d2c_is_explicit_and_scope_is_freeze_review_only(self):
        a = self.cfg["authorization"]
        self.assertEqual(a["status"], "AUTHORIZED_AFTER_D2B_REVIEW")
        self.assertEqual(a["user_command"], "GO D2C")
        self.assertIn("FREEZE_D2B_RANKING", a["scope"])
        self.assertTrue(all(v is False for v in self.cfg["guards"].values()))

    def test_parent_d2b_census_is_pinned(self):
        p = self.cfg["parent_d2b"]
        self.assertEqual(p["required_status"], "PASS_TO_D2B_REVIEW_STOP")
        self.assertEqual(p["expected_candidates"], 12676)
        self.assertEqual(p["expected_true_loo_stable"], 10250)
        self.assertEqual(p["expected_fusion_ge_p90"], 1136)
        self.assertEqual(p["expected_fusion_ge_p95"], 618)
        self.assertEqual(p["expected_high_priority"], 618)
        self.assertEqual(p["expected_split_candidate_tier"], 518)
        self.assertEqual(p["expected_evidence_only"], 11540)

    def test_frozen_model_is_identical_to_formal_fusion_config(self):
        m = self.cfg["frozen_model"]
        f = self.formal["fusion"]
        self.assertEqual(m["expected_fusion_artifact_sha256"], f["source_freeze_sha256"])
        self.assertEqual(m["signals"], f["signals"])
        self.assertEqual(m["weights"], f["weights"])
        self.assertAlmostEqual(m["development_p90"], f["development_p90"])
        self.assertAlmostEqual(m["development_p95"], f["development_p95"])

    def test_geometry_policy_forbids_split_generation_and_mutation(self):
        g = self.cfg["geometry"]
        self.assertEqual(g["default_geometry"], "OFFICIAL_2025_GEOMETRY")
        self.assertTrue(g["review_geometry_only"])
        self.assertFalse(g["split_line_generation"])
        self.assertFalse(g["persist_repaired_geometry"])
        self.assertFalse(g["automatic_geometry_replacement"])

    def test_review_and_audit_census_is_frozen(self):
        r = self.cfg["review_product"]
        self.assertEqual(r["ranked_candidate_gpkg_rows"], 12676)
        self.assertEqual(r["p90plus_rows"], 1136)
        self.assertEqual(r["p95_rows"], 618)
        a = r["audit_sample"]
        self.assertEqual(a["total"], 100)
        self.assertEqual(a["high_priority_p95"], 50)
        self.assertEqual(a["p90_only"], 50)
        self.assertEqual(a["selection"], "GEOGRAPHY_COVERAGE_THEN_SHA256_WITHIN_TIER")

    def test_audit_selector_is_deterministic_and_geography_first(self):
        rows = []
        for cell in ("A", "B", "C"):
            for i in range(10):
                rows.append({"parent_field_id_2025": f"2025|{cell}|{i}", "analysis_cell_id": cell, "fusion_ge_dev_p95": True})
        df = pd.DataFrame(rows)
        mask = df.fusion_ge_dev_p95
        a = self.m.select_geography_then_hash(df, mask, 7, "seed", "group")
        b = self.m.select_geography_then_hash(df, mask, 7, "seed", "group")
        self.assertEqual(a.parent_field_id_2025.tolist(), b.parent_field_id_2025.tolist())
        self.assertEqual(len(a), 7)
        self.assertEqual(set(a.analysis_cell_id), {"A", "B", "C"})
        self.assertEqual(a.parent_field_id_2025.nunique(), 7)

    def test_source_has_no_network_or_model_execution_path(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("import requests", text)
        self.assertNotIn("import urllib", text)
        self.assertNotIn("import boto3", text)
        self.assertNotIn("deterministic_k2(", text)
        self.assertNotIn("fit_mask(", text)
        self.assertNotIn("download_assets", text)
        self.assertNotIn("query_date(", text)


if __name__ == "__main__":
    unittest.main()
